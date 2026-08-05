"""Manual charge schedules returned by the newer charger API."""
import json
from typing import Any, Dict


class ManualSchedule:
    """Representation of a manual charger schedule."""

    def __init__(self, data: Dict[str, Any]):
        self.uid: str = data.get("uid", None)
        self.start_day: int = data.get("startDay", None)
        self.start_time: str = data.get("startTime", None)
        self.end_day: int = data.get("endDay", None)
        self.end_time: str = data.get("endTime", None)
        self.status: Dict[str, Any] = data.get("status", {})

    @property
    def dict(self) -> Dict[str, Any]:
        return {
            "uid": self.uid,
            "startDay": self.start_day,
            "startTime": self.start_time,
            "endDay": self.end_day,
            "endTime": self.end_time,
            "status": self.status,
        }

    def to_json(self):
        """JSON representation of a ManualSchedule object."""
        return json.dumps(self.dict, ensure_ascii=False)
