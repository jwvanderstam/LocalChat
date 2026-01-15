import os
from pathlib import Path
from flask import Flask
from ..utils.logging_config import get_logger
from .. import config

logger = get_logger(__name__)
try:
    from .. import security
    SECURITY_ENABLED = True
except ImportError:
    SECURITY_ENABLED = False

def create_app():
    ROOT_DIR = Path(__file__).parent.parent.parent
    app = Flask(__name__, template_folder=str(ROOT_DIR / 'templates'), static_folder=str(ROOT_DIR / 'static'))
    app.config['SECRET_KEY'] = config.SECRET_KEY
    app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
    app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
    if SECURITY_ENABLED:
        security.init_security(app)
        security.setup_auth_routes(app)
        security.setup_health_check(app)
        security.setup_rate_limit_handler(app)
    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
    from ..routes import error_handlers
    error_handlers.register_error_handlers(app)
    from ..blueprints.web import web_bp
    app.register_blueprint(web_bp)
    return app
