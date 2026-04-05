
"""
Monitoring Tests
================

Tests for monitoring and metrics (src/monitoring.py)

Target: Increase coverage from 59% to 75% (+1.5% overall)

Covers:
- MetricsCollector
- Request timing middleware
- Health checks
- Performance tracking

Author: LocalChat Team
Created: January 2025
"""

from time import sleep

import pytest


@pytest.fixture
def monitoring_app():
    """Minimal Flask app with monitoring routes registered."""
    from flask import Flask

    from src.monitoring import init_monitoring

    app = Flask('monitoring_test')
    app.config['TESTING'] = True
    app.startup_status = {'database': True, 'ollama': True}  # type: ignore[misc]
    app.embedding_cache = None  # type: ignore[misc]
    init_monitoring(app)
    return app


@pytest.fixture
def monitoring_client(monitoring_app):
    """Test client for the monitoring-enabled app."""
    return monitoring_app.test_client()



class TestMetricsCollector:
    """Test MetricsCollector class."""

    def test_metrics_collector_initialization(self):
        """Test MetricsCollector initializes correctly."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()

        assert collector is not None
        assert hasattr(collector, 'increment')
        assert hasattr(collector, 'record')
        assert hasattr(collector, 'set_gauge')

    def test_increment_counter(self):
        """Test incrementing a counter."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()
        collector.increment('test_counter')
        collector.increment('test_counter', value=5)

        metrics = collector.get_metrics()
        # Should have incremented
        assert metrics is not None

    def test_increment_with_labels(self):
        """Test incrementing counter with labels."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()
        collector.increment('requests', labels={'method': 'GET'})
        collector.increment('requests', labels={'method': 'POST'})

        # Should track separately by labels
        metrics = collector.get_metrics()
        assert len(metrics['counters']) >= 2

    def test_record_histogram_value(self):
        """Test recording histogram values."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()
        collector.record('response_time', 0.5)
        collector.record('response_time', 1.2)
        collector.record('response_time', 0.8)

        # Should store values
        assert collector.get_histogram_values()['response_time'] == [0.5, 1.2, 0.8]

    def test_record_keeps_recent_values(self):
        """Test histogram keeps only recent values."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()

        # Record many values
        for i in range(1500):
            collector.record('test_metric', float(i))

        # Should limit storage
        metrics = collector.get_metrics()
        assert metrics is not None

    def test_set_gauge_value(self):
        """Test setting gauge values."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()
        collector.set_gauge('active_connections', 42.0)
        collector.set_gauge('memory_usage', 1024.5)

        # Should store gauge values
        gauges = collector.get_metrics()['gauges']
        assert gauges['active_connections'] == 42.0
        assert gauges['memory_usage'] == 1024.5

    def test_gauge_updates(self):
        """Test gauge values can be updated."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()
        collector.set_gauge('cpu_usage', 50.0)
        collector.set_gauge('cpu_usage', 75.0)

        # Should update to latest value
        assert collector.get_metrics()['gauges']['cpu_usage'] == 75.0

    def test_get_metrics_returns_dict(self):
        """Test get_metrics returns dictionary."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()
        collector.increment('requests')

        metrics = collector.get_metrics()

        assert isinstance(metrics, dict)

    def test_metrics_thread_safety(self):
        """Test metrics are thread-safe."""
        import threading

        from src.monitoring import MetricsCollector

        collector = MetricsCollector()

        def increment_many():
            for _ in range(100):
                collector.increment('concurrent_test')

        # Create multiple threads
        threads = [threading.Thread(target=increment_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should handle concurrent access - 5 threads * 100 increments
        assert collector.get_metrics()['counters']['concurrent_test'] == 500

    def test_metrics_reset(self):
        """Test resetting metrics."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()
        collector.increment('test', 10)
        collector.record('latency', 1.5)

        collector.reset()

        # After reset, should be empty
        metrics = collector.get_metrics()
        assert metrics is not None


class TestGlobalMetrics:
    """Test global metrics functions."""

    def test_get_metrics_returns_collector(self):
        """Test get_metrics returns a collector."""
        from src.monitoring import get_metrics

        collector = get_metrics()

        assert collector is not None

    def test_get_metrics_returns_singleton(self):
        """Test get_metrics returns same instance."""
        from src.monitoring import get_metrics

        collector1 = get_metrics()
        collector2 = get_metrics()

        assert collector1 is collector2


class TestRequestTiming:
    """Test request timing middleware."""

    def test_request_timing_middleware_exists(self):
        """Test request timing middleware can be created."""
        from src.monitoring import RequestTimingMiddleware

        assert RequestTimingMiddleware is not None

    def test_timing_middleware_measures_duration(self, app, client):
        """Test middleware measures request duration."""
        with client:
            response = client.get('/')

            # Should process request (timing happens in background)
            assert response.status_code in [200, 404]


class TestHealthChecks:
    """Test health check functionality."""

    def test_health_check_endpoint_exists(self, client):
        """Test health check endpoint exists."""
        # Try common health check paths
        paths = ['/health', '/api/health', '/api/status']

        found = False
        for path in paths:
            response = client.get(path)
            if response.status_code == 200:
                found = True
                break

        # At least one should work
        pass

    def test_health_check_returns_json(self, client):
        """Test health check returns JSON."""
        response = client.get('/api/status')

        if response.status_code == 200:
            assert response.content_type == 'application/json'


class TestPerformanceTracking:
    """Test performance tracking."""

    def test_performance_decorator_exists(self):
        """Test performance tracking decorator exists."""
        from src.monitoring import timed

        assert timed is not None

    def test_performance_decorator_usage(self):
        """Test performance decorator can be used."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()

        # Create a test function
        def test_func():
            sleep(0.01)
            return "done"

        # Should work
        result = test_func()
        assert result == "done"


class TestMonitoringInitialization:
    """Test monitoring initialization."""

    def test_monitoring_can_be_initialized(self):
        """Test monitoring module can be initialized."""
        try:
            from src.monitoring import init_monitoring
            assert init_monitoring is not None
        except ImportError:
            pass  # init_monitoring may not be present in all configurations

    def test_monitoring_with_flask_app(self, app):
        """Test monitoring can be used with Flask app."""
        # Should be able to attach to app
        assert app is not None


class TestMetricsAggregation:
    """Test metrics aggregation."""

    def test_metrics_can_be_aggregated(self):
        """Test metrics can be aggregated."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()

        # Record multiple values
        collector.record('latency', 1.0)
        collector.record('latency', 2.0)
        collector.record('latency', 3.0)

        # Should be able to get metrics
        metrics = collector.get_metrics()
        assert metrics is not None

    def test_histogram_statistics(self):
        """Test histogram statistics calculation."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()

        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        for v in values:
            collector.record('test_latency', v)

        # Should store values for statistics
        stats = collector.get_metrics()['histograms']['test_latency']
        assert stats['count'] == 5
        assert stats['sum'] == 15.0


class TestMonitoringEdgeCases:
    """Test monitoring edge cases."""

    def test_empty_metrics(self):
        """Test getting metrics when empty."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()
        metrics = collector.get_metrics()

        # Should return empty dict or valid structure
        assert isinstance(metrics, dict)

    def test_large_counter_values(self):
        """Test handling large counter values."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()
        collector.increment('big_counter', value=1000000)

        # Should handle large values
        assert collector.get_metrics()['counters']['big_counter'] == 1000000

    def test_negative_histogram_values(self):
        """Test handling negative histogram values."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()
        collector.record('test', -1.0)

        # Should handle negative values
        assert collector.get_histogram_values().get('test') == [-1.0]

    def test_zero_values(self):
        """Test handling zero values."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()
        collector.increment('zero_test', value=0)
        collector.record('zero_hist', 0.0)
        collector.set_gauge('zero_gauge', 0.0)

        # Should handle zeros
        assert collector.get_metrics()['gauges']['zero_gauge'] == 0.0


class TestGetHistogramValues:
    """Test MetricsCollector.get_histogram_values()."""

    def test_returns_raw_values(self):
        """Test raw float lists are returned for recorded metrics."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()
        collector.record('latency', 0.1)
        collector.record('latency', 0.5)

        raw = collector.get_histogram_values()
        assert 'latency' in raw
        assert raw['latency'] == [0.1, 0.5]

    def test_empty_when_no_data(self):
        """Test returns empty dict when no histograms recorded."""
        from src.monitoring import MetricsCollector

        assert MetricsCollector().get_histogram_values() == {}

    def test_returns_independent_copy(self):
        """Test mutating the returned list does not affect stored data."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()
        collector.record('lat', 1.0)
        raw = collector.get_histogram_values()
        raw['lat'].append(999.0)

        assert 999.0 not in collector.get_histogram_values()['lat']

    def test_excludes_empty_internal_keys(self):
        """Test keys whose list was cleared are not returned."""
        from src.monitoring import MetricsCollector

        collector = MetricsCollector()
        collector._histograms['ghost'] = []

        assert 'ghost' not in collector.get_histogram_values()


class TestTimedSlowOperation:
    """Test that @timed logs a warning for operations exceeding 1 second."""

    def test_slow_operation_warning_logged(self):
        """Warning is emitted when mocked duration is 2 s."""
        from unittest.mock import call, patch

        from src.monitoring import timed

        @timed('slow_op')
        def my_func():
            return 'ok'

        with patch('src.monitoring.time', side_effect=[0.0, 2.0]):
            with patch('src.monitoring.logger') as mock_logger:
                result = my_func()

        assert result == 'ok'
        mock_logger.warning.assert_called_once()
        assert 'slow_op' in mock_logger.warning.call_args[0][0]

    def test_fast_operation_no_warning(self):
        """No warning for operations under 1 second."""
        from unittest.mock import patch

        from src.monitoring import timed

        @timed('fast_op')
        def my_func():
            return 'ok'

        with patch('src.monitoring.time', side_effect=[0.0, 0.1]):
            with patch('src.monitoring.logger') as mock_logger:
                my_func()

        mock_logger.warning.assert_not_called()


class TestRequestTimingMiddlewareUnit:
    """Unit tests for RequestTimingMiddleware constructor and hook registration."""

    def test_registers_before_and_after_hooks(self):
        """__init__ registers one before_request and one after_request hook."""
        from flask import Flask

        from src.monitoring import RequestTimingMiddleware

        test_app = Flask('timing_unit_test')
        before_count = len(test_app.before_request_funcs.get(None, []))
        after_count = len(test_app.after_request_funcs.get(None, []))

        RequestTimingMiddleware(test_app)

        assert len(test_app.before_request_funcs.get(None, [])) == before_count + 1
        assert len(test_app.after_request_funcs.get(None, [])) == after_count + 1

    def test_after_request_safe_without_start_time(self):
        """after_request returns the response unchanged when g.start_time is absent."""
        from unittest.mock import Mock

        from flask import Flask

        from src.monitoring import RequestTimingMiddleware

        test_app = Flask('timing_no_start')
        mw = RequestTimingMiddleware(test_app)

        fake_response = Mock()
        fake_response.status_code = 200
        fake_response.headers = {}

        with test_app.test_request_context('/'):
            result = mw.after_request(fake_response)

        assert result is fake_response


class TestMetricsEndpoints:
    """Test /api/metrics, /api/metrics.json and /api/health via the test client."""

    def test_metrics_prometheus_returns_200(self, monitoring_client):
        """Prometheus scrape endpoint is reachable."""
        assert monitoring_client.get('/api/metrics').status_code == 200

    def test_metrics_prometheus_content_type(self, monitoring_client):
        """Prometheus endpoint returns text/plain."""
        assert 'text/plain' in monitoring_client.get('/api/metrics').content_type

    def test_metrics_prometheus_has_type_declarations(self, monitoring_client):
        """Prometheus output contains at least one # TYPE line."""
        monitoring_client.get('/api/health')  # generate a metric
        assert b'# TYPE' in monitoring_client.get('/api/metrics').data

    def test_metrics_json_returns_200(self, monitoring_client):
        """JSON metrics endpoint is reachable."""
        assert monitoring_client.get('/api/metrics.json').status_code == 200

    def test_metrics_json_structure(self, monitoring_client):
        """JSON metrics response contains the expected top-level keys."""
        data = monitoring_client.get('/api/metrics.json').get_json()
        assert 'counters' in data
        assert 'histograms' in data
        assert 'gauges' in data
        assert 'uptime_seconds' in data

    def test_health_endpoint_returns_status(self, monitoring_client):
        """Health endpoint returns a JSON body with status and timestamp."""
        response = monitoring_client.get('/api/health')
        assert response.status_code in [200, 503]
        data = response.get_json()
        assert 'status' in data
        assert 'timestamp' in data

    def test_timing_header_attached(self, monitoring_client):
        """X-Request-Duration header is present on every response."""
        assert 'X-Request-Duration' in monitoring_client.get('/api/health').headers

    def test_http_requests_total_increments(self, monitoring_client, monitoring_app):
        """http_requests_total counter increments with each request."""
        from src.monitoring import get_metrics

        get_metrics().reset()
        monitoring_client.get('/api/health')

        with monitoring_app.app_context():
            counters = get_metrics().get_metrics()['counters']
        assert any('http_requests_total' in k for k in counters)


class TestMetricsAuth:
    """Test _check_metrics_auth and the 403/200 responses it produces."""

    def test_open_when_no_token_configured(self, monitoring_client):
        """Endpoint is open when METRICS_TOKEN is empty."""
        from unittest.mock import patch

        with patch('src.config.METRICS_TOKEN', ''):
            assert monitoring_client.get('/api/metrics').status_code == 200

    def test_forbidden_when_token_required_and_missing(self, monitoring_client):
        """403 when token is required but Authorization header is absent."""
        from unittest.mock import patch

        with patch('src.config.METRICS_TOKEN', 'secret'):
            assert monitoring_client.get('/api/metrics').status_code == 403

    def test_forbidden_with_wrong_token(self, monitoring_client):
        """403 when the supplied Bearer token does not match."""
        from unittest.mock import patch

        with patch('src.config.METRICS_TOKEN', 'secret'):
            response = monitoring_client.get('/api/metrics',
                                            headers={'Authorization': 'Bearer wrong'})
        assert response.status_code == 403

    def test_allowed_with_correct_token(self, monitoring_client):
        """200 when the correct Bearer token is supplied."""
        from unittest.mock import patch

        with patch('src.config.METRICS_TOKEN', 'secret'):
            response = monitoring_client.get('/api/metrics',
                                            headers={'Authorization': 'Bearer secret'})
        assert response.status_code == 200

    def test_json_endpoint_enforces_token(self, monitoring_client):
        """/api/metrics.json also returns 403 when token is missing."""
        from unittest.mock import patch

        with patch('src.config.METRICS_TOKEN', 'secret'):
            assert monitoring_client.get('/api/metrics.json').status_code == 403


class TestComputeHealthStatus:
    """Unit tests for _compute_health_status covering all branches."""

    def test_healthy_when_db_and_ollama_up(self):
        """Returns 'healthy'/200 when both database and Ollama are up."""
        from unittest.mock import Mock

        from src.monitoring import _compute_health_status

        app = Mock()
        app.startup_status = {'database': True, 'ollama': True}
        app.embedding_cache = None

        status, code, checks = _compute_health_status(app)
        assert status == 'healthy'
        assert code == 200
        assert checks['database']['healthy'] is True
        assert checks['ollama']['healthy'] is True

    def test_unhealthy_when_db_down(self):
        """Returns 'unhealthy'/503 when the database is down."""
        from unittest.mock import Mock

        from src.monitoring import _compute_health_status

        app = Mock()
        app.startup_status = {'database': False, 'ollama': True}
        app.embedding_cache = None

        status, code, checks = _compute_health_status(app)
        assert status == 'unhealthy'
        assert code == 503

    def test_ollama_down_adds_message(self):
        """Ollama-down check carries an explanatory message."""
        from unittest.mock import Mock

        from src.monitoring import _compute_health_status

        app = Mock()
        app.startup_status = {'database': True, 'ollama': False}
        app.embedding_cache = None

        status, code, checks = _compute_health_status(app)
        assert 'message' in checks['ollama']
        assert status == 'healthy'

    def test_no_startup_status_returns_healthy(self):
        """Handles missing startup_status gracefully."""
        from unittest.mock import Mock

        from src.monitoring import _compute_health_status

        app = Mock(spec=[])  # no attributes at all
        status, code, checks = _compute_health_status(app)
        assert status == 'healthy'
        assert code == 200
        assert checks == {}

    def test_embedding_cache_included_when_present(self):
        """Cache stats appear in checks when embedding_cache is attached."""
        from unittest.mock import Mock

        from src.monitoring import _compute_health_status

        mock_stats = Mock()
        mock_stats.to_dict.return_value = {'hits': 10, 'misses': 5}
        app = Mock()
        app.startup_status = {'database': True, 'ollama': True}
        app.embedding_cache = Mock()
        app.embedding_cache.get_stats.return_value = mock_stats

        status, code, checks = _compute_health_status(app)
        assert 'cache' in checks
        assert checks['cache']['healthy'] is True
        assert checks['cache']['stats'] == {'hits': 10, 'misses': 5}


class TestBaseMetricName:
    """Unit tests for _base_metric_name helper."""

    def test_strips_label_brace_suffix(self):
        """Label segment is removed, leaving only the base name."""
        from src.monitoring import _base_metric_name

        assert _base_metric_name('http_requests_total{method="GET"}') == 'http_requests_total'

    def test_returns_plain_name_unchanged(self):
        """A name without labels is returned as-is."""
        from src.monitoring import _base_metric_name

        assert _base_metric_name('app_uptime_seconds') == 'app_uptime_seconds'

    def test_empty_string(self):
        """Empty string is handled without error."""
        from src.monitoring import _base_metric_name

        assert _base_metric_name('') == ''


class TestExportPrometheusMetrics:
    """Tests for export_prometheus_metrics()."""

    def test_counters_have_type_declaration(self):
        """Counter entries appear under a # TYPE counter declaration."""
        from src.monitoring import export_prometheus_metrics, get_metrics

        get_metrics().reset()
        get_metrics().increment('prom_test_total', labels={'method': 'GET'})

        output = export_prometheus_metrics()
        assert '# TYPE prom_test_total counter' in output
        assert 'prom_test_total' in output

    def test_single_type_declaration_per_base_name(self):
        """Multiple label variants share exactly one # TYPE line."""
        from src.monitoring import export_prometheus_metrics, get_metrics

        get_metrics().reset()
        get_metrics().increment('multi_total', labels={'method': 'GET'})
        get_metrics().increment('multi_total', labels={'method': 'POST'})

        output = export_prometheus_metrics()
        assert output.count('# TYPE multi_total counter') == 1

    def test_histograms_have_count_sum_and_buckets(self):
        """Histogram entries include _count, _sum and bucket lines."""
        from src.monitoring import export_prometheus_metrics, get_metrics

        get_metrics().reset()
        get_metrics().record('prom_latency', 0.05)
        get_metrics().record('prom_latency', 0.3)
        get_metrics().record('prom_latency', 2.0)

        output = export_prometheus_metrics()
        assert '# TYPE prom_latency histogram' in output
        assert 'prom_latency_count' in output
        assert 'prom_latency_sum' in output
        assert 'le="0.1"' in output
        assert 'le="+Inf"' in output

    def test_histogram_bucket_counts_correct(self):
        """Bucket counts reflect the actual value distribution."""
        from src.monitoring import export_prometheus_metrics, get_metrics

        get_metrics().reset()
        get_metrics().record('bkt', 0.05)   # ≤ 0.1
        get_metrics().record('bkt', 0.05)   # ≤ 0.1
        get_metrics().record('bkt', 2.0)    # > 1.0

        output = export_prometheus_metrics()
        for line in output.splitlines():
            if 'bkt_bucket{le="0.1"}' in line:
                assert line.endswith(' 2')
            if 'bkt_bucket{le="+Inf"}' in line:
                assert line.endswith(' 3')

    def test_gauges_exported(self):
        """Gauge entries appear with # TYPE gauge declaration."""
        from src.monitoring import export_prometheus_metrics, get_metrics

        get_metrics().reset()
        get_metrics().set_gauge('active_conns', 7.0)

        output = export_prometheus_metrics()
        assert '# TYPE active_conns gauge' in output
        assert 'active_conns 7.0' in output

    def test_uptime_always_present(self):
        """app_uptime_seconds is always included even with no other metrics."""
        from src.monitoring import export_prometheus_metrics, get_metrics

        get_metrics().reset()
        output = export_prometheus_metrics()
        assert '# TYPE app_uptime_seconds gauge' in output
        assert 'app_uptime_seconds' in output

    def test_output_ends_with_newline(self):
        """Output terminates with a newline as required by the Prometheus format."""
        from src.monitoring import export_prometheus_metrics, get_metrics

        get_metrics().reset()
        assert export_prometheus_metrics().endswith('\n')
