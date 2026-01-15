from flask import Blueprint, render_template
from pathlib import Path

web_bp = Blueprint('web', __name__)
ROOT_DIR = Path(__file__).parent.parent

@web_bp.route('/favicon.ico')
def favicon():
    from flask import current_app
    favicon_path = ROOT_DIR / 'static' / 'favicon.ico'
    if favicon_path.exists():
        return current_app.send_static_file('favicon.ico')
    return '', 204

@web_bp.route('/')
def index():
    return render_template('chat.html')

@web_bp.route('/chat')
def chat():
    return render_template('chat.html')

@web_bp.route('/documents')
def documents():
    return render_template('documents.html')

@web_bp.route('/models')
def models():
    return render_template('models.html')

@web_bp.route('/overview')
def overview():
    return render_template('overview.html')
