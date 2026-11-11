# Python 3.14 compatibility: Use string annotations to avoid __annotate__ issues
from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    Field,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)

_MODEL_NAME_EMPTY = 'Model name cannot be empty'
_MODEL_NAME_INVALID_CHARS = 'Model name contains invalid characters'
from . import config
from .utils.logging_config import get_logger

logger = get_logger(__name__)


class ChatRequest(BaseModel):

    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="User's chat message"
    )
    use_rag: bool = Field(
        default=True,
        description="Whether to use RAG mode for document context"
    )
    enhance: bool = Field(
        default=False,
        description="Whether to enrich RAG context with web search results"
    )
    history: list[dict[str, str]] = Field(
        default_factory=list,
        max_length=50,
        description="Chat conversation history"
    )
    conversation_id: str | None = Field(
        default=None,
        description="Conversation UUID for persistent memory (omit to start a new conversation)"
    )
    images: list[str] | None = Field(
        default=None,
        description="Optional list of base64-encoded images for vision-capable models"
    )
    temperature: float = Field(
        default=config.DEFAULT_TEMPERATURE,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (0 = deterministic, 2 = very creative)"
    )
    model_override: str | None = Field(
        default=None,
        max_length=100,
        description="Override the model router selection — use this exact Ollama model ID"
    )
    additional_workspace_ids: list[str] | None = Field(
        default=None,
        description="Additional workspace UUIDs to include in cross-workspace retrieval"
    )
    active_source_ids: list[str] | None = Field(
        default=None,
        description="Connector or source IDs to restrict retrieval to; omit for all sources"
    )
    knowledge_scope: Literal["local", "global", "hybrid"] = Field(
        default="local",
        description=(
            "Which documents to retrieve from: this workspace's (local), the global "
            "knowledge tier contributed by every project (global), or both (hybrid). "
            "A workspace API key may use local only."
        ),
    )

    @field_validator('conversation_id')
    @classmethod
    def valid_uuid(cls, v: str | None) -> str | None:
        """Validate conversation_id is a well-formed UUID if provided."""
        import uuid as _uuid
        # An empty value means "no conversation yet", not "a conversation named ''".
        # API clients that always send the field — an n8n HTTP node filling it from a
        # stored id that does not exist on the first message — send '' rather than
        # omitting it, and that must start a new conversation like any absent id.
        if v is not None and not v.strip():
            return None
        if v is not None:
            try:
                _uuid.UUID(v)
            except ValueError as e:
                raise ValueError('conversation_id must be a valid UUID') from e
        return v

    @field_validator('message')
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('Message cannot be empty or whitespace only')
        return v.strip()

    @field_validator('history')
    @classmethod
    def validate_history(cls, v: list[dict[str, str]]) -> list[dict[str, str]]:
        for msg in v:
            if 'role' not in msg or 'content' not in msg:
                raise ValueError('History messages must have "role" and "content" fields')
            if msg['role'] not in ['user', 'assistant']:
                raise ValueError('Role must be "user" or "assistant"')
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "message": "What is in the documents?",
                    "use_rag": True,
                    "history": [
                        {"role": "user", "content": "Hello"},
                        {"role": "assistant", "content": "Hi! How can I help?"}
                    ]
                }
            ]
        }
    }


class ModelRequest(BaseModel):

    model: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Model name"
    )

    @field_validator('model')
    @classmethod
    def model_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(_MODEL_NAME_EMPTY)
        # Remove potentially dangerous characters
        if any(char in v for char in ['/', '\\', '..', '<', '>', '|', '&']):
            raise ValueError(_MODEL_NAME_INVALID_CHARS)
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"model": "llama3.2:latest"},
                {"model": "nomic-embed-text"}
            ]
        }
    }


class ModelPullRequest(BaseModel):

    model: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Model name to pull"
    )

    @field_validator('model')
    @classmethod
    def valid_model_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(_MODEL_NAME_EMPTY)
        # Basic validation for model name format
        if not all(c.isalnum() or c in ['-', '_', '.', ':'] for c in v):
            raise ValueError(_MODEL_NAME_INVALID_CHARS)
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"model": "llama3.2"},
                {"model": "mistral:7b-instruct"}
            ]
        }
    }


class ModelDeleteRequest(BaseModel):

    model: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Model name to delete"
    )

    @field_validator('model')
    @classmethod
    def model_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(_MODEL_NAME_EMPTY)
        return v.strip()


class ChunkingParameters(BaseModel):

    chunk_size: int = Field(
        default=768,
        ge=100,
        le=2000,
        description="Chunk size in characters"
    )
    chunk_overlap: int = Field(
        default=128,
        ge=0,
        le=500,
        description="Overlap between chunks"
    )

    @model_validator(mode='after')
    def validate_overlap_less_than_size(self) -> ChunkingParameters:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError('Chunk overlap must be less than chunk size')
        return self


logger.info("Validation models loaded")


class ChangePasswordRequest(BaseModel):
    """Body of POST /api/users/me/password."""

    # Neither field is stripped or capped: a password is compared as typed, and a
    # length cap would leak the storage constraint (see LoginRequest).
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=config.USER_PASSWORD_MIN_LENGTH)


def _blank_is_none(value: str | None) -> str | None:
    return (value.strip() or None) if value is not None else None


class CreateUserRequest(BaseModel):
    """Body of POST /api/users (admin)."""

    username: StrictStr
    # Never stripped: login, password change and reset take the password as typed, so a
    # stripped one here is a password its owner cannot sign in with (defect 2).
    password: StrictStr = Field(..., min_length=config.USER_PASSWORD_MIN_LENGTH)
    email: StrictStr | None = None
    role: Literal["admin", "user"] = "user"
    # Granted in the same request, not as a follow-up call; see UsersService.create_user.
    workspace_id: StrictStr | None = None
    workspace_role: Literal["viewer", "editor", "owner"] = "editor"

    @field_validator("username")
    @classmethod
    def username_present(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("username is required")
        return v.strip()

    @field_validator("email", "workspace_id")
    @classmethod
    def blank_is_none(cls, v: str | None) -> str | None:
        return _blank_is_none(v)


class UpdateUserRequest(BaseModel):
    """Body of PUT /api/users/{id} (admin). Only the fields sent are changed."""

    # Strict, because the last-administrator rule tests ``is_active is False``: a
    # string "false" passed it and was then stored as false by Postgres (R-10).
    email: StrictStr | None = None
    role: Literal["admin", "user"] | None = None
    is_active: StrictBool | None = None
    password: StrictStr | None = Field(None, min_length=config.USER_PASSWORD_MIN_LENGTH)

    @field_validator("email")
    @classmethod
    def blank_is_none(cls, v: str | None) -> str | None:
        return _blank_is_none(v)

    @model_validator(mode="after")
    def only_email_may_be_cleared(self) -> UpdateUserRequest:
        for name in ("role", "is_active", "password"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class GrantWorkspaceRequest(BaseModel):
    """Body of POST /api/users/{id}/workspaces (admin)."""

    workspace_id: StrictStr
    role: Literal["viewer", "editor", "owner"] = "editor"

    @field_validator("workspace_id")
    @classmethod
    def workspace_present(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("workspace_id is required")
        return v.strip()


class LoginRequest(BaseModel):
    """Credentials for POST /api/auth/login."""

    username: str = Field(..., min_length=1, max_length=150, description="Username")
    # No max_length on the password: a length cap here would leak the storage
    # constraint, and PBKDF2 hashes any input to a fixed size anyway.
    password: str = Field(..., min_length=1, description="Password")

    @field_validator('username')
    @classmethod
    def username_normalised(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Username cannot be empty")
        return v.strip().lower()


class ContributionRequest(BaseModel):
    """Documents a workspace contributes to the global knowledge tier (GKB-2)."""

    # A contribution is a curated choice, not a bulk export; the cap says so and bounds
    # the one transaction the copy runs in.
    document_ids: list[int] = Field(..., min_length=1, max_length=100)
