# Coding Standards

> On-demand reference for Claude Code. Load with `@docs/coding-standards.md` when
> reviewing code quality, implementing new patterns, or evaluating whether a proposed
> approach is consistent with project conventions.

---

## Python Version and Compatibility

All code targets **Python 3.11** as the minimum (enforced in `pyproject.toml`).
The following features are available and should be preferred:

- `X | Y` union syntax instead of `Union[X, Y]` or `Optional[X]`
- `match` / `case` structural pattern matching for complex branching
- `tomllib` from stdlib for TOML parsing (no external dependency needed)
- `ExceptionGroup` and `except*` for grouped error handling
- `typing.Self` for fluent builder patterns
- `typing.TypeAlias` for explicit type alias declarations
- `StrEnum` from the `enum` module

Never use features requiring `from __future__ import annotations` unless forward
references are the specific need.

---

## Type Annotations

Every public function, method, and class attribute must be fully annotated.
`mypy --strict` is the enforcement gate and must produce zero errors.

**Accepted patterns:**

```python
# Correct: explicit return type, typed parameters
def extract_headings(page_text: str, *, min_score: float = 0.5) -> list[Heading]:
    ...

# Correct: TypeAlias for complex types
NodeMap: TypeAlias = dict[str, list[HierarchyNode]]

# Correct: Generic with TypeVar
T = TypeVar("T", bound="StrataModel")

def clone(entity: T) -> T:
    ...
```

**Forbidden patterns:**

```python
# WRONG: no annotations
def process(data):
    ...

# WRONG: Optional[] instead of X | None
from typing import Optional
def get(id: Optional[str]) -> Optional[User]:
    ...

# WRONG: Any without explicit justification
from typing import Any
def parse(raw: Any) -> Any:
    ...
```

When `Any` is genuinely necessary (e.g., interfacing with an untyped third-party library),
annotate with a comment:

```python
raw_payload: Any  # LiteLLM returns untyped dict; validated via Pydantic below
```

No `# type: ignore` without an inline explanation of why it is necessary.

---

## mypy Configuration

The actual configuration in `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.11"
strict = true
warn_unused_configs = true
show_error_codes = true
pretty = true
packages = ["nullvector"]
explicit_package_bases = true
mypy_path = ["src"]

[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = true

[[tool.mypy.overrides]]
module = ["fitz", "fitz.*"]
ignore_missing_imports = true
follow_untyped_imports = true

[[tool.mypy.overrides]]
module = ["litellm", "litellm.*"]
ignore_missing_imports = true
follow_untyped_imports = true
```

Key points:
- `fitz` (PyMuPDF) and `litellm` have no type stubs; their imports are ignored.
- Tests must have typed function definitions but are not held to full strict mode.
- Run with: `uv run mypy src/`

---

## Ruff Configuration

Ruff handles both linting and formatting. The actual configuration in `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py311"
line-length = 100
src = ["src", "tests"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.ruff.lint]
select = ["B", "E", "F", "I", "PTH", "RUF", "SIM", "UP", "W"]

[tool.ruff.lint.isort]
known-first-party = ["nullvector"]
```

Selected rule groups:

| Code | Category |
|------|----------|
| `B` | flake8-bugbear (common pitfalls) |
| `E` | pycodestyle errors |
| `F` | pyflakes (unused imports, undefined names) |
| `I` | isort (import ordering) |
| `PTH` | flake8-use-pathlib (prefer `pathlib` over `os.path`) |
| `RUF` | Ruff-specific rules |
| `SIM` | flake8-simplify (unnecessary complexity) |
| `UP` | pyupgrade (modernize syntax for target Python) |
| `W` | pycodestyle warnings |

Run linting: `uv run ruff check --fix .`
Run formatting: `uv run ruff format .`

---

## Domain Models (Pydantic v2)

All domain types inherit from `StrataModel` (defined in `domain/common.py`).
Use Pydantic v2 semantics throughout. Pydantic v1 compatibility shims are prohibited.

```python
from nullvector.domain.common import StrataModel

class PageProfile(StrataModel):
    """StrataModel enforces: frozen=True, extra='forbid', strict=True."""

    page_index: NonNegativeInt
    text_density: float
    has_images: bool
```

Constrained types defined in `domain/common.py`:
- `NonEmptyStr` -- stripped, minimum length 1
- `Sha256Hex` -- exactly 64 lowercase hex characters
- `PositiveInt`, `NonNegativeInt` -- from Pydantic
- `ScalarValue` -- `str | int | float | bool | None`

Domain models live exclusively in `src/nullvector/domain/`. Never define Pydantic
models in service or adapter modules -- import them from the domain layer.

---

## Exception Hierarchy

Exceptions are organized by bounded context, not by HTTP status code (there is no
HTTP layer).

### Ingest exceptions (`ingest/errors.py`)

All rooted at `ParseSubstrateError`, which wraps a typed `ParseFailure` domain model:

```
ParseSubstrateError
  +-- InvalidSourceError        (source PDF cannot be read or fingerprinted)
  +-- ParseConflictError        (run ID reused with different inputs)
  +-- MissingOcrRuntimeError    (Tesseract unavailable when needed)
  +-- ExtractionFailureError    (parser/OCR operation fails)
```

### LLM gateway exceptions (`llm/errors.py`)

All rooted at `GatewayError`, which wraps a typed `GatewayFailure` envelope:

```
GatewayError
  +-- GatewayValidationError
  +-- GatewayTimeoutError
  +-- GatewayRateLimitError
  +-- GatewayNetworkError
  +-- GatewayProviderRefusalError
  +-- GatewayContextLengthError
  +-- GatewayAuthError
  +-- GatewayUnsupportedCapabilityError
  +-- GatewayUnknownProviderError

GatewayConfigurationError       (standalone, not a GatewayError subclass)
```

General rules:
- Never swallow exceptions silently. Log before re-raising.
- Bare `except Exception:` only for documented defensive cases.
- Domain code never references HTTP concepts.

---

## Logging

Use the structured logging helpers from `observability/logging.py`. Never use `print()`.
Never call `logging.basicConfig()` in library code.

```python
import logging

logger = logging.getLogger(__name__)

# Correct: structured fields as keyword arguments
logger.info("Heading extracted", extra={"page_index": 3, "score": 0.85})

# Correct: lazy interpolation, not f-strings
logger.debug("Processing %d pages", page_count)

# Wrong: f-string evaluated even when log level is disabled
logger.debug(f"Processing {page_count} pages")
```

---

## Synchronous Design

NullVector is a **synchronous library**. All I/O operations (file reads, PDF parsing,
LLM HTTP calls) use synchronous APIs. There is no async runtime, no event loop, and no
`asyncio` dependency.

- File I/O uses `pathlib.Path` methods
- HTTP calls use `httpx` (synchronous client) or `litellm` (synchronous mode)
- PDF parsing uses `fitz` (PyMuPDF) synchronous API

Do not introduce `async def`, `await`, `asyncio.gather`, or `asyncio.run` unless there
is an explicit decision to change this.

---

## Imports

PEP 517 src layout. All imports are absolute:

```python
# Correct
from nullvector.domain.tree import HierarchyNode
from nullvector.storage.protocol import DocumentStore

# Wrong: relative imports across packages
from ..domain.tree import HierarchyNode
```

Relative imports are acceptable only within the same sub-package (e.g., within
`nullvector/llm/`).

Never add dependencies without explicit human approval.

---

## Testing Conventions

### pytest configuration

The actual configuration in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "-ra --strict-config --strict-markers"
testpaths = ["tests"]
filterwarnings = ["error::DeprecationWarning"]
```

Key points:
- `--strict-config` rejects unknown configuration keys
- `--strict-markers` rejects unregistered markers (no typos in `@pytest.mark.xxx`)
- Deprecation warnings are treated as errors and will fail tests

### Test organization

| Directory | Scope | Rules |
|-----------|-------|-------|
| `tests/unit/` | Pure logic | No filesystem, network, or database I/O |
| `tests/integration/` | Real infrastructure | May use real files, external services |
| `tests/retrieval/` | Retrieval-specific | Retrieval pipeline tests |
| `tests/llm/` | LLM adapter tests | LLM provider integration |

### File naming

`tests/unit/test_[descriptive_name].py` -- e.g., `test_domain_models.py`,
`test_strategy_unit.py`, `test_tree_pipeline_unit.py`.

### Assertion style

Use plain `assert` with descriptive messages. Do not use `unittest` assertion methods.

```python
assert node.depth == 2, f"Expected depth 2, got {node.depth}"
```

### Parametrize

Prefer `@pytest.mark.parametrize` over loops in test bodies.

### Not installed

Note that `pytest-asyncio` and `pytest-mock` are **not** in the project dependencies.
Use `unittest.mock` directly if mocking is needed. Do not add dependencies without
explicit human approval.

---

## pyproject.toml as Single Source of Truth

`pyproject.toml` is the single configuration file for all tooling. Never introduce
`setup.cfg`, `tox.ini`, `.flake8`, `mypy.ini`, or separate `pytest.ini` files.
