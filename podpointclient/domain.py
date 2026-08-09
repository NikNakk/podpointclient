"""Stable domain-level facade over legacy Pod and newer Home APIs."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Union

from .charge import Charge
from .charge_history import ChargeHistoryItem
from .charge_override import ChargeOverride
from .charger import Charger
from .charger_charge_override import ChargerChargeOverride
from .connectivity_status import ConnectivityStatus
from .connectivity_status_v2 import ConnectivityStatusV2
from .errors import (
    APIError, ChargeModeTransitionError, RequestValidationError,
    UnsupportedCapabilityError,
    is_unsupported_api_error,
)
from .manual_schedule import ManualSchedule
from .pod import Pod
from .schedule import Schedule


class ChargerIdentityError(ValueError):
    """Raised when a low-level object has no usable canonical PPID."""


class ChargerSource(Enum):
    """Wire API used to create and operate a charger reference."""

    HOME = "home"
    LEGACY = "legacy"


class CapabilitySupport(Enum):
    """Observed support state for a domain capability."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class ChargerCapability(Enum):
    """Features scoped to an individual charger."""

    CONNECTIVITY_STATE = "connectivity_state"
    TIMED_BOOST = "timed_boost"
    LEGACY_SCHEDULING = "legacy_scheduling"
    MANUAL_SCHEDULING = "manual_scheduling"
    DELEGATED_SMART_CHARGING = "delegated_smart_charging"
    SMART_CHARGING_PREFERENCES = "smart_charging_preferences"
    TARIFFS = "tariffs"
    REMOTE_LOCK = "remote_lock"
    FIRMWARE = "firmware"
    BASIC_CHARGING_MODE = "basic_charging_mode"
    SCHEDULES = "schedules"
    FULL_SCHEDULE_REPLACEMENT = "full_schedule_replacement"


class AccountCapability(Enum):
    """Features fetched once at account scope and optionally grouped by PPID."""

    DELEGATED_VEHICLES = "delegated_vehicles"
    # Retained as a compatibility view over the two history-source capabilities.
    CHARGE_HISTORY = "charge_history"
    HOME_CHARGE_HISTORY = "home_charge_history"
    LEGACY_CHARGES = "legacy_charges"
    REWARD_WALLET = "reward_wallet"


class BasicChargingMode(Enum):
    """Canonical persistent/basic charging mode."""

    SCHEDULED = "scheduled"
    ALWAYS_ON = "always_on"
    TIMED_BOOST = "timed_boost"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ChargerSchedule:
    """One canonical charger schedule entry shared by both wire APIs.

    ``uid`` is retained for endpoint round trips and diagnostics, but Pod Point
    regenerates every UID whenever the seven-entry collection is replaced.
    Consumers must not use it as stable schedule identity.
    """

    start_day: int
    start_time: str
    end_day: int
    end_time: str
    is_active: bool
    uid: Optional[str] = field(default=None, compare=False)

    @property
    def manual_dict(self) -> Dict[str, Any]:
        """Return the newer Home API representation."""
        return {
            "uid": self.uid,
            "startDay": self.start_day,
            "startTime": self.start_time,
            "endDay": self.end_day,
            "endTime": self.end_time,
            "status": {"isActive": self.is_active},
        }


class ChargeSessionSource(Enum):
    """API namespace which supplied a canonical charge session."""

    HOME_HISTORY = "home_history"
    LEGACY = "legacy"
    UNKNOWN = "unknown"


class StateValue(Enum):
    """Normalized connectivity or charging value."""

    ONLINE = "online"
    OFFLINE = "offline"
    AVAILABLE = "available"
    IDLE = "idle"
    UNAVAILABLE = "unavailable"
    OUT_OF_SERVICE = "out_of_service"
    CHARGING = "charging"
    SUSPENDED_EV = "suspended_ev"
    SUSPENDED_EVSE = "suspended_evse"
    FINISHING = "finishing"
    PREPARING = "preparing"
    FAULTED = "faulted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class NormalizedStateValue:
    """Known normalized state plus the unmodified wire value."""

    value: Optional[StateValue]
    raw: Optional[str] = None

    @property
    def known(self) -> bool:
        """Whether the wire value maps to a state understood by this version."""
        return self.value not in (None, StateValue.UNKNOWN)


@dataclass(frozen=True)
class ConnectionQualityDiagnostic:
    """Source-qualified connection-quality value without cross-API scaling."""

    raw: Optional[int]
    source: ChargerSource


@dataclass(frozen=True)
class ChargerState:
    """API-independent connectivity and charging state."""

    connection: NormalizedStateValue
    charging: NormalizedStateValue
    last_seen_at: Optional[datetime] = None
    signal_strength_dbm: Optional[int] = None
    connection_quality: Optional[ConnectionQualityDiagnostic] = None


@dataclass(frozen=True)
# pylint: disable-next=too-many-instance-attributes
class BoostState:
    """Canonical active, timed, or open-ended charge override state."""

    ppid: str
    active: bool
    timed: bool
    requested_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    source_id: Optional[str] = None
    raw: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
# pylint: disable-next=too-many-instance-attributes
class ChargeSession:
    """Canonical charge session from legacy or Home account history."""

    ppid: str
    session_id: Optional[str]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    active: bool
    energy_kwh: Optional[float]
    duration_seconds: Optional[int]
    cost: Optional[float]
    currency: Optional[str]
    correlation_key: str
    raw: Any = field(default=None, repr=False, compare=False)
    source: ChargeSessionSource = ChargeSessionSource.UNKNOWN


def normalize_state(value: Optional[str]) -> NormalizedStateValue:
    """Normalize camel, title, snake and hyphenated state spellings safely."""
    if value is None:
        return NormalizedStateValue(None, None)
    raw = str(value)
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw)
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized).strip("_").lower()
    try:
        state = StateValue(normalized)
    except ValueError:
        state = StateValue.UNKNOWN
    return NormalizedStateValue(state, raw)


class _CapabilityState:
    """Privately mutable support observations with a read-only public view."""

    def __init__(self, values: Mapping[Any, CapabilitySupport]):
        self._values = dict(values)

    def get(self, capability: Any) -> CapabilitySupport:
        """Return one observation."""
        return self._values.get(capability, CapabilitySupport.UNKNOWN)

    def set(self, capability: Any, support: CapabilitySupport) -> None:
        """Retain one observation for this domain lifetime."""
        self._values[capability] = support

    @property
    def view(self) -> Mapping[Any, CapabilitySupport]:
        """Return an immutable snapshot."""
        return MappingProxyType(dict(self._values))


def _initial_charger_capabilities(source: ChargerSource, unit_id: Optional[int]):
    values = {capability: CapabilitySupport.UNKNOWN for capability in ChargerCapability}
    if source is ChargerSource.HOME:
        values[ChargerCapability.LEGACY_SCHEDULING] = CapabilitySupport.UNSUPPORTED
    else:
        for capability in (
            ChargerCapability.MANUAL_SCHEDULING,
            ChargerCapability.FULL_SCHEDULE_REPLACEMENT,
            ChargerCapability.DELEGATED_SMART_CHARGING,
            ChargerCapability.SMART_CHARGING_PREFERENCES,
            ChargerCapability.TARIFFS,
            ChargerCapability.REMOTE_LOCK,
        ):
            values[capability] = CapabilitySupport.UNSUPPORTED
    if unit_id is None:
        values[ChargerCapability.FIRMWARE] = CapabilitySupport.UNSUPPORTED
    return values


@dataclass(frozen=True, eq=False)
# pylint: disable-next=too-many-instance-attributes
class ChargerRef:
    """Canonical PPID identity with privately retained capability observations."""

    ppid: str
    unit_id: Optional[int]
    timezone: Optional[str]
    model_name: Optional[str]
    linked_at: Optional[datetime]
    source: ChargerSource
    raw: Union[Pod, Charger] = field(repr=False, compare=False)
    _capability_state: _CapabilityState = field(repr=False, compare=False)

    def __post_init__(self):
        if not isinstance(self.ppid, str) or not self.ppid.strip():
            raise ChargerIdentityError("A canonical charger requires a non-empty PPID")

    def capability(self, capability: ChargerCapability) -> CapabilitySupport:
        """Return the currently observed support state."""
        return self._capability_state.get(capability)

    @property
    def capabilities(self) -> Mapping[ChargerCapability, CapabilitySupport]:
        """Return an immutable snapshot of current support observations."""
        return self._capability_state.view

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ChargerRef):
            return NotImplemented
        return self.ppid == other.ppid

    def __hash__(self) -> int:
        return hash(self.ppid)


def charger_ref_from_charger(
    charger: Charger, capability_state: _CapabilityState = None
) -> ChargerRef:
    """Adapt a Home Charger without creating a synthetic Pod."""
    model = charger.model_info
    model_name = None
    if model is not None:
        model_name = " ".join(
            item for item in (model.architecture, model.style) if item
        ) or None
    state = capability_state or _CapabilityState(
        _initial_charger_capabilities(ChargerSource.HOME, charger.unit_id)
    )
    return ChargerRef(
        ppid=charger.ppid, unit_id=charger.unit_id, timezone=charger.timezone,
        model_name=model_name, linked_at=charger.linked_at,
        source=ChargerSource.HOME, raw=charger, _capability_state=state,
    )


def charger_ref_from_pod(
    pod: Pod, capability_state: _CapabilityState = None
) -> ChargerRef:
    """Adapt a legacy Pod using PPID as canonical identity."""
    state = capability_state or _CapabilityState(
        _initial_charger_capabilities(ChargerSource.LEGACY, pod.unit_id)
    )
    return ChargerRef(
        ppid=pod.ppid, unit_id=pod.unit_id, timezone=pod.timezone,
        model_name=pod.model.name if pod.model is not None else None,
        linked_at=pod.commissioned_at, source=ChargerSource.LEGACY, raw=pod,
        _capability_state=state,
    )


def boost_state_from_legacy(ppid: str, override: Optional[ChargeOverride]) -> BoostState:
    """Normalize a legacy override, including its open-ended manual form."""
    if override is None:
        return BoostState(ppid=ppid, active=False, timed=False)
    timed = override.ends_at is not None
    active = override.active if timed else override.requested_at is not None
    return BoostState(
        ppid=ppid, active=active, timed=timed,
        requested_at=override.requested_at, started_at=override.received_at,
        ends_at=override.ends_at, raw=override,
    )


def boost_state_from_home(
    ppid: str, override: Optional[ChargerChargeOverride]
) -> BoostState:
    """Normalize a Home timed or open-ended override."""
    if override is None:
        return BoostState(ppid=ppid, active=False, timed=False)
    return BoostState(
        ppid=ppid, active=override.active, timed=override.end_at is not None,
        requested_at=override.requested_at, started_at=override.received_at,
        ends_at=override.end_at, source_id=override.id, raw=override,
    )


def basic_charging_mode_from_boost(state: BoostState) -> BasicChargingMode:
    """Derive scheduled, always-on, or timed-boost mode from canonical state."""
    if not state.active:
        return BasicChargingMode.SCHEDULED
    if state.timed:
        return BasicChargingMode.TIMED_BOOST
    return BasicChargingMode.ALWAYS_ON


def charger_schedule_from_legacy(schedule: Schedule) -> ChargerSchedule:
    """Normalize one schedule returned by legacy Pod discovery."""
    return ChargerSchedule(
        uid=schedule.uid,
        start_day=schedule.start_day,
        start_time=schedule.start_time,
        end_day=schedule.end_day,
        end_time=schedule.end_time,
        is_active=schedule.status.is_active,
    )


def charger_schedule_from_home(schedule: ManualSchedule) -> ChargerSchedule:
    """Normalize one manual schedule returned by the Home API."""
    return ChargerSchedule(
        uid=schedule.uid,
        start_day=schedule.start_day,
        start_time=schedule.start_time,
        end_day=schedule.end_day,
        end_time=schedule.end_time,
        is_active=schedule.status.get("isActive", False),
    )


def _correlation_key(ppid: str, started_at: Optional[datetime]) -> str:
    started = started_at.isoformat() if started_at else "unknown"
    return f"{ppid}:{started}"


def charge_session_from_legacy(ppid: str, charge: Charge) -> ChargeSession:
    """Normalize one legacy account charge."""
    billing = charge.billing_event
    duration = charge.charging_duration.raw
    if duration is None:
        duration = charge.duration
    cost = billing.amount if billing.amount is not None else charge.energy_cost
    return ChargeSession(
        ppid=ppid, session_id=str(charge.id) if charge.id is not None else None,
        started_at=charge.starts_at, ended_at=charge.ends_at,
        active=charge.ends_at is None, energy_kwh=charge.kwh_used,
        duration_seconds=duration, cost=cost, currency=billing.currency,
        correlation_key=_correlation_key(ppid, charge.starts_at),
        source=ChargeSessionSource.LEGACY, raw=charge,
    )


def charge_session_from_home(ppid: str, charge: ChargeHistoryItem) -> ChargeSession:
    """Normalize one Home account-history charge."""
    return ChargeSession(
        ppid=ppid, session_id=str(charge.id) if charge.id is not None else None,
        started_at=charge.started_at, ended_at=charge.ended_at,
        active=charge.ended_at is None, energy_kwh=charge.energy_total,
        duration_seconds=charge.duration, cost=charge.cost.amount,
        currency=charge.cost.currency,
        correlation_key=_correlation_key(ppid, charge.started_at),
        source=ChargeSessionSource.HOME_HISTORY, raw=charge,
    )


def _session_sort_key(session: ChargeSession):
    """Return a deterministic key without comparing naive and aware datetimes."""
    return (
        session.started_at is None,
        session.started_at.isoformat() if session.started_at else "",
        session.ppid,
        session.session_id or "",
        session.ended_at.isoformat() if session.ended_at else "",
    )


def reconcile_charge_sessions(
    completed: List[ChargeSession],
    provisional: List[ChargeSession],
    *,
    tolerance: timedelta = timedelta(seconds=60),
) -> List[ChargeSession]:
    """Combine authoritative completed sessions with unmatched provisional ones."""
    if tolerance < timedelta(0):
        raise ValueError("tolerance must not be negative")

    unique_completed = {}
    for session in completed:
        identity = (
            ("id", session.source, session.ppid, session.session_id)
            if (
                session.session_id is not None
                and session.source is not ChargeSessionSource.UNKNOWN
            )
            else (
                "time", session.source, session.ppid, session.started_at,
                session.ended_at, session.energy_kwh,
            )
        )
        unique_completed.setdefault(identity, session)

    authoritative = list(unique_completed.values())

    def matches(candidate: ChargeSession, final: ChargeSession) -> bool:
        if candidate.ppid != final.ppid:
            return False
        if (
            candidate.session_id is not None
            and final.session_id is not None
            and candidate.session_id == final.session_id
            and candidate.source is final.source
            and candidate.source is not ChargeSessionSource.UNKNOWN
        ):
            return True
        if candidate.started_at is None or final.started_at is None:
            return False
        try:
            difference = abs(candidate.started_at - final.started_at)
        except TypeError:
            return False
        return difference <= tolerance

    unmatched = [
        session for session in provisional
        if not any(matches(session, final) for final in authoritative)
    ]
    return sorted(authoritative + unmatched, key=_session_sort_key)


class ChargerDomain:  # pylint: disable=too-many-public-methods
    """High-level operations which hide endpoint selection from consumers."""

    def __init__(self, client: Any):
        self._client = client
        self._charger_states: Dict[Any, _CapabilityState] = {}
        self._legacy_ppid_by_pod_id: Dict[Any, str] = {}
        self._legacy_ppid_by_unit_id: Dict[Any, str] = {}
        self._account_state = _CapabilityState({
            capability: CapabilitySupport.UNKNOWN for capability in AccountCapability
        })

    def account_capability(self, capability: AccountCapability) -> CapabilitySupport:
        """Return the observed support state of an account-level feature."""
        if capability is AccountCapability.CHARGE_HISTORY:
            home = self._account_state.get(AccountCapability.HOME_CHARGE_HISTORY)
            legacy = self._account_state.get(AccountCapability.LEGACY_CHARGES)
            if CapabilitySupport.SUPPORTED in (home, legacy):
                return CapabilitySupport.SUPPORTED
            if home is legacy is CapabilitySupport.UNSUPPORTED:
                return CapabilitySupport.UNSUPPORTED
            return CapabilitySupport.UNKNOWN
        return self._account_state.get(capability)

    async def _call(
        self, charger: ChargerRef, capability: ChargerCapability,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Apply the complete charger capability lifecycle around one call."""
        if charger.capability(capability) is CapabilitySupport.UNSUPPORTED:
            raise UnsupportedCapabilityError(capability, charger.ppid)
        try:
            result = await operation()
        except APIError as error:
            if is_unsupported_api_error(error):
                charger._capability_state.set(  # pylint: disable=protected-access
                    capability, CapabilitySupport.UNSUPPORTED
                )
                raise UnsupportedCapabilityError(capability, charger.ppid) from error
            raise
        charger._capability_state.set(  # pylint: disable=protected-access
            capability, CapabilitySupport.SUPPORTED
        )
        return result

    async def _call_account(
        self, capability: AccountCapability,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Apply the complete account capability lifecycle around one call."""
        if self.account_capability(capability) is CapabilitySupport.UNSUPPORTED:
            raise UnsupportedCapabilityError(capability)
        try:
            result = await operation()
        except APIError as error:
            if is_unsupported_api_error(error):
                self._account_state.set(capability, CapabilitySupport.UNSUPPORTED)
                raise UnsupportedCapabilityError(capability) from error
            raise
        self._account_state.set(capability, CapabilitySupport.SUPPORTED)
        return result

    def _state(self, ppid: str, source: ChargerSource, unit_id: Optional[int]):
        key = (ppid, source)
        if key not in self._charger_states:
            self._charger_states[key] = _CapabilityState(
                _initial_charger_capabilities(source, unit_id)
            )
        return self._charger_states[key]

    async def _discover_home_chargers(self) -> List[ChargerRef]:
        """Create canonical references backed by Home Charger models."""
        get_chargers = getattr(self._client, "async_get_chargers", None)
        if not callable(get_chargers):
            raise NotImplementedError("Home charger discovery is unavailable")
        chargers = await get_chargers()
        return [
            charger_ref_from_charger(
                item, self._state(item.ppid, ChargerSource.HOME, item.unit_id)
            ) for item in chargers
        ]

    async def _discover_legacy_chargers(self) -> List[ChargerRef]:
        """Create canonical references backed by legacy Pod models."""
        get_pods = getattr(self._client, "async_get_all_pods", None)
        if not callable(get_pods):
            raise NotImplementedError("Legacy Pod discovery is unavailable")
        pods = await get_pods()
        return [
            charger_ref_from_pod(
                item, self._state(item.ppid, ChargerSource.LEGACY, item.unit_id)
            ) for item in pods
        ]

    async def async_discover_chargers(
        self, preferred_protocol: ChargerSource = ChargerSource.HOME
    ) -> List[ChargerRef]:
        """Discover with an explicit preferred wire API and absent-only fallback."""
        if not isinstance(preferred_protocol, ChargerSource):
            raise TypeError("preferred_protocol must be a ChargerSource")

        if preferred_protocol is ChargerSource.HOME:
            preferred = self._discover_home_chargers
            fallback = self._discover_legacy_chargers
        else:
            preferred = self._discover_legacy_chargers
            fallback = self._discover_home_chargers

        try:
            return await preferred()
        except NotImplementedError:
            pass
        except APIError as error:
            if not is_unsupported_api_error(error):
                raise
        return await fallback()

    async def async_charger_credentials_verified(self) -> bool:
        """Verify credentials through Home-first canonical discovery."""
        return bool(await self.async_discover_chargers())

    async def async_get_state(self, charger: ChargerRef) -> ChargerState:
        """Fetch and normalize connectivity and charging state."""
        async def operation():
            if charger.source is ChargerSource.HOME:
                status: ConnectivityStatusV2 = (
                    await self._client.async_get_connectivity_status_v2(charger.raw)
                )
                connection = status.connection_state if status else None
                charging = status.charging_state if status else None
                last_seen_at = status.last_seen_at if status else None
                signal_strength_dbm = None
                quality = status.connection_quality if status else None
            else:
                status: ConnectivityStatus = (
                    await self._client.async_get_connectivity_status(charger.raw)
                )
                connection = status.connectivity_status if status else None
                charging = status.charging_state if status else None
                last_seen_at = status.last_message_at if status else None
                signal_strength_dbm = status.signal_strength if status else None
                quality = status.connection_quality if status else None
            connection_quality = (
                ConnectionQualityDiagnostic(quality, charger.source)
                if quality is not None
                else None
            )
            return ChargerState(
                connection=normalize_state(connection),
                charging=normalize_state(charging),
                last_seen_at=last_seen_at,
                signal_strength_dbm=signal_strength_dbm,
                connection_quality=connection_quality,
            )
        return await self._call(charger, ChargerCapability.CONNECTIVITY_STATE, operation)

    async def async_get_firmware(self, charger: ChargerRef):
        """Get firmware through the legacy unit endpoint for either source."""
        async def operation():
            return await self._client.async_get_firmware(charger.raw)
        return await self._call(charger, ChargerCapability.FIRMWARE, operation)

    async def async_get_active_boost(self, charger: ChargerRef) -> BoostState:
        """Return canonical active/inactive override state."""
        async def operation():
            return await self._async_get_boost_state(charger)
        return await self._call(charger, ChargerCapability.TIMED_BOOST, operation)

    async def _async_get_boost_state(self, charger: ChargerRef) -> BoostState:
        """Fetch canonical override state without applying a capability lifecycle."""
        if charger.source is ChargerSource.HOME:
            items = await self._client.async_get_charger_charge_overrides(
                charger.raw, active_only=True
            )
            return boost_state_from_home(charger.ppid, items[0] if items else None)
        override = await self._client.async_get_charge_override(charger.raw)
        return boost_state_from_legacy(charger.ppid, override)

    async def async_get_basic_charging_mode(
        self, charger: ChargerRef, boost_state: Optional[BoostState] = None
    ) -> BasicChargingMode:
        """Derive basic mode across APIs, optionally reusing fetched boost state."""
        if boost_state is not None:
            if not isinstance(boost_state, BoostState):
                raise RequestValidationError("boost_state must be a BoostState")
            if boost_state.ppid != charger.ppid:
                raise RequestValidationError(
                    "boost_state PPID must match the charger PPID"
                )

        async def operation():
            state = boost_state
            if state is None:
                state = await self._async_get_boost_state(charger)
            return basic_charging_mode_from_boost(state)
        return await self._call(
            charger, ChargerCapability.BASIC_CHARGING_MODE, operation
        )

    async def async_set_basic_charging_mode(
        self, charger: ChargerRef, mode: BasicChargingMode
    ) -> BasicChargingMode:
        """Set one of the two persistent Home basic charging modes."""
        if not isinstance(mode, BasicChargingMode):
            raise RequestValidationError("mode must be a BasicChargingMode")
        if mode not in (BasicChargingMode.SCHEDULED, BasicChargingMode.ALWAYS_ON):
            raise RequestValidationError(
                "only scheduled or always_on can be set as a persistent mode"
            )
        if charger.source is not ChargerSource.HOME:
            raise UnsupportedCapabilityError(
                ChargerCapability.BASIC_CHARGING_MODE, charger.ppid
            )

        async def operation():
            if mode is BasicChargingMode.ALWAYS_ON:
                await self._client.async_set_charger_charge_mode_always_on(charger.raw)
            else:
                await self._client.async_set_charger_charge_mode_scheduled(charger.raw)
            return mode
        return await self._call(
            charger, ChargerCapability.BASIC_CHARGING_MODE, operation
        )

    async def async_start_boost(
        self, charger: ChargerRef, hours: int = 0, minutes: int = 0, seconds: int = 0
    ) -> BoostState:
        """Start a timed boost using the charger's backing API."""
        async def operation():
            if charger.source is ChargerSource.HOME:
                items = await self._client.async_create_charger_charge_override(
                    charger.raw, hours=hours, minutes=minutes, seconds=seconds
                )
                return boost_state_from_home(charger.ppid, items[0] if items else None)
            override = await self._client.async_set_charge_override(
                charger.raw, hours=hours, minutes=minutes, seconds=seconds
            )
            return boost_state_from_legacy(charger.ppid, override)
        return await self._call(charger, ChargerCapability.TIMED_BOOST, operation)

    async def async_stop_boost(self, charger: ChargerRef) -> bool:
        """Stop active boosts using the charger's backing API."""
        async def operation():
            if charger.source is ChargerSource.HOME:
                return await self._client.async_delete_charger_charge_overrides(charger.raw)
            return await self._client.async_delete_charge_override(charger.raw)
        return await self._call(charger, ChargerCapability.TIMED_BOOST, operation)

    async def async_get_schedules(
        self, charger: ChargerRef, *, refresh: bool = False
    ) -> List[ChargerSchedule]:
        """Return canonical schedule entries using the charger's backing API."""
        async def operation():
            if charger.source is ChargerSource.HOME:
                schedules = await self._client.async_get_manual_schedules(charger.raw)
                return [charger_schedule_from_home(item) for item in schedules]
            pod = charger.raw
            if refresh and getattr(pod, "id", None) is not None:
                pod = await self._client.async_get_pod(pod.id)
            return [
                charger_schedule_from_legacy(item)
                for item in pod.charge_schedules
            ]
        return await self._call(charger, ChargerCapability.SCHEDULES, operation)

    async def async_replace_schedules(
        self, charger: ChargerRef, schedules: List[ChargerSchedule]
    ) -> List[ChargerSchedule]:
        """Replace all seven schedules through the full Home schedule API."""
        if not isinstance(schedules, list) or not all(
            isinstance(item, ChargerSchedule) for item in schedules
        ):
            raise RequestValidationError(
                "schedules must be a list of ChargerSchedule objects"
            )
        if charger.source is not ChargerSource.HOME:
            raise UnsupportedCapabilityError(
                ChargerCapability.FULL_SCHEDULE_REPLACEMENT, charger.ppid
            )

        async def operation():
            delegated_control = await self._client.async_get_delegated_control(
                charger.raw
            )
            status = (
                delegated_control.status if delegated_control is not None else None
            )
            if status != "INACTIVE":
                raise ChargeModeTransitionError(
                    "Schedules cannot be replaced while smart charging is active"
                )
            saved = await self._client.async_set_manual_schedules(
                charger.raw, [item.manual_dict for item in schedules]
            )
            return [charger_schedule_from_home(item) for item in saved]
        return await self._call(
            charger, ChargerCapability.FULL_SCHEDULE_REPLACEMENT, operation
        )

    async def async_get_legacy_schedules(
        self, charger: ChargerRef, *, refresh: bool = False
    ) -> List[Schedule]:
        """Return discovery schedules, optionally refreshing the legacy Pod."""
        async def operation():
            pod = charger.raw
            if refresh and getattr(pod, "id", None) is not None:
                pod = await self._client.async_get_pod(pod.id)
            return list(pod.charge_schedules)
        return await self._call(charger, ChargerCapability.LEGACY_SCHEDULING, operation)

    async def async_set_legacy_schedule(self, charger: ChargerRef, enabled: bool):
        """Enable or disable the existing all-week legacy schedule semantics."""
        async def operation():
            return await self._client.async_set_schedule(enabled=enabled, pod=charger.raw)
        return await self._call(charger, ChargerCapability.LEGACY_SCHEDULING, operation)

    async def async_get_manual_schedules(self, charger: ChargerRef):
        """Get Home manual/basic schedules."""
        async def operation():
            return await self._client.async_get_manual_schedules(charger.raw)
        return await self._call(charger, ChargerCapability.MANUAL_SCHEDULING, operation)

    async def async_replace_manual_schedules(self, charger: ChargerRef, schedules):
        """Replace Home manual/basic schedules."""
        async def operation():
            return await self._client.async_set_manual_schedules(charger.raw, schedules)
        return await self._call(charger, ChargerCapability.MANUAL_SCHEDULING, operation)

    async def async_get_smart_charging(self, charger: ChargerRef):
        """Get delegated smart-charging configuration."""
        async def operation():
            return await self._client.async_get_delegated_control(charger.raw)
        return await self._call(
            charger, ChargerCapability.DELEGATED_SMART_CHARGING, operation
        )

    async def async_set_smart_charging(self, charger: ChargerRef, enabled: bool):
        """Enable or disable delegated smart charging."""
        async def operation():
            return await self._client.async_set_charger_smart_charging(
                charger.raw, enabled
            )
        return await self._call(
            charger, ChargerCapability.DELEGATED_SMART_CHARGING, operation
        )

    async def async_get_smart_charging_preferences(self, charger: ChargerRef):
        """Get smart-charging preferences."""
        async def operation():
            return await self._client.async_get_smart_charging_preferences(charger.raw)
        return await self._call(
            charger, ChargerCapability.SMART_CHARGING_PREFERENCES, operation
        )

    async def async_set_smart_charging_max_price(
        self, charger: ChargerRef, max_price: float
    ):
        """Update the smart-charging maximum unit price."""
        async def operation():
            return await self._client.async_set_smart_charging_max_price(
                charger.raw, max_price
            )
        return await self._call(
            charger, ChargerCapability.SMART_CHARGING_PREFERENCES, operation
        )

    async def async_get_tariffs(self, charger: ChargerRef):
        """Get tariffs associated with a charger."""
        async def operation():
            return await self._client.async_get_tariffs(charger.raw)
        return await self._call(charger, ChargerCapability.TARIFFS, operation)

    async def async_get_remote_lock(self, charger: ChargerRef):
        """Get remote lock/off-mode state."""
        async def operation():
            return await self._client.async_get_remote_lock(charger.raw)
        return await self._call(charger, ChargerCapability.REMOTE_LOCK, operation)

    async def async_get_delegated_vehicles(self, charger: ChargerRef):
        """Fetch account vehicles once and return records matching this PPID."""
        groups = await self.async_get_delegated_vehicle_groups()
        return groups.get(charger.ppid, [])

    async def async_get_delegated_vehicle_groups(self):
        """Fetch account vehicles once and group records by canonical PPID."""
        async def operation():
            records = await self._client.async_get_delegated_vehicles()
            groups = {}
            for item in records:
                groups.setdefault(item.ppid, []).append(item)
            return groups
        return await self._call_account(AccountCapability.DELEGATED_VEHICLES, operation)

    async def async_get_charge_history(
        self, charger: ChargerRef, from_date: date, to_date: date
    ) -> List[ChargeSession]:
        """Compatibility wrapper returning completed sessions for one charger."""
        groups = await self.async_get_completed_charge_sessions(
            [charger], from_date, to_date
        )
        return groups.get(charger.ppid, [])

    async def async_get_charge_history_groups(
        self, chargers: List[ChargerRef], from_date: date, to_date: date
    ) -> Dict[str, List[ChargeSession]]:
        """Compatibility wrapper for grouped completed charge sessions."""
        return await self.async_get_completed_charge_sessions(
            chargers, from_date, to_date
        )

    async def async_get_completed_charge_sessions(
        self, chargers: List[ChargerRef], from_date: date, to_date: date
    ) -> Dict[str, List[ChargeSession]]:
        """Partition completed history by source and merge canonical results."""
        groups = {charger.ppid: [] for charger in chargers}
        if not chargers:
            return groups

        home_ppids = {
            charger.ppid for charger in chargers
            if charger.source is ChargerSource.HOME
        }
        legacy_ppids = {
            charger.ppid for charger in chargers
            if charger.source is ChargerSource.LEGACY
        }
        home_succeeded = False

        async def operation():
            history = await self._client.async_get_charge_history(from_date, to_date)
            for item in history.charges:
                if item.charger_id in home_ppids and item.ended_at is not None:
                    groups[item.charger_id].append(
                        charge_session_from_home(item.charger_id, item)
                    )
            return groups

        if home_ppids:
            try:
                await self._call_account(
                    AccountCapability.HOME_CHARGE_HISTORY, operation
                )
                home_succeeded = True
            except UnsupportedCapabilityError:
                legacy_ppids.update(home_ppids)

        if legacy_ppids:
            legacy_chargers = [
                charger for charger in chargers if charger.ppid in legacy_ppids
            ]
            try:
                legacy_groups = await self._async_get_legacy_completed_sessions(
                    legacy_chargers, from_date, to_date
                )
            except UnsupportedCapabilityError:
                if not home_succeeded:
                    raise
            else:
                for ppid, sessions in legacy_groups.items():
                    groups[ppid] = reconcile_charge_sessions(
                        groups[ppid], sessions
                    )

        for sessions in groups.values():
            sessions.sort(key=_session_sort_key)
        return groups

    async def async_get_live_charge_sessions(
        self,
        chargers: List[ChargerRef],
        *,
        per_page: int = 50,
        include_completed: bool = False,
    ) -> Dict[str, List[ChargeSession]]:
        """Get recent legacy provisional sessions grouped by canonical PPID."""
        if isinstance(per_page, bool) or not isinstance(per_page, int) or per_page < 1:
            raise RequestValidationError("per_page must be a positive integer")
        if not isinstance(include_completed, bool):
            raise RequestValidationError("include_completed must be a boolean")
        if not chargers:
            return {}

        async def operation():
            await self._async_resolve_legacy_identities(chargers)
            charges = await self._client.async_get_charges(
                perpage=per_page, page=1
            )
            return self._group_legacy_sessions(
                chargers, charges, include_completed=include_completed
            )
        return await self._call_account(AccountCapability.LEGACY_CHARGES, operation)

    async def _async_get_legacy_completed_sessions(
        self, chargers: List[ChargerRef], from_date: date, to_date: date
    ) -> Dict[str, List[ChargeSession]]:
        """Get date-filtered completed legacy charges once for fallback use."""
        async def operation():
            await self._async_resolve_legacy_identities(chargers)
            charges = await self._client.async_get_all_charges()
            groups = self._group_legacy_sessions(
                chargers, charges, include_completed=True
            )
            for ppid, sessions in groups.items():
                groups[ppid] = [
                    session for session in sessions
                    if not session.active
                    and session.started_at is not None
                    and from_date <= session.started_at.date() <= to_date
                ]
            return groups
        return await self._call_account(AccountCapability.LEGACY_CHARGES, operation)

    async def _async_resolve_legacy_identities(
        self, chargers: List[ChargerRef]
    ) -> None:
        """Resolve legacy Pod IDs to PPIDs once, without affecting discovery."""
        for charger in chargers:
            if charger.source is ChargerSource.LEGACY:
                pod_id = getattr(charger.raw, "id", None)
                if pod_id is not None:
                    self._legacy_ppid_by_pod_id[pod_id] = charger.ppid
                if charger.unit_id is not None:
                    self._legacy_ppid_by_unit_id[charger.unit_id] = charger.ppid
        known_ppids = (
            set(self._legacy_ppid_by_pod_id.values())
            | set(self._legacy_ppid_by_unit_id.values())
        )
        if all(charger.ppid in known_ppids for charger in chargers):
            return
        pods = await self._client.async_get_all_pods()
        for pod in pods:
            if not isinstance(pod.ppid, str) or not pod.ppid.strip():
                continue
            if pod.id is not None:
                self._legacy_ppid_by_pod_id[pod.id] = pod.ppid
            if pod.unit_id is not None:
                self._legacy_ppid_by_unit_id[pod.unit_id] = pod.ppid

    def _group_legacy_sessions(
        self,
        chargers: List[ChargerRef],
        charges: List[Charge],
        *,
        include_completed: bool,
    ) -> Dict[str, List[ChargeSession]]:
        """Normalize legacy charges and associate their pod identity with PPIDs."""
        groups = {charger.ppid: [] for charger in chargers}
        for charge in charges:
            if not include_completed and charge.ends_at is not None:
                continue
            if charge.ends_at is None:
                # Live legacy records use the unit ID in their nested pod shape.
                ppid = (
                    self._legacy_ppid_by_unit_id.get(charge.pod.id)
                    or self._legacy_ppid_by_pod_id.get(charge.pod.id)
                )
            else:
                # Historical legacy records traditionally use the pod ID.
                ppid = (
                    self._legacy_ppid_by_pod_id.get(charge.pod.id)
                    or self._legacy_ppid_by_unit_id.get(charge.pod.id)
                )
            if ppid in groups:
                groups[ppid].append(charge_session_from_legacy(ppid, charge))
        for sessions in groups.values():
            sessions.sort(key=_session_sort_key)
        return groups

    async def async_get_reward_wallet(self):
        """Get the account reward wallet with account-level capability semantics."""
        async def operation():
            return await self._client.async_get_reward_wallet()
        return await self._call_account(AccountCapability.REWARD_WALLET, operation)
