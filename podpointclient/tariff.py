"""Tariff models returned by the newer charger API."""
import json
from datetime import datetime
from typing import Any, Dict, List

from .helpers.functions import lazy_convert_to_datetime, lazy_iso_format_datetime


class TariffPeriod:
    """A time period and unit price within a tariff."""

    def __init__(self, data: Dict[str, Any]):
        self.days: List[str] = data.get("days", [])
        self.start: str = data.get("start", None)
        self.end: str = data.get("end", None)
        self.price: float = data.get("price", None)

    @property
    def dict(self):
        return {
            "days": self.days,
            "start": self.start,
            "end": self.end,
            "price": self.price,
        }


class Tariff:
    """Representation of a charger energy tariff."""

    def __init__(self, data: Dict[str, Any]):
        self.id: str = data.get("id", None)
        self.ppid: str = data.get("ppid", None)
        self.supplier_id: str = data.get("supplierId", None)
        self.tariff_info = [TariffPeriod(item) for item in data.get("tariffInfo", [])]
        self.timezone: str = data.get("timezone", None)
        self.cheapest_unit_price: float = data.get("cheapestUnitPrice", None)
        self.effective_from: datetime = lazy_convert_to_datetime(data.get("effectiveFrom", None))
        self.smart_charging_supported: bool = data.get("smartChargingSupported", None)
        self.max_charge_price: float = data.get("maxChargePrice", None)

    @property
    def dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "ppid": self.ppid,
            "supplierId": self.supplier_id,
            "tariffInfo": [item.dict for item in self.tariff_info],
            "timezone": self.timezone,
            "cheapestUnitPrice": self.cheapest_unit_price,
            "effectiveFrom": lazy_iso_format_datetime(self.effective_from),
            "smartChargingSupported": self.smart_charging_supported,
            "maxChargePrice": self.max_charge_price,
        }

    def to_json(self):
        """JSON representation of a Tariff object."""
        return json.dumps(self.dict, ensure_ascii=False)
