
"""
Error Handlers Module
====================

Centralized error handling for LocalChat application.
Provides user-friendly error responses and logging.

"""

from typing import Any

from flask import Flask, current_app, jsonify, request
from flask.typing import ResponseReturnValue
from pydantic import ValidationError as PydanticValidationError

from .. import exceptions
from ..db import DatabaseUnavailableError
from ..models import ErrorResponse
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


def _build_validation_message(errors: list) -> str:
    """Build a user-friendly validation error message from Pydantic error list."""
    if len(errors) == 1:
        err = errors[0]
        field = err.get('loc', ['field'])[-1]
        error_type = err.get('type', 'validation_error')
        if error_type == 'string_too_long':
            max_length = err.get('ctx', {}).get('max_length', 5000)
            input_length = len(str(err.get('input', '')))
            return (
                f"Your {field} is too long ({input_length:,} characters). "
                f"Please shorten it to {max_length:,} characters or less."
            )
        if error_type == 'string_too_short':
            min_length = err.get('ctx', {}).get('min_length', 1)
            return f"Your {field} must be at least {min_length} character(s) long."
        if error_type == 'missing':
            return f"Required field '{field}' is missing."
        return f"Invalid {field}: {err.get('msg', 'Please check your input')}"
    msg = "Multiple validation errors occurred:\n"
    for idx, err in enumerate(errors[:3], 1):
        field = err.get('loc', ['field'])[-1]
        msg += f"{idx}. {field}: {err.get('msg', 'Invalid value')}\n"
    if len(errors) > 3:
        msg += f"... and {len(errors) - 3} more error(s)."
    return msg


def register_error_handlers(app: Flask) -> None:
    """
    Register all error handlers for the application.

    Handles HTTP errors and custom exceptions with appropriate
    responses and logging.

    Args:
        app: Flask application instance
    """
    logger.info("? Error handlers initialized with Pydantic validation")

    # Register HTTP error handlers
    @app.errorhandler(400)
    def bad_request_handler(error: Any) -> ResponseReturnValue:
        """Handle 400 Bad Request errors."""
        logger.warning(f"Bad request: {error}")

        error_response = ErrorResponse(
            error="BadRequest",
            message="The request was invalid or cannot be served",
            details={"description": str(error)}
        )
        return jsonify(error_response.model_dump()), 400

    @app.errorhandler(404)
    def not_found_handler(error: Any) -> ResponseReturnValue:
        """Handle 404 Not Found errors."""
        logger.warning(f"Resource not found: {error}")

        error_response = ErrorResponse(
            error="NotFound",
            message="The requested resource was not found",
            details={"path": request.path}
        )
        return jsonify(error_response.model_dump()), 404

    @app.errorhandler(405)
    def method_not_allowed_handler(_error: Any) -> ResponseReturnValue:
        """Handle 405 Method Not Allowed errors."""
        from ..utils.logging_config import sanitize_log_value as _slv
        logger.warning("Method not allowed: %s %s", request.method, _slv(request.path))

        error_response = ErrorResponse(
            error="MethodNotAllowed",
            message=f"Method {request.method} not allowed for this endpoint",
            details={"method": request.method, "path": request.path}
        )
        return jsonify(error_response.model_dump()), 405

    @app.errorhandler(413)
    def request_entity_too_large_handler(error: Any) -> ResponseReturnValue:
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
    def internal_server_error_handler(error: Any) -> ResponseReturnValue:
        """Handle 500 Internal Server Error."""
        logger.error(f"Internal server error: {error}", exc_info=True)

        details = {"type": type(error).__name__} if current_app.debug else {}
        error_response = ErrorResponse(
            error="InternalServerError",
            message="An unexpected error occurred on the server",
            details=details
        )
        return jsonify(error_response.model_dump()), 500

    # Register Pydantic validation error handlers
    @app.errorhandler(PydanticValidationError)
    def validation_error_handler(error: PydanticValidationError) -> ResponseReturnValue:
        """Handle Pydantic validation errors with user-friendly messages."""
        errors = error.errors()
        user_message = _build_validation_message(errors)
        logger.warning("Validation error (%d issue(s)): %s",
                       len(errors),
                       user_message[:80].replace('\r', '').replace('\n', ' '))
        error_response = ErrorResponse(
            error="ValidationError",
            message=user_message,
            details={"errors": errors, "help": "Please check your input and try again."}
        )
        return jsonify(error_response.model_dump()), 400

    @app.errorhandler(exceptions.LocalChatException)
    def localchat_exception_handler(error: exceptions.LocalChatException) -> ResponseReturnValue:
        """Handle custom LocalChat exceptions."""
        status_code = exceptions.get_status_code(error)
        logger.error(f"{error.__class__.__name__}: {error.message}", extra=error.details)

        error_response = ErrorResponse(
            error=error.__class__.__name__,
            message=error.message,
            details=error.details
        )
        return jsonify(error_response.model_dump()), status_code

    @app.errorhandler(DatabaseUnavailableError)
    def database_unavailable_handler(error: DatabaseUnavailableError) -> ResponseReturnValue:
        """Handle database unavailable errors (degraded mode)."""
        logger.warning(f"Database unavailable: {str(error)}")

        error_response = ErrorResponse(
            error="DatabaseUnavailable",
            message="Database is not available",
            details={
                "description": str(error),
                "help": "The application is running in degraded mode. Please ensure PostgreSQL is running and restart the application."
            }
        )
        return jsonify(error_response.model_dump()), 503

    logger.debug("Error handlers registered")
