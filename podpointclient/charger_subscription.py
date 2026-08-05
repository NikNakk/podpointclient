"""Charger subscription models returned by the newer API."""
import json
from typing import Any, Dict


class ChargerSubscription:
    """Representation of a subscription attached to a charger."""

    def __init__(self, data: Dict[str, Any]):
        self.id: str = data.get("id", None)
        self.status: str = data.get("status", None)
        self.order_origin: str = data.get("order", {}).get("origin", None)
        self.plan_type: str = data.get("plan", {}).get("type", None)

    @property
    def dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "order": {"origin": self.order_origin},
            "plan": {"type": self.plan_type},
            "status": self.status,
        }

    def to_json(self):
        """JSON representation of a ChargerSubscription object."""
        return json.dumps(self.dict, ensure_ascii=False)
