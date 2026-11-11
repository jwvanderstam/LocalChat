"""
Example LocalChat Plugin
========================

Drop this file (or a copy with a new name) into the ``plugins/`` directory.
LocalChat discovers and loads it automatically on the next startup, or
immediately via ``POST /api/plugins/reload``.

A plugin defines ``setup(services)`` and registers its tools there, through
``services.tools.register``. It imports nothing from ``src``: everything it needs
from the core arrives on ``services``. The ``PLUGIN_*`` names below are its manifest;
each is optional and shown with its default. See ``plugins/README.md``.

To write your own plugin:
  1. Copy this file to ``plugins/my_plugin.py``.
  2. Replace the example tools with your own logic.
  3. Restart or call ``POST /api/plugins/reload`` — done.
"""

# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

PLUGIN_META = {
    "name": "Example Plugin",
    "version": "2.0.0",
    "author": "LocalChat Team",
    "description": "Demonstrates the plugin contract with two sample tools.",
}

PLUGIN_SCOPE = "local"  # retrieval reach: local | global | hybrid
PLUGIN_MIN_ROLE = "viewer"  # who may use its tools: viewer | editor | owner | admin
PLUGIN_CONFIG = {  # read from PLUGIN_EXAMPLE_PLUGIN_<KEY>; the default applies when unset
    "MAX_CHARS": ("int", 10_000),
}


def setup(services):
    max_chars = services.config.get("MAX_CHARS")

    @services.tools.register(
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
        text = text[:max_chars]
        return f"{len(text.split())} word(s), {len(text)} character(s)."

    @services.tools.register(
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
        return text[:max_chars][::-1]
