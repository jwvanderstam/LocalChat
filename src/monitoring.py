
"""
Monitoring and Metrics Module
==============================

Provides comprehensive monitoring, metrics, and observability
for the LocalChat application.

Endpoints registered by ``init_monitoring()``::

    GET /api/metrics       — Prometheus text format v0.0.4 scrape endpoint
    GET /api/metrics.json  — JSON metrics snapshot for the admin dashboard
    GET /api/health        — Detailed component health check

Features:
- Prometheus metrics export (counters, histograms with buckets, gauges)
- Request timing middleware (``X-Request-Duration`` header on every response)
- Detailed health checks (database, Ollama, embedding cache)
- GPU-aware health reporting via Ollama ``/api/ps`` data in health checks
- Performance tracking decorators (``@timed``, ``@counted``)
- Optional Bearer-token authentication for scrape endpoints (``METRICS_TOKEN``)
- Thread-safe ``MetricsCollector`` with per-key label support
- ``app_uptime_seconds`` gauge always present in Prometheus output

"""

import threading
from collections import defaultdict
from datetime import datetime
from functools import wraps
from time import time
from typing import Any, Callable, Dict, Optional

from flask import Flask, g, jsonify, request

from .utils.logging_config import get_logger

logger = get_logger(__name__)


class MetricsCollector:
    """
    Collects and aggregates application metrics.

    Thread-safe metrics collection with aggregation support.
    """

    def __init__(self):
        """Initialize metrics collector."""
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._histograms: dict[str, list] = defaultdict(list)
        self._gauges: dict[str, float] = {}
        self._start_time = datetime.now()

        logger.info("MetricsCollector initialized")

    def increment(self, name: str, value: int = 1, labels: dict | None = None):
        """
        Increment a counter.

        Args:
            name: Metric name
            value: Increment value
            labels: Optional labels dict
        """
        with self._lock:
            key = self._make_key(name, labels)
            self._counters[key] += value

    def record(self, name: str, value: float, labels: dict | None = None):
        """
        Record a histogram value.

        Args:
            name: Metric name
            value: Value to record
            labels: Optional labels dict
        """
        with self._lock:
            key = self._make_key(name, labels)
            self._histograms[key].append(value)

            # Keep last 1000 values
            if len(self._histograms[key]) > 1000:
                self._histograms[key] = self._histograms[key][-1000:]

    def set_gauge(self, name: str, value: float, labels: dict | None = None):
        """
        Set a gauge value.

        Args:
            name: Metric name
            value: Gauge value
            labels: Optional labels dict
        """
        with self._lock:
            key = self._make_key(name, labels)
            self._gauges[key] = value

    def get_metrics(self) -> dict[str, Any]:
        """
        Get all metrics in Prometheus format.

        Returns:
            Dictionary of metrics
        """
        with self._lock:
            metrics = {
                'counters': dict(self._counters),
                'histograms': {},
                'gauges': dict(self._gauges),
                'uptime_seconds': (datetime.now() - self._start_time).total_seconds()
            }

            # Calculate histogram statistics
            for key, values in self._histograms.items():
                if values:
                    metrics['histograms'][key] = {
                        'count': len(values),
                        'sum': sum(values),
                        'min': min(values),
                        'max': max(values),
                        'avg': sum(values) / len(values),
                        'p50': self._percentile(values, 50),
                        'p95': self._percentile(values, 95),
                        'p99': self._percentile(values, 99),
                    }

            return metrics

    def _make_key(self, name: str, labels: dict | None) -> str:
        """Create metric key with labels."""
        if not labels:
            return name

        label_str = ','.join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f'{name}{{{label_str}}}'

    def _percentile(self, values: list, percentile: int) -> float:
        """Calculate percentile."""
        sorted_values = sorted(values)
        index = int(len(sorted_values) * (percentile / 100.0))
        return sorted_values[min(index, len(sorted_values) - 1)]

    def reset(self):
        """Reset all metrics."""
        with self._lock:
            self._counters.clear()
            self._histograms.clear()
            self._gauges.clear()
            self._start_time = datetime.now()

    def get_histogram_values(self) -> dict[str, list]:
        """Return a snapshot of raw histogram value lists (for Prometheus bucket export)."""
        with self._lock:
            return {k: list(v) for k, v in self._histograms.items() if v}


# Global metrics collector
_metrics: MetricsCollector | None = None


def get_metrics() -> MetricsCollector:
    """Get global metrics collector."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics


def timed(metric_name: str):
    """
    Decorator to time function execution.

    Args:
        metric_name: Name for the timing metric

    Example:
        >>> @timed('rag.retrieve')
        >>> def retrieve_context(query):
        >>>     ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time() - start
                get_metrics().record(metric_name, duration)

                if duration > 1.0:  # Log slow operations
                    logger.warning(f"Slow operation: {metric_name} took {duration:.2f}s")

        return wrapper
    return decorator


def counted(metric_name: str, labels: dict | None = None):
    """
    Decorator to count function calls.

    Args:
        metric_name: Name for the counter metric
        labels: Optional labels

    Example:
        >>> @counted('api.requests', labels={'endpoint': 'chat'})
        >>> def chat():
        >>>     ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            get_metrics().increment(metric_name, labels=labels)
            return func(*args, **kwargs)

        return wrapper
    return decorator


class RequestTimingMiddleware:
    """
    Middleware to track request timing and metrics.

    Automatically instruments all requests with timing data.
    """

    def __init__(self, app: Flask):
        """
        Initialize middleware.

        Args:
            app: Flask application
        """
        self.app = app
        app.before_request(self.before_request)
        app.after_request(self.after_request)

        logger.info("RequestTimingMiddleware initialized")

    def before_request(self):
        """Record request start time; request_id is already on g via RequestIdMiddleware."""
        g.start_time = time()

    def after_request(self, response):
        """Record request metrics."""
        if hasattr(g, 'start_time'):
            duration = time() - g.start_time

            # Record metrics
            metrics = get_metrics()

            # Request duration
            metrics.record('http_request_duration_seconds', duration, labels={
                'method': request.method,
                'endpoint': request.endpoint or 'unknown',
                'status': response.status_code
            })

            # Request counter
            metrics.increment('http_requests_total', labels={
                'method': request.method,
                'endpoint': request.endpoint or 'unknown',
                'status': response.status_code
            })

            # Add timing header; request_id header is handled by RequestIdMiddleware
            response.headers['X-Request-Duration'] = f"{duration:.3f}s"

        return response


def _check_metrics_auth() -> bool:
    """
    Return True if the request is authorised to read metrics.

    When ``METRICS_TOKEN`` is configured the caller must supply it as a
    Bearer token (``Authorization: Bearer <token>``).  When the config value
    is empty the endpoint is open — acceptable when it is only reachable from
    a private network or a dedicated scrape interface.
    """
    from . import config
    if not config.METRICS_TOKEN:
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:] == config.METRICS_TOKEN:
        return True
    return False


def init_monitoring(app: Flask):
    """
    Initialize monitoring for Flask app.

    Registers:
      * ``/api/metrics``       — Prometheus text format (scrape endpoint)
      * ``/api/metrics.json``  — JSON metrics for the admin dashboard
      * ``/api/health``        — Detailed health check

    Args:
        app: Flask application
    """
    # Attach timing middleware
    RequestTimingMiddleware(app)

    @app.route('/api/metrics', methods=['GET'])
    def metrics_endpoint():
        """
        Prometheus-compatible metrics scrape endpoint.

        Returns text/plain in the Prometheus exposition format (v0.0.4).
        Requires a Bearer token when ``METRICS_TOKEN`` is set.
        ---
        tags:
          - System
        """
        if not _check_metrics_auth():
            return "Forbidden", 403, {"WWW-Authenticate": 'Bearer realm="metrics"'}
        text = export_prometheus_metrics()
        return text, 200, {"Content-Type": "text/plain; version=0.0.4; charset=utf-8"}

    @app.route('/api/metrics.json', methods=['GET'])
    def metrics_json_endpoint():
        """
        JSON metrics endpoint — used internally by the admin dashboard.
        Requires the same optional token as /api/metrics.
        ---
        tags:
          - System
        """
        if not _check_metrics_auth():
            return jsonify({"error": "Forbidden"}), 403
        return jsonify(get_metrics().get_metrics())

    @app.route('/api/health', methods=['GET'])
    def health_check():
        """
        Detailed health check.

        Checks all system components and returns detailed status.
        ---
        tags:
          - System
        summary: Health check
        responses:
          200:
            description: System healthy or degraded
          503:
            description: System unhealthy (database down)
        """
        from flask import current_app
        status, status_code, checks = _compute_health_status(current_app)
        return (
            jsonify({"status": status, "checks": checks,
                     "timestamp": datetime.now().isoformat()}),
            status_code,
        )

    logger.info("✓ Monitoring endpoints initialized")


def _compute_health_status(app) -> tuple:
    """Compute health status dict from app startup_status. Returns (status, code, checks)."""
    checks = {}
    overall_healthy = True
    if hasattr(app, 'startup_status'):
        db_up = app.startup_status.get('database', False)
        checks['database'] = {'status': 'up' if db_up else 'down', 'healthy': db_up}
        if not db_up:
            overall_healthy = False
        ollama_up = app.startup_status.get('ollama', False)
        checks['ollama'] = {'status': 'up' if ollama_up else 'down', 'healthy': ollama_up}
        if not ollama_up:
            checks['ollama']['message'] = 'Ollama unavailable - direct LLM mode disabled'
    if getattr(app, 'embedding_cache', None) is not None:
        checks['cache'] = {'status': 'up', 'healthy': True, 'stats': app.embedding_cache.get_stats().to_dict()}
    if overall_healthy:
        return 'healthy', 200, checks
    if checks.get('database', {}).get('healthy', False):
        return 'degraded', 200, checks
    return 'unhealthy', 503, checks


# Prometheus text format export
def _base_metric_name(key: str) -> str:
    """Strip label suffix from a storage key to get the Prometheus base name."""
    brace = key.find('{')
    return key[:brace] if brace != -1 else key


def export_prometheus_metrics() -> str:
    """
    Export metrics in Prometheus text format.

    Returns:
        Prometheus-formatted metrics string
    """
    collector = get_metrics()
    metrics = collector.get_metrics()
    raw_histograms = collector.get_histogram_values()
    lines = []

    # Counters — one TYPE declaration per base name, all label variants beneath it
    counter_groups: dict[str, dict[str, int]] = {}
    for key, value in metrics['counters'].items():
        counter_groups.setdefault(_base_metric_name(key), {})[key] = value
    for base_name, entries in counter_groups.items():
        lines.append(f'# TYPE {base_name} counter')
        for key, value in entries.items():
            lines.append(f'{key} {value}')

    # Histograms
    histogram_groups: dict[str, dict] = {}
    for key, stats in metrics['histograms'].items():
        histogram_groups.setdefault(_base_metric_name(key), {})[key] = stats
    for base_name, entries in histogram_groups.items():
        lines.append(f'# TYPE {base_name} histogram')
        for key, stats in entries.items():
            raw = raw_histograms.get(key, [])
            lines.append(f'{key}_count {stats["count"]}')
            lines.append(f'{key}_sum {stats["sum"]}')
            lines.append(f'{key}_bucket{{le="0.1"}} {sum(1 for v in raw if v <= 0.1)}')
            lines.append(f'{key}_bucket{{le="0.5"}} {sum(1 for v in raw if v <= 0.5)}')
            lines.append(f'{key}_bucket{{le="1.0"}} {sum(1 for v in raw if v <= 1.0)}')
            lines.append(f'{key}_bucket{{le="+Inf"}} {stats["count"]}')

    # Gauges
    gauge_groups: dict[str, dict[str, float]] = {}
    for key, value in metrics['gauges'].items():
        gauge_groups.setdefault(_base_metric_name(key), {})[key] = value
    for base_name, entries in gauge_groups.items():
        lines.append(f'# TYPE {base_name} gauge')
        for key, value in entries.items():
            lines.append(f'{key} {value}')

    # Uptime
    lines.append('# TYPE app_uptime_seconds gauge')
    lines.append(f'app_uptime_seconds {metrics["uptime_seconds"]}')

    return '\n'.join(lines) + '\n'
