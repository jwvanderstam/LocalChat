#!/usr/bin/env python3
"""Extract routes from app.py to create minimal app.py"""

with open('src/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Create new minimal app.py
minimal_app = '''# -*- coding: utf-8 -*-

"""
Flask Application Module
========================

Main application entry point for LocalChat RAG application.
Routes are defined in blueprints (see src/blueprints/).

Author: LocalChat Team
"""

import os
import sys
from .utils.logging_config import setup_logging, get_logger
from .initialization import create_app, register_lifecycle_handlers, startup_status, startup_checks

# Initialize logging
setup_logging(log_level="INFO", log_file="logs/app.log")
logger = get_logger(__name__)

# Create app
app = create_app()
wsgi_app = app.wsgi_app
register_lifecycle_handlers()

# Main entry point
if __name__ == '__main__':
    startup_checks()
    
    HOST = os.environ.get('SERVER_HOST', 'localhost')
    try:
        PORT = int(os.environ.get('SERVER_PORT', '5000'))
    except ValueError:
        PORT = 5000
    
    logger.info(f"Starting Flask server on {HOST}:{PORT}")
    app.run(HOST, PORT, debug=True, use_reloader=False)
'''

with open('src/app_minimal.py', 'w', encoding='utf-8') as f:
    f.write(minimal_app)

print(f"Created minimal app.py with {len(minimal_app.splitlines())} lines")
print("Original app.py lines:", len(content.splitlines()))
