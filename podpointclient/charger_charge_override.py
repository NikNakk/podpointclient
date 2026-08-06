"""Charge-override history models returned by the charger API."""
import json
from datetime import datetime
from typing import Any, Dict

from .helpers.functions import lazy_convert_to_datetime, lazy_iso_format_datetime


class ChargerChargeOverride:
    """A charger-centric charge override, including deleted history entries."""

    def __init__(self, data: Dict[str, Any]):
        self.id: str = data.get("id")
        self.requested_at: datetime = lazy_convert_to_datetime(data.get("requestedAt"))
        self.received_at: datetime = lazy_convert_to_datetime(data.get("receivedAt"))
        self.end_at: datetime = lazy_convert_to_datetime(data.get("endAt"))
        self.deleted_at: datetime = lazy_convert_to_datetime(data.get("deletedAt"))
        evse = data.get("evse") or {}
        self.door = evse.get("door")
        self.ocpp_evse_id = evse.get("ocppEvseId")
        station = data.get("chargingStation") or {}
        self.ppid: str = station.get("ppid")

    @property
    def active(self) -> bool:
        """Whether the override has not been deleted."""
        return self.deleted_at is None

    @property
    def dict(self):
        result = {
            "id": self.id,
            "requestedAt": lazy_iso_format_datetime(self.requested_at),
            "receivedAt": lazy_iso_format_datetime(self.received_at),
            "endAt": lazy_iso_format_datetime(self.end_at),
            "evse": {"door": self.door, "ocppEvseId": self.ocpp_evse_id},
            "chargingStation": {"ppid": self.ppid},
        }
        if self.deleted_at is not None:
            result["deletedAt"] = lazy_iso_format_datetime(self.deleted_at)
        return result

    def to_json(self):
        return json.dumps(self.dict, ensure_ascii=False)
