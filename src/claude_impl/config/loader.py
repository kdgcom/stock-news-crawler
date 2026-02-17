"""Configuration loader for the Stock Trading System.

Loads settings from YAML files with environment variable overrides.

Loading priority (later overrides earlier):
    1. config/settings.yaml         (base defaults, committed to Git)
    2. config/settings.local.yaml   (local overrides, gitignored)
    3. Environment variables         (prefix STOCK_, e.g. STOCK_GCP_PROJECT_ID)

Usage::

    from src.claude_impl.config.loader import load_config

    config = load_config()
    print(config.gcp.project_id)
    print(config.mongodb.atlas_uri)
    print(config["risk"]["hard_limits"]["max_daily_loss_pct"])
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Project root is determined relative to this file:
# src/claude_impl/config/loader.py -> project root is 4 levels up
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_ENV_PREFIX = "STOCK_"


class DotDict(dict):
    """A dict subclass that supports attribute-style access.

    Nested dicts are automatically wrapped as DotDict instances, so
    you can write ``config.gcp.project_id`` instead of
    ``config["gcp"]["project_id"]``.

    Attribute access returns ``None`` for missing keys (instead of
    raising ``KeyError``) to simplify optional lookups.

    Examples::

        d = DotDict({"gcp": {"project_id": "my-project"}})
        assert d.gcp.project_id == "my-project"
        assert d.gcp.nonexistent is None
    """

    def __getattr__(self, key: str) -> Any:
        try:
            value = self[key]
        except KeyError:
            return None
        if isinstance(value, dict) and not isinstance(value, DotDict):
            value = DotDict(value)
            self[key] = value
        return value

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value

    def __delattr__(self, key: str) -> None:
        try:
            del self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __repr__(self) -> str:
        return f"DotDict({super().__repr__()})"


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*, modifying *base* in place.

    - If both values for a key are dicts, merge recursively.
    - Otherwise, the *override* value wins.

    Args:
        base: The base dict to merge into (modified in place).
        override: The dict whose values take priority.

    Returns:
        The merged *base* dict (same object, for convenience).
    """
    for key, value in override.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _apply_env_overrides(config: dict) -> None:
    """Apply environment variable overrides with the STOCK_ prefix.

    Environment variable names are mapped to nested config keys by
    walking the existing config tree with a greedy matching strategy.
    For example:

        STOCK_GCP_PROJECT_ID  ->  gcp.project_id
        STOCK_MONGODB_ATLAS_URI  ->  mongodb.atlas_uri
        STOCK_RISK_HARD_LIMITS_MAX_DAILY_LOSS_PCT  ->  risk.hard_limits.max_daily_loss_pct

    The matching algorithm tries the longest config key at each level
    first, which resolves ambiguity for keys containing underscores
    (e.g. "cloud_run" is treated as a single key, not split into two).
    """
    env_vars = {
        k: v for k, v in os.environ.items() if k.startswith(_ENV_PREFIX)
    }
    if not env_vars:
        return

    for env_key, env_value in env_vars.items():
        # Strip prefix and lowercase
        path_str = env_key[len(_ENV_PREFIX):].lower()
        keys = _resolve_config_path(config, path_str)
        if keys is None:
            logger.debug(
                "Environment variable %s does not match any config path, skipping",
                env_key,
            )
            continue

        # Navigate to the parent dict and set the value
        target = config
        for k in keys[:-1]:
            target = target[k]

        # Attempt type coercion to match the existing value type
        existing = target.get(keys[-1])
        target[keys[-1]] = _coerce_value(env_value, existing)
        logger.info(
            "Config override from env: %s -> %s", env_key, ".".join(keys)
        )


def _resolve_config_path(config: dict, path_str: str) -> list[str] | None:
    """Resolve an underscore-separated env suffix to a list of nested config keys.

    Uses a greedy matching strategy: at each level, try the longest matching
    key first. For example, given config keys ``cloud_run`` and ``cloud``, the
    path ``cloud_run_region`` resolves to ``["cloud_run", "region"]``.

    Args:
        config: The current config dict.
        path_str: The lowered env var suffix (without STOCK_ prefix).

    Returns:
        A list of key segments, or None if no match was found.
    """
    if not path_str:
        return []

    if not isinstance(config, dict):
        return None

    # Collect candidate keys sorted by length (longest first) for greedy match
    candidates = sorted(config.keys(), key=len, reverse=True)

    for candidate in candidates:
        candidate_lower = candidate.lower()
        if path_str == candidate_lower:
            return [candidate]
        if path_str.startswith(candidate_lower + "_"):
            remainder = path_str[len(candidate_lower) + 1:]
            sub_result = _resolve_config_path(config[candidate], remainder)
            if sub_result is not None:
                return [candidate] + sub_result

    return None


def _coerce_value(value: str, existing: Any) -> Any:
    """Coerce a string environment variable value to match the type of the existing config value.

    Args:
        value: The string value from the environment variable.
        existing: The current value in the config (used for type inference).

    Returns:
        The coerced value.
    """
    if existing is None:
        return value

    if isinstance(existing, bool):
        return value.lower() in ("true", "1", "yes")
    if isinstance(existing, int):
        try:
            return int(value)
        except ValueError:
            return value
    if isinstance(existing, float):
        try:
            return float(value)
        except ValueError:
            return value

    return value


def _to_dotdict(obj: Any) -> Any:
    """Recursively convert all dicts in a structure to DotDict instances."""
    if isinstance(obj, dict):
        return DotDict({k: _to_dotdict(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_to_dotdict(item) for item in obj]
    return obj


def load_config(
    base_path: str | Path | None = None,
    local_path: str | Path | None = None,
) -> DotDict:
    """Load the application configuration.

    Merges base settings, local overrides, and environment variables
    into a single DotDict that supports both dict-style and
    attribute-style access.

    Args:
        base_path: Path to the base settings YAML file.
            Defaults to ``<project_root>/config/settings.yaml``.
        local_path: Path to the local override YAML file.
            Defaults to ``<project_root>/config/settings.local.yaml``.

    Returns:
        A DotDict containing the fully merged configuration.
    """
    if base_path is None:
        base_path = _PROJECT_ROOT / "config" / "settings.yaml"
    else:
        base_path = Path(base_path)

    if local_path is None:
        local_path = _PROJECT_ROOT / "config" / "settings.local.yaml"
    else:
        local_path = Path(local_path)

    # 1. Load base config
    if not base_path.exists():
        logger.warning(
            "Base config file not found at %s, using empty config", base_path
        )
        config: dict = {}
    else:
        with open(base_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        logger.info("Loaded base config from %s", base_path)

    # 2. Overlay local config if it exists
    if local_path.exists():
        with open(local_path, "r", encoding="utf-8") as f:
            local_config = yaml.safe_load(f) or {}
        deep_merge(config, local_config)
        logger.info("Merged local config from %s", local_path)
    else:
        logger.debug(
            "Local config file not found at %s, skipping", local_path
        )

    # 3. Apply environment variable overrides
    _apply_env_overrides(config)

    # 4. Convert to DotDict for attribute access
    return _to_dotdict(config)
