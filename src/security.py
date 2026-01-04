"""
Security Module - Week 1 Security Improvements
==============================================

Authentication, rate limiting, and security middleware for LocalChat application.

Features:
    - JWT authentication
    - Rate limiting
    - CORS support
    - Health checks
    - Request logging

Author: LocalChat Team
Last Updated: 2026-01-03 (Week 1 - Security Improvements)
"""

from flask import Flask, request, jsonify, Response
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from functools import wraps
from typing import Callable, Any
from datetime import timedelta
from . import config
from .utils.logging_config import get_logger

logger = get_logger(__name__)

# ============================================================================
# GLOBAL INSTANCES (will be initialized by init_security)
# ============================================================================

jwt_manager = None
limiter = None

# ============================================================================
# AUTHENTICATION
# ============================================================================

# Simple in-memory user store (replace with database in production)
USERS = {
    'admin': {
        'password': 'change_this_password',  # Should be hashed in production
        'role': 'admin'
    }
}

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
    
    # JWT Configuration
    app.config['JWT_SECRET_KEY'] = config.JWT_SECRET_KEY
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(seconds=config.JWT_ACCESS_TOKEN_EXPIRES)
    jwt_manager = JWTManager(app)
    logger.info("? JWT authentication configured")
    
    # Rate Limiting Configuration
    if config.RATELIMIT_ENABLED:
        limiter = Limiter(
            app=app,
            key_func=get_remote_address,
            default_limits=[config.RATELIMIT_GENERAL],
            storage_uri="memory://"
        )
        logger.info("? Rate limiting enabled")
    else:
        # Create a dummy limiter that doesn't actually limit
        limiter = Limiter(
            app=app,
            key_func=get_remote_address,
            enabled=False
        )
        logger.info("??  Rate limiting disabled")
    
    # CORS Configuration
    if config.CORS_ENABLED:
        CORS(app, origins=config.CORS_ORIGINS)
        logger.info(f"? CORS enabled for origins: {config.CORS_ORIGINS}")
    else:
        logger.info("??  CORS disabled")
    
    # Request Logging Middleware
    @app.before_request
    def log_request():
        """Log incoming requests."""
        logger.info(f"{request.method} {request.path} from {request.remote_addr}")
    
    @app.after_request
    def log_response(response):
        """Log outgoing responses."""
        logger.debug(f"{request.method} {request.path} ? {response.status_code}")
        return response
    
    logger.info("? Security initialization complete")


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
    def login() -> Response:
        """
        Authenticate user and return JWT token.
        
        Request Body:
            username (str): Username
            password (str): Password
        
        Returns:
            JSON with access_token on success, error message on failure
        
        Example:
            >>> POST /api/auth/login
            >>> {"username": "admin", "password": "secret"}
            {
                "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
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
        
        # Verify credentials
        user = USERS.get(username)
        if not user or user['password'] != password:
            logger.warning(f"Failed login attempt for user: {username}")
            return jsonify({'message': 'Invalid credentials'}), 401
        
        # Create access token
        access_token = create_access_token(
            identity=username,
            additional_claims={'role': user['role']}
        )
        
        logger.info(f"User {username} logged in successfully")
        
        return jsonify({
            'access_token': access_token,
            'token_type': 'Bearer',
            'expires_in': config.JWT_ACCESS_TOKEN_EXPIRES
        }), 200
    
    @app.route('/api/auth/verify', methods=['GET'])
    @jwt_required()
    def verify_token() -> Response:
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
    
    logger.info("? Authentication routes registered")


# ============================================================================
# AUTHORIZATION DECORATORS
# ============================================================================

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
        except:
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


# ============================================================================
# HEALTH CHECK
# ============================================================================

def setup_health_check(app: Flask) -> None:
    """
    Setup health check endpoint.
    
    Args:
        app: Flask application instance
    """
    
    @app.route('/health')
    @app.route('/api/health')
    def health_check() -> Response:
        """
        Health check endpoint.
        
        Returns:
            JSON with service health status
        
        Example:
            >>> GET /health
            {
                "status": "healthy",
                "version": "1.0.0",
                "timestamp": "2026-01-03T10:30:00Z"
            }
        """
        from datetime import datetime
        
        return jsonify({
            'status': 'healthy',
            'version': '1.0.0',
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 200
    
    logger.info("? Health check endpoint registered")


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
    def ratelimit_handler(e) -> Response:
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
    
    logger.info("? Rate limit error handler registered")


logger.info("Security module loaded")
