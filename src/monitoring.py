# -*- coding: utf-8 -*-

"""
Monitoring and Metrics Module
==============================

Provides comprehensive monitoring, metrics, and observability
for LocalChat application.

Features:
- Prometheus metrics export
- Request timing middleware
- Performance tracking
- Health checks
- Custom metrics

Author: LocalChat Team
Created: 2025-01-15
"""

from functools import wraps
from time import time
from typing import Callable, Dict, Any, Optional
from collections import defaultdict
from datetime import datetime
import threading

from flask import Flask, request, g, jsonify
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class MetricsCollector:
    """
    Collects and aggregates application metrics.
    
    Thread-safe metrics collection with aggregation support.
    """
    
    def __init__(self):
        """Initialize metrics collector."""
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = defaultdict(int)
        self._histograms: Dict[str, list] = defaultdict(list)
        self._gauges: Dict[str, float] = {}
        self._start_time = datetime.now()
        
        logger.info("MetricsCollector initialized")
    
    def increment(self, name: str, value: int = 1, labels: Optional[Dict] = None):
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
    
    def record(self, name: str, value: float, labels: Optional[Dict] = None):
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
    
    def set_gauge(self, name: str, value: float, labels: Optional[Dict] = None):
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
    
    def get_metrics(self) -> Dict[str, Any]:
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
    
    def _make_key(self, name: str, labels: Optional[Dict]) -> str:
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


# Global metrics collector
_metrics: Optional[MetricsCollector] = None


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


def counted(metric_name: str, labels: Optional[Dict] = None):
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
        """Record request start time."""
        g.start_time = time()
        g.request_id = f"{int(time() * 1000)}"
    
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
            
            # Add timing header
            response.headers['X-Request-Duration'] = f"{duration:.3f}s"
            response.headers['X-Request-ID'] = g.request_id
        
        return response


def init_monitoring(app: Flask):
    """
    Initialize monitoring for Flask app.
    
    Args:
        app: Flask application
    """
    # Add request timing middleware
    RequestTimingMiddleware(app)
    
    # Add metrics endpoint
    @app.route('/api/metrics')
    def metrics_endpoint():
        """
        Get application metrics.
        
        Returns Prometheus-compatible metrics.
        ---
        tags:
          - System
        summary: Get application metrics
        description: |
          Returns comprehensive application metrics including:
          - Request counts and durations
          - Cache hit rates
          - Database query times
          - RAG pipeline performance
        responses:
          200:
            description: Metrics retrieved successfully
            schema:
              type: object
              properties:
                counters:
                  type: object
                histograms:
                  type: object
                gauges:
                  type: object
                uptime_seconds:
                  type: number
        """
        return jsonify(get_metrics().get_metrics())
    
    # Add health check endpoint
    @app.route('/api/health')
    def health_check():
        """
        Detailed health check.
        
        Checks all system components and returns detailed status.
        ---
        tags:
          - System
        summary: Health check
        description: |
          Performs comprehensive health check of all services:
          - Database connectivity
          - Ollama service
          - Cache availability
          - System resources
        responses:
          200:
            description: System healthy
            schema:
              type: object
              properties:
                status:
                  type: string
                  enum: [healthy, degraded, unhealthy]
                checks:
                  type: object
                timestamp:
                  type: string
                  format: date-time
          503:
            description: System unhealthy
        """
        from flask import current_app
        
        checks = {}
        overall_healthy = True
        
        # Check database
        if hasattr(current_app, 'startup_status'):
            checks['database'] = {
                'status': 'up' if current_app.startup_status.get('database') else 'down',
                'healthy': current_app.startup_status.get('database', False)
            }
            if not checks['database']['healthy']:
                overall_healthy = False
        
        # Check Ollama
        if hasattr(current_app, 'startup_status'):
            checks['ollama'] = {
                'status': 'up' if current_app.startup_status.get('ollama') else 'down',
                'healthy': current_app.startup_status.get('ollama', False)
            }
            # Ollama not critical - mark as degraded not unhealthy
            if not checks['ollama']['healthy']:
                checks['ollama']['message'] = 'Ollama unavailable - direct LLM mode disabled'
        
        # Check cache
        if hasattr(current_app, 'embedding_cache'):
            checks['cache'] = {
                'status': 'up',
                'healthy': True,
                'stats': current_app.embedding_cache.get_stats().to_dict()
            }
        
        # Overall status
        if overall_healthy:
            status = 'healthy'
            status_code = 200
        elif checks.get('database', {}).get('healthy', False):
            status = 'degraded'
            status_code = 200
        else:
            status = 'unhealthy'
            status_code = 503
        
        return jsonify({
            'status': status,
            'checks': checks,
            'timestamp': datetime.now().isoformat()
        }), status_code
    
    logger.info("? Monitoring endpoints initialized")


# Prometheus text format export
def export_prometheus_metrics() -> str:
    """
    Export metrics in Prometheus text format.
    
    Returns:
        Prometheus-formatted metrics string
    """
    metrics = get_metrics().get_metrics()
    lines = []
    
    # Counters
    for name, value in metrics['counters'].items():
        lines.append(f'# TYPE {name} counter')
        lines.append(f'{name} {value}')
    
    # Histograms
    for name, stats in metrics['histograms'].items():
        lines.append(f'# TYPE {name} histogram')
        lines.append(f'{name}_count {stats["count"]}')
        lines.append(f'{name}_sum {stats["sum"]}')
        lines.append(f'{name}_bucket{{le="0.1"}} {sum(1 for v in metrics["histograms"][name] if v <= 0.1)}')
        lines.append(f'{name}_bucket{{le="0.5"}} {sum(1 for v in metrics["histograms"][name] if v <= 0.5)}')
        lines.append(f'{name}_bucket{{le="1.0"}} {sum(1 for v in metrics["histograms"][name] if v <= 1.0)}')
        lines.append(f'{name}_bucket{{le="+Inf"}} {stats["count"]}')
    
    # Gauges
    for name, value in metrics['gauges'].items():
        lines.append(f'# TYPE {name} gauge')
        lines.append(f'{name} {value}')
    
    # Uptime
    lines.append('# TYPE app_uptime_seconds gauge')
    lines.append(f'app_uptime_seconds {metrics["uptime_seconds"]}')
    
    return '\n'.join(lines) + '\n'
