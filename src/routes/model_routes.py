# -*- coding: utf-8 -*-

"""
Model Routes Blueprint
=====================

Model management API endpoints for LocalChat application.
Handles model listing, activation, pulling, deletion, and testing.

Author: LocalChat Team
Created: 2025-01-15
"""

from flask import Blueprint, jsonify, request, Response, current_app
from typing import Generator
import json

from ..utils.logging_config import get_logger

bp = Blueprint('models', __name__)
logger = get_logger(__name__)


@bp.route('/', methods=['GET'])
def api_list_models():
    """
    List all available Ollama models.
    
    Retrieve all LLM models available in the Ollama instance.
    ---
    tags:
      - Models
    summary: List available models
    description: |
      Returns all models installed in Ollama with metadata:
      - Model name and size
      - Last modified timestamp
      - Model family and version
    responses:
      200:
        description: Model list retrieved successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            models:
              type: array
              items:
                $ref: '#/definitions/Model'
        examples:
          application/json:
            success: true
            models:
              - name: "llama3.2"
                size: 4500000000
                modified_at: "2025-01-10T15:30:00Z"
              - name: "nomic-embed-text"
                size: 274000000
                modified_at: "2025-01-12T09:15:00Z"
      503:
        description: Ollama service unavailable
        schema:
          $ref: '#/definitions/Error'
    """
    success, models = current_app.ollama_client.list_models()
    return jsonify({
        'success': success,
        'models': models
    })


@bp.route('/active', methods=['GET', 'POST'])
def api_active_model():
    """
    Get or set the active model.
    
    Retrieve or change the currently active LLM model for chat.
    ---
    tags:
      - Models
    summary: Get/Set active model
    description: |
      **GET**: Returns the currently active model name
      
      **POST**: Sets a new active model (must be installed first)
    parameters:
      - name: body
        in: body
        required: false
        description: Model name to activate (POST only)
        schema:
          type: object
          required:
            - model
          properties:
            model:
              type: string
              description: Model name to activate
              example: "llama3.2"
    responses:
      200:
        description: Active model retrieved or set successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            model:
              type: string
              description: Active model name
        examples:
          application/json:
            success: true
            model: "llama3.2"
      400:
        description: Bad request (model name missing)
        schema:
          $ref: '#/definitions/Error'
      404:
        description: Model not found
        schema:
          $ref: '#/definitions/Error'
      503:
        description: Ollama service unavailable
        schema:
          $ref: '#/definitions/Error'
    """
    from .. import config
    
    try:
        if request.method == 'POST':
            data = request.get_json()
            
            # Try Month 2 validation
            try:
                from ..models import ModelRequest
                from ..utils.sanitization import sanitize_model_name
                from .. import exceptions
                
                request_data = ModelRequest(**data)
                model_name = sanitize_model_name(request_data.model)
                month2_enabled = True
                
            except ImportError:
                # Month 1 validation
                model_name = data.get('model', '').strip()
                month2_enabled = False
                
                if not model_name:
                    logger.warning("Model name not provided")
                    return jsonify({'success': False, 'message': 'Model name required'}), 400
            
            logger.info(f"Setting active model to: {model_name}")
            
            # Verify model exists
            success, models = current_app.ollama_client.list_models()
            if not success:
                error_msg = "Failed to list models"
                logger.error(error_msg)
                if month2_enabled:
                    raise exceptions.OllamaConnectionError(error_msg)
                return jsonify({'success': False, 'message': error_msg}), 503
            
            model_names = [m['name'] for m in models]
            if model_name not in model_names:
                error_msg = f"Model '{model_name}' not found"
                logger.warning(error_msg)
                if month2_enabled:
                    raise exceptions.InvalidModelError(
                        error_msg, 
                        details={'requested': model_name, 'available': model_names[:10]}
                    )
                return jsonify({'success': False, 'message': error_msg}), 404
            
            config.app_state.set_active_model(model_name)
            logger.info(f"Active model changed to: {model_name}")
            return jsonify({'success': True, 'model': model_name})
        
        else:  # GET
            active_model = config.app_state.get_active_model()
            return jsonify({'model': active_model})
            
    except Exception as e:
        logger.error(f"Error in active_model endpoint: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to get/set active model'}), 500


@bp.route('/pull', methods=['POST'])
def api_pull_model():
    """
    Pull a new model from Ollama registry.
    
    Streams download progress via Server-Sent Events.
    
    Request Body:
        - model (str): Model name to pull
    
    Returns:
        Server-Sent Events stream with pull progress
    """
    try:
        data = request.get_json()
        
        # Try Month 2 validation
        try:
            from ..models import ModelPullRequest
            from ..utils.sanitization import sanitize_model_name
            
            request_data = ModelPullRequest(**data)
            model_name = sanitize_model_name(request_data.model)
            
        except ImportError:
            # Month 1 validation
            model_name = data.get('model', '').strip()
            
            if not model_name:
                return jsonify({'success': False, 'message': 'Model name required'}), 400
        
        logger.info(f"Pulling model: {model_name}")
        
        # Capture app object before entering generator
        app = current_app._get_current_object()
        
        def generate() -> Generator[str, None, None]:
            try:
                for progress in app.ollama_client.pull_model(model_name):
                    yield f"data: {json.dumps(progress)}\n\n"
            except Exception as e:
                logger.error(f"Error pulling model: {e}", exc_info=True)
                error_msg = json.dumps({'error': str(e)})
                yield f"data: {error_msg}\n\n"
        
        response = Response(generate(), mimetype='text/event-stream')
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['X-Accel-Buffering'] = 'no'
        return response
        
    except Exception as e:
        logger.error(f"Error in pull_model endpoint: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to pull model'}), 500


@bp.route('/delete', methods=['DELETE'])
def api_delete_model():
    """
    Delete a model.
    
    Request Body:
        - model (str): Model name to delete
    
    Returns:
        JSON response with success status
    """
    try:
        data = request.get_json()
        
        # Try Month 2 validation
        try:
            from ..models import ModelDeleteRequest
            from ..utils.sanitization import sanitize_model_name
            from .. import exceptions
            
            request_data = ModelDeleteRequest(**data)
            model_name = sanitize_model_name(request_data.model)
            month2_enabled = True
            
        except ImportError:
            # Month 1 validation
            model_name = data.get('model', '').strip()
            month2_enabled = False
            
            if not model_name:
                return jsonify({'success': False, 'message': 'Model name required'}), 400
        
        logger.info(f"Deleting model: {model_name}")
        
        success, message = current_app.ollama_client.delete_model(model_name)
        
        if not success:
            error_msg = f"Failed to delete model: {message}"
            logger.error(error_msg)
            if month2_enabled:
                raise exceptions.InvalidModelError(error_msg, details={"model": model_name})
            return jsonify({'success': False, 'message': error_msg}), 500
        
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        logger.error(f"Error deleting model: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to delete model'}), 500


@bp.route('/test', methods=['POST'])
def api_test_model():
    """
    Test a model with a simple prompt.
    
    Request Body:
        - model (str): Model name to test
    
    Returns:
        JSON response with test results
    """
    try:
        data = request.get_json()
        
        # Try Month 2 validation
        try:
            from ..models import ModelRequest
            from ..utils.sanitization import sanitize_model_name
            
            request_data = ModelRequest(**data)
            model_name = sanitize_model_name(request_data.model)
            
        except ImportError:
            # Month 1 validation
            model_name = data.get('model', '').strip()
            
            if not model_name:
                return jsonify({'success': False, 'message': 'Model name required'}), 400
        
        logger.info(f"Testing model: {model_name}")
        
        success, result = current_app.ollama_client.test_model(model_name)
        
        return jsonify({'success': success, 'result': result})
        
    except Exception as e:
        logger.error(f"Error testing model: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to test model'}), 500
