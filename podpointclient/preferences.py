"""Smart-charging and notification preference models."""
import json
from typing import Any, Dict


class SmartChargingPreferences:
    """Mutable smart-charging preferences for a charger."""

    def __init__(self, data: Dict[str, Any]):
        self.max_price = data.get("maxPrice")

    @property
    def dict(self):
        return {"maxPrice": self.max_price}

    def to_json(self):
        return json.dumps(self.dict, ensure_ascii=False)


class NotificationPreferences:
    """The user's named notification switches."""

    def __init__(self, data: Dict[str, Any]):
        self.preferences: Dict[str, bool] = data.get("preferences", {})

    def enabled(self, name: str) -> bool:
        """Return whether a named notification is enabled."""
        return self.preferences.get(name, False)

    @property
    def dict(self):
        return {"preferences": self.preferences}

    def to_json(self):
        return json.dumps(self.dict, ensure_ascii=False)
