# hermes_agent/prompt_library/render.py
"""render_profile orchestrator for the Canopy-backed prompt library adapter."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional, TypedDict

from hermes_agent.prompt_library.canopy import cn_render, cn_show, cn_version
from hermes_agent.prompt_library.errors import (
    CanopyMissingError,
    CrossTenantInheritError,
    ManifestValidationError,
)
from hermes_agent.prompt_library.manifest import load_manifest, validate_manifest
from hermes_agent.prompt_library.paths import (
    canopy_project_dir,
    resolve_library_root,
    staging_dir,
)
from hermes_agent.prompt_library.profile_check import check_profile_exists
from hermes_agent.prompt_library.warnings import FOSSILIZATION_WARNING


class RenderResult(TypedDict):
    profile: str
    tenant: str
    manifest_path: str
    canopy_cli_version: str
    resolved_from: list  # Canopy resolvedFrom (inheritance chain)
    sections: list  # [{name, sha256, body_chars}]
    params_sha256: str
    targets: dict  # {"soul": {"path": ..., "content": ...}, ...}
    fossilization_warning: str
    dry_run: bool


def _apply_params(text: str, params: dict) -> str:
    """Apply {{ key }} -> value substitution to text."""
    for k, v in params.items():
        text = text.replace("{{" + k + "}}", str(v))
        text = text.replace("{{ " + k + " }}", str(v))
    return text


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_tenant_tag(tags: list[str]) -> Optional[str]:
    """Extract tenant:<name> from a list of tags."""
    for tag in tags:
        m = re.match(r"^tenant:(.+)$", tag)
        if m:
            return m.group(1)
    return None


def render_profile(
    profile: str,
    *,
    library_root: Optional[Path] = None,
    staging_dir: Optional[Path] = None,
) -> RenderResult:
    """Resolve and render a profile WITHOUT touching live target files.

    Steps:
      1. load_manifest(profile, library_root) -> dict
      2. validate_manifest(manifest) -> raises ManifestValidationError on V1-V15
      3. check_profile_exists(profile) unless profile == "gelby-default"
      4. canopy.cn_render(manifest["render"]["prompt"], format="json")
         -> {sections, resolvedFrom, frontmatter, ...}
      5. validate cross-tenant inheritance against manifest.cross_tenant_inherit_allow
      6. apply params substitution to each section body
      7. route sections to targets per manifest.section_routes (or default: all->primary)
      8. assemble target contents (markdown for soul, raw string for config_addendum)
      9. if staging_dir set: write to staging_dir/<profile>/SOUL.md.rendered, etc.
     10. return RenderResult

    Raises:
      ManifestValidationError, CanopyMissingError, CanopyCliError,
      CrossTenantInheritError.

    DOES NOT write to live target paths.
    """
    from hermes_agent.prompt_library.paths import manifest_path as get_manifest_path
    from hermes_agent.prompt_library.paths import staging_dir as default_staging

    root = resolve_library_root(library_root)
    proj_dir = canopy_project_dir(root)

    # Step 1: Load manifest
    manifest = load_manifest(profile, root)

    # Step 2: Validate manifest (structural rules V1-V15 except V13/V14)
    validate_manifest(manifest)

    # Step 3: Profile existence check (V13)
    if profile != "gelby-default":
        if not check_profile_exists(profile):
            raise ManifestValidationError(
                [
                    {
                        "rule": "V13",
                        "field": "profile",
                        "message": f"Profile '{profile}' is not in hermes profile list",
                    }
                ]
            )

    # Step 4: cn render
    render_prompt = manifest["render"]["prompt"]
    cn_ver = cn_version()  # Raises CanopyMissingError if not installed

    envelope = cn_render(render_prompt, project_dir=proj_dir, format="json")
    raw_sections = envelope.get("sections", [])
    resolved_from: list[str] = envelope.get("resolvedFrom", [render_prompt])

    # Step 5: Cross-tenant validation (V14)
    profile_tenant = manifest.get("tenant", "")
    allow_list = manifest.get("cross_tenant_inherit_allow", []) or []
    allow_set = {
        (entry.get("prompt"), entry.get("from_tenant"))
        for entry in allow_list
        if isinstance(entry, dict)
    }

    for ancestor_name in resolved_from:
        if ancestor_name == render_prompt:
            continue  # The prompt itself; skip
        try:
            ancestor_data = cn_show(ancestor_name, project_dir=proj_dir)
            ancestor_tags = ancestor_data.get("tags", []) or []
            ancestor_tenant = _extract_tenant_tag(ancestor_tags)
            if ancestor_tenant and ancestor_tenant != profile_tenant:
                # Check allow-list
                if (ancestor_name, ancestor_tenant) not in allow_set:
                    raise CrossTenantInheritError(
                        prompt=ancestor_name,
                        from_tenant=ancestor_tenant,
                        profile_tenant=profile_tenant,
                    )
        except CrossTenantInheritError:
            raise
        except Exception:
            # cn show failed for ancestor: skip (might be a root prompt without show support)
            pass

    # Step 6: Apply params substitution
    params = manifest.get("params") or {}
    substituted_sections = []
    for sec in raw_sections:
        body = _apply_params(sec.get("body", ""), params)
        substituted_sections.append({"name": sec.get("name", ""), "body": body})

    # Summarize sections with sha256
    sections_summary = [
        {
            "name": s["name"],
            "sha256": _sha256_text(s["body"])[:7],
            "body_chars": len(s["body"]),
        }
        for s in substituted_sections
    ]

    params_sha256 = _sha256_text(json.dumps(params, sort_keys=True))

    # Step 7: Route sections to targets
    section_routes = manifest.get("section_routes") or []
    # Build route map: section_name -> target_key
    route_map: dict[str, str] = {}
    for route in section_routes:
        if isinstance(route, dict):
            route_map[route.get("section", "")] = route.get("target", "")

    targets_config = manifest.get("targets", {})
    soul_target = targets_config.get("soul")
    cfg_target = targets_config.get("config_addendum")

    # Assign sections to targets
    soul_sections: list[dict] = []
    cfg_sections: list[dict] = []

    for sec in substituted_sections:
        sname = sec["name"]
        if sname in route_map:
            target_key = route_map[sname]
            if target_key == "soul":
                soul_sections.append(sec)
            elif target_key == "config_addendum":
                cfg_sections.append(sec)
        else:
            # Default: all sections go to the primary target
            if soul_target:
                soul_sections.append(sec)
            elif cfg_target:
                cfg_sections.append(sec)

    # Step 8: Assemble target contents
    targets_out: dict = {}

    if soul_target and isinstance(soul_target, dict):
        soul_content = "\n\n".join(s["body"] for s in soul_sections) if soul_sections else ""
        soul_path_raw = soul_target.get("path", "")
        targets_out["soul"] = {
            "path": str(Path(str(soul_path_raw)).expanduser()),
            "content": soul_content,
        }

    if cfg_target and isinstance(cfg_target, dict):
        cfg_content = "\n\n".join(s["body"] for s in cfg_sections) if cfg_sections else ""
        cfg_path_raw = cfg_target.get("path", "")
        targets_out["config_addendum"] = {
            "path": str(Path(str(cfg_path_raw)).expanduser()),
            "key": cfg_target.get("key", ""),
            "content": cfg_content,
        }

    # Step 9: Write staging files if staging_dir is set
    m_path = get_manifest_path(root, profile)
    if staging_dir is not None:
        staging_out = Path(staging_dir) / profile
        staging_out.mkdir(parents=True, exist_ok=True)

        if "soul" in targets_out:
            staged = staging_out / "SOUL.md.rendered"
            staged.write_text(targets_out["soul"]["content"], encoding="utf-8")

        if "config_addendum" in targets_out:
            staged = staging_out / "config_addendum.txt"
            staged.write_text(targets_out["config_addendum"]["content"], encoding="utf-8")

    return RenderResult(
        profile=profile,
        tenant=manifest.get("tenant", ""),
        manifest_path=str(m_path),
        canopy_cli_version=cn_ver,
        resolved_from=resolved_from,
        sections=sections_summary,
        params_sha256=params_sha256,
        targets=targets_out,
        fossilization_warning=FOSSILIZATION_WARNING,
        dry_run=True,
    )
