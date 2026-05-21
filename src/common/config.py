"""Configuration management for AgentOrchestration."""
import os
from typing import Any


def _coerce_value(value: str) -> Any:
    """Coerce a string env value to its proper Python type."""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _load_env_overrides(env_prefix: str = "ORCHESTRATION_") -> dict[str, Any]:
    """Load configuration overrides from environment variables.
    
    Environment variables prefixed with ORCHESTRATION_ override config values.
    Example: ORCHESTRATION_MAX_WORKERS=10 overrides config["max_workers"].
    
    Supports boolean strings ("true"/"false"), integers, floats, and raw strings.
    """
    overrides: dict[str, Any] = {}
    for key, value in os.environ.items():
        if key.startswith(env_prefix):
            config_key = key[len(env_prefix):].lower()
            overrides[config_key] = _coerce_value(value)
    return overrides


def merge_config(base: dict[str, Any], env_overrides: dict[str, Any]) -> dict[str, Any]:
    """Merge environment overrides into base configuration."""
    result = base.copy()
    result.update(env_overrides)
    return result


def load_config() -> dict[str, Any]:
    """Load and return the application configuration."""
    base_config = {
        "max_workers": 10,
        "timeout_seconds": 300,
        "retry_attempts": 3,
        "debug_mode": False,
    }
    env_overrides = _load_env_overrides()
    return merge_config(base_config, env_overrides)
