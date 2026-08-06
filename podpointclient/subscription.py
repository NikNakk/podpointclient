"""Account subscription models returned by Pod Point."""
import json
from datetime import datetime
from typing import Any, Dict, List

from .helpers.functions import lazy_convert_to_datetime, lazy_iso_format_datetime


class SubscriptionAction:
    """An action within a subscription workflow."""

    def __init__(self, data: Dict[str, Any]):
        self.id: str = data.get("id", None)
        self.subscription_id: str = data.get("subscriptionId", None)
        self.type: str = data.get("type", None)
        self.owner: str = data.get("owner", None)
        self.status: str = data.get("status", None)
        self.depends_on: List[str] = data.get("dependsOn", [])
        self.data: Dict[str, Any] = data.get("data", {})
        self.created_at: datetime = lazy_convert_to_datetime(data.get("createdAt", None))
        self.updated_at: datetime = lazy_convert_to_datetime(data.get("updatedAt", None))
        self.deleted_at: datetime = lazy_convert_to_datetime(data.get("deletedAt", None))

    @property
    def dict(self):
        return {
            "id": self.id,
            "subscriptionId": self.subscription_id,
            "type": self.type,
            "owner": self.owner,
            "status": self.status,
            "dependsOn": self.depends_on,
            "data": self.data,
            "createdAt": lazy_iso_format_datetime(self.created_at),
            "updatedAt": lazy_iso_format_datetime(self.updated_at),
            "deletedAt": lazy_iso_format_datetime(self.deleted_at),
        }


class Subscription:
    """Account subscription and its workflow state."""

    def __init__(self, data: Dict[str, Any]):
        self.id: str = data.get("id", None)
        self.status: str = data.get("status", None)
        self.actions = [SubscriptionAction(item) for item in data.get("actions", [])]
        self.order: Dict[str, Any] = data.get("order", {})
        self.plan: Dict[str, Any] = data.get("plan", {})
        self.activated_at: datetime = lazy_convert_to_datetime(data.get("activatedAt", None))
        self.created_at: datetime = lazy_convert_to_datetime(data.get("createdAt", None))
        self.updated_at: datetime = lazy_convert_to_datetime(data.get("updatedAt", None))
        self.deleted_at: datetime = lazy_convert_to_datetime(data.get("deletedAt", None))

    @property
    def dict(self):
        return {
            "id": self.id,
            "status": self.status,
            "actions": [action.dict for action in self.actions],
            "order": self.order,
            "plan": self.plan,
            "activatedAt": lazy_iso_format_datetime(self.activated_at),
            "createdAt": lazy_iso_format_datetime(self.created_at),
            "updatedAt": lazy_iso_format_datetime(self.updated_at),
            "deletedAt": lazy_iso_format_datetime(self.deleted_at),
        }

    def to_json(self):
        """JSON representation of a Subscription object."""
        return json.dumps(self.dict, ensure_ascii=False)
