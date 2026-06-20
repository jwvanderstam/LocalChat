# Python Coding Standards

## Type hints

- All public functions and methods must be fully annotated, including return types.
- Avoid `Any`. Use a specific type or `Union`. If `Any` is unavoidable, add an inline comment saying why.
- Prefer `T | None` over `Optional[T]` for new code (Python 3.10+).
- Return type `-> None` is required even when trivially obvious.

## Imports

- Order: stdlib → third-party → local. One blank line between groups.
- No wildcard imports (`from x import *`).
- Remove unused imports. `ruff` will flag them; fix them rather than `# noqa`.

## Exception handling

- Never use bare `except:`. Minimum: `except Exception as e:`.
- Catch the narrowest applicable exception type.
- Use `except Exception` only at SSE stream top-level boundaries — always log `e`.
- Re-raise with context: `raise SomeError("msg") from e`, not swallowed or re-raised without cause.

## Comments

- Comments explain *why* — a hidden constraint, a non-obvious invariant, a specific bug workaround.
- If you need a comment to say what the code does, rename the identifiers instead.
- No multi-line docstrings for internal functions. One short line max for public APIs.
- No task tracking in code (`# TODO`, `# FIXME`). Use issues.

## Code hygiene

- No commented-out code. Delete it — git is the history.
- No `_old`, `_v2`, `_backup` name variants. Rename or delete.
- No `# type: ignore` outside `src/types.py`. New occurrences need an inline justification.

## Naming

- Functions and variables: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE` — define in `src/config.py`
- Private module-level helpers: `_leading_underscore`

## Logging

- Use `logging.getLogger(__name__)`. Never `print()` for diagnostics.
- In production `LOG_FORMAT=json` — structured output via `JsonFormatter`.
- Levels: `debug` for trace, `info` for business events, `warning` for degraded-but-recoverable, `error` for failures requiring attention.
