"""Factories used to create top level objects such as pods, sessions and charges"""
from typing import Dict, Any, List
from .pod import Pod, Firmware
from .user import User
from .schedule import Schedule, ScheduleStatus
from .charge import Charge
from .charge_override import ChargeOverride
from .connectivity_status import ConnectivityStatus
from .charger import Charger
from .charger_subscription import ChargerSubscription
from .connectivity_status_v2 import ConnectivityStatusV2
from .manual_schedule import ManualSchedule
from .security_log import SecurityLogPage
from .tariff import Tariff
from .user_access import UserAccessStatus, UserAgreements

class PodFactory:
    """Factory for creating Pod objects"""
    def build_pods(self, pods_response: Dict[str, Any]) -> List[Pod]:
        """Build a number of pod objects based off of a response from pod point"""
        pods = []

        pods_data = pods_response.get('pods', None)  if pods_response is not None else None
        if pods_data is None:
            return pods

        for pod_data in pods_data:
            pods.append(Pod(data=pod_data))

        return pods

class ScheduleFactory:
    """Factory for creating Schedule objects"""
    def build_schedules(
        self,
        enabled: bool,
        start_time: str = "00:00:00",
        end_time: str = "00:00:01"
    ) -> List[Schedule]:
        """Build a number of schedule objects based off of a response from pod point"""
        schedules = []

        for iterator in range(7):
            day = iterator + 1

            schedule = Schedule(
                start_day=day,
                start_time=start_time,
                end_day=day,
                end_time=end_time,
                status=ScheduleStatus(is_active=enabled)
            )

            schedules.append(schedule)

        return schedules


class ChargeFactory:
    """Factory  for creating Charge objects"""
    def build_charges(self, charge_response: Dict[str, Any]) -> List[Charge]:
        """Build a list of charge objects based off of a response from pod point"""
        charges = []

        charge_data = charge_response.get('charges', None) if charge_response is not None else None
        if charge_data is None:
            return charges

        for charge in charge_data:
            charges.append(Charge(data=charge))

        return charges

class ChargeOverrideFactory:
    """Factory  for creating Charge objects"""
    def build_charge_override(self, charge_override_response: Dict[str, Any]) -> ChargeOverride:
        """Build a list of charge objects based off of a response from pod point"""
        if charge_override_response is None:
            return None

        return ChargeOverride(data=charge_override_response)

class FirmwareFactory:
    """Factory  for creating Firmware objects"""
    def build_firmwares(self, firmware_response: Dict[str, Any]) -> List[Firmware]:
        """Build a list of firmware objects based off of a response from pod point"""
        firmwares = []

        firmware_data = firmware_response.get('data', None) if firmware_response is not None else None
        if firmware_data is None:
            return firmwares

        for firmware in firmware_data:
            firmwares.append(Firmware(data=firmware))

        return firmwares

class UserFactory:
    """Factory  for creating User objects"""
    def build_user(self, user_response: Dict[str, Any]) -> User:
        """Build a user object based off of a response from pod point"""
        user_data = user_response.get('users', None) if user_response is not None else None
        if user_data is None:
            return None

        return User(data=user_data)

class ConnectivityStatusFactory:
    """Factory  for creating ConnectivityStatus objects"""
    def build_connectivity_status(self, connectivity_status_response: Dict[str, Any]):
        """Build a ConnectivityStatus object based off of a response from pod point"""
        if connectivity_status_response is None:
            return None

        return ConnectivityStatus(data=connectivity_status_response)


class ChargerFactory:
    """Factory for creating chargers."""

    def build_chargers(self, charger_response: List[Dict[str, Any]]) -> List[Charger]:
        """Build chargers from a newer API response."""
        if not isinstance(charger_response, list):
            return []
        return [Charger(data=data) for data in charger_response]


class ConnectivityStatusV2Factory:
    """Factory for creating newer connectivity status objects."""

    def build_connectivity_status(self, response: Dict[str, Any]):
        """Build a connectivity status, returning None for no response."""
        if response is None:
            return None
        return ConnectivityStatusV2(data=response)


class TariffFactory:
    """Factory for creating charger tariffs."""

    def build_tariffs(self, tariff_response: Dict[str, Any]) -> List[Tariff]:
        """Build tariffs from a newer API response."""
        data = tariff_response.get("data", []) if tariff_response else []
        return [Tariff(item) for item in data]


class ManualScheduleFactory:
    """Factory for creating manual schedules."""

    def build_schedules(self, schedule_response: Dict[str, Any]) -> List[ManualSchedule]:
        """Build manual schedules from a newer API response."""
        data = schedule_response.get("data", []) if schedule_response else []
        return [ManualSchedule(item) for item in data]


class SecurityLogFactory:
    """Factory for creating a security log page."""

    def build_security_logs(self, response: Dict[str, Any]):
        """Build a security log page, returning None for no response."""
        if response is None:
            return None
        return SecurityLogPage(response)


class ChargerSubscriptionFactory:
    """Factory for creating charger subscriptions."""

    def build_subscriptions(self, response: Dict[str, Any]) -> List[ChargerSubscription]:
        """Build charger subscriptions from a newer API response."""
        data = response.get("subscriptions", []) if response else []
        return [ChargerSubscription(item) for item in data]


class UserAccessStatusFactory:
    """Factory for creating user access statuses."""

    def build_access_statuses(self, response: List[Dict[str, Any]]) -> List[UserAccessStatus]:
        """Build access statuses from a newer API response."""
        if not isinstance(response, list):
            return []
        return [UserAccessStatus(item) for item in response]


class UserAgreementsFactory:
    """Factory for creating user agreements."""

    def build_agreements(self, response: Dict[str, Any]):
        """Build user agreements, returning None for no response."""
        if response is None:
            return None
        return UserAgreements(response)
