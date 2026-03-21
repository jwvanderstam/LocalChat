"""
Example LocalChat Plugin
========================

Drop this file (or a copy with a new name) into the ``plugins/`` directory.
LocalChat discovers and loads it automatically on the next startup, or
immediately via ``POST /api/plugins/reload``.

Required: at least one ``@tool_registry.register`` decorated function.
Optional: a ``PLUGIN_META`` dict for display in ``GET /api/plugins``.

To write your own plugin:
  1. Copy this file to ``plugins/my_plugin.py``.
  2. Replace the example tools with your own logic.
  3. Restart or call ``POST /api/plugins/reload`` — done.
"""

from src.tools.registry import tool_registry

# ---------------------------------------------------------------------------
# Metadata (optional — shown in GET /api/plugins)
# ---------------------------------------------------------------------------

PLUGIN_META = {
    "name": "Example Plugin",
    "version": "1.0.0",
    "author": "LocalChat Team",
    "description": "Demonstrates the plugin system with two sample tools.",
}


# ---------------------------------------------------------------------------
# Tool 1 — word_count
# ---------------------------------------------------------------------------

@tool_registry.register(
    name="word_count",
    description=(
        "Count the number of words in the provided text. "
        "Useful when the user asks how long a passage or document excerpt is."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text whose words should be counted.",
            },
        },
        "required": ["text"],
    },
)
def word_count(text: str) -> str:
    """Return word and character counts for *text*."""
    words = len(text.split())
    chars = len(text)
    return f"{words} word(s), {chars} character(s)."


# ---------------------------------------------------------------------------
# Tool 2 — reverse_text
# ---------------------------------------------------------------------------

@tool_registry.register(
    name="reverse_text",
    description="Reverse the characters in the provided text.",
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to reverse.",
            },
        },
        "required": ["text"],
    },
)
def reverse_text(text: str) -> str:
    """Return *text* with its characters in reverse order."""
    return text[::-1]
