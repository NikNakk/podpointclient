"""PodPoint Basic API Client."""
import logging
import math
import re
from typing import Dict, Any, List, Union
from datetime import date, datetime, timedelta, timezone

import aiohttp
import pytz

from .endpoints import (
    ACCESS_STATUS, AGREEMENTS, API_BASE_URL, AUTH, CHARGE_OVERRIDE,
    CHARGE_OVERRIDES,
    CHARGE_SCHEDULES, CHARGERS, CHARGES, CONNECTIVITY_STATUS,
    CONNECTIVITY_STATUS_V2, DELEGATED_CONTROLS, DELEGATED_VEHICLES,
    ENERGY_SUPPLIERS, FIRMWARE, MANUAL_SCHEDULES, MOBILE_API_BASE_URL, PODS,
    NOTIFICATION_PREFERENCES, PREFERENCES, REMOTE_LOCK, REWARD_WALLET,
    SECURITY_LOGS, STATS, SUBSCRIPTIONS, TARIFFS, TRANSACTIONS, UNITS, USERS
)
from .helpers.auth import Auth
from .helpers.functions import auth_headers
from .helpers.api_wrapper import APIWrapper
from .factories import (
    ChargeFactory, ChargeHistoryFactory, ChargeOverrideFactory, ChargerFactory,
    ChargerChargeOverrideFactory,
    ChargerSubscriptionFactory, ConnectivityStatusFactory,
    ConnectivityStatusV2Factory, DelegatedChargerFactory,
    DelegatedControlFactory, EnergySupplierFactory, FirmwareFactory,
    ManualScheduleFactory, PodFactory, RemoteLockFactory, RewardWalletFactory,
    PreferencesFactory, ScheduleFactory, SecurityLogFactory, SubscriptionFactory,
    TariffFactory,
    UserAccessStatusFactory, UserAgreementsFactory, UserFactory
)
from .charger import Charger
from .charger_subscription import ChargerSubscription
from .connectivity_status_v2 import ConnectivityStatusV2
from .manual_schedule import ManualSchedule
from .security_log import SecurityLogPage
from .tariff import Tariff, TariffPeriod
from .user_access import UserAccessStatus, UserAgreements
from .energy_supplier import EnergySupplier
from .remote_lock import RemoteLock
from .reward_wallet import RewardTransactionPage, RewardWallet
from .smart_charging import (
    DelegatedCharger, DelegatedControl, VehicleIntent, VehicleIntentDetail
)
from .subscription import Subscription
from .charger_charge_override import ChargerChargeOverride
from .charge_history import ChargeHistory, ChargeStats
from .preferences import NotificationPreferences, SmartChargingPreferences
from .pod import Pod, Firmware
from .charge import Charge
from .charge_mode import ChargeMode
from .charge_override import ChargeOverride
from .connectivity_status import ConnectivityStatus
from .schedule import Schedule
from .user import User
from .errors import (
    ChargeModeTransitionError, ChargeOverrideValidationError,
    RequestValidationError
)

TIMEOUT = 10

_LOGGER: logging.Logger = logging.getLogger(__package__)

HEADERS = {"Content-type": "application/json; charset=UTF-8"}
DEFAULT_POD_INCLUDES = ["statuses", "price", "model",
                    "unit_connectors", "charge_schedules", "charge_override"]
DEFAULT_USER_INCLUDES = ["account", "vehicle", "vehicle.make", "unit.pod.unit_connectors", "unit.pod.statuses", "unit.pod.model", "unit.pod.charge_schedules", "unit.pod.charge_override"]
DEFAULT_REWARD_TRANSACTION_INCLUDES = [
    "MILES_CHARGED", "PAYOUT", "PAYOUT_REFUNDED", "BONUS_MILES"
]
VALID_WEEKDAYS = {
    "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"
}
VALID_STATS_INTERVALS = {"day", "week", "month", "year"}

class PodPointClient:
    """API Client for communicating with Pod Point."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession = None,
        include_timestamp: bool = False,
        http_debug: bool = None
    ) -> None:
        """Pod Point API Client."""
        self.email = username
        self.password = password
        self._session = session if session is not None else aiohttp.ClientSession()
        self._http_debug = http_debug if http_debug is not None else False
        self.auth = Auth(
            email=self.email,
            password=self.password,
            session=self._session,
            http_debug=self._http_debug
        )
        self.api_wrapper = APIWrapper(session=self._session)
        self.include_timestamp = include_timestamp

    async def async_credentials_verified(self) -> bool:
        """Perform a minimum call to verify we have working credentials and can get one Pod"""
        await self.auth.async_update_access_token()

        pods = await self.async_get_pods(perpage=1, page=1, includes=[])
        return len(pods) > 0

    async def async_get_all_pods(
        self,
        perpage: Union[str, int] = 5,
        includes: Union[List[str], None] = None
    ) -> List[Pod]:
        """Get all pods from the API"""
        page = 1
        pods: List[Pod] = []

        more_pods = True
        while more_pods:
            new_pods: List[Pod] = await self.async_get_pods(
                perpage=perpage,
                page=page,
                includes=includes
            )
            # Should be replaced by reading "meta > pagination > page_count" but
            # would require a larger refactor
            if len(new_pods) < perpage:
                more_pods = False

            pods.extend(new_pods)
            page += 1

        return pods

    async def async_get_pods(
        self,
        perpage: Union[str, int] = 5,
        page: Union[str, int] = 1,
        includes: Union[List[str], None] = None
    ) -> List[Pod]:
        """Get pods from the API"""
        await self.auth.async_update_access_token()

        if includes is None:
            includes = DEFAULT_POD_INCLUDES

        params = {"perpage": perpage, "page": page}
        if len(includes) > 0:
            params["include"] = ",".join(includes)

        response = await self.api_wrapper.get(
            url=self._url_from_path(path=f"{USERS}/{self.auth.user_id}{PODS}"),
            params=self._generate_complete_params(params=params),
            headers=auth_headers(access_token=self.auth.access_token)
        )

        json = await self._handle_json_response(response=response)

        pods = PodFactory().build_pods(pods_response=json)

        return pods

    async def async_get_pod(self, pod_id: int) -> Pod:
        """Get specific pod from the API"""
        pods = await self.async_get_all_pods()
        return next((pod for pod in pods if pod.id == pod_id), None)

    async def async_set_schedule(self, enabled: bool, pod: Pod) -> bool:
        """Send data from the API."""
        await self.auth.async_update_access_token()

        unit_id = pod.unit_id

        _LOGGER.debug(
            "Updating pod schedule for unit %s. Enabling schedule: %s",
            unit_id,
            enabled
        )

        response = await self.api_wrapper.put(
            url=self._url_from_path(
                path=f"{UNITS}/{unit_id}{CHARGE_SCHEDULES}"),
            params=self._generate_complete_params(params=None),
            headers=auth_headers(access_token=self.auth.access_token),
            body=self._schedule_data(enabled=enabled)
        )

        #  Quick exit if the response code is 201
        if response.status == 201:
            return True

        text = await response.text()
        _LOGGER.warning(
            "Expected to recieve 201 status code when creating schedules. Got (%s) - %s",
            response.status,
            text
        )
        return False

    async def async_get_all_charges(
        self,
        perpage: Union[str, int] = 50
    ) -> List[Charge]:
        """Get all charges from the API"""
        page = 1
        charges: List[Charge] = []

        more_charges = True
        while more_charges:
            new_charges: List[Charge] = await self.async_get_charges(perpage=perpage, page=page)
            # Should be replaced by reading "meta > pagination > page_count" but
            # would require a larger refactor
            if len(new_charges) < perpage:
                more_charges = False

            charges.extend(new_charges)
            page += 1

        return charges

    async def async_get_charges(
        self,
        perpage: Union[str, int] = 5,
        page: Union[str, int] = 1
    ) -> List[Charge]:
        """Get charges from the API."""
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{USERS}/{self.auth.user_id}{CHARGES}"),
            params=self._generate_complete_params(
                params={"perpage": perpage, "page": page}),
            headers=auth_headers(access_token=self.auth.access_token)
        )

        json = await self._handle_json_response(response=response)

        charges = ChargeFactory().build_charges(charge_response=json)

        return charges

    async def async_get_firmware(self, pod: Pod) -> List[Firmware]:
        """Get firmware information for a given unit."""
        await self.auth.async_update_access_token()
        
        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{UNITS}/{pod.unit_id}{FIRMWARE}"),
            params=self._generate_complete_params(params=None),
            headers=auth_headers(access_token=self.auth.access_token)
        )

        json = await self._handle_json_response(response=response)

        firmwares = FirmwareFactory().build_firmwares(firmware_response=json)

        return firmwares

    async def async_get_user(self, includes: Union[List[str], None] = None) -> User:
        """Get user from the API"""
        await self.auth.async_update_access_token()

        if includes is None:
            includes = DEFAULT_USER_INCLUDES

        params = {}
        if len(includes) > 0:
            params["include"] = ",".join(includes)

        response = await self.api_wrapper.get(
            url=self._url_from_path(path=f"{AUTH}"),
            params=self._generate_complete_params(params=params),
            headers=auth_headers(access_token=self.auth.access_token)
        )

        json = await self._handle_json_response(response=response)

        user = UserFactory().build_user(user_response=json)

        return user

    async def async_get_charge_override(self, pod: Pod) -> Union[None, ChargeOverride]:
        await self.auth.async_update_access_token()
        
        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{UNITS}/{pod.unit_id}{CHARGE_OVERRIDE}"),
            params=self._generate_complete_params(params=None),
            headers=auth_headers(access_token=self.auth.access_token)
        )

        # If there is no charge mode (smart mode), return None
        if response.status == 204:
            return None

        json = await self._handle_json_response(response=response)

        return ChargeOverrideFactory().build_charge_override(charge_override_response=json)

    async def async_delete_charge_override(self, pod:Pod) -> bool:
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.delete(
            url=self._url_from_path(
                path=f"{UNITS}/{pod.unit_id}{CHARGE_OVERRIDE}"),
            params=self._generate_complete_params(params=None),
            headers=auth_headers(access_token=self.auth.access_token)
        )

        return response.status == 204

    async def async_get_connectivity_status(self, pod:Pod) -> ConnectivityStatus:
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{CHARGERS}/{pod.ppid}{CONNECTIVITY_STATUS}",
                base=MOBILE_API_BASE_URL
            ),
            params=self._generate_complete_params(params=None),
            headers=auth_headers(access_token=self.auth.access_token)
        )

        json = await self._handle_json_response(response=response)

        return ConnectivityStatusFactory().build_connectivity_status(connectivity_status_response=json)

    async def async_get_chargers(self) -> List[Charger]:
        """Get chargers from the newer API."""
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(path=CHARGERS, base=MOBILE_API_BASE_URL),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return ChargerFactory().build_chargers(charger_response=json)

    async def async_get_charger(self, ppid: str) -> Union[None, Charger]:
        """Get a charger by PPID from the newer API."""
        chargers = await self.async_get_chargers()
        return next((charger for charger in chargers if charger.ppid == ppid), None)

    async def async_get_connectivity_status_v2(
        self,
        charger: Charger
    ) -> ConnectivityStatusV2:
        """Get compact connectivity information for a charger."""
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{CHARGERS}/{charger.ppid}{CONNECTIVITY_STATUS_V2}",
                base=MOBILE_API_BASE_URL
            ),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return ConnectivityStatusV2Factory().build_connectivity_status(json)

    async def async_get_tariffs(self, charger: Charger) -> List[Tariff]:
        """Get tariffs associated with a charger."""
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{CHARGERS}/{charger.ppid}{TARIFFS}",
                base=MOBILE_API_BASE_URL
            ),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return TariffFactory().build_tariffs(json)

    async def async_get_manual_schedules(self, charger: Charger) -> List[ManualSchedule]:
        """Get manual schedules associated with a charger."""
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{CHARGERS}/{charger.ppid}{MANUAL_SCHEDULES}",
                base=MOBILE_API_BASE_URL
            ),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return ManualScheduleFactory().build_schedules(json)

    async def async_get_security_logs(
        self,
        charger: Charger,
        page_number: int = 1
    ) -> SecurityLogPage:
        """Get security logs associated with a charger."""
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{CHARGERS}/{charger.ppid}{SECURITY_LOGS}",
                base=MOBILE_API_BASE_URL
            ),
            params={"pageNumber": page_number},
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return SecurityLogFactory().build_security_logs(json)

    async def async_get_charger_subscriptions(
        self,
        charger: Charger
    ) -> List[ChargerSubscription]:
        """Get subscriptions associated with a charger."""
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{CHARGERS}/{charger.ppid}{SUBSCRIPTIONS}",
                base=MOBILE_API_BASE_URL
            ),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return ChargerSubscriptionFactory().build_subscriptions(json)

    async def async_get_user_access_status(self) -> List[UserAccessStatus]:
        """Get the current user's charger access statuses."""
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{USERS}{ACCESS_STATUS}",
                base=MOBILE_API_BASE_URL
            ),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return UserAccessStatusFactory().build_access_statuses(json)

    async def async_get_user_agreements(self) -> UserAgreements:
        """Get the current user's accepted agreement versions."""
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{USERS}{AGREEMENTS}",
                base=MOBILE_API_BASE_URL
            ),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return UserAgreementsFactory().build_agreements(json)

    async def async_get_delegated_vehicles(self) -> List[DelegatedCharger]:
        """Get chargers and vehicles using delegated smart charging."""
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=DELEGATED_VEHICLES,
                base=MOBILE_API_BASE_URL
            ),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return DelegatedChargerFactory().build_delegated_chargers(json)

    async def async_get_delegated_control(
        self,
        charger: Charger
    ) -> DelegatedControl:
        """Get delegated smart-charging configuration for a charger."""
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{DELEGATED_CONTROLS}/{charger.ppid}",
                base=MOBILE_API_BASE_URL
            ),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return DelegatedControlFactory().build_delegated_control(json)

    async def async_get_reward_wallet(self) -> RewardWallet:
        """Get the current user's reward wallet."""
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(path=REWARD_WALLET, base=MOBILE_API_BASE_URL),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return RewardWalletFactory().build_wallet(json)

    async def async_get_reward_transactions(
        self,
        includes: Union[List[str], None] = None
    ) -> RewardTransactionPage:
        """Get reward transactions of the requested event types."""
        await self.auth.async_update_access_token()

        if includes is None:
            includes = DEFAULT_REWARD_TRANSACTION_INCLUDES

        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{REWARD_WALLET}{TRANSACTIONS}",
                base=MOBILE_API_BASE_URL
            ),
            params=[("include", include) for include in includes],
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return RewardWalletFactory().build_transactions(json)

    async def async_get_energy_suppliers(self) -> List[EnergySupplier]:
        """Get the available energy suppliers and their default tariffs."""
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(path=ENERGY_SUPPLIERS, base=MOBILE_API_BASE_URL),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return EnergySupplierFactory().build_suppliers(json)

    async def async_get_remote_lock(self, charger: Charger) -> RemoteLock:
        """Get remote lock/off-mode state for a charger."""
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{REMOTE_LOCK}/{charger.ppid}",
                base=MOBILE_API_BASE_URL
            ),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return RemoteLockFactory().build_remote_lock(json)

    async def async_get_subscriptions(self) -> List[Subscription]:
        """Get account subscriptions and their workflow state."""
        await self.auth.async_update_access_token()

        response = await self.api_wrapper.get(
            url=self._url_from_path(path=SUBSCRIPTIONS, base=MOBILE_API_BASE_URL),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return SubscriptionFactory().build_subscriptions(json)

    async def async_get_charger_charge_overrides(
        self,
        charger: Charger,
        active_only: bool = False
    ) -> List[ChargerChargeOverride]:
        """Get charger override history, optionally excluding deleted entries."""
        await self.auth.async_update_access_token()
        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{CHARGERS}/{charger.ppid}{CHARGE_OVERRIDES}",
                base=MOBILE_API_BASE_URL
            ),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        overrides = ChargerChargeOverrideFactory().build_overrides(json)
        return [item for item in overrides if item.active] if active_only else overrides

    async def async_get_smart_charging_preferences(
        self,
        charger: Charger
    ) -> SmartChargingPreferences:
        """Get mutable smart-charging preferences for a charger."""
        await self.auth.async_update_access_token()
        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=f"{DELEGATED_CONTROLS}/{charger.ppid}{PREFERENCES}",
                base=MOBILE_API_BASE_URL
            ),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return PreferencesFactory().build_smart_charging(json)

    async def async_get_charge_history(
        self,
        from_date: date,
        to_date: date
    ) -> ChargeHistory:
        """Get charger-centric charge history for an inclusive date range."""
        from_value, to_value = self._validate_date_range(from_date, to_date)
        await self.auth.async_update_access_token()
        response = await self.api_wrapper.get(
            url=self._url_from_path(path=CHARGES, base=MOBILE_API_BASE_URL),
            params={"from": from_value, "to": to_value},
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return ChargeHistoryFactory().build_history(json)

    async def async_get_charge_stats(
        self,
        from_date: date,
        to_date: date,
        interval: str = "month"
    ) -> ChargeStats:
        """Get aggregate and interval charge statistics for a date range."""
        from_value, to_value = self._validate_date_range(from_date, to_date)
        if interval not in VALID_STATS_INTERVALS:
            raise RequestValidationError(
                "interval must be one of: day, week, month, year"
            )
        await self.auth.async_update_access_token()
        response = await self.api_wrapper.get(
            url=self._url_from_path(path=f"{CHARGES}{STATS}", base=MOBILE_API_BASE_URL),
            params={"from": from_value, "to": to_value, "interval": interval},
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return ChargeHistoryFactory().build_stats(json)

    async def async_get_notification_preferences(self) -> NotificationPreferences:
        """Get the current user's notification switches."""
        await self.auth.async_update_access_token()
        response = await self.api_wrapper.get(
            url=self._url_from_path(
                path=NOTIFICATION_PREFERENCES,
                base=MOBILE_API_BASE_URL
            ),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return PreferencesFactory().build_notifications(json)

    async def async_create_charger_charge_override(
        self,
        charger: Charger,
        hours: int = 0,
        minutes: int = 0,
        seconds: int = 0,
        requested_at: datetime = None,
        end_at: datetime = None
    ) -> List[ChargerChargeOverride]:
        """Create a charger override using a positive duration or explicit end time."""
        values = (hours, minutes, seconds)
        if any(type(value) is not int or value < 0 for value in values):
            raise RequestValidationError("override duration values must be non-negative integers")
        requested_at = requested_at or datetime.now(timezone.utc)
        self._validate_aware_datetime(requested_at, "requested_at")
        if end_at is not None and any(values):
            raise RequestValidationError("pass either a duration or end_at, not both")
        if end_at is None:
            if not any(values):
                raise RequestValidationError("override duration must be greater than zero")
            end_at = requested_at + timedelta(
                hours=hours, minutes=minutes, seconds=seconds
            )
        self._validate_aware_datetime(end_at, "end_at")
        if end_at <= requested_at:
            raise RequestValidationError("end_at must be later than requested_at")

        return await self._async_create_charger_charge_override(
            charger=charger,
            requested_at=requested_at,
            end_at=end_at
        )

    async def async_set_charger_charge_mode_always_on(
        self,
        charger: Charger,
        requested_at: datetime = None
    ) -> List[ChargerChargeOverride]:
        """Enable basic charging indefinitely by creating an open-ended override."""
        requested_at = requested_at or datetime.now(timezone.utc)
        self._validate_aware_datetime(requested_at, "requested_at")
        await self._async_require_basic_charging(charger)
        return await self._async_create_charger_charge_override(
            charger=charger,
            requested_at=requested_at
        )

    async def async_delete_charger_charge_overrides(self, charger: Charger) -> bool:
        """Delete active charger overrides."""
        await self.auth.async_update_access_token()
        response = await self.api_wrapper.delete(
            url=self._url_from_path(
                path=f"{CHARGERS}/{charger.ppid}{CHARGE_OVERRIDES}",
                base=MOBILE_API_BASE_URL
            ),
            headers=auth_headers(access_token=self.auth.access_token)
        )
        return response.status == 200

    async def async_set_charger_charge_mode_scheduled(
        self,
        charger: Charger
    ) -> bool:
        """Return basic charging to its configured manual schedules."""
        await self._async_require_basic_charging(charger)
        return await self.async_delete_charger_charge_overrides(charger)

    async def async_set_charger_smart_charging(
        self,
        charger: Charger,
        enabled: bool
    ) -> bool:
        """Enable or disable delegated smart charging for a charger."""
        if not isinstance(enabled, bool):
            raise RequestValidationError("enabled must be a boolean")
        await self.auth.async_update_access_token()
        response = await self.api_wrapper.patch(
            url=self._url_from_path(
                path=f"{DELEGATED_CONTROLS}/{charger.ppid}",
                base=MOBILE_API_BASE_URL
            ),
            body={"status": "ACTIVE" if enabled else "INACTIVE"},
            headers=auth_headers(access_token=self.auth.access_token)
        )
        return response.status == 204

    async def async_set_manual_schedules(
        self,
        charger: Charger,
        schedules: List[ManualSchedule]
    ) -> List[ManualSchedule]:
        """Replace all seven manual charger schedules."""
        if not isinstance(schedules, list):
            raise RequestValidationError("schedules must be a list")
        schedule_data = [
            item.dict if isinstance(item, ManualSchedule) else item
            for item in schedules
        ]
        self._validate_manual_schedules(schedule_data)
        await self.auth.async_update_access_token()
        response = await self.api_wrapper.put(
            url=self._url_from_path(
                path=f"{CHARGERS}/{charger.ppid}{MANUAL_SCHEDULES}",
                base=MOBILE_API_BASE_URL
            ),
            body={"schedules": schedule_data},
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return ManualScheduleFactory().build_schedules(json)

    async def async_set_vehicle_intents(
        self,
        charger: Charger,
        vehicle_link_id: str,
        intents: List[VehicleIntentDetail]
    ) -> VehicleIntent:
        """Replace recurring charging targets for a delegated vehicle link."""
        if not isinstance(intents, list):
            raise RequestValidationError("intents must be a list")
        details = [
            item.dict if isinstance(item, VehicleIntentDetail) else item
            for item in intents
        ]
        self._validate_vehicle_intents(details)
        if not vehicle_link_id:
            raise RequestValidationError("vehicle_link_id is required")
        await self.auth.async_update_access_token()
        response = await self.api_wrapper.put(
            url=self._url_from_path(
                path=(f"{DELEGATED_CONTROLS}/{charger.ppid}/vehicles/"
                      f"{vehicle_link_id}/intents"),
                base=MOBILE_API_BASE_URL
            ),
            body={"intentDetails": details},
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return VehicleIntent(json)

    async def async_set_smart_charging_max_price(
        self,
        charger: Charger,
        max_price: float
    ) -> bool:
        """Set the maximum smart-charging unit price."""
        if isinstance(max_price, bool) or not isinstance(max_price, (int, float)):
            raise RequestValidationError("max_price must be a non-negative number")
        if not math.isfinite(max_price) or max_price < 0:
            raise RequestValidationError("max_price must be a non-negative number")
        await self.auth.async_update_access_token()
        response = await self.api_wrapper.patch(
            url=self._url_from_path(
                path=f"{DELEGATED_CONTROLS}/{charger.ppid}{PREFERENCES}",
                base=MOBILE_API_BASE_URL
            ),
            body={"maxPrice": max_price},
            headers=auth_headers(access_token=self.auth.access_token)
        )
        return response.status == 204

    async def async_set_tariff(
        self,
        charger: Charger,
        supplier_id: str,
        tariff_info: List[TariffPeriod],
        effective_from: date,
        timezone_name: str,
        smart_charging_supported: bool = True
    ) -> Tariff:
        """Create or replace a charger tariff."""
        effective_value = self._date_value(effective_from, "effective_from")
        try:
            pytz.timezone(timezone_name)
        except (pytz.UnknownTimeZoneError, AttributeError, TypeError) as error:
            raise RequestValidationError("timezone_name must be a valid IANA timezone") from error
        if not isinstance(tariff_info, list):
            raise RequestValidationError("tariff_info must be a list")
        periods = [
            item.dict if isinstance(item, TariffPeriod) else item
            for item in tariff_info
        ]
        self._validate_tariff_periods(periods)
        if not supplier_id:
            raise RequestValidationError("supplier_id is required")
        if type(smart_charging_supported) is not bool:
            raise RequestValidationError("smart_charging_supported must be a boolean")

        await self.auth.async_update_access_token()
        response = await self.api_wrapper.post(
            url=self._url_from_path(
                path=f"{CHARGERS}/{charger.ppid}{TARIFFS}",
                base=MOBILE_API_BASE_URL
            ),
            body={
                "effectiveFrom": effective_value,
                "supplierId": supplier_id,
                "smartChargingSupported": smart_charging_supported,
                "tariffInfo": periods,
                "timezone": timezone_name,
            },
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return Tariff(json)

    async def _async_create_charger_charge_override(
        self,
        charger: Charger,
        requested_at: datetime,
        end_at: datetime = None
    ) -> List[ChargerChargeOverride]:
        """Create a timed or open-ended charger-centric override."""
        body = {"requestedAt": self._utc_iso(requested_at)}
        if end_at is not None:
            body["endAt"] = self._utc_iso(end_at)

        await self.auth.async_update_access_token()
        response = await self.api_wrapper.post(
            url=self._url_from_path(
                path=f"{CHARGERS}/{charger.ppid}{CHARGE_OVERRIDES}",
                base=MOBILE_API_BASE_URL
            ),
            body=body,
            headers=auth_headers(access_token=self.auth.access_token)
        )
        json = await self._handle_json_response(response=response)
        return ChargerChargeOverrideFactory().build_overrides(json)

    async def _async_require_basic_charging(self, charger: Charger) -> None:
        """Raise a clear error unless delegated smart charging is inactive."""
        delegated_control = await self.async_get_delegated_control(charger)
        status = delegated_control.status if delegated_control is not None else None
        if status != "INACTIVE":
            raise ChargeModeTransitionError(
                "Basic charging mode is unavailable while smart charging is active"
            )

    async def async_set_charge_override(self, pod:Pod, hours:int=0, minutes:int=0, seconds:int=0) -> ChargeOverride:
        await self.auth.async_update_access_token()

        valid_hours = (hours is not None and type(hours) is int and hours >= 0)
        valid_minutes = (minutes is not None and type(minutes) is int  and minutes >= 0)
        valid_seconds = (seconds is not None and type(seconds) is int  and seconds >= 0)
        valid = (
            valid_hours
            and valid_minutes
            and valid_seconds
            and (
                hours > 0
                or minutes > 0
                or seconds > 0
            )
        )

        if valid is False:
            raise ChargeOverrideValidationError()
        
        now = datetime.now().astimezone()
        ends_at = now + timedelta(hours=hours, minutes=minutes, seconds=seconds)
        datetime_format_string = "%Y-%m-%dT%H:%M:%S%z"

        body = {
            "requested_at": now.strftime(datetime_format_string),
            "ends_at": ends_at.strftime(datetime_format_string)
        }

        response = await self.api_wrapper.put(
            url=self._url_from_path(
                path=f"{UNITS}/{pod.unit_id}{CHARGE_OVERRIDE}"),
            params=self._generate_complete_params(params=None),
            body=body,
            headers=auth_headers(access_token=self.auth.access_token)
        )

        json = await self._handle_json_response(response=response)

        return ChargeOverrideFactory().build_charge_override(charge_override_response=json)

    async def async_set_charge_mode_manual(self, pod) -> bool:
        """Set user's pod into 'manual' charge mode"""
        await self.auth.async_update_access_token()

        body = {
            "requested_at": datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z") #2023-04-25T09:35:34+01:00
        }

        response = await self._async_set_charge_mode(pod, body)

        expected_response = (
            response.ppid == pod.ppid 
            and response.requested_at is not None
            and response.received_at is not None
            and response.ends_at is None)

        return expected_response

    async def async_set_charge_mode_smart(self, pod) -> bool:
        """Set the user's pod into 'smart' charge mode"""
        response = await self.api_wrapper.delete(
            url=self._url_from_path(
                path=f"{UNITS}/{pod.unit_id}{CHARGE_OVERRIDE}"
            ),
            params=self._generate_complete_params(params=None),
            headers=auth_headers(access_token=self.auth.access_token)
        )

        return response.status == 204

 
    async def _async_set_charge_mode(self, pod, body) -> ChargeMode:
        """Given a body object, set the charge mode for a user's pod"""
        response = await self.api_wrapper.put(
            url=self._url_from_path(
                path=f"{UNITS}/{pod.unit_id}{CHARGE_OVERRIDE}"),
            params=self._generate_complete_params(params=None),
            body=body,
            headers=auth_headers(access_token=self.auth.access_token)
        )

        json = await self._handle_json_response(response=response)

        return ChargeOverrideFactory().build_charge_override(charge_override_response=json)

    @staticmethod
    def _validate_aware_datetime(value: datetime, name: str) -> None:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise RequestValidationError(f"{name} must be a timezone-aware datetime")
        if value.utcoffset() is None:
            raise RequestValidationError(f"{name} must be a timezone-aware datetime")

    @staticmethod
    def _utc_iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _date_value(value: date, name: str) -> str:
        if isinstance(value, datetime):
            value = value.date()
        if not isinstance(value, date):
            raise RequestValidationError(f"{name} must be a date")
        return value.isoformat()

    @classmethod
    def _validate_date_range(cls, from_date: date, to_date: date):
        from_value = cls._date_value(from_date, "from_date")
        to_value = cls._date_value(to_date, "to_date")
        if from_value > to_value:
            raise RequestValidationError("from_date must not be later than to_date")
        return from_value, to_value

    @staticmethod
    def _valid_time(value: Any) -> bool:
        if not isinstance(value, str) or not re.match(r"^\d{2}:\d{2}:\d{2}$", value):
            return False
        try:
            datetime.strptime(value, "%H:%M:%S")
        except ValueError:
            return False
        return True

    @classmethod
    def _validate_vehicle_intents(cls, details: List[Dict[str, Any]]) -> None:
        if not isinstance(details, list) or not details:
            raise RequestValidationError("intents must contain at least one charge target")
        seen_days = set()
        for detail in details:
            if not isinstance(detail, dict):
                raise RequestValidationError("each intent must be a VehicleIntentDetail or dict")
            day = detail.get("dayOfWeek")
            charge_kwh = detail.get("chargeKWh")
            if day not in VALID_WEEKDAYS or day in seen_days:
                raise RequestValidationError("intent weekdays must be valid and unique")
            if isinstance(charge_kwh, bool) or not isinstance(charge_kwh, (int, float)):
                raise RequestValidationError("intent chargeKWh must be a positive number")
            if not math.isfinite(charge_kwh) or charge_kwh <= 0:
                raise RequestValidationError("intent chargeKWh must be a positive number")
            if not cls._valid_time(detail.get("chargeByTime")):
                raise RequestValidationError("intent chargeByTime must use HH:MM:SS")
            seen_days.add(day)

    @classmethod
    def _validate_tariff_periods(cls, periods: List[Dict[str, Any]]) -> None:
        if not isinstance(periods, list) or not periods:
            raise RequestValidationError("tariff_info must contain at least one period")
        for period in periods:
            if not isinstance(period, dict):
                raise RequestValidationError("each tariff period must be a TariffPeriod or dict")
            days = period.get("days")
            valid_days = (
                isinstance(days, list) and bool(days) and len(days) == len(set(days))
                and all(
                    (isinstance(day, int) and not isinstance(day, bool) and 1 <= day <= 7)
                    or (isinstance(day, str) and day in VALID_WEEKDAYS)
                    for day in days
                )
            )
            if not valid_days:
                raise RequestValidationError("tariff days must be unique weekdays or integers 1-7")
            if not cls._valid_time(period.get("start")) or not cls._valid_time(period.get("end")):
                raise RequestValidationError("tariff start and end must use HH:MM:SS")
            price = period.get("price")
            if (
                isinstance(price, bool)
                or not isinstance(price, (int, float))
                or not math.isfinite(price)
                or price < 0
            ):
                raise RequestValidationError("tariff price must be a non-negative number")

    @classmethod
    def _validate_manual_schedules(cls, schedules: List[Dict[str, Any]]) -> None:
        if len(schedules) != 7:
            raise RequestValidationError(
                "schedules must contain all seven days because this operation replaces them"
            )
        start_days = set()
        for schedule in schedules:
            if not isinstance(schedule, dict):
                raise RequestValidationError(
                    "each schedule must be a ManualSchedule or dict"
                )
            uid = schedule.get("uid")
            start_day = schedule.get("startDay")
            end_day = schedule.get("endDay")
            status = schedule.get("status")
            if not isinstance(uid, str) or not uid:
                raise RequestValidationError("each schedule must have a uid")
            if (
                isinstance(start_day, bool)
                or not isinstance(start_day, int)
                or start_day not in range(1, 8)
                or start_day in start_days
            ):
                raise RequestValidationError(
                    "schedule startDay values must uniquely cover days 1-7"
                )
            if (
                isinstance(end_day, bool)
                or not isinstance(end_day, int)
                or end_day not in range(1, 8)
            ):
                raise RequestValidationError(
                    "schedule endDay must be an integer from 1 to 7"
                )
            if not cls._valid_time(schedule.get("startTime")):
                raise RequestValidationError("schedule startTime must use HH:MM:SS")
            if not cls._valid_time(schedule.get("endTime")):
                raise RequestValidationError("schedule endTime must use HH:MM:SS")
            if (
                not isinstance(status, dict)
                or not isinstance(status.get("isActive"), bool)
            ):
                raise RequestValidationError(
                    "schedule status.isActive must be a boolean"
                )
            start_days.add(start_day)
        if start_days != set(range(1, 8)):
            raise RequestValidationError(
                "schedule startDay values must uniquely cover days 1-7"
            )


    def _schedule_data(self, enabled: bool) -> Dict[str, Any]:
        """Generate a new schedule body with all the enable attributes set to the `enabled` value"""
        schedules: List[Schedule] = ScheduleFactory(
        ).build_schedules(enabled=enabled)

        d_list = list(map(lambda schedule: schedule.dict, schedules))

        return {"data": d_list}

    def _url_from_path(self, path: str, base: str = API_BASE_URL) -> str:
        """Given a path, return a complete API URL"""
        return f"{base}{path}"

    def _generate_complete_params(self, params: Union[None, Dict[str, Any]]) -> Dict[str, any]:
        """Given a params object, add optional params if required"""
        if not self.include_timestamp:
            return params

        if params is None:
            params = {}

        params["timestamp"] = datetime.now().astimezone().timestamp()
        return params

    async def _handle_json_response(self, response: aiohttp.ClientResponse) -> Dict[str, any]:
        """Given a Coroutine (assuming a response from ApiWrapper), await calling
        json() and if needed, debug log the response"""
        json = await response.json()

        if self._http_debug:
            _LOGGER.debug(json)

        return json
