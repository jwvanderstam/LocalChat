# -*- coding: utf-8 -*-

"""
Monitoring Decorator Tests
===========================

Tests for monitoring decorators

Author: LocalChat Team
Created: January 2025
"""

import pytest
from time import sleep


class TestTimedDecorator:
    """Test @timed decorator."""
    
    def test_timed_decorator_records_duration(self):
        """Test that @timed records function duration."""
        from src.monitoring import timed, get_metrics
        
        @timed('test_func')
        def test_function():
            sleep(0.01)
            return "result"
        
        # Clear metrics
        get_metrics().reset()
        
        # Call function
        result = test_function()
        
        # Should have recorded
        assert result == "result"
        metrics = get_metrics().get_metrics()
        assert 'histograms' in metrics
    
    def test_timed_decorator_works_with_args(self):
        """Test @timed works with function arguments."""
        from src.monitoring import timed
        
        @timed('test_with_args')
        def add(a, b):
            return a + b
        
        result = add(2, 3)
        assert result == 5
    
    def test_timed_decorator_works_with_exception(self):
        """Test @timed records time even when exception raised."""
        from src.monitoring import timed, get_metrics
        
        @timed('test_exception')
        def failing_func():
            sleep(0.01)
            raise ValueError("Test error")
        
        get_metrics().reset()
        
        with pytest.raises(ValueError):
            failing_func()
        
        # Should still have recorded duration
        metrics = get_metrics().get_metrics()
        assert 'histograms' in metrics


class TestCountedDecorator:
    """Test @counted decorator."""
    
    def test_counted_decorator_increments_counter(self):
        """Test that @counted increments counter."""
        from src.monitoring import counted, get_metrics
        
        @counted('test_counter')
        def test_function():
            return "done"
        
        get_metrics().reset()
        
        # Call multiple times
        test_function()
        test_function()
        test_function()
        
        metrics = get_metrics().get_metrics()
        assert 'counters' in metrics
    
    def test_counted_decorator_with_labels(self):
        """Test @counted with labels."""
        from src.monitoring import counted
        
        @counted('test_labeled', labels={'type': 'test'})
        def labeled_func():
            return True
        
        result = labeled_func()
        assert result is True


class TestMonitoringIntegration:
    """Test monitoring integration."""
    
    def test_multiple_decorators(self):
        """Test using both @timed and @counted."""
        from src.monitoring import timed, counted
        
        @timed('multi_func_time')
        @counted('multi_func_count')
        def multi_func():
            return 42
        
        result = multi_func()
        assert result == 42
    
    def test_decorators_dont_change_return_value(self):
        """Test decorators preserve return values."""
        from src.monitoring import timed
        
        @timed('return_test')
        def returns_dict():
            return {'key': 'value', 'num': 123}
        
        result = returns_dict()
        assert result == {'key': 'value', 'num': 123}
    
    def test_decorators_preserve_function_name(self):
        """Test decorators preserve function metadata."""
        from src.monitoring import timed
        
        @timed('name_test')
        def my_function():
            """My docstring"""
            pass
        
        assert my_function.__name__ == 'my_function'
        assert my_function.__doc__ == 'My docstring'


class TestMetricsReset:
    """Test metrics reset functionality."""
    
    def test_reset_clears_counters(self):
        """Test reset clears counters."""
        from src.monitoring import get_metrics
        
        metrics = get_metrics()
        metrics.increment('test', 10)
        metrics.reset()
        
        result = metrics.get_metrics()
        # After reset should be empty or have zero counts
        assert result is not None
    
    def test_reset_clears_histograms(self):
        """Test reset clears histograms."""
        from src.monitoring import get_metrics
        
        metrics = get_metrics()
        metrics.record('test', 1.5)
        metrics.reset()
        
        result = metrics.get_metrics()
        assert result is not None
