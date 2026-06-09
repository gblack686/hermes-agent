# hermes_agent/prompt_library/profile_check.py
"""Profile existence check for the Canopy-backed prompt library adapter."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def check_profile_exists(profile: str) -> bool:
    """Return True iff `profile` is in the set of known Hermes profiles.

    Implementation order:
      1. Special-case: profile == "gelby-default" -> always True (synthetic).
      2. Try subprocess hermes profile list --json and parse.
      3. Filesystem fallback: scan ~/.hermes/profiles/ for matching dir.

    Does NOT raise on absence -- returns False. Caller decides whether to
    raise (validate_manifest raises ManifestValidationError V13).
    """
    if profile == "gelby-default":
        return True

    # Attempt 1: hermes profile list --json
    try:
        result = subprocess.run(
            ["hermes", "profile", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, list):
                # Expected: [{"name": "...", ...}, ...]
                names = [
                    item.get("name") or item.get("profile")
                    for item in data
                    if isinstance(item, dict)
                ]
                if profile in names:
                    return True
            elif isinstance(data, dict):
                # Maybe {"profiles": [...]}
                profiles_list = data.get("profiles") or []
                names = [
                    item.get("name") or item.get("profile")
                    for item in profiles_list
                    if isinstance(item, dict)
                ]
                if profile in names:
                    return True
    except Exception:
        pass

    # Attempt 2: filesystem scan of ~/.hermes/profiles/
    try:
        from hermes_constants import get_hermes_home  # type: ignore[import]

        hermes_home = Path(get_hermes_home())
    except Exception:
        hermes_home = Path.home() / ".hermes"

    profiles_root = hermes_home / "profiles"
    if profiles_root.is_dir() and (profiles_root / profile).is_dir():
        return True

    return False
