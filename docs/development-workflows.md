# Development Workflows

> On-demand reference for Claude Code. Load with `@docs/development-workflows.md` when
> working on build processes, branch strategy, or onboarding new contributors.

---

## Local Development Setup

```bash
# 1. Clone and enter repository
git clone <repo-url> && cd NullVector

# 2. Install uv if not present (idempotent)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Bootstrap environment -- creates .venv and installs all dev dependencies
uv sync --extra dev

# 4. Verify setup
uv run pytest tests/unit/ -q
```

The `.venv` directory is managed entirely by `uv`. Never activate it manually or install
packages into it with `pip`. Always use `uv add` (with human approval per `CLAUDE.md`).

There is no `docker-compose.yml`, no `.env.example`, and no infrastructure services
required for basic development. The optional PostgreSQL storage backend requires a
running PostgreSQL instance and the `postgres` extra (`uv sync --extra postgres`).

---

## Quality Gate

The full quality gate is defined in the `Makefile` and run with:

```bash
make ci
```

This executes the following steps in order, each of which must exit 0:

```bash
uv run ruff format --check src tests   # formatting (check-only, no mutation)
uv run ruff check src tests            # lint
uv run mypy src tests                  # strict type checking
uv run pytest                          # all tests
```

### Running individual tools

```bash
# Auto-fix lint violations
uv run ruff check --fix .

# Format in-place
uv run ruff format .

# Type check (src only, faster)
uv run mypy src/

# Fast-fail tests
uv run pytest -x -q

# Unit tests only
uv run pytest tests/unit/

# Integration tests only
uv run pytest tests/integration/
```

### Makefile targets

| Target | Command | Purpose |
|--------|---------|---------|
| `make setup` | `uv sync --extra dev` | Bootstrap dev environment |
| `make format` | `uv run ruff format src tests` | Format in-place |
| `make format-check` | `uv run ruff format --check src tests` | Check formatting |
| `make lint` | `uv run ruff check src tests` | Run linter |
| `make typecheck` | `uv run mypy src tests` | Run mypy strict |
| `make test` | `uv run pytest` | Run all tests |
| `make ci` | format-check + lint + typecheck + test | Full quality gate |

---

## What Is Not Configured Yet

The following are **not** currently set up for this project:

- **CI/CD**: No GitHub Actions, no automated pipelines. `make ci` is the local gate.
- **Pre-commit hooks**: No `.pre-commit-config.yaml`. Developers run `make ci` manually.
- **Commitlint**: No commit message linting or enforcement.
- **Changelog generation**: No `git-cliff` or equivalent.
- **Release automation**: No automated tagging, publishing, or changelog workflows.

---

## Branch Strategy

The primary branch is `master`. Development currently happens with direct commits to
`master` or short-lived feature branches merged via pull request.

Recommended branch naming when using feature branches:

| Branch pattern | Purpose |
|----------------|---------|
| `feat/<slug>` | New features |
| `fix/<slug>` | Bug fixes |
| `chore/<slug>` | Tooling, deps, docs |

---

## Commit Conventions

There is no enforced commit message standard. The project does not use Conventional
Commits tooling. In practice, commit messages should be concise and describe the change.

When Claude Code creates commits, it appends a co-authorship line:

```
Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## Dependency Management

Dependencies are managed with `uv`. Never use `pip install` directly.

```bash
# Add a production dependency (requires human approval)
uv add <package>

# Add a dev dependency (requires human approval)
uv add --dev <package>

# Regenerate lockfile after manual pyproject.toml edits
uv lock

# Install all dev extras
uv sync --extra dev

# Install with optional PostgreSQL support
uv sync --extra dev --extra postgres
```

The `uv.lock` file is committed and ensures deterministic installs across environments.

---

## Test Data and Fixtures

Test fixtures live in `fixtures/` with golden expectations for deterministic validation.
These are used by both unit and integration tests to verify that processing phases
produce stable, reproducible output.

---

## Environment Variables

NullVector does not use `pydantic-settings` or a `.env` file for configuration. LLM
provider credentials (API keys) are expected to be present as standard environment
variables read by `litellm` or `httpx` at runtime.

Secrets (API keys, credentials) must never be committed to the repository.
