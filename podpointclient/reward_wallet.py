"""Pod Point reward wallet models."""
import json
from datetime import datetime
from typing import Any, Dict, List

from .helpers.functions import lazy_convert_to_datetime, lazy_iso_format_datetime


class RewardWallet:
    """Reward allowance, earnings, and payment totals."""

    def __init__(self, data: Dict[str, Any]):
        self.allowance: Dict[str, Any] = data.get("allowance", {})
        self.rewards: Dict[str, Any] = data.get("rewards", {})
        self.payments: Dict[str, Any] = data.get("payments", {})

    @property
    def dict(self):
        return {
            "allowance": self.allowance,
            "rewards": self.rewards,
            "payments": self.payments,
        }

    def to_json(self):
        """JSON representation of a RewardWallet object."""
        return json.dumps(self.dict, ensure_ascii=False)


class RewardTransaction:
    """A transaction within a reward wallet."""

    def __init__(self, data: Dict[str, Any]):
        self.type: str = data.get("type", None)
        self.timestamp: datetime = lazy_convert_to_datetime(data.get("timestamp", None))
        self.amount: float = data.get("amount", None)
        self.amount_points: float = data.get("amountPoints", None)
        self.charge_id: str = data.get("chargeId", None)

    @property
    def dict(self):
        return {
            "type": self.type,
            "timestamp": lazy_iso_format_datetime(self.timestamp),
            "amount": self.amount,
            "amountPoints": self.amount_points,
            "chargeId": self.charge_id,
        }


class RewardTransactionPage:
    """A page of reward transactions and its continuation key."""

    def __init__(self, data: Dict[str, Any]):
        self.transactions: List[RewardTransaction] = [
            RewardTransaction(item) for item in data.get("transactions", [])
        ]
        self.last_key: str = data.get("meta", {}).get("lastKey", None)

    @property
    def dict(self):
        return {
            "transactions": [transaction.dict for transaction in self.transactions],
            "meta": {"lastKey": self.last_key},
        }

    def to_json(self):
        """JSON representation of a RewardTransactionPage object."""
        return json.dumps(self.dict, ensure_ascii=False)
