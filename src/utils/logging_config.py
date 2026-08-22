"""
Logging Utility Module
=====================

Provides structured logging configuration for the LocalChat application.
Implements rotating file handlers and consistent formatting across all modules.

Example:
    >>> from utils.logging_config import get_logger
    >>> logger = get_logger(__name__)
    >>> logger.info("Application started")
"""

import atexit
import functools
import json
import logging
import logging.handlers
import re
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Everything that can start a new line in a log consumer, or drive a terminal.
#: C0 controls (CR, LF, VT, FF, ESC, the file/group/record separators), DEL, the C1
#: range (NEL is 0x85), and the Unicode line/paragraph separators.
_LOG_UNSAFE = re.compile(r'[\x00-\x1f\x7f-\x9f\u2028\u2029]')


def sanitize_log_value(value: object) -> str:
    """Flatten a user-supplied value before embedding it in a log message.

    Stripping CR/LF alone is not enough, which is what this used to do.
    `str.splitlines()` — and most log consumers — also break on VT, FF, the ASCII
    separators, NEL and U+2028/U+2029, so a message containing any of them still
    forged new log records. ESC survived too, letting a crafted value clear or
    overwrite lines in anyone's terminal when they read the log.
    """
    return _LOG_UNSAFE.sub(' ', str(value))


class SafeStreamHandler(logging.StreamHandler):
    """
    StreamHandler that silently drops 'I/O operation on closed file' errors.

    During interpreter shutdown (or pytest teardown), the stream held by this
    handler can be closed before all atexit/teardown callbacks have finished.
    The base class would then print a noisy --- Logging error --- traceback to
    stderr via handleError().  We suppress only that specific case.
    """

    def handleError(self, record: logging.LogRecord) -> None:
        t, v, _ = sys.exc_info()
        if t is ValueError and "closed file" in str(v):
            return  # silently ignore — stream was closed during teardown
        super().handleError(record)


class JsonFormatter(logging.Formatter):
    """
    Emit each log record as a single JSON line.

    Fields: timestamp (ISO-8601), level, logger, message, module,
    funcName, lineno, and — when available on the record — request_id.

    Enable by setting ``LOG_FORMAT=json`` in the environment.  Recommended
    for production deployments feeding logs into an aggregator (Loki,
    Elasticsearch, CloudWatch, etc.).
    """

    # Standard LogRecord attributes that should not be re-emitted as extras.
    _STANDARD_ATTRS: frozenset[str] = frozenset({
        "name", "msg", "args", "created", "filename", "funcName", "levelname",
        "levelno", "lineno", "module", "msecs", "message", "pathname",
        "process", "processName", "relativeCreated", "stack_info", "thread",
        "threadName", "exc_info", "exc_text", "request_id", "user_agent",
    })

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
            "lineno": record.lineno,
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        user_agent = getattr(record, "user_agent", None)
        if user_agent:
            payload["user_agent"] = user_agent
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Emit any caller-supplied extra fields (e.g. duration_ms, model, chunks_retrieved)
        for key, value in record.__dict__.items():
            if key not in self._STANDARD_ATTRS and not key.startswith("_") and value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


class RequestIdFilter(logging.Filter):
    """Copies the current request ID onto every log record.

    Reads from request_id_var (set by RequestIdMiddleware). Falls back to an
    empty string outside a request context — tests, background threads, startup.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        from .request_id import request_id_var
        record.request_id = request_id_var.get()
        record.user_agent = ""
        return True


class ColoredFormatter(logging.Formatter):
    """Colored console formatter for better readability."""

    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'        # Reset
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors."""
        # Add color to level name
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"

        # Format message
        formatted = super().format(record)

        # Reset color at end
        return formatted


#: Records emitted before setup_logging() runs are held here and replayed into the
#: real handlers once they exist. Bounded so a process that never configures
#: logging cannot grow this without limit; startup emits ~20 records at INFO and
#: above, so this is headroom rather than a working limit.
_MAX_STARTUP_RECORDS = 500


class _StartupBuffer(logging.Handler):
    """Captures log records emitted before setup_logging() installs the handlers.

    Module import and create_app() both log before bootstrap_app() configures
    logging. Without this, those records are lost two different ways: INFO and
    below never reach a handler at all (the root logger defaults to WARNING), and
    WARNING and above go to logging's last-resort stderr writer — unformatted, so
    not JSON, and never written to the log file. That silently applied to the
    [Security] messages validate_secrets() emits before aborting a production boot.
    """

    def __init__(self) -> None:
        # INFO and above only. create_app() alone emits ~1300 records, 491 of them
        # DEBUG, which at NOTSET filled the buffer during import and evicted the
        # very startup lines this exists to preserve. The desired level is not
        # knowable before setup_logging() reads it from config anyway.
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []
        self.dropped = 0

    def emit(self, record: logging.LogRecord) -> None:
        if len(self.records) >= _MAX_STARTUP_RECORDS:
            self.dropped += 1
            return
        self.records.append(record)


def _install_startup_buffer() -> _StartupBuffer:
    buffer = _StartupBuffer()
    root_logger = logging.getLogger()
    root_logger.addHandler(buffer)
    # A logger drops records below its own level before any handler sees them, so
    # the root default of WARNING would hide exactly the INFO this buffer exists
    # to keep. INFO rather than DEBUG so the ~1275 DEBUG records the markdown
    # library emits during import are never materialised at all.
    # setup_logging() sets the real level moments later.
    root_logger.setLevel(logging.INFO)
    # Attaching any handler suppresses logging's last-resort stderr writer, which
    # is what carried WARNING and above until now. Without this the buffer would
    # swallow them outright whenever setup_logging() never runs.
    atexit.register(_flush_startup_buffer_to_stderr)
    return buffer


def _flush_startup_buffer_to_stderr() -> None:
    """Safety net for a process that exits before setup_logging() runs.

    validate_secrets() aborts a misconfigured production boot from inside
    create_app(), which is before bootstrap_app() configures logging — so the
    [Security] record explaining the exit would otherwise die with the buffer.
    Mirrors the last-resort behaviour this buffer displaces: WARNING and above,
    to stderr, unformatted.
    """
    global _startup_buffer
    buffer, _startup_buffer = _startup_buffer, None
    if buffer is None:
        return

    logging.getLogger().removeHandler(buffer)
    for record in buffer.records:
        if record.levelno >= logging.WARNING:
            sys.stderr.write(f"{record.levelname}: {record.getMessage()}\n")


_startup_buffer: _StartupBuffer | None = _install_startup_buffer()


def _replay_startup_buffer() -> None:
    """Flush anything logged before setup_logging() into the configured handlers."""
    global _startup_buffer
    buffer, _startup_buffer = _startup_buffer, None
    if buffer is None:
        return

    root_logger = logging.getLogger()
    root_logger.removeHandler(buffer)
    for record in buffer.records:
        for handler in root_logger.handlers:
            if record.levelno >= handler.level:
                handler.handle(record)
    if buffer.dropped:
        root_logger.warning(
            "Startup log buffer overflowed — %d early record(s) were dropped",
            buffer.dropped,
        )


#: Sinks setup_logging() knows how to build. "console" is stdout/stderr, which the
#: container runtime collects; "file" is the rotating local log; "syslog" ships to a
#: SOC/SIEM collector. Anything else is rejected loudly rather than ignored.
_KNOWN_SINKS = ("console", "file", "syslog")


def _text_formatter() -> logging.Formatter:
    return logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d"
        " - [%(request_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _parse_syslog_address(address: str) -> str | tuple[str, int]:
    """Return a Unix socket path, or a (host, port) pair for a network collector."""
    if ":" not in address:
        return address
    host, _, port = address.rpartition(":")
    return (host, int(port))


def _build_file_handler(
    log_file: str, max_bytes: int, backup_count: int, use_json: bool
) -> logging.Handler:
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    # DEBUG deliberately: the file is the troubleshooting record and holds strictly
    # more than the console, which sits at INFO. Rotation is what keeps that bounded.
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(JsonFormatter() if use_json else _text_formatter())
    return handler


def _build_console_handler(use_json: bool) -> logging.Handler:
    handler = SafeStreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        JsonFormatter() if use_json else ColoredFormatter("%(levelname)s - %(name)s - %(message)s")
    )
    return handler


def _build_syslog_handler(address: str, protocol: str) -> logging.Handler:
    import socket

    proto = socket.SOCK_STREAM if protocol.lower() == "tcp" else socket.SOCK_DGRAM
    handler = logging.handlers.SysLogHandler(
        address=_parse_syslog_address(address), socktype=proto
    )
    handler.setLevel(logging.INFO)
    # Always JSON: a SIEM parses fields, it does not read prose.
    handler.setFormatter(JsonFormatter())
    return handler


#: Libraries that log at INFO or DEBUG about their own internals. httpx narrates
#: every request the app makes; the markdown extension registry emits ~1275 DEBUG
#: records per boot. Together they were the bulk of the log file, which matters
#: twice over: they crowd out the application's own records inside a bounded
#: rotation, and their messages never pass through this project's log sanitiser —
#: httpx logs full URLs, query string included, which is how third-party signed
#: URLs ended up on disk.
_NOISY_THIRD_PARTY = (
    "httpx",
    "httpcore",
    "huggingface_hub",
    "sentence_transformers",
    "urllib3",
    "MARKDOWN",
    "PIL",
    "matplotlib",
)


def _quieten_third_party(level: str) -> None:
    """Raise the floor for libraries that narrate their own internals."""
    if not level:
        return
    resolved = getattr(logging, level.upper(), None)
    if not isinstance(resolved, int):
        return
    for name in _NOISY_THIRD_PARTY:
        logging.getLogger(name).setLevel(resolved)


def setup_logging(
    log_level: str = "INFO",
    log_file: str = "logs/app.log",
    max_bytes: int = 4 * 1024 * 1024,
    backup_count: int = 4,
    log_format: str = "text",
    sinks: Sequence[str] = ("console", "file"),
    syslog_address: str = "",
    syslog_protocol: str = "udp",
    third_party_level: str = "WARNING",
) -> logging.Logger:
    """Configure application-wide logging across the requested sinks.

    A sink that cannot be built is reported and skipped — logging is diagnostics,
    and losing a diagnostic channel is never a reason to take the application
    down. An unwritable log file used to crash-loop the container.

    Args:
        log_level: Minimum level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Path to the rotating log file, when the ``file`` sink is active.
        max_bytes: Size at which the log file rotates.
        backup_count: Rotated files retained. Disk ceiling is
            ``max_bytes * (1 + backup_count)`` — bounded on purpose, since log
            volume is driven by request volume and an attacker controls that.
        log_format: ``'json'`` for JSON lines, ``'text'`` for human-readable.
        sinks: Any of ``console``, ``file``, ``syslog``.
        syslog_address: ``host:port`` or a Unix socket path such as ``/dev/log``.
        syslog_protocol: ``udp`` or ``tcp``.

    Returns:
        Configured root logger.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    root_logger.handlers.clear()

    request_id_filter = RequestIdFilter()
    use_json = log_format.lower() == "json"
    requested = [s.strip().lower() for s in sinks if s and s.strip()]

    builders = {
        # Console first: it is the sink least able to fail, so a later sink's
        # failure has somewhere to be reported.
        "console": lambda: _build_console_handler(use_json),
        "file": lambda: _build_file_handler(log_file, max_bytes, backup_count, use_json),
        "syslog": lambda: _build_syslog_handler(syslog_address, syslog_protocol),
    }

    active: list[str] = []
    failed: list[tuple[str, str]] = []
    for name in _KNOWN_SINKS:
        if name not in requested:
            continue
        try:
            handler = builders[name]()
        except Exception as exc:
            failed.append((name, f"{type(exc).__name__}: {exc}"))
            continue
        handler.addFilter(request_id_filter)
        root_logger.addHandler(handler)
        active.append(name)

    _quieten_third_party(third_party_level)

    _replay_startup_buffer()

    for name, reason in failed:
        root_logger.error(
            "Logging sink %r unavailable — continuing without it: %s", name, reason
        )
    for name in requested:
        if name not in _KNOWN_SINKS:
            root_logger.error("Unknown logging sink %r — ignored", name)
    if not active and logging.lastResort is not None:
        # Every sink failed. Fall back to stderr for WARNING and above rather than
        # running blind.
        root_logger.addHandler(logging.lastResort)

    root_logger.info(
        "Logging system initialized (format=%s, sinks=%s)",
        log_format,
        ",".join(active) or "none",
    )
    if "file" in active:
        root_logger.debug(
            "Log file: %s | level: %s | ceiling: %d bytes",
            log_file,
            log_level,
            max_bytes * (1 + backup_count),
        )
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.

    Args:
        name: Logger name (typically __name__ of the module)

    Returns:
        Logger instance

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Module initialized")
    """
    return logging.getLogger(name)


def log_function_call(func: Callable) -> Callable:
    """
    Decorator to log function calls with arguments and results.

    Args:
        func: Function to decorate

    Returns:
        Wrapped function

    Example:
        >>> @log_function_call
        ... def my_function(x, y):
        ...     return x + y
    """
    logger = get_logger(func.__module__)

    @functools.wraps(func)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        logger.debug(f"Calling {func.__name__} with args={args}, kwargs={kwargs}")
        try:
            result = func(*args, **kwargs)
            logger.debug(f"{func.__name__} returned {result}")
            return result
        except Exception as e:
            logger.exception("%s raised %s", func.__name__, type(e).__name__)
            raise

    return wrapper



