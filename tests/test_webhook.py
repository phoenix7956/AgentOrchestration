import pytest
from src.orchestrator.webhook import (
    IdempotencyStore,
    WorkspaceIsolation,
    WebhookDelivery,
    WebhookManager,
)


class TestIdempotencyStore:
    """Tests for Issue #1947 — idempotency keys per event delivery."""

    def test_first_delivery_accepted(self):
        store = IdempotencyStore(max_age_seconds=3600)
        key = "evt-001"
        event = {"type": "agent.started", "payload": {"agent_id": "a1"}}
        is_new, cached = store.check_and_record(key, event)
        assert is_new is True
        assert cached is None

    def test_duplicate_same_event_returns_cached(self):
        store = IdempotencyStore(max_age_seconds=3600)
        key = "evt-002"
        event = {"type": "agent.started", "payload": {"agent_id": "a1"}}
        store.check_and_record(key, event)
        is_new, cached = store.check_and_record(key, event)
        assert is_new is False
        assert cached["status"] == "accepted"

    def test_same_key_different_payload_rejected(self):
        store = IdempotencyStore(max_age_seconds=3600)
        key = "evt-003"
        event_v1 = {"type": "agent.started", "payload": {"agent_id": "a1"}}
        event_v2 = {"type": "agent.started", "payload": {"agent_id": "a2"}}  # different payload
        store.check_and_record(key, event_v1)
        is_new, cached = store.check_and_record(key, event_v2)
        assert is_new is False
        assert cached["status"] == "rejected"
        assert cached["reason"] == "idempotency_key_reused"

    def test_different_key_same_event_accepted(self):
        store = IdempotencyStore(max_age_seconds=3600)
        event = {"type": "agent.started", "payload": {"agent_id": "a1"}}
        store.check_and_record("key-a", event)
        is_new, _ = store.check_and_record("key-b", event)
        assert is_new is True  # different key = different delivery

    def test_expired_entries_purged(self):
        store = IdempotencyStore(max_age_seconds=0.1)
        store.check_and_record("expire-test", {"type": "x"})
        import time; time.sleep(0.2)
        is_new, _ = store.check_and_record("expire-test", {"type": "x"})
        assert is_new is True  # expired entry was purged

    def test_internal_fields_ignored_in_hash(self):
        store = IdempotencyStore(max_age_seconds=3600)
        event_a = {"type": "agent.started", "_internal_ts": 12345, "_delivery_attempt": 1}
        event_b = {"type": "agent.started", "_internal_ts": 99999, "_delivery_attempt": 3}
        store.check_and_record("internal-test", event_a)
        is_new, cached = store.check_and_record("internal-test", event_b)
        # Same core event, internal metadata differs — treated as duplicate
        assert is_new is False


class TestWorkspaceIsolation:
    def test_register_and_validate_endpoint(self):
        ws = WorkspaceIsolation()
        ws.register_endpoint("ws-1", "ep-1")
        assert ws.is_valid("ws-1", "ep-1") is True

    def test_invalid_endpoint_rejected(self):
        ws = WorkspaceIsolation()
        ws.register_endpoint("ws-1", "ep-1")
        assert ws.is_valid("ws-1", "ep-999") is False

    def test_disable_endpoint(self):
        ws = WorkspaceIsolation()
        ws.register_endpoint("ws-1", "ep-1")
        ws.disable_endpoint("ws-1", "ep-1")
        assert ws.is_valid("ws-1", "ep-1") is False
        assert ws.is_rotated("ws-1", "ep-1") is True

    def test_rotated_endpoint_rejected(self):
        ws = WorkspaceIsolation()
        ws.register_endpoint("ws-1", "ep-1")
        ws.disable_endpoint("ws-1", "ep-1")
        assert ws.is_rotated("ws-1", "ep-1") is True


class TestWebhookDelivery:
    def test_record_strips_internal_fields(self):
        delivery = WebhookDelivery()
        delivery.record(
            delivery_id="del-1",
            endpoint_id="ep-1",
            workspace_id="ws-1",
            event={"type": "test"},
            outcome={"status": "delivered", "_internal_ts": 999, "_delivery_attempt": 2},
        )
        outcome = delivery.get_outcome("del-1")
        assert outcome == {"status": "delivered"}
        assert "_internal_ts" not in outcome

    def test_unknown_delivery_id_returns_none(self):
        delivery = WebhookDelivery()
        assert delivery.get_outcome("unknown-id") is None


class TestWebhookManager:
    def test_valid_delivery_first_time(self):
        mgr = WebhookManager()
        mgr.register_endpoint("ws-1", "ep-1")
        ok, outcome = mgr.deliver(
            idempotency_key="key-1",
            workspace_id="ws-1",
            endpoint_id="ep-1",
            event={"type": "test"},
        )
        assert ok is True
        assert outcome is None

    def test_duplicate_suppressed(self):
        mgr = WebhookManager()
        mgr.register_endpoint("ws-1", "ep-1")
        mgr.deliver(idempotency_key="key-2", workspace_id="ws-1", endpoint_id="ep-1", event={"type": "test"})
        ok, outcome = mgr.deliver(idempotency_key="key-2", workspace_id="ws-1", endpoint_id="ep-1", event={"type": "test"})
        assert ok is False
        assert outcome["status"] == "accepted"

    def test_invalid_endpoint_raises(self):
        mgr = WebhookManager()
        with pytest.raises(ValueError, match="not registered"):
            mgr.deliver(idempotency_key="key-3", workspace_id="ws-1", endpoint_id="ep-999", event={"type": "test"})

    def test_rotated_endpoint_raises(self):
        mgr = WebhookManager()
        mgr.register_endpoint("ws-1", "ep-rotated")
        mgr.disable_endpoint("ws-1", "ep-rotated")
        with pytest.raises(ValueError, match="rotated"):
            mgr.deliver(idempotency_key="key-4", workspace_id="ws-1", endpoint_id="ep-rotated", event={"type": "test"})

    def test_workspace_isolation(self):
        mgr = WebhookManager()
        mgr.register_endpoint("ws-a", "ep-a")
        mgr.register_endpoint("ws-b", "ep-b")
        # ep-a belongs to ws-a, not ws-b
        with pytest.raises(ValueError, match="not registered"):
            mgr.deliver(idempotency_key="key-5", workspace_id="ws-b", endpoint_id="ep-a", event={"type": "test"})
