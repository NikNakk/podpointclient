"""Models for the newer charge history and aggregate statistics APIs."""
import json
from datetime import datetime
from typing import Any, Dict

from .helpers.functions import lazy_convert_to_datetime, lazy_iso_format_datetime


class Money:
    """A currency amount returned by the charge APIs."""

    def __init__(self, data: Dict[str, Any]):
        self.amount = data.get("amount")
        self.currency = data.get("currency")

    @property
    def dict(self):
        return {"amount": self.amount, "currency": self.currency}


class ChargeHistoryItem:
    """One charge from the charger-centric history API."""

    def __init__(self, data: Dict[str, Any]):
        self.id = data.get("id")
        self.started_at: datetime = lazy_convert_to_datetime(data.get("startedAt"))
        self.ended_at: datetime = lazy_convert_to_datetime(data.get("endedAt"))
        self.duration = data.get("duration")
        self.energy_total = data.get("energyTotal")
        self.cost = Money(data.get("cost") or {})
        charger = data.get("charger") or {}
        self.charger_type = charger.get("type")
        self.charger_id = charger.get("id")
        self.door = charger.get("door")
        self.plugged_in_at = lazy_convert_to_datetime(charger.get("pluggedInAt"))
        self.unplugged_at = lazy_convert_to_datetime(charger.get("unpluggedAt"))
        self.plugged_in_duration = charger.get("pluggedInDuration")
        self.rewards_eligible_energy = (data.get("rewards") or {}).get("eligibleEnergy")

    @property
    def dict(self):
        return {
            "id": self.id,
            "startedAt": lazy_iso_format_datetime(self.started_at),
            "endedAt": lazy_iso_format_datetime(self.ended_at),
            "duration": self.duration,
            "energyTotal": self.energy_total,
            "cost": self.cost.dict,
            "charger": {
                "type": self.charger_type,
                "id": self.charger_id,
                "door": self.door,
                "pluggedInAt": lazy_iso_format_datetime(self.plugged_in_at),
                "unpluggedAt": lazy_iso_format_datetime(self.unplugged_at),
                "pluggedInDuration": self.plugged_in_duration,
            },
            "rewards": {"eligibleEnergy": self.rewards_eligible_energy},
        }


class ChargeHistory:
    """A charge-history response including its count and metadata."""

    def __init__(self, response: Dict[str, Any]):
        data = response.get("data") or {}
        self.count = data.get("count", 0)
        self.charges = [ChargeHistoryItem(item) for item in data.get("charges", [])]
        self.meta = response.get("meta", {})

    @property
    def dict(self):
        return {
            "data": {"count": self.count, "charges": [item.dict for item in self.charges]},
            "meta": self.meta,
        }

    def to_json(self):
        return json.dumps(self.dict, ensure_ascii=False)


class ChargeStats:
    """Aggregate and interval charge statistics.

    The nested statistics remain dictionaries because the API groups values by
    charger type and currency and may add new groups without a client release.
    """

    def __init__(self, response: Dict[str, Any]):
        data = response.get("data") or {}
        self.summary = data.get("summary", {})
        self.intervals = data.get("intervals", [])
        self.meta = response.get("meta", {})

    @property
    def dict(self):
        return {
            "data": {"summary": self.summary, "intervals": self.intervals},
            "meta": self.meta,
        }

    def to_json(self):
        return json.dumps(self.dict, ensure_ascii=False)
