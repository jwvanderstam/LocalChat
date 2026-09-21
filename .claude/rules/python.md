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
- Use `except Exception` only where the breadth is the point — an SSE boundary, an
  optional subsystem, a per-item loop that must not abandon the rest. `ruff` enforces
  this (`BLE001`). Clear it by narrowing, by calling `logger.exception`, or with
  `# noqa: BLE001 — <what degrades, and to what>`. A bare `# noqa: BLE001` is the thing
  the rule exists to prevent; write the reason or narrow the catch. Always log.
- Re-raise with context: `raise SomeError("msg") from e`, not swallowed or re-raised without cause.

## Comments

- Comments explain *why* — a hidden constraint, a non-obvious invariant, a specific bug workaround.
- If you need a comment to say what the code does, rename the identifiers instead.
- No multi-line docstrings for internal functions. One short line max for public APIs.
- No task tracking in code (`# TODO`, `# FIXME`). Use issues.

## Code hygiene

- No commented-out code. Delete it — git is the history.
- No `assert` in `src/`. `python -O` strips them, so an invariant written that way is
  not enforced by the interpreter that ships. Write `if not <cond>: raise
  AssertionError("why")` — same exception, same message, and it survives. `ruff`
  enforces this (`S101`); `tests/**` is exempt, where a stripped assert is harmless.
- No `_old`, `_v2`, `_backup` name variants. Rename or delete.
- No bare `# type: ignore`. Scope every one to its error code — `# type: ignore[attr-defined]`,
  `# type: ignore[import]` — so it silences the one thing it was added for and a second,
  unrelated error still surfaces. All 15 in `src/` are scoped this way; keep it that way.
  (This rule used to say "outside `src/types.py`". No such file has ever existed in this
  repository, so the exemption it offered was unreachable and the rule unfollowable as
  written. Corrected 2026-08-27 to the practice the code actually follows.)

## Naming

- Functions and variables: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE` — define in `src/config.py`
- Private module-level helpers: `_leading_underscore`

## Logging

- Use `logging.getLogger(__name__)`. Never `print()` for diagnostics.
- In production `LOG_FORMAT=json` — structured output via `JsonFormatter`.
- Levels: `debug` for trace, `info` for business events, `warning` for degraded-but-recoverable, `error` for failures requiring attention.
