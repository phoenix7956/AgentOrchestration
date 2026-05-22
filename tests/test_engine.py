import pytest
from src.orchestrator.engine import OrchestrationEngine, sanitize_task_for_exception


class TestSanitizeTaskForException:
    """Tests for Issue #1953 — raw payload sanitization in exception tracking."""

    def test_strips_raw_payload_fields(self):
        """Only structural fields survive sanitization; raw payload is dropped."""
        task = {
            "id": "task-123",
            "target_agent": "agent-a",
            "type": "process",
            "priority": 5,
            "payload": {"api_key": "secret", "user_data": {"ssn": "123-45-6789"}},
        }
        safe = sanitize_task_for_exception(task)
        assert safe == {"id": "task-123", "target_agent": "agent-a", "type": "process", "priority": 5}
        assert "payload" not in safe
        assert "api_key" not in safe

    def test_preserves_task_id_and_agent_id(self):
        """Task ID and agent ID — the fields dashboards need — are preserved."""
        task = {
            "id": "task-456",
            "target_agent": "agent-b",
            "payload": {"credit_card": "4111111111111111"},
        }
        safe = sanitize_task_for_exception(task)
        assert safe["id"] == "task-456"
        assert safe["target_agent"] == "agent-b"

    def test_nested_context_stripped(self):
        """Deeply nested local variable context is fully removed."""
        task = {
            "id": "task-789",
            "target_agent": "agent-c",
            "payload": {
                "inner": {
                    "credentials": {"password": "hunter2"},
                    "data": {"token": "jwt-token-xyz"},
                }
            },
        }
        safe = sanitize_task_for_exception(task)
        assert "payload" not in safe
        assert "inner" not in safe

    def test_mixed_structural_and_payload_fields(self):
        """When both structural and arbitrary fields coexist, only allowlist survives."""
        task = {
            "id": "task-abc",
            "target_agent": "agent-d",
            "type": "webhook",
            "priority": 10,
            "retries": 2,
            "enqueued_at": 1716400000.0,
            "raw_data": {"db_password": "dbpass", "debug": True},
            "config": {"secret_key": "sk-live"},
        }
        safe = sanitize_task_for_exception(task)
        assert safe == {
            "id": "task-abc",
            "target_agent": "agent-d",
            "type": "webhook",
            "priority": 10,
            "retries": 2,
            "enqueued_at": 1716400000.0,
        }
        assert "raw_data" not in safe
        assert "config" not in safe

    def test_empty_task(self):
        """Empty task dict is returned as-is (no fields to strip)."""
        assert sanitize_task_for_exception({}) == {}

    def test_unknown_fields_only(self):
        """Task with no structural fields — all fields treated as unknown, result empty."""
        task = {"foo": "bar", "baz": 123}
        assert sanitize_task_for_exception(task) == {}
