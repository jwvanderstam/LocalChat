# -*- coding: utf-8 -*-

"""
API Documentation Configuration Tests
======================================

Tests for API documentation configuration (src/api_docs.py)

Target: Increase coverage from 0% to 100% (+0.5% overall)

Covers:
- SWAGGER_CONFIG
- SWAGGER_TEMPLATE  
- Configuration structure validation

Author: LocalChat Team
Created: January 2025
"""

import pytest


class TestSwaggerConfig:
    """Test Swagger configuration."""
    
    def test_swagger_config_exists(self):
        """Test SWAGGER_CONFIG is defined."""
        from src import api_docs
        
        assert hasattr(api_docs, 'SWAGGER_CONFIG')
        assert isinstance(api_docs.SWAGGER_CONFIG, dict)
    
    def test_swagger_config_has_specs(self):
        """Test SWAGGER_CONFIG has specs list."""
        from src.api_docs import SWAGGER_CONFIG
        
        assert 'specs' in SWAGGER_CONFIG
        assert isinstance(SWAGGER_CONFIG['specs'], list)
        assert len(SWAGGER_CONFIG['specs']) > 0
    
    def test_swagger_config_has_title(self):
        """Test SWAGGER_CONFIG has title."""
        from src.api_docs import SWAGGER_CONFIG
        
        assert 'title' in SWAGGER_CONFIG
        assert isinstance(SWAGGER_CONFIG['title'], str)
        assert len(SWAGGER_CONFIG['title']) > 0
    
    def test_swagger_config_has_version(self):
        """Test SWAGGER_CONFIG has version."""
        from src.api_docs import SWAGGER_CONFIG
        
        assert 'version' in SWAGGER_CONFIG
        assert isinstance(SWAGGER_CONFIG['version'], str)
    
    def test_swagger_config_specs_route(self):
        """Test SWAGGER_CONFIG specs route."""
        from src.api_docs import SWAGGER_CONFIG
        
        assert 'specs_route' in SWAGGER_CONFIG
        assert SWAGGER_CONFIG['specs_route'] == '/api/docs/'
    
    def test_swagger_config_swagger_ui_enabled(self):
        """Test Swagger UI is enabled."""
        from src.api_docs import SWAGGER_CONFIG
        
        assert 'swagger_ui' in SWAGGER_CONFIG
        assert SWAGGER_CONFIG['swagger_ui'] is True


class TestSwaggerTemplate:
    """Test Swagger template configuration."""
    
    def test_swagger_template_exists(self):
        """Test SWAGGER_TEMPLATE is defined."""
        from src import api_docs
        
        assert hasattr(api_docs, 'SWAGGER_TEMPLATE')
        assert isinstance(api_docs.SWAGGER_TEMPLATE, dict)
    
    def test_swagger_template_has_info(self):
        """Test SWAGGER_TEMPLATE has info section."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        assert 'info' in SWAGGER_TEMPLATE
        assert isinstance(SWAGGER_TEMPLATE['info'], dict)
    
    def test_swagger_template_info_has_title(self):
        """Test info section has title."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        info = SWAGGER_TEMPLATE['info']
        assert 'title' in info
        assert isinstance(info['title'], str)
        assert 'LocalChat' in info['title']
    
    def test_swagger_template_info_has_description(self):
        """Test info section has description."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        info = SWAGGER_TEMPLATE['info']
        assert 'description' in info
        assert isinstance(info['description'], str)
        assert len(info['description']) > 100
    
    def test_swagger_template_info_has_version(self):
        """Test info section has version."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        info = SWAGGER_TEMPLATE['info']
        assert 'version' in info
        assert isinstance(info['version'], str)
    
    def test_swagger_template_info_has_contact(self):
        """Test info section has contact."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        info = SWAGGER_TEMPLATE['info']
        assert 'contact' in info
        assert isinstance(info['contact'], dict)
    
    def test_swagger_template_info_has_license(self):
        """Test info section has license."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        info = SWAGGER_TEMPLATE['info']
        assert 'license' in info
        assert isinstance(info['license'], dict)
        assert 'name' in info['license']


class TestSwaggerSpec:
    """Test Swagger specification structure."""
    
    def test_swagger_template_has_swagger_version(self):
        """Test Swagger version is specified."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        assert 'swagger' in SWAGGER_TEMPLATE
        assert SWAGGER_TEMPLATE['swagger'] == '2.0'
    
    def test_swagger_template_has_host(self):
        """Test Swagger host is specified."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        assert 'host' in SWAGGER_TEMPLATE
        assert isinstance(SWAGGER_TEMPLATE['host'], str)
    
    def test_swagger_template_has_base_path(self):
        """Test Swagger basePath is specified."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        assert 'basePath' in SWAGGER_TEMPLATE
        assert SWAGGER_TEMPLATE['basePath'] == '/'
    
    def test_swagger_template_has_schemes(self):
        """Test Swagger schemes are specified."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        assert 'schemes' in SWAGGER_TEMPLATE
        assert isinstance(SWAGGER_TEMPLATE['schemes'], list)
        assert 'http' in SWAGGER_TEMPLATE['schemes']
    
    def test_swagger_template_has_consumes(self):
        """Test Swagger consumes is specified."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        assert 'consumes' in SWAGGER_TEMPLATE
        assert isinstance(SWAGGER_TEMPLATE['consumes'], list)
        assert 'application/json' in SWAGGER_TEMPLATE['consumes']
    
    def test_swagger_template_has_produces(self):
        """Test Swagger produces is specified."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        assert 'produces' in SWAGGER_TEMPLATE
        assert isinstance(SWAGGER_TEMPLATE['produces'], list)
        assert 'application/json' in SWAGGER_TEMPLATE['produces']


class TestSwaggerSecurity:
    """Test Swagger security definitions."""
    
    def test_swagger_template_has_security_definitions(self):
        """Test security definitions exist."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        assert 'securityDefinitions' in SWAGGER_TEMPLATE
        assert isinstance(SWAGGER_TEMPLATE['securityDefinitions'], dict)
    
    def test_swagger_template_has_bearer_auth(self):
        """Test Bearer authentication is defined."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        sec_defs = SWAGGER_TEMPLATE['securityDefinitions']
        assert 'Bearer' in sec_defs
        assert sec_defs['Bearer']['type'] == 'apiKey'
        assert sec_defs['Bearer']['name'] == 'Authorization'


class TestSwaggerTags:
    """Test Swagger tags."""
    
    def test_swagger_template_has_tags(self):
        """Test tags are defined."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        assert 'tags' in SWAGGER_TEMPLATE
        assert isinstance(SWAGGER_TEMPLATE['tags'], list)
        assert len(SWAGGER_TEMPLATE['tags']) > 0
    
    def test_swagger_tags_have_required_fields(self):
        """Test each tag has name and description."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        for tag in SWAGGER_TEMPLATE['tags']:
            assert 'name' in tag
            assert 'description' in tag
            assert isinstance(tag['name'], str)
            assert isinstance(tag['description'], str)
    
    def test_swagger_has_system_tag(self):
        """Test System tag exists."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        tag_names = [tag['name'] for tag in SWAGGER_TEMPLATE['tags']]
        assert 'System' in tag_names
    
    def test_swagger_has_documents_tag(self):
        """Test Documents tag exists."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        tag_names = [tag['name'] for tag in SWAGGER_TEMPLATE['tags']]
        assert 'Documents' in tag_names
    
    def test_swagger_has_models_tag(self):
        """Test Models tag exists."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        tag_names = [tag['name'] for tag in SWAGGER_TEMPLATE['tags']]
        assert 'Models' in tag_names
    
    def test_swagger_has_chat_tag(self):
        """Test Chat tag exists."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        tag_names = [tag['name'] for tag in SWAGGER_TEMPLATE['tags']]
        assert 'Chat' in tag_names


class TestSwaggerDefinitions:
    """Test Swagger definitions."""
    
    def test_swagger_template_has_definitions(self):
        """Test definitions section exists."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        assert 'definitions' in SWAGGER_TEMPLATE
        assert isinstance(SWAGGER_TEMPLATE['definitions'], dict)
    
    def test_swagger_has_error_definition(self):
        """Test Error definition exists."""
        from src.api_docs import SWAGGER_TEMPLATE
        
        assert 'Error' in SWAGGER_TEMPLATE['definitions']
        error_def = SWAGGER_TEMPLATE['definitions']['Error']
        assert 'type' in error_def
        assert error_def['type'] == 'object'
