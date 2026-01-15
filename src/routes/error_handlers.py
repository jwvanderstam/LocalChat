# -*- coding: utf-8 -*-

"""
Error Handlers Module
====================

Centralized error handling for LocalChat application.
Provides user-friendly error responses and logging.

Author: LocalChat Team
Created: 2025-01-15
"""

from flask import Flask, jsonify, request
from typing import Any

from ..utils.logging_config import get_logger

logger = get_logger(__name__)


def register_error_handlers(app: Flask) -> None:
    """
    Register all error handlers for the application.
    
    Handles HTTP errors and custom exceptions with appropriate
    responses and logging.
    
    Args:
        app: Flask application instance
    """
    # Import validation and error models (required)
    from pydantic import ValidationError as PydanticValidationError
    from .. import exceptions
    from ..models import ErrorResponse
    logger.info("? Error handlers initialized with Pydantic validation")
    
    # Register HTTP error handlers
    @app.errorhandler(400)
    def bad_request_handler(error: Any):
        """Handle 400 Bad Request errors."""
        logger.warning(f"Bad request: {error}")
        
        error_response = ErrorResponse(
            error="BadRequest",
            message="The request was invalid or cannot be served",
            details={"description": str(error)}
        )
        return jsonify(error_response.model_dump()), 400
    
    @app.errorhandler(404)
    def not_found_handler(error: Any):
        """Handle 404 Not Found errors."""
        logger.warning(f"Resource not found: {error}")
        
        error_response = ErrorResponse(
            error="NotFound",
            message="The requested resource was not found",
            details={"path": request.path}
        )
        return jsonify(error_response.model_dump()), 404
    
    @app.errorhandler(405)
    def method_not_allowed_handler(error: Any):
        """Handle 405 Method Not Allowed errors."""
        logger.warning(f"Method not allowed: {request.method} {request.path}")
        
        error_response = ErrorResponse(
            error="MethodNotAllowed",
            message=f"Method {request.method} not allowed for this endpoint",
            details={"method": request.method, "path": request.path}
        )
        return jsonify(error_response.model_dump()), 405
    
    @app.errorhandler(413)
    def request_entity_too_large_handler(error: Any):
        """Handle 413 Request Entity Too Large errors."""
        logger.warning(f"File too large: {error}")
        
        max_size = app.config.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024)
        max_size_mb = max_size / (1024 * 1024)
        
        error_response = ErrorResponse(
            error="FileTooLarge",
            message="The uploaded file is too large",
            details={"max_size": f"{max_size_mb:.0f}MB"}
        )
        return jsonify(error_response.model_dump()), 413
    
    @app.errorhandler(500)
    def internal_server_error_handler(error: Any):
        """Handle 500 Internal Server Error."""
        logger.error(f"Internal server error: {error}", exc_info=True)
        
        error_response = ErrorResponse(
            error="InternalServerError",
            message="An unexpected error occurred on the server",
            details={"type": type(error).__name__}
        )
        return jsonify(error_response.model_dump()), 500
    
    # Register Pydantic validation error handlers
    @app.errorhandler(PydanticValidationError)
    def validation_error_handler(error: PydanticValidationError):
        """Handle Pydantic validation errors with user-friendly messages."""
        errors = error.errors()
        
        # Create user-friendly message
        if len(errors) == 1:
                err = errors[0]
                field = err.get('loc', ['field'])[-1]
                error_type = err.get('type', 'validation_error')
                
                # Create specific messages
                if error_type == 'string_too_long':
                    max_length = err.get('ctx', {}).get('max_length', 5000)
                    input_length = len(str(err.get('input', '')))
                    user_message = (
                        f"Your {field} is too long ({input_length:,} characters). "
                        f"Please shorten it to {max_length:,} characters or less."
                    )
                elif error_type == 'string_too_short':
                    min_length = err.get('ctx', {}).get('min_length', 1)
                    user_message = f"Your {field} must be at least {min_length} character(s) long."
                elif error_type == 'value_error':
                    user_message = f"Invalid {field}: {err.get('msg', 'Please check your input')}"
                elif error_type == 'missing':
                    user_message = f"Required field '{field}' is missing."
                else:
                    user_message = f"Invalid {field}: {err.get('msg', 'Please check your input')}"
                    
                logger.warning(f"Validation error: {user_message}")
            else:
                # Multiple errors
                user_message = "Multiple validation errors occurred:\n"
                for idx, err in enumerate(errors[:3], 1):
                    field = err.get('loc', ['field'])[-1]
                    user_message += f"{idx}. {field}: {err.get('msg', 'Invalid value')}\n"
                if len(errors) > 3:
                    user_message += f"... and {len(errors) - 3} more error(s)."
                logger.warning(f"Multiple validation errors: {len(errors)} total")
            
            error_response = ErrorResponse(
                error="ValidationError",
                message=user_message,
                details={
                    "errors": errors,
                    "help": "Please check your input and try again."
                }
            )
            return jsonify(error_response.model_dump()), 400
    
    @app.errorhandler(exceptions.LocalChatException)
        def localchat_exception_handler(error: exceptions.LocalChatException):
            """Handle custom LocalChat exceptions."""
            status_code = exceptions.get_status_code(error)
            logger.error(f"{error.__class__.__name__}: {error.message}", extra=error.details)
            
            error_response = ErrorResponse(
                error=error.__class__.__name__,
                message=error.message,
                details=error.details
            )
            return jsonify(error_response.model_dump()), status_code
    
    logger.debug("Error handlers registered")
