"""Security log page returned by the newer charger API."""
import json
from typing import Any, Dict, List


class SecurityLogPage:
    """A page of charger security logs and pagination metadata."""

    def __init__(self, data: Dict[str, Any]):
        self.data: List[Dict[str, Any]] = data.get("data", [])
        pagination = data.get("meta", {}).get("pagination", {})
        self.current_page: int = pagination.get("currentPage", None)
        self.item_count: int = pagination.get("itemCount", None)
        self.per_page: int = pagination.get("perPage", None)
        self.page_count: int = pagination.get("pageCount", None)
        self.update_id: int = pagination.get("updateId", None)

    @property
    def dict(self) -> Dict[str, Any]:
        return {
            "data": self.data,
            "meta": {
                "pagination": {
                    "currentPage": self.current_page,
                    "itemCount": self.item_count,
                    "perPage": self.per_page,
                    "pageCount": self.page_count,
                    "updateId": self.update_id,
                }
            },
        }

    def to_json(self):
        """JSON representation of a SecurityLogPage object."""
        return json.dumps(self.dict, ensure_ascii=False)
