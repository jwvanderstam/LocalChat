# -*- coding: utf-8 -*-

"""
Web Routes Blueprint
===================

Web page routes for LocalChat application.
Serves HTML templates for the web interface.

Author: LocalChat Team
Created: 2025-01-15
"""

from flask import Blueprint, render_template
from pathlib import Path

bp = Blueprint('web', __name__)


@bp.route('/favicon.ico')
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


@bp.route('/')
def index() -> str:
    """
    Redirect to chat page.
    
    Returns:
        Rendered chat template
    """
    return render_template('chat.html')


@bp.route('/chat')
def chat() -> str:
    """
    Render chat page.
    
    Returns:
        Rendered chat template
    """
    return render_template('chat.html')


@bp.route('/documents')
def documents() -> str:
    """
    Render document management page.
    
    Returns:
        Rendered documents template
    """
    return render_template('documents.html')


@bp.route('/models')
def models() -> str:
    """
    Render model management page.
    
    Returns:
        Rendered models template
    """
    return render_template('models.html')


@bp.route('/overview')
def overview() -> str:
    """
    Render overview page.
    
    Returns:
        Rendered overview template
    """
    return render_template('overview.html')
