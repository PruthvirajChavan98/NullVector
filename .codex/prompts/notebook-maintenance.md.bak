# Notebook Maintenance Contract

Whenever the current task changes runnable behavior, update:

- `notebooks/progress.ipynb`

Notebook contract:
- must run top-to-bottom
- must target the current phase only
- must use committed fixtures where possible
- must write temporary outputs under a notebook-local temp/artifact path
- must not require manual cell editing before first execution

Required notebook sections:
1. title / phase / objective
2. environment assumptions
3. imports
4. configuration
5. execution
6. output inspection
7. known limitations

If the implementation is not runnable yet:
- update the notebook to reflect the current incomplete state honestly
- include the exact blocker in a markdown cell
- do not fake outputs

