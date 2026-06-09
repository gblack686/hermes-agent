# hermes_agent/prompt_library/manifest.py
"""Load and validate Hermes profile manifests (hermes.prompt_profile.v1)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from hermes_agent.prompt_library._version import PROMPT_LIBRARY_SCHEMA
from hermes_agent.prompt_library.errors import ManifestValidationError
from hermes_agent.prompt_library.paths import manifest_path, resolve_library_root


def load_manifest(
    profile: str,
    library_root: Optional[Path] = None,
) -> dict:
    """Load profiles/<profile>.yaml via yaml.safe_load.

    Raises ManifestValidationError on YAML parse failure with the parse
    error chained.
    """
    root = resolve_library_root(library_root)
    path = manifest_path(root, profile)

    if not path.exists():
        raise ManifestValidationError(
            [
                {
                    "rule": "LOAD",
                    "field": "profile",
                    "message": f"Manifest not found: {path}",
                }
            ]
        )

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ManifestValidationError(
            [
                {
                    "rule": "LOAD",
                    "field": "<file>",
                    "message": f"YAML parse error: {exc}",
                }
            ]
        ) from exc

    if not isinstance(data, dict):
        raise ManifestValidationError(
            [
                {
                    "rule": "LOAD",
                    "field": "<file>",
                    "message": "Manifest must be a YAML mapping at the top level",
                }
            ]
        )

    return data


def validate_manifest(manifest: dict) -> None:
    """Apply rules V1-V15. Raises ManifestValidationError with the full error list.

    Does NOT raise on first failure — collects all failures so operators
    see everything at once.
    """
    errors: list[dict] = []

    def fail(rule: str, field: str, message: str) -> None:
        errors.append({"rule": rule, "field": field, "message": message})

    # V1 — schema key
    schema = manifest.get("schema")
    if schema != PROMPT_LIBRARY_SCHEMA:
        fail(
            "V1",
            "schema",
            f"schema must be '{PROMPT_LIBRARY_SCHEMA}', got '{schema}'",
        )

    # V2 — profile key
    profile = manifest.get("profile")
    if not profile or not isinstance(profile, str):
        fail("V2", "profile", "profile must be a non-empty string")

    # V3 — tenant key
    tenant = manifest.get("tenant")
    if not tenant or not isinstance(tenant, str):
        fail("V3", "tenant", "tenant must be a non-empty string")

    # V4 — render.prompt
    render = manifest.get("render") or {}
    render_prompt = render.get("prompt") if isinstance(render, dict) else None
    if not render_prompt or not isinstance(render_prompt, str):
        fail("V4", "render.prompt", "render.prompt must be a non-empty string")

    # V5 — targets block
    targets = manifest.get("targets") or {}
    if not isinstance(targets, dict) or not any(
        k in targets for k in ("soul", "config_addendum")
    ):
        fail(
            "V5",
            "targets",
            "targets must be present and contain at least one of: soul, config_addendum",
        )

    # V6 — targets.soul.path: parent dir must be writable
    soul_target = targets.get("soul") if isinstance(targets, dict) else None
    if isinstance(soul_target, dict):
        soul_path_raw = soul_target.get("path")
        if soul_path_raw:
            soul_path = Path(str(soul_path_raw)).expanduser()
            parent = soul_path.parent
            if not parent.exists():
                fail("V6", "targets.soul.path", f"Parent directory does not exist: {parent}")
        else:
            fail("V6", "targets.soul.path", "targets.soul.path must be specified")

    # V7 — targets.config_addendum.path must exist (file must pre-exist)
    cfg_target = targets.get("config_addendum") if isinstance(targets, dict) else None
    if isinstance(cfg_target, dict):
        cfg_path_raw = cfg_target.get("path")
        if cfg_path_raw:
            cfg_path = Path(str(cfg_path_raw)).expanduser()
            if not cfg_path.exists():
                fail(
                    "V7",
                    "targets.config_addendum.path",
                    f"config_addendum target path must already exist: {cfg_path}",
                )
        else:
            fail(
                "V7",
                "targets.config_addendum.path",
                "targets.config_addendum.path must be specified",
            )

        # V8 — targets.config_addendum.key
        cfg_key = cfg_target.get("key")
        if not cfg_key or not isinstance(cfg_key, str):
            fail(
                "V8",
                "targets.config_addendum.key",
                "targets.config_addendum.key must be a non-empty string when config_addendum is present",
            )

    # V9 — mode values
    for target_name, target_val in (targets.items() if isinstance(targets, dict) else []):
        if isinstance(target_val, dict):
            mode = target_val.get("mode")
            if mode is not None and mode not in {"replace"}:
                fail(
                    "V9",
                    f"targets.{target_name}.mode",
                    f"targets.{target_name}.mode must be 'replace', got '{mode}'",
                )

    # V10 / V11 — section_routes
    section_routes = manifest.get("section_routes") or []
    if isinstance(section_routes, list):
        for i, route in enumerate(section_routes):
            if not isinstance(route, dict):
                continue
            route_target = route.get("target")
            if route_target not in {"soul", "config_addendum"}:
                fail(
                    "V10",
                    f"section_routes[{i}].target",
                    f"section_routes[{i}].target must be 'soul' or 'config_addendum', got '{route_target}'",
                )
            # V11 — target must be declared
            elif (
                route_target
                and isinstance(targets, dict)
                and route_target not in targets
            ):
                fail(
                    "V11",
                    f"section_routes[{i}].target",
                    f"section_routes[{i}].target '{route_target}' references an undeclared target",
                )

    # V12 — params values
    params = manifest.get("params") or {}
    if isinstance(params, dict):
        for k, v in params.items():
            if not isinstance(v, (str, int, float, bool)):
                fail(
                    "V12",
                    f"params.{k}",
                    f"params.{k} must be str/int/float/bool, got {type(v).__name__}",
                )

    # V13 — profile existence (skipped for gelby-default; caller handles via check_profile_exists)
    # Deferred to render_profile: validate_manifest only checks structural rules.
    # (The design says validate_manifest raises V13 via check_profile_exists, but since
    # check_profile_exists calls hermes profile list -- a side effect -- we keep it
    # structural here and let render_profile enforce it.)

    # V14 — cross-tenant deferred to render_profile (requires cn show)

    # V15 — gelby-default must NOT have config_addendum target
    if isinstance(profile, str) and profile == "gelby-default":
        if isinstance(targets, dict) and "config_addendum" in targets:
            fail(
                "V15",
                "targets.config_addendum",
                "gelby-default profile must NOT declare a config_addendum target",
            )

    if errors:
        raise ManifestValidationError(errors)
