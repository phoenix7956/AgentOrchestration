"""Webhook delivery with idempotency key support.

Implements per-event idempotency keys so that retries and repeated deliveries
are handled safely without duplicating work or overwriting newer state.

Issue: AgentOrchestration/AgentOrchestration#1947
"""

import hashlib
import logging
import time
from collections import defaultdict
from threading import Lock
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)


# Fields that are internal-only and must never be exposed to external callers.
INTERNAL_FIELDS: Set[str] = {
    "_internal_ts",
    "_delivery_attempt",
    "_workspace_id",
    "_rotated",
}


class IdempotencyStore:
    """Thread-safe store for idempotency key -> outcome mapping.

    Tracks the hash of the last accepted event per key along with its outcome
    and timestamp so that duplicate deliveries can be rejected and out-of-order
    deliveries cannot overwrite newer state.
    """

    def __init__(self, max_age_seconds: float = 3600.0):
        self._max_age = max_age_seconds
        self._lock = Lock()
        # key -> (event_hash, outcome, timestamp)
        self._store: Dict[str, tuple[str, Dict, float]] = {}

    def _hash_event(self, event: Dict[str, Any]) -> str:
        """Stable hash of the event's action + payload, ignoring metadata."""
        payload = {
            k: v for k, v in event.items() if k not in INTERNAL_FIELDS
        }
        return hashlib.sha256(str(sorted(payload.items())).encode()).hexdigest()

    def check_and_record(
        self, key: str, event: Dict[str, Any]
    ) -> tuple[bool, Optional[Dict]]:
        """Atomically check whether an event with this idempotency key is new.

        Returns:
            (True, None)           — event is new, recorded and should proceed
            (False, existing_outcome) — duplicate, return cached outcome
        """
        with self._lock:
            self._purge_expired()
            event_hash = self._hash_event(event)
            if key in self._store:
                old_hash, outcome, ts = self._store[key]
                if old_hash == event_hash:
                    # Same event delivered again — safe idempotent replay
                    return False, outcome
                else:
                    # Same key, different payload — out-of-order or retry
                    # with changed payload. Reject to protect newer state.
                    logger.warning(
                        "Idempotency key %s reused for different event; rejecting.", key
                    )
                    return False, {"status": "rejected", "reason": "idempotency_key_reused"}
            else:
                self._store[key] = (event_hash, {"status": "accepted"}, time.time())
                return True, None

    def _purge_expired(self) -> None:
        """Remove entries older than max_age_seconds."""
        now = time.time()
        expired = [k for k, (_, _, ts) in self._store.items() if now - ts > self._max_age]
        for k in expired:
            self._store.pop(k, None)


class WorkspaceIsolation:
    """Ensures webhook deliveries are scoped to the correct workspace."""

    def __init__(self):
        self._lock = Lock()
        # workspace_id -> set of valid endpoint IDs
        self._workspace_endpoints: Dict[str, Set[str]] = defaultdict(set)

    def register_endpoint(self, workspace_id: str, endpoint_id: str) -> None:
        with self._lock:
            self._workspace_endpoints[workspace_id].add(endpoint_id)

    def disable_endpoint(self, workspace_id: str, endpoint_id: str) -> None:
        with self._lock:
            if endpoint_id in self._workspace_endpoints.get(workspace_id, set()):
                self._workspace_endpoints[workspace_id].discard(endpoint_id)

    def is_valid(self, workspace_id: str, endpoint_id: str) -> bool:
        with self._lock:
            return endpoint_id in self._workspace_endpoints.get(workspace_id, set())

    def is_rotated(self, workspace_id: str, endpoint_id: str) -> bool:
        """Check if the endpoint has been rotated/disable-ed since registration."""
        # A rotated endpoint is one that was registered then removed
        with self._lock:
            # If not currently valid and was previously tracked, it's rotated
            return not self.is_valid(workspace_id, endpoint_id)


class WebhookDelivery:
    """Records webhook deliveries with idempotency and workspace isolation."""

    def __init__(self):
        self._lock = Lock()
        # delivery_id -> delivery record (never exposed externally)
        self._records: Dict[str, Dict] = {}

    def record(
        self,
        delivery_id: str,
        endpoint_id: str,
        workspace_id: str,
        event: Dict[str, Any],
        outcome: Dict[str, Any],
    ) -> None:
        with self._lock:
            # Store outcome but strip internal fields from the record
            safe_outcome = {k: v for k, v in outcome.items() if k not in INTERNAL_FIELDS}
            self._records[delivery_id] = {
                "endpoint_id": endpoint_id,
                "workspace_id": workspace_id,
                "outcome": safe_outcome,
                "_internal_ts": time.time(),
            }

    def get_outcome(self, delivery_id: str) -> Optional[Dict]:
        with self._lock:
            rec = self._records.get(delivery_id)
            if rec:
                return rec["outcome"]
        return None


class WebhookManager:
    """Main entry point for webhook idempotent delivery.

    Usage::

        manager = WebhookManager()
        manager.register_workspace("ws-1")

        # Delivery attempt
        ok, outcome = manager.deliver(
            idempotency_key="evt-abc-123",
            workspace_id="ws-1",
            endpoint_id="ep-1",
            event={"type": "agent.started", "payload": {"agent_id": "agent-1"}},
        )
        if not ok:
            print("Duplicate suppressed:", outcome)
    """

    def __init__(self, idempotency_store: Optional[IdempotencyStore] = None):
        self._idempotency = idempotency_store or IdempotencyStore()
        self._workspaces = WorkspaceIsolation()
        self._delivery = WebhookDelivery()

    def register_workspace(self, workspace_id: str) -> None:
        self._workspaces.register_endpoint(workspace_id, workspace_id)

    def register_endpoint(self, workspace_id: str, endpoint_id: str) -> None:
        self._workspaces.register_endpoint(workspace_id, endpoint_id)

    def disable_endpoint(self, workspace_id: str, endpoint_id: str) -> None:
        self._workspaces.disable_endpoint(workspace_id, endpoint_id)

    def deliver(
        self,
        idempotency_key: str,
        workspace_id: str,
        endpoint_id: str,
        event: Dict[str, Any],
    ) -> tuple[bool, Optional[Dict]]:
        """Attempt to deliver an event.

        Returns (True, None) on first delivery.
        Returns (False, cached_outcome) on duplicate delivery.
        Raises ValueError if endpoint is not registered or has been rotated.
        """
        # 1. Workspace isolation check
        if not self._workspaces.is_valid(workspace_id, endpoint_id):
            raise ValueError(f"Endpoint {endpoint_id} is not registered or has been disabled")

        # 2. Check if endpoint was rotated (re-registered then removed)
        if self._workspaces.is_rotated(workspace_id, endpoint_id):
            raise ValueError(f"Endpoint {endpoint_id} has been rotated")

        # 3. Idempotency check
        is_new, cached = self._idempotency.check_and_record(idempotency_key, event)
        if not is_new:
            return False, cached

        # 4. Record delivery (outcome is internal-only, not exposed)
        delivery_id = hashlib.sha256(f"{idempotency_key}:{time.time()}".encode()).hexdigest()
        self._delivery.record(delivery_id, endpoint_id, workspace_id, event, {"status": "delivered"})

        return True, None


# Singleton for use across the application
webhook_manager = WebhookManager()
