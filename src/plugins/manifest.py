"""A plugin's manifest: what it may reach, who may use it, and what it configures.

Read from module-level names once the plugin file has been imported. Anything wrong
raises :class:`ManifestError`, and the loader disables that plugin and nothing else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

from ..utils.caller import ROLE_LEVELS

#: How far the plugin's retrieval reaches: its workspace, the global tier, or both.
SCOPES = ("local", "global", "hybrid")
#: The hooks PC-2 will fire. Named now so a manifest is validated against the catalogue.
HOOKS = ("on_document_ingested", "on_scheduler_tick", "on_tool_invocation", "on_route_mount")
_CONFIG_TYPES: dict[str, type] = {"str": str, "int": int, "float": float, "bool": bool}
_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")

ConfigValue = str | int | float | bool


class ManifestError(ValueError):
    """The manifest is malformed; the plugin is disabled."""


@dataclass(frozen=True)
class Manifest:
    scope: str = "local"
    min_role: str = "viewer"
    hooks: tuple[str, ...] = ()
    #: key -> (type name, default)
    config: dict[str, tuple[str, ConfigValue]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "min_role": self.min_role,
            "hooks": list(self.hooks),
            "config": {k: {"type": t, "default": d} for k, (t, d) in self.config.items()},
        }


def read_manifest(module: ModuleType) -> Manifest:
    """Validate the ``PLUGIN_*`` names on *module*; an absent one takes its default."""
    scope = getattr(module, "PLUGIN_SCOPE", "local")
    if scope not in SCOPES:
        raise ManifestError(f"PLUGIN_SCOPE must be one of {', '.join(SCOPES)}, not {scope!r}")

    min_role = getattr(module, "PLUGIN_MIN_ROLE", "viewer")
    if min_role not in ROLE_LEVELS:
        raise ManifestError(
            f"PLUGIN_MIN_ROLE must be one of {', '.join(ROLE_LEVELS)}, not {min_role!r}"
        )

    # Writing to the Global Knowledge Base is an admin's decision (GKB-2), and no service
    # lets a plugin write anything yet. Accepting True would promise what nothing honours.
    contributes = getattr(module, "PLUGIN_CONTRIBUTES", False)
    if contributes is not False:
        raise ManifestError("PLUGIN_CONTRIBUTES must be False: no contribution service exists")

    hooks = getattr(module, "PLUGIN_HOOKS", [])
    if not isinstance(hooks, (list, tuple)) or not all(isinstance(h, str) for h in hooks):
        raise ManifestError("PLUGIN_HOOKS must be a list of hook names")
    unknown = sorted(set(hooks) - set(HOOKS))
    if unknown:
        raise ManifestError(f"PLUGIN_HOOKS names unknown hook(s): {', '.join(unknown)}")

    return Manifest(
        scope=scope,
        min_role=min_role,
        hooks=tuple(hooks),
        config=_read_config(getattr(module, "PLUGIN_CONFIG", {})),
    )


def _read_config(declared: object) -> dict[str, tuple[str, ConfigValue]]:
    if not isinstance(declared, dict):
        raise ManifestError("PLUGIN_CONFIG must be a dict of KEY: (type, default)")
    out: dict[str, tuple[str, ConfigValue]] = {}
    for key, spec in declared.items():
        if not isinstance(key, str) or not _KEY.match(key):
            raise ManifestError(f"PLUGIN_CONFIG key {key!r} must be UPPER_SNAKE_CASE")
        if not (isinstance(spec, tuple) and len(spec) == 2 and spec[0] in _CONFIG_TYPES):
            raise ManifestError(
                f"PLUGIN_CONFIG[{key!r}] must be (type, default) with type one of "
                f"{', '.join(_CONFIG_TYPES)}"
            )
        type_name, default = spec
        if not _is_type(default, type_name):
            raise ManifestError(f"PLUGIN_CONFIG[{key!r}] default {default!r} is not a {type_name}")
        out[key] = (type_name, default)
    return out


def _is_type(value: object, type_name: str) -> bool:
    # bool is an int in Python; a flag must not pass as a number, nor a number as a flag.
    if type_name == "bool":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if type_name == "float":
        return isinstance(value, (int, float))
    return isinstance(value, _CONFIG_TYPES[type_name])


def parse_setting(raw: str, type_name: str) -> ConfigValue:
    """Type an environment value for a declared key; raise ManifestError if it does not parse."""
    if type_name == "str":
        return raw
    if type_name == "bool":
        lowered = raw.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
        raise ManifestError(f"{raw!r} is not a bool")
    try:
        return int(raw) if type_name == "int" else float(raw)
    except ValueError as exc:
        raise ManifestError(f"{raw!r} is not a {type_name}") from exc
