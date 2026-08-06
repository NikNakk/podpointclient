"""Energy supplier models returned by Pod Point."""
import json
from typing import Any, Dict

from .tariff import TariffPeriod


class EnergySupplier:
    """Energy supplier and its default tariff configuration."""

    def __init__(self, data: Dict[str, Any]):
        self.id: str = data.get("id", None)
        self.name: str = data.get("name", None)
        self.timezone: str = data.get("timeZone", None)
        self.icon: str = data.get("icon", None)
        self.default_tariff_info = [
            TariffPeriod(item) for item in data.get("defaultTariffInfo", [])
        ]
        self.default_max_charge_price: float = data.get("defaultMaxChargePrice", None)

    @property
    def dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "timeZone": self.timezone,
            "icon": self.icon,
            "defaultTariffInfo": [period.dict for period in self.default_tariff_info],
            "defaultMaxChargePrice": self.default_max_charge_price,
        }

    def to_json(self):
        """JSON representation of an EnergySupplier object."""
        return json.dumps(self.dict, ensure_ascii=False)
