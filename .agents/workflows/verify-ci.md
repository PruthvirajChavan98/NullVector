---
description: Run the full NullVector CI pipeline (format, lint, typecheck, test) and verify notebook state.
---

# CI Verification Workflow

1. Run `make ci` in the terminal to execute formatting, linting, typechecking, and tests.
2. If `ruff format --check` fails, automatically run `make format` to fix it.
3. If `mypy` or `pytest` fails, analyze the output and propose fixes to the code.
4. Verify that `notebooks/progress.ipynb` is fully executable top-to-bottom and reflects the current state of the implementation.
5. Generate the Delivery Footer documenting the validation run results.
