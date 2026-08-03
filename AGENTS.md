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
