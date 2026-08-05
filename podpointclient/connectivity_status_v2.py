"""Connectivity status returned by the newer charger API."""
import json
from datetime import datetime
from typing import Any, Dict

from .helpers.functions import lazy_convert_to_datetime, lazy_iso_format_datetime


class ConnectivityStatusV2:
    """Compact connectivity and charging state for a charger."""

    def __init__(self, data: Dict[str, Any]):
        self.connection_state: str = data.get("connectionState", None)
        self.connection_quality: int = data.get("connectionQuality", None)
        self.charging_state: str = data.get("chargingState", None)
        self.last_seen_at: datetime = lazy_convert_to_datetime(data.get("lastSeenAt", None))

    @property
    def dict(self) -> Dict[str, Any]:
        return {
            "connectionState": self.connection_state,
            "connectionQuality": self.connection_quality,
            "chargingState": self.charging_state,
            "lastSeenAt": lazy_iso_format_datetime(self.last_seen_at),
        }

    def to_json(self):
        """JSON representation of a ConnectivityStatusV2 object."""
        return json.dumps(self.dict, ensure_ascii=False)
