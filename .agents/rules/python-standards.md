# Python & Tooling Standards

- **Dependency Management:** Use `uv`. Run scripts via `uv run` or manage deps via `uv sync --extra dev`.
- **Domain Contracts:** All data structures MUST use `pydantic` v2. Models must inherit from `StrataModel` (defined in `src/nullvector/domain/models.py`) which enforces `ConfigDict(extra="forbid", frozen=True, strict=True)`.
- **Linting & Formatting:** Use `ruff`. You must run `make format-check` and `make lint` to verify code quality.
- **Type Checking:** Strict type hinting is mandatory. Run `make typecheck` (which uses `mypy --strict`) to verify.
- **Testing:** Use `pytest`. Run `make test` for unit/integration tests.
