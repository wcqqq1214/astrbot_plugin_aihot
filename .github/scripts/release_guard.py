"""Fail-closed guards used by the release workflow.

The functions in this module are intentionally small and side-effect free where
possible so version and remote-probe behavior can be tested without GitHub.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
ZERO_SHA_RE = re.compile(r"^0+$")
_METADATA_VERSION_RE = re.compile(r"^version:\s*([^\s#]+)", re.MULTILINE)
_PYPROJECT_VERSION_RE = re.compile(r"^version\s*=\s*\"([^\"]+)\"", re.MULTILINE)


class ReleaseGuardError(ValueError):
    """A release input is malformed, stale, or could not be verified."""


@dataclass(frozen=True)
class VersionDecision:
    current_version: str
    old_version: str | None
    changed: bool


def parse_semver(value: str) -> tuple[int, int, int]:
    """Parse strict X.Y.Z SemVer without prerelease/build suffixes."""

    if not isinstance(value, str) or not SEMVER_RE.fullmatch(value):
        raise ReleaseGuardError(f"not strict SemVer: {value!r}")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def _extract(pattern: re.Pattern[str], text: str, label: str) -> str:
    match = pattern.search(text)
    if not match:
        raise ReleaseGuardError(f"could not read {label}")
    value = match.group(1)
    parse_semver(value)
    return value


def metadata_version(text: str) -> str:
    return _extract(_METADATA_VERSION_RE, text, "metadata version")


def pyproject_version(text: str) -> str:
    return _extract(_PYPROJECT_VERSION_RE, text, "pyproject version")


def lock_version(text: str) -> str:
    lines = text.splitlines()
    in_plugin = False
    for line in lines:
        if line == 'name = "astrbot-plugin-aihot"':
            in_plugin = True
            continue
        if in_plugin and line.startswith("[[package]]"):
            break
        if in_plugin and line.startswith("version = "):
            value = line.split('"', 2)[1]
            parse_semver(value)
            return value
    raise ReleaseGuardError("could not read uv.lock plugin version")


def synchronized_version(metadata: str, pyproject: str, lock: str) -> str:
    """Read and require the one synchronized project version."""

    versions = (
        metadata_version(metadata),
        pyproject_version(pyproject),
        lock_version(lock),
    )
    if len(set(versions)) != 1:
        raise ReleaseGuardError(f"version sources differ: {versions!r}")
    return versions[0]


def latest_semver_tag(tags: Iterable[str]) -> str | None:
    strict = [tag for tag in tags if SEMVER_RE.fullmatch(tag)]
    if not strict:
        return None
    return max(strict, key=parse_semver)


def evaluate_version(
    *,
    event_name: str,
    event_ref: str,
    current: str,
    latest_tag: str | None,
    previous: str | None,
) -> VersionDecision:
    """Validate manual/push semantics and return workflow output values."""

    current_parts = parse_semver(current)
    if latest_tag is not None:
        parse_semver(latest_tag)
    if event_ref != "refs/heads/main":
        raise ReleaseGuardError("release workflow is only allowed on refs/heads/main")

    if event_name == "workflow_dispatch":
        if latest_tag is not None and current_parts <= parse_semver(latest_tag):
            raise ReleaseGuardError(
                f"manual version {current} is not newer than latest tag {latest_tag}"
            )
        return VersionDecision(current, latest_tag, True)

    if event_name != "push":
        raise ReleaseGuardError(f"unsupported event: {event_name}")
    if previous is None:
        raise ReleaseGuardError("push event is missing a verified previous version")
    previous_parts = parse_semver(previous)
    if current_parts == previous_parts:
        return VersionDecision(current, previous, False)
    if current_parts < previous_parts:
        raise ReleaseGuardError(
            f"new version {current} is not greater than previous {previous}"
        )
    if latest_tag is not None and current_parts <= parse_semver(latest_tag):
        raise ReleaseGuardError(
            f"push version {current} is not newer than latest tag {latest_tag}"
        )
    return VersionDecision(current, previous, True)


def load_previous_version(
    before: str,
    *,
    commit_exists: Callable[[str], bool],
    read_metadata: Callable[[str], str],
) -> str | None:
    """Read the prior commit's metadata, failing closed on every read error."""

    if ZERO_SHA_RE.fullmatch(before):
        return None
    if not SHA_RE.fullmatch(before):
        raise ReleaseGuardError("event.before is not a full commit SHA")
    if not commit_exists(before):
        raise ReleaseGuardError(f"event.before commit is unreadable: {before}")
    try:
        text = read_metadata(before)
    except Exception as exc:
        raise ReleaseGuardError("could not read previous metadata.yaml") from exc
    return metadata_version(text)


def classify_tag_probe(returncode: int, output: str) -> bool:
    """Return existence; only git's documented no-match status means absent."""

    if returncode == 0:
        return True
    if returncode == 2:
        return False
    raise ReleaseGuardError(f"tag probe failed ({returncode}): {output.strip()}")


def classify_release_probe(returncode: int, output: str) -> bool:
    """Return existence; only an explicit HTTP 404 means absent."""

    if returncode == 0:
        return True
    if re.search(r"(?im)^\s*HTTP/\S+\s+404(?:\s|$)", output):
        return False
    raise ReleaseGuardError(f"release probe failed ({returncode}): {output.strip()}")


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _git_commit_exists(sha: str) -> bool:
    return _run(["git", "cat-file", "-e", f"{sha}^{{commit}}"]).returncode == 0


def _git_read_metadata(sha: str) -> str:
    result = _run(["git", "show", f"{sha}:metadata.yaml"])
    if result.returncode != 0:
        raise ReleaseGuardError(result.stderr.strip() or "metadata read failed")
    return result.stdout


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseGuardError(f"could not read {path}") from exc


def _version_command(args: argparse.Namespace) -> None:
    current = synchronized_version(
        _read(args.metadata), _read(args.pyproject), _read(args.lock)
    )
    tags_result = _run(["git", "tag", "--list"])
    if tags_result.returncode != 0:
        raise ReleaseGuardError(tags_result.stderr.strip() or "could not read tags")
    latest_tag = latest_semver_tag(tags_result.stdout.splitlines())
    previous = None
    if args.event_name == "push":
        previous = load_previous_version(
            args.event_before,
            commit_exists=_git_commit_exists,
            read_metadata=_git_read_metadata,
        )
    decision = evaluate_version(
        event_name=args.event_name,
        event_ref=args.event_ref,
        current=current,
        latest_tag=latest_tag,
        previous=previous,
    )
    print(f"changed={'true' if decision.changed else 'false'}")
    print(f"version={decision.current_version}")
    print(f"old_version={decision.old_version or 'none'}")


def _remote_command(args: argparse.Namespace) -> None:
    tag_result = _run(
        [
            "git",
            "ls-remote",
            "--exit-code",
            "--refs",
            "origin",
            f"refs/tags/{args.version}",
        ]
    )
    tag_exists = classify_tag_probe(
        tag_result.returncode, tag_result.stdout + tag_result.stderr
    )
    release_result = _run(
        [
            "gh",
            "api",
            "--include",
            f"repos/{args.repository}/releases/tags/{args.version}",
        ]
    )
    release_exists = classify_release_probe(
        release_result.returncode, release_result.stdout + release_result.stderr
    )
    if tag_exists or release_exists:
        raise ReleaseGuardError(
            f"version {args.version} already exists (tag={tag_exists}, release={release_exists})"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    version = subparsers.add_parser("version")
    version.add_argument("--event-name", required=True)
    version.add_argument("--event-ref", required=True)
    version.add_argument("--event-before", default="0" * 40)
    version.add_argument("--metadata", required=True)
    version.add_argument("--pyproject", required=True)
    version.add_argument("--lock", required=True)
    version.set_defaults(func=_version_command)
    remote = subparsers.add_parser("remote")
    remote.add_argument("--repository", required=True)
    remote.add_argument("--version", required=True)
    remote.set_defaults(func=_remote_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        args.func(args)
    except ReleaseGuardError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
