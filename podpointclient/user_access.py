"""User access models returned by the newer API."""
import json
from typing import Any, Dict


class UserAccessStatus:
    """A user's access status for a charger subscription."""

    def __init__(self, data: Dict[str, Any]):
        self.subscription_id: str = data.get("subscriptionId", None)
        self.status: str = data.get("status", None)
        self.ppid: str = data.get("ppid", None)

    @property
    def dict(self) -> Dict[str, Any]:
        return {
            "subscriptionId": self.subscription_id,
            "status": self.status,
            "ppid": self.ppid,
        }

    def to_json(self):
        """JSON representation of a UserAccessStatus object."""
        return json.dumps(self.dict, ensure_ascii=False)


class UserAgreements:
    """Agreement versions accepted by the current user."""

    def __init__(self, data: Dict[str, Any]):
        self.mobile_app_terms_v1: str = data.get("MOBILE_APP_TERMS_V1", None)
        self.pod_rewards_terms_v1: str = data.get("POD_REWARDS_TERMS_V1", None)
        self.privacy_notice_v1: str = data.get("PRIVACY_NOTICE_V1", None)

    @property
    def dict(self) -> Dict[str, Any]:
        return {
            "MOBILE_APP_TERMS_V1": self.mobile_app_terms_v1,
            "POD_REWARDS_TERMS_V1": self.pod_rewards_terms_v1,
            "PRIVACY_NOTICE_V1": self.privacy_notice_v1,
        }

    def to_json(self):
        """JSON representation of a UserAgreements object."""
        return json.dumps(self.dict, ensure_ascii=False)
