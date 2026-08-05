"""Representations of chargers returned by the newer Pod Point API."""
import json
from datetime import datetime
from typing import Any, Dict, Union

from .helpers.functions import lazy_convert_to_datetime, lazy_iso_format_datetime


class Charger:
    """Representation of a charger from Pod Point."""

    def __init__(self, data: Dict[str, Any]):
        self.ppid: str = data.get("ppid", None)
        self.unit_id: int = data.get("unitId", None)
        self.timezone: str = data.get("timezone", None)
        self.linked_at: datetime = lazy_convert_to_datetime(data.get("linkedAt", None))

        delegated_control = data.get("delegatedControl", None)
        self.delegated_control_status: Union[str, None] = (
            delegated_control.get("status", None) if delegated_control else None
        )

        model_info = data.get("modelInfo", {})
        self.model_info = self.ModelInfo(model_info) if model_info else None

        subscription = data.get("subscription", {})
        self.subscription = self.Subscription(subscription) if subscription else None

    @property
    def dict(self) -> Dict[str, Any]:
        return {
            "ppid": self.ppid,
            "unitId": self.unit_id,
            "timezone": self.timezone,
            "linkedAt": lazy_iso_format_datetime(self.linked_at),
            "delegatedControl": (
                {"status": self.delegated_control_status}
                if self.delegated_control_status is not None else None
            ),
            "modelInfo": self.model_info.dict if self.model_info else None,
            "subscription": self.subscription.dict if self.subscription else None,
        }

    def to_json(self):
        """JSON representation of a Charger object."""
        return json.dumps(self.dict, ensure_ascii=False)

    class ModelInfo:
        """Hardware model information for a charger."""

        def __init__(self, data: Dict[str, Any]):
            self.led_colour_set: str = data.get("ledColourSet", None)
            self.colour: str = data.get("colour", None)
            self.architecture: str = data.get("architecture", None)
            self.style: str = data.get("style", None)

        @property
        def dict(self):
            return {
                "ledColourSet": self.led_colour_set,
                "colour": self.colour,
                "architecture": self.architecture,
                "style": self.style,
            }

    class Subscription:
        """Summary of the subscription attached to a charger."""

        def __init__(self, data: Dict[str, Any]):
            self.id: str = data.get("id", None)
            self.status: str = data.get("status", None)
            self.is_subscription_owner: bool = data.get("isSubscriptionOwner", None)

        @property
        def dict(self):
            return {
                "id": self.id,
                "status": self.status,
                "isSubscriptionOwner": self.is_subscription_owner,
            }
