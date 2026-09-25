"""Optional persisted subscriptions for Signal Fabric routing aids."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .envelope import AgentSignalSubscription, utc_now
from .store import SignalStore

if TYPE_CHECKING:
    pass


class SubscriptionManager:
    def __init__(self, store: SignalStore) -> None:
        self.store = store

    def subscribe(
        self,
        *,
        subscriber_type: str,
        subscriber_id: str,
        signal_type: str | None = None,
        role: str | None = None,
        capability: str | None = None,
        mission_id: str | None = None,
    ) -> AgentSignalSubscription:
        sub = AgentSignalSubscription(
            subscription_id=SignalStore.new_id("ssub"),
            subscriber_type=subscriber_type,
            subscriber_id=subscriber_id,
            signal_type=signal_type,
            role=role,
            capability=capability,
            mission_id=mission_id,
            enabled=True,
            created_at=utc_now(),
        )
        return self.store.create_subscription(sub)

    def list_for_type(self, signal_type: str) -> list[AgentSignalSubscription]:
        return self.store.list_subscriptions(signal_type=signal_type)
