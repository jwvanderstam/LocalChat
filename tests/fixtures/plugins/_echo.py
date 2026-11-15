"""The reference plugin (PC-3): every service and every hook, with no domain logic.

It is the core's own fixture, not a shipped plugin. Each capability of the contract is
proven against it before any domain plugin uses one (`.claude/rules/plugins.md`). It
lives under ``tests/`` so the ``core-without-plugins`` job, which empties ``plugins/``,
still runs it, and so no installation ever offers its tool to a model.

Copy it to start a plugin: the shape is the contract, the bodies are placeholders.
It imports nothing from ``src``; everything it uses arrives on ``services``.
"""

import json

PLUGIN_META = {
    "name": "Echo",
    "version": "1.0.0",
    "author": "LocalChat",
    "description": "Echoes what each service and hook hands it.",
}

PLUGIN_SCOPE = "hybrid"  # retrieval reach: local | global | hybrid
PLUGIN_MIN_ROLE = "viewer"  # who may use its tools: viewer | editor | owner | admin
PLUGIN_HOOKS = ["on_document_ingested", "on_scheduler_tick", "on_tool_invocation"]
PLUGIN_CONFIG = {  # read from PLUGIN__ECHO_<KEY>; the default applies when unset
    "PREFIX": ("str", "echo"),
}

#: Every hook payload received, in order, as (hook, payload).
received = []


def setup(services):
    prefix = services.config.get("PREFIX")

    @services.tools.register(
        name="echo",
        description="Echo the text back, with what the core says about the caller and the text.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to echo."},
                "knowledge_scope": {
                    "type": "string",
                    "enum": ["local", "global", "hybrid"],
                    "description": "Which tier to search for the text.",
                },
            },
            "required": ["text"],
        },
    )
    def echo(text, knowledge_scope="local"):
        caller = services.identity.current()
        return json.dumps({
            "prefix": prefix,
            "text": text,
            "role": caller.role if caller else None,
            "may_edit": services.identity.has_role("editor"),
            "found": [c["filename"] for c in services.retrieval.retrieve(text, knowledge_scope, top_k=3)],
            "dimensions": len(services.llm.embed(text)),
        })


def on_document_ingested(payload):
    received.append(("on_document_ingested", payload))


def on_scheduler_tick(payload):
    received.append(("on_scheduler_tick", payload))


def on_tool_invocation(payload):
    received.append(("on_tool_invocation", payload))
