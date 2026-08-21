"""Reading the application log back for the admin log viewer.

The log file is the only sink that can be read back: the console is owned by the
container runtime and syslog has left the box. It also holds more than the console
does — DEBUG against the console's INFO — which is why the viewer reads it rather
than shelling out to ``docker logs``.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..utils.logging_config import get_logger

logger = get_logger(__name__)

#: Read backwards in chunks rather than loading the file. A rotated log is several
#: megabytes and the viewer only ever wants the tail of it.
_CHUNK = 64 * 1024

#: Ceiling on what one request may ask for, so a caller cannot turn the viewer into
#: a way to read the whole file into memory.
MAX_LIMIT = 1000

_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _read_last_lines(path: str, count: int) -> list[str]:
    """Return at most *count* trailing lines, without reading the whole file."""
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        end = handle.tell()
        blocks: list[bytes] = []
        newlines = 0
        while end > 0 and newlines <= count:
            size = min(_CHUNK, end)
            end -= size
            handle.seek(end)
            block = handle.read(size)
            newlines += block.count(b"\n")
            blocks.insert(0, block)

    text = b"".join(blocks).decode("utf-8", errors="replace")
    return text.splitlines()[-count:]


def _parse(line: str) -> dict[str, Any]:
    """Shape one raw line into a record.

    Handles both formats on purpose: a deployment may switch ``LOG_FORMAT`` at any
    time, and the file then holds a mixture. A line that is not JSON is still worth
    showing, so it is returned with its text intact and no parsed fields invented.
    """
    stripped = line.strip()
    if stripped.startswith("{"):
        try:
            record = json.loads(stripped)
        except ValueError:
            pass
        else:
            if isinstance(record, dict):
                return {
                    "timestamp": record.get("timestamp"),
                    "level": record.get("level"),
                    "logger": record.get("logger"),
                    "message": record.get("message"),
                    "parsed": True,
                    "raw": line,
                }

    # Text format: "<time> - <logger> - <LEVEL> - <func>:<lineno> - [<rid>] <msg>"
    level = next((lv for lv in _LEVELS if f" - {lv} - " in line), None)
    return {
        "timestamp": None,
        "level": level,
        "logger": None,
        "message": line,
        "parsed": False,
        "raw": line,
    }


def read_log_tail(
    path: str,
    limit: int = 200,
    level: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    """Return the tail of the log file, newest last, optionally filtered.

    Filtering happens after reading, so a narrow filter over a large file can return
    fewer than *limit* rows. That is honest about what was scanned rather than
    re-reading until the page is full.
    """
    limit = max(1, min(limit, MAX_LIMIT))

    try:
        # Read a wider window than requested when filtering, or a level filter over
        # a chatty log would return almost nothing.
        scan = limit if not (level or query) else min(limit * 10, MAX_LIMIT * 10)
        lines = _read_last_lines(path, scan)
    except FileNotFoundError:
        return {"records": [], "available": False, "reason": "log file does not exist"}
    except OSError as exc:
        logger.warning("Log viewer could not read %s: %s", path, exc)
        return {"records": [], "available": False, "reason": "log file is not readable"}

    records = [_parse(line) for line in lines if line.strip()]

    if level:
        wanted = level.upper()
        records = [r for r in records if r["level"] == wanted]
    if query:
        needle = query.lower()
        records = [r for r in records if needle in r["raw"].lower()]

    return {
        "records": records[-limit:],
        "available": True,
        "scanned": len(lines),
    }
