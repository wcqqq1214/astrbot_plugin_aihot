# AGENTS.md

## Commit conventions

- Write all commit messages in **English**.
- Do **not** append a `Co-Authored-By` trailer or any other attribution line.
- Use conventional commit prefixes, e.g. `feat:`, `fix:`, `chore:`, `docs:`.

## Development notes

- Use English for all comments and logs.
- Use `httpx` or `aiohttp` for network requests (do not use `requests`).
- Persist data under the AstrBot `data` directory, not the plugin directory.
- Run `ruff format .` and `ruff check .` before committing.
- Add third-party dependencies to `requirements.txt`.

## Development environment

The plugin has its own uv-managed virtualenv (`.venv`, Python 3.12.13) that
holds **only the plugin's own dependencies** (`httpx`, `apscheduler`, plus
`ruff` in the dev group). AstrBot — and all of AstrBot's framework
dependencies — is *not* installed here; the plugin gets it from the AstrBot
process at runtime.

- `uv sync` — install or refresh the plugin's dependencies.
- `uv run ruff check .` / `uv run ruff format .` — lint and format.

Anything that needs to `import astrbot` (e.g. integration checks) must run
against the local AstrBot checkout's venv instead, so it uses the same
interpreter and astrbot code as the deployed AstrBot:

```
/Users/wcqqq1214/Project/AstrBot/.venv/bin/python your_script.py
```

Keep the `requirements.txt` in sync with the `dependencies` list in
`pyproject.toml` (same `httpx`/`apscheduler` constraints).
