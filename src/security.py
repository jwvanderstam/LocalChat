"""
Security Module
==============

Authentication, rate limiting, and security middleware for LocalChat application.

Features:
    - JWT authentication
    - Rate limiting
    - CORS support
    - Health checks
    - Request logging

Author: LocalChat Team
Last Updated: 2025-01-27
"""

import hashlib
import hmac
import os
from datetime import timedelta
from functools import wraps
from typing import Any, Callable

from flask import Flask, Response, jsonify, request
from flask.typing import ResponseReturnValue
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from . import config
from .utils.logging_config import get_logger

logger = get_logger(__name__)

# ============================================================================
# GLOBAL INSTANCES (will be initialized by init_security)
# ============================================================================

jwt_manager = None
limiter = None


def _resolve_ratelimit_storage(desired_uri: str) -> str:
    """Return *desired_uri* if Redis is reachable, otherwise fall back to ``memory://``.

    Performed once at startup so every worker process knows its storage backend
    before the first request arrives.
    """
    if not desired_uri.startswith("redis://"):
        return desired_uri
    try:
        from urllib.parse import urlparse

        import redis as redis_lib
        parsed = urlparse(desired_uri)
        r = redis_lib.Redis(
            host=parsed.hostname,
            port=parsed.port or 6379,
            password=parsed.password,
            socket_timeout=2,
            socket_connect_timeout=2,
        )
        r.ping()
        return desired_uri
    except Exception as exc:
        logger.warning(
            f"Redis unreachable for rate limiting ({exc}), falling back to memory://"
        )
        return "memory://"

# ============================================================================
# AUTHENTICATION
# ============================================================================

# Credentials are loaded from the ADMIN_PASSWORD environment variable.
# The password is hashed with PBKDF2-HMAC-SHA256 at startup so it is never
# stored or compared in plaintext.  The salt is regenerated each time the
# process starts; this is intentional (env-var secrets should not be stored).
_ADMIN_PASSWORD_RAW: str = os.environ.get('ADMIN_PASSWORD', '')
_ADMIN_PASSWORD_SALT: bytes = os.urandom(32)
_ADMIN_PASSWORD_HASH: bytes = hashlib.pbkdf2_hmac(
    'sha256', _ADMIN_PASSWORD_RAW.encode('utf-8'), _ADMIN_PASSWORD_SALT, 100_000
)

USERS = {
    'admin': {
        'role': 'admin'
    }
}

# Shared string constants (S1192 — avoid repetition)
_AUTH_REQUIRED = 'Authentication required'
_ROLE_LEVELS: dict[str, int] = {'viewer': 0, 'editor': 1, 'owner': 2}


def _verify_credentials(username: str, password: str) -> tuple[str, str] | None:
    """Return ``(user_sub, user_role)`` on success, ``None`` on failure.

    Tries DB-backed users first; falls back to the legacy env-var admin account.
    """
    from flask import current_app
    if hasattr(current_app, 'db') and current_app.db.is_connected:
        db_user = current_app.db.verify_user_password(username, password)
        if db_user:
            return str(db_user['id']), db_user.get('role', 'user')
    # Legacy: hardcoded admin account validated against env-var hash
    if username != 'admin' or not _ADMIN_PASSWORD_RAW:
        return None
    provided_hash = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), _ADMIN_PASSWORD_SALT, 100_000
    )
    if not hmac.compare_digest(provided_hash, _ADMIN_PASSWORD_HASH):
        return None
    return 'admin', 'admin'


def _is_rbac_bypassed(app) -> bool:
    """Return True when RBAC enforcement should be skipped (dev / test modes)."""
    return (
        not _ADMIN_PASSWORD_RAW
        or config.DEMO_MODE
        or app.config.get('TESTING', False)
    )


def _resolve_workspace_id(kwargs: dict, req) -> str | None:
    """Extract workspace_id from URL params, request JSON, or active state."""
    return (
        kwargs.get('workspace_id')
        or (req.get_json(silent=True) or {}).get('workspace_id')
        or config.app_state.get_active_workspace_id()
    )

def init_security(app: Flask) -> None:
    """
    Initialize security features for Flask application.

    Args:
        app: Flask application instance

    Sets up:
        - JWT authentication
        - Rate limiting
        - CORS (if enabled)
        - Request logging
    """
    global jwt_manager, limiter

    logger.info("Initializing security features...")

    # Skip JWT and rate-limiting in demo mode — auth is intentionally off.
    if config.DEMO_MODE:
        if os.environ.get('APP_ENV') == 'production':
            raise RuntimeError("DEMO_MODE must not be enabled in production")
        logger.warning("DEMO_MODE: JWT authentication and rate limiting are disabled.")
        jwt_manager = JWTManager(app)
        limiter = Limiter(app=app, key_func=get_remote_address, enabled=False)
        if config.CORS_ENABLED:
            CORS(app, origins=config.CORS_ORIGINS)
        logger.info("Security initialization complete (demo mode)")
        return

    if not _ADMIN_PASSWORD_RAW:
        if os.environ.get('APP_ENV') == 'production':
            raise RuntimeError("ADMIN_PASSWORD must be set in production")
        logger.warning("ADMIN_PASSWORD is not set — admin login will be rejected until it is configured.")

    app.config['JWT_SECRET_KEY'] = config.JWT_SECRET_KEY
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(seconds=config.JWT_ACCESS_TOKEN_EXPIRES)
    app.config['JWT_COOKIE_SECURE'] = not config.DEMO_MODE
    app.config['SESSION_COOKIE_SECURE'] = not config.DEMO_MODE
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    jwt_manager = JWTManager(app)
    logger.info("JWT authentication configured")

    # Rate Limiting Configuration
    if config.RATELIMIT_ENABLED:
        storage_uri = _resolve_ratelimit_storage(config.RATELIMIT_STORAGE_URI)
        limiter = Limiter(
            app=app,
            key_func=get_remote_address,
            default_limits=[config.RATELIMIT_GENERAL],
            storage_uri=storage_uri,
        )
        backend = "Redis" if storage_uri.startswith("redis://") else "memory"
        logger.info(f"Rate limiting enabled (storage: {backend})")
    else:
        # Create a dummy limiter that doesn't actually limit
        limiter = Limiter(
            app=app,
            key_func=get_remote_address,
            enabled=False
        )
        logger.info("Rate limiting disabled")

    # CORS Configuration
    if config.CORS_ENABLED:
        CORS(app, origins=config.CORS_ORIGINS)
        logger.info(f"CORS enabled for origins: {config.CORS_ORIGINS}")
    else:
        logger.info("CORS disabled")

    # Request Logging Middleware
    @app.before_request
    def log_request():
        """Log incoming requests."""
        logger.info(f"{request.method} {request.path} from {request.remote_addr}")

    @app.after_request
    def log_response(response):
        """Log outgoing responses."""
        logger.debug(f"{request.method} {request.path} -> {response.status_code}")
        return response

    logger.info("Security initialization complete")


# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================

def setup_auth_routes(app: Flask) -> None:
    """
    Setup authentication routes.

    Args:
        app: Flask application instance
    """

    @app.route('/api/auth/login', methods=['POST'])
    @limiter.limit(config.RATELIMIT_GENERAL)
    def login() -> ResponseReturnValue:
        """
        Authenticate user and return JWT token.

        Request Body:
            username (str): Username
            password (str): Password

        Returns:
            JSON with access_token on success, error message on failure

        Example:
            >>> POST /api/auth/login
            >>> {"username": "admin", "password": "<password>"}
            {
                "access_token": "<jwt-token>",
                "token_type": "Bearer",
                "expires_in": 3600
            }
        """
        data = request.get_json()

        if not data:
            return jsonify({'message': 'Missing JSON body'}), 400

        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({'message': 'Username and password required'}), 400

        result = _verify_credentials(username, password)
        if result is None:
            logger.warning("Failed login attempt")
            return jsonify({'message': 'Invalid credentials'}), 401

        user_sub, user_role = result

        # Create access token
        access_token = create_access_token(
            identity=user_sub,
            additional_claims={'role': user_role, 'username': username}
        )

        logger.info(f"User {username} logged in successfully")

        return jsonify({
            'access_token': access_token,
            'token_type': 'Bearer',
            'expires_in': config.JWT_ACCESS_TOKEN_EXPIRES
        }), 200

    @app.route('/api/auth/verify', methods=['GET'])
    @jwt_required()
    def verify_token() -> ResponseReturnValue:
        """
        Verify JWT token is valid.

        Returns:
            JSON with current user info

        Example:
            >>> GET /api/auth/verify
            >>> Authorization: Bearer <token>
            {
                "username": "admin",
                "valid": true
            }
        """
        current_user = get_jwt_identity()
        return jsonify({
            'username': current_user,
            'valid': True
        }), 200

    logger.info("Authentication routes registered")


# ============================================================================
# AUTHORIZATION DECORATORS
# ============================================================================

def get_current_user_id() -> str | None:
    """Return the JWT ``sub`` claim (user UUID or 'admin') if a token is present."""
    try:
        from flask_jwt_extended import get_jwt_identity
        return get_jwt_identity()
    except Exception:
        return None


def require_workspace_role(min_role: str):
    """Decorator requiring the caller to hold at least *min_role* in the active workspace.

    Role hierarchy (lowest → highest): viewer → editor → owner.
    Admin JWT role bypasses the check.
    Bypassed entirely in DEMO_MODE, testing, and when ADMIN_PASSWORD is not set.
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from flask import current_app, request as _request
            if _is_rbac_bypassed(current_app):
                return f(*args, **kwargs)

            from flask_jwt_extended import get_jwt, verify_jwt_in_request
            try:
                verify_jwt_in_request()
            except Exception:
                return jsonify({'message': _AUTH_REQUIRED}), 401

            claims = get_jwt()
            if claims.get('role') == 'admin':
                return f(*args, **kwargs)

            user_id = get_jwt_identity()
            if not user_id:
                return jsonify({'message': _AUTH_REQUIRED}), 401

            workspace_id = _resolve_workspace_id(kwargs, _request)
            if not workspace_id:
                return jsonify({'message': 'No workspace context'}), 400

            if not (hasattr(current_app, 'db') and current_app.db.is_connected):
                return jsonify({'message': 'Database unavailable'}), 503

            role = current_app.db.get_workspace_member_role(workspace_id, user_id)
            if role is None:
                return jsonify({'message': 'Access denied: not a workspace member'}), 403
            if _ROLE_LEVELS.get(role, -1) < _ROLE_LEVELS.get(min_role, 0):
                return jsonify({'message': f'Requires {min_role} role or higher'}), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_auth_optional(f: Callable) -> Callable:
    """
    Optional authentication decorator.

    Allows both authenticated and unauthenticated access,
    but provides user info if authenticated.

    Args:
        f: Function to decorate

    Returns:
        Decorated function
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            # Try to get user if token is provided
            from flask_jwt_extended import verify_jwt_in_request
            verify_jwt_in_request(optional=True)
        except Exception:
            pass
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f: Callable) -> Callable:
    """
    Require admin role for endpoint access.

    Args:
        f: Function to decorate

    Returns:
        Decorated function

    Raises:
        403: If user is not an admin
    """
    @wraps(f)
    @jwt_required()
    def decorated_function(*args, **kwargs):
        from flask_jwt_extended import get_jwt
        claims = get_jwt()

        if claims.get('role') != 'admin':
            logger.warning(f"Non-admin user attempted to access admin endpoint: {request.path}")
            return jsonify({'message': 'Admin access required'}), 403

        return f(*args, **kwargs)
    return decorated_function


def require_admin(f: Callable) -> Callable:
    """
    DEMO_MODE-aware admin guard.

    In DEMO_MODE the endpoint is accessible without a token (single-user
    local evaluation).  In all other modes a valid JWT with ``role=admin``
    is required.

    Args:
        f: Function to decorate

    Returns:
        Decorated function
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask import current_app
        # Allow unauthenticated access when no password has been configured,
        # in DEMO_MODE, or during automated tests.
        if not _ADMIN_PASSWORD_RAW or config.DEMO_MODE or current_app.config.get('TESTING', False):
            return f(*args, **kwargs)
        from flask_jwt_extended import get_jwt, verify_jwt_in_request
        try:
            verify_jwt_in_request()
        except Exception:
            return jsonify({'message': _AUTH_REQUIRED}), 401
        claims = get_jwt()
        if claims.get('role') != 'admin':
            logger.warning(f"Non-admin user attempted to access admin endpoint: {request.path}")
            return jsonify({'message': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function


# ============================================================================
# HEALTH CHECK
# ============================================================================

def setup_health_check(_app: Flask) -> None:
    """
    Setup health check endpoint.

    NOTE: Health check is now provided by the monitoring module at /api/health
    This function is kept for backwards compatibility but does nothing.

    Args:
        app: Flask application instance
    """
    # Health check is now handled by monitoring module
    # Monitoring provides a more comprehensive health check with component status
    logger.info("Health check is provided by monitoring module at /api/health")


# ============================================================================
# RATE LIMIT ERROR HANDLER
# ============================================================================

def setup_rate_limit_handler(app: Flask) -> None:
    """
    Setup custom rate limit error handler.

    Args:
        app: Flask application instance
    """

    @app.errorhandler(429)
    def ratelimit_handler(e) -> ResponseReturnValue:
        """
        Handle rate limit exceeded errors.

        Args:
            e: Rate limit error

        Returns:
            JSON error response
        """
        logger.warning(f"Rate limit exceeded for {request.remote_addr} on {request.path}")
        return jsonify({
            'success': False,
            'error': 'RateLimitExceeded',
            'message': 'Too many requests. Please slow down and try again later.',
            'retry_after': e.description
        }), 429

    logger.info("Rate limit error handler registered")


logger.info("Security module loaded")
