"""Tests for configuration management."""
import os
import pytest
from src.common.config import _coerce_value, _load_env_overrides, merge_config


class TestCoerceValue:
    """Tests for _coerce_value helper."""

    def test_coerce_true_strings(self):
        assert _coerce_value("true") is True
        assert _coerce_value("True") is True
        assert _coerce_value("TRUE") is True

    def test_coerce_false_strings(self):
        assert _coerce_value("false") is False
        assert _coerce_value("False") is False
        assert _coerce_value("FALSE") is False

    def test_coerce_boolean_mixed_case(self):
        assert _coerce_value("FaLsE") is False
        assert _coerce_value("tRuE") is True

    def test_coerce_integer(self):
        assert _coerce_value("123") == 123
        assert _coerce_value("-456") == -456
        assert _coerce_value("0") == 0

    def test_coerce_float(self):
        assert _coerce_value("1.5") == 1.5
        assert _coerce_value("-2.5") == -2.5
        assert _coerce_value("0.0") == 0.0

    def test_coerce_string(self):
        assert _coerce_value("hello") == "hello"
        assert _coerce_value("hello world") == "hello world"


class TestLoadEnvOverrides:
    """Tests for _load_env_overrides."""

    def test_env_override_boolean_false(self, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_DEBUG_MODE", "false")
        overrides = _load_env_overrides()
        assert overrides.get("debug_mode") is False

    def test_env_override_boolean_true(self, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_DEBUG_MODE", "true")
        overrides = _load_env_overrides()
        assert overrides.get("debug_mode") is True

    def test_env_override_boolean_mixed_case(self, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_DEBUG_MODE", "FaLsE")
        overrides = _load_env_overrides()
        assert overrides.get("debug_mode") is False

    def test_env_override_integer(self, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_MAX_WORKERS", "25")
        overrides = _load_env_overrides()
        assert overrides.get("max_workers") == 25

    def test_env_override_float(self, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_TIMEOUT_SECONDS", "60.5")
        overrides = _load_env_overrides()
        assert overrides.get("timeout_seconds") == 60.5

    def test_env_override_string(self, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_CUSTOM_SETTING", "my_value")
        overrides = _load_env_overrides()
        assert overrides.get("custom_setting") == "my_value"

    def test_env_override_lowercase_key(self, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_MAX_WORKERS", "50")
        overrides = _load_env_overrides()
        assert "max_workers" in overrides


class TestMergeConfig:
    """Tests for merge_config."""

    def test_merge_overrides_base(self):
        base = {"a": 1, "b": 2}
        overrides = {"b": 3, "c": 4}
        result = merge_config(base, overrides)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_merge_does_not_mutate_base(self):
        base = {"a": 1}
        overrides = {"b": 2}
        merge_config(base, overrides)
        assert base == {"a": 1}
