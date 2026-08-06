"""Remote lock state returned by Pod Point."""
import json
from typing import Any, Dict


class RemoteLock:
    """Remote lock/off-mode state for a charger."""

    def __init__(self, data: Dict[str, Any]):
        self.off_mode = data.get("offMode", None)

    @property
    def dict(self):
        return {"offMode": self.off_mode}

    def to_json(self):
        """JSON representation of a RemoteLock object."""
        return json.dumps(self.dict, ensure_ascii=False)
