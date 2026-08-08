from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github" / "scripts"))

from release_guard import (
    ReleaseGuardError,
    classify_release_probe,
    classify_tag_probe,
    evaluate_version,
    load_previous_version,
    parse_semver,
    synchronized_version,
)


class ReleaseGuardBehaviorTests(unittest.TestCase):
    def test_strict_semver_and_synchronized_sources(self) -> None:
        self.assertEqual(parse_semver("1.2.3"), (1, 2, 3))
        with self.assertRaises(ReleaseGuardError):
            parse_semver("1.2")
        metadata = "version: 1.2.3\n"
        pyproject = 'version = "1.2.3"\n'
        lock = 'name = "astrbot-plugin-aihot"\nversion = "1.2.3"\n'
        self.assertEqual(synchronized_version(metadata, pyproject, lock), "1.2.3")

    def test_manual_release_requires_main_and_newer_tag(self) -> None:
        with self.assertRaises(ReleaseGuardError):
            evaluate_version(
                event_name="workflow_dispatch",
                event_ref="refs/heads/feature",
                current="1.2.4",
                latest_tag="1.2.3",
                previous="1.2.3",
            )
        with self.assertRaises(ReleaseGuardError):
            evaluate_version(
                event_name="workflow_dispatch",
                event_ref="refs/heads/main",
                current="1.2.3",
                latest_tag="1.2.3",
                previous=None,
            )

    def test_push_requires_readable_previous_commit_metadata(self) -> None:
        with self.assertRaises(ReleaseGuardError):
            load_previous_version(
                "deadbeef",
                commit_exists=lambda _: False,
                read_metadata=lambda _: "version: 1.2.2\n",
            )
        with self.assertRaises(ReleaseGuardError):
            load_previous_version(
                "deadbeef",
                commit_exists=lambda _: True,
                read_metadata=lambda _: (_ for _ in ()).throw(OSError("missing")),
            )

    def test_push_version_must_increase_and_not_reuse_latest_tag(self) -> None:
        decision = evaluate_version(
            event_name="push",
            event_ref="refs/heads/main",
            current="1.2.4",
            latest_tag="1.2.3",
            previous="1.2.3",
        )
        self.assertTrue(decision.changed)
        self.assertEqual(decision.old_version, "1.2.3")
        with self.assertRaises(ReleaseGuardError):
            evaluate_version(
                event_name="push",
                event_ref="refs/heads/main",
                current="1.2.2",
                latest_tag="1.2.3",
                previous="1.2.1",
            )

    def test_remote_probe_distinguishes_absence_from_failure(self) -> None:
        self.assertFalse(classify_tag_probe(2, ""))
        self.assertTrue(classify_tag_probe(0, "refs/tags/1.2.3"))
        with self.assertRaises(ReleaseGuardError):
            classify_tag_probe(128, "network unreachable")
        self.assertFalse(classify_release_probe(1, "HTTP/2 404\n"))
        with self.assertRaises(ReleaseGuardError):
            classify_release_probe(1, "proxy returned 404 while connecting")
        self.assertTrue(classify_release_probe(0, "HTTP/2 200\n{}"))
        with self.assertRaises(ReleaseGuardError):
            classify_release_probe(1, "HTTP/2 500\nservice unavailable")


if __name__ == "__main__":
    unittest.main()
