# Test Suite Notes

## Quick iteration

- Use `pytest -m "not mock_long"` to skip the slower mock/integration checks when you just need a fast sanity pass.
- Run the full suite (`pytest`) before packaging or pushing to CI, since mock/integration coverage is excluded when filtering.

## Markers

- `mock_long`: marks mock-mode and integration scenarios that spin up the full runtime pipeline and take noticeably longer (>3 minutes).

