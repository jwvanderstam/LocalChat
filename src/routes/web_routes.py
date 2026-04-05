
"""
Web Routes Blueprint
===================

Web page routes for LocalChat application.
Serves HTML templates for the web interface.

Author: LocalChat Team
Created: 2025-01-15
"""

from pathlib import Path

from flask import Blueprint, render_template

bp = Blueprint('web', __name__)


@bp.route('/favicon.ico', methods=['GET'])
def favicon():
    """
    Serve favicon or return 204 No Content if not found.

    Prevents 404 errors in browser console.

    Returns:
        Favicon file or 204 status code
    """
    from flask import current_app
    root_dir = Path(current_app.root_path).parent
    favicon_path = root_dir / 'static' / 'favicon.ico'

    if favicon_path.exists():
        return current_app.send_static_file('favicon.ico')
    return '', 204


@bp.route('/', methods=['GET'])
def index() -> str:
    """
    Redirect to chat page.

    Returns:
        Rendered chat template
    """
    return render_template('chat.html')


@bp.route('/chat', methods=['GET'])
def chat() -> str:
    """
    Render chat page.

    Returns:
        Rendered chat template
    """
    return render_template('chat.html')


@bp.route('/documents', methods=['GET'])
def documents() -> str:
    """
    Render document management page.

    Returns:
        Rendered documents template
    """
    return render_template('documents.html')


@bp.route('/models', methods=['GET'])
def models() -> str:
    """
    Render model management page.

    Returns:
        Rendered models template
    """
    return render_template('models.html')


@bp.route('/overview', methods=['GET'])
def overview() -> str:
    """
    Render overview page.

    Returns:
        Rendered overview template
    """
    return render_template('overview.html')
