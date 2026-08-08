"""Stable domain-level facade over legacy Pod and newer Home APIs."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
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
from .errors import APIError, UnsupportedCapabilityError, is_unsupported_api_error
from .pod import Pod


class ChargerIdentityError(ValueError):
    """Raised when a low-level object has no usable canonical PPID."""


class ChargerSource(Enum):
    """Wire API which supplied a charger reference (diagnostics only)."""

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

class AccountCapability(Enum):
    """Features fetched once at account scope and optionally grouped by PPID."""

    DELEGATED_VEHICLES = "delegated_vehicles"
    CHARGE_HISTORY = "charge_history"
    REWARD_WALLET = "reward_wallet"


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
class ChargerState:
    """API-independent connectivity and charging state."""

    connection: NormalizedStateValue
    charging: NormalizedStateValue


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
        correlation_key=_correlation_key(ppid, charge.starts_at), raw=charge,
    )


def charge_session_from_home(ppid: str, charge: ChargeHistoryItem) -> ChargeSession:
    """Normalize one Home account-history charge."""
    return ChargeSession(
        ppid=ppid, session_id=str(charge.id) if charge.id is not None else None,
        started_at=charge.started_at, ended_at=charge.ended_at,
        active=charge.ended_at is None, energy_kwh=charge.energy_total,
        duration_seconds=charge.duration, cost=charge.cost.amount,
        currency=charge.cost.currency,
        correlation_key=_correlation_key(ppid, charge.started_at), raw=charge,
    )


class ChargerDomain:  # pylint: disable=too-many-public-methods
    """High-level operations which hide endpoint selection from consumers."""

    def __init__(self, client: Any):
        self._client = client
        self._charger_states: Dict[Any, _CapabilityState] = {}
        self._account_state = _CapabilityState({
            capability: CapabilitySupport.UNKNOWN for capability in AccountCapability
        })

    def account_capability(self, capability: AccountCapability) -> CapabilitySupport:
        """Return the observed support state of an account-level feature."""
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

    async def async_discover_chargers(self) -> List[ChargerRef]:
        """Discover via Home first, falling back only when it is unsupported."""
        get_chargers = getattr(self._client, "async_get_chargers", None)
        if callable(get_chargers):
            try:
                chargers = await get_chargers()
                return [
                    charger_ref_from_charger(
                        item, self._state(item.ppid, ChargerSource.HOME, item.unit_id)
                    ) for item in chargers
                ]
            except NotImplementedError:
                pass
            except APIError as error:
                if not is_unsupported_api_error(error):
                    raise
        pods = await self._client.async_get_all_pods()
        return [
            charger_ref_from_pod(
                item, self._state(item.ppid, ChargerSource.LEGACY, item.unit_id)
            ) for item in pods
        ]

    async def async_get_state(self, charger: ChargerRef) -> ChargerState:
        """Fetch and normalize connectivity and charging state."""
        async def operation():
            if charger.source is ChargerSource.HOME:
                status: ConnectivityStatusV2 = (
                    await self._client.async_get_connectivity_status_v2(charger.raw)
                )
                connection = status.connection_state if status else None
                charging = status.charging_state if status else None
            else:
                status: ConnectivityStatus = (
                    await self._client.async_get_connectivity_status(charger.raw)
                )
                connection = status.connectivity_status if status else None
                charging = status.charging_state if status else None
            return ChargerState(normalize_state(connection), normalize_state(charging))
        return await self._call(charger, ChargerCapability.CONNECTIVITY_STATE, operation)

    async def async_get_firmware(self, charger: ChargerRef):
        """Get firmware through the legacy unit endpoint for either source."""
        async def operation():
            return await self._client.async_get_firmware(charger.raw)
        return await self._call(charger, ChargerCapability.FIRMWARE, operation)

    async def async_get_active_boost(self, charger: ChargerRef) -> BoostState:
        """Return canonical active/inactive override state."""
        async def operation():
            if charger.source is ChargerSource.HOME:
                items = await self._client.async_get_charger_charge_overrides(
                    charger.raw, active_only=True
                )
                return boost_state_from_home(charger.ppid, items[0] if items else None)
            override = await self._client.async_get_charge_override(charger.raw)
            return boost_state_from_legacy(charger.ppid, override)
        return await self._call(charger, ChargerCapability.TIMED_BOOST, operation)

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

    async def async_get_legacy_schedules(self, charger: ChargerRef):
        """Return legacy schedule models for a legacy charger."""
        async def operation():
            pod = charger.raw
            if getattr(pod, "id", None) is not None:
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
        """Fetch account history and return canonical sessions for one charger."""
        groups = await self.async_get_charge_history_groups(
            [charger], from_date, to_date
        )
        return groups.get(charger.ppid, [])

    async def async_get_charge_history_groups(
        self, chargers: List[ChargerRef], from_date: date, to_date: date
    ) -> Dict[str, List[ChargeSession]]:
        """Fetch each account history API once and group sessions by PPID."""
        async def operation():
            groups = {charger.ppid: [] for charger in chargers}
            home_chargers = {
                charger.ppid: charger for charger in chargers
                if charger.source is ChargerSource.HOME
            }
            if home_chargers:
                history = await self._client.async_get_charge_history(from_date, to_date)
                for item in history.charges:
                    if item.charger_id in home_chargers:
                        groups[item.charger_id].append(
                            charge_session_from_home(item.charger_id, item)
                        )
            legacy_by_id = {}
            for charger in chargers:
                pod_id = getattr(charger.raw, "id", None)
                if charger.source is ChargerSource.LEGACY and pod_id is not None:
                    legacy_by_id[pod_id] = charger
            if legacy_by_id:
                charges = await self._client.async_get_all_charges()
                for item in charges:
                    charger = legacy_by_id.get(item.pod.id)
                    if charger is None:
                        continue
                    if item.starts_at is not None and not (
                        from_date <= item.starts_at.date() <= to_date
                    ):
                        continue
                    groups[charger.ppid].append(
                        charge_session_from_legacy(charger.ppid, item)
                    )
            return groups
        return await self._call_account(AccountCapability.CHARGE_HISTORY, operation)

    async def async_get_reward_wallet(self):
        """Get the account reward wallet with account-level capability semantics."""
        async def operation():
            return await self._client.async_get_reward_wallet()
        return await self._call_account(AccountCapability.REWARD_WALLET, operation)
