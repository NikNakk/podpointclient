"""Stable domain-level facade over legacy Pod and newer Home APIs."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from .charger import Charger
from .connectivity_status import ConnectivityStatus
from .connectivity_status_v2 import ConnectivityStatusV2
from .errors import (
    APIError, UnsupportedCapabilityError, is_unsupported_api_error,
)
from .pod import Pod


class ChargerSource(Enum):
    """Wire API which supplied a charger reference (diagnostics only)."""

    HOME = "home"
    LEGACY = "legacy"


class CapabilitySupport(Enum):
    """Knowledge state for a charger capability."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class ChargerCapability(Enum):
    """Features consumers can query without inspecting endpoint models."""

    CONNECTIVITY_STATE = "connectivity_state"
    TIMED_BOOST = "timed_boost"
    LEGACY_SCHEDULING = "legacy_scheduling"
    MANUAL_SCHEDULING = "manual_scheduling"
    DELEGATED_SMART_CHARGING = "delegated_smart_charging"
    SMART_CHARGING_PREFERENCES = "smart_charging_preferences"
    TARIFFS = "tariffs"
    REMOTE_LOCK = "remote_lock"
    DELEGATED_VEHICLES = "delegated_vehicles"
    CHARGE_HISTORY = "charge_history"
    FIRMWARE = "firmware"


class StateValue(Enum):
    """Normalized connectivity or charging value."""

    ONLINE = "online"
    OFFLINE = "offline"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
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


_HOME_CAPABILITIES = {
    capability: CapabilitySupport.SUPPORTED for capability in (
        ChargerCapability.CONNECTIVITY_STATE,
        ChargerCapability.TIMED_BOOST,
        ChargerCapability.MANUAL_SCHEDULING,
        ChargerCapability.DELEGATED_SMART_CHARGING,
        ChargerCapability.SMART_CHARGING_PREFERENCES,
        ChargerCapability.TARIFFS,
        ChargerCapability.REMOTE_LOCK,
        ChargerCapability.DELEGATED_VEHICLES,
        ChargerCapability.CHARGE_HISTORY,
    )
}
_HOME_CAPABILITIES.update({
    ChargerCapability.LEGACY_SCHEDULING: CapabilitySupport.UNSUPPORTED,
    ChargerCapability.FIRMWARE: CapabilitySupport.SUPPORTED,
})
_LEGACY_CAPABILITIES = {
    capability: CapabilitySupport.UNSUPPORTED for capability in ChargerCapability
}
_LEGACY_CAPABILITIES.update({
    ChargerCapability.CONNECTIVITY_STATE: CapabilitySupport.SUPPORTED,
    ChargerCapability.TIMED_BOOST: CapabilitySupport.SUPPORTED,
    ChargerCapability.LEGACY_SCHEDULING: CapabilitySupport.SUPPORTED,
    ChargerCapability.CHARGE_HISTORY: CapabilitySupport.SUPPORTED,
    ChargerCapability.FIRMWARE: CapabilitySupport.SUPPORTED,
})


@dataclass(frozen=True, eq=False)
# pylint: disable-next=too-many-instance-attributes
class ChargerRef:
    """Canonical charger identity and its explicitly known capabilities."""

    ppid: str
    unit_id: Optional[int]
    timezone: Optional[str]
    model_name: Optional[str]
    linked_at: Optional[datetime]
    source: ChargerSource
    raw: Union[Pod, Charger]
    capabilities: Dict[ChargerCapability, CapabilitySupport]

    def capability(self, capability: ChargerCapability) -> CapabilitySupport:
        """Return support knowledge without relying on missing values."""
        return self.capabilities.get(capability, CapabilitySupport.UNKNOWN)

    def __eq__(self, other: object) -> bool:
        """Compare canonical charger identity independently of its wire source."""
        if not isinstance(other, ChargerRef):
            return NotImplemented
        return self.ppid == other.ppid

    def __hash__(self) -> int:
        """Hash by stable cross-API PPID identity."""
        return hash(self.ppid)


def charger_ref_from_charger(charger: Charger) -> ChargerRef:
    """Adapt a Home Charger response without creating a synthetic Pod."""
    model = charger.model_info
    model_name = None
    if model is not None:
        model_name = " ".join(
            item for item in (model.architecture, model.style) if item
        ) or None
    capabilities = dict(_HOME_CAPABILITIES)
    if charger.unit_id is None:
        capabilities[ChargerCapability.FIRMWARE] = CapabilitySupport.UNKNOWN
    return ChargerRef(
        ppid=charger.ppid, unit_id=charger.unit_id, timezone=charger.timezone,
        model_name=model_name, linked_at=charger.linked_at,
        source=ChargerSource.HOME, raw=charger,
        capabilities=capabilities,
    )


def charger_ref_from_pod(pod: Pod) -> ChargerRef:
    """Adapt a legacy Pod response using PPID as canonical identity."""
    capabilities = dict(_LEGACY_CAPABILITIES)
    if pod.unit_id is None:
        capabilities[ChargerCapability.FIRMWARE] = CapabilitySupport.UNKNOWN
    return ChargerRef(
        ppid=pod.ppid, unit_id=pod.unit_id, timezone=pod.timezone,
        model_name=pod.model.name if pod.model is not None else None,
        linked_at=pod.commissioned_at, source=ChargerSource.LEGACY, raw=pod,
        capabilities=capabilities,
    )


class ChargerDomain:
    """High-level operations which hide endpoint selection from consumers."""

    def __init__(self, client: Any):
        self._client = client

    async def async_discover_chargers(self) -> List[ChargerRef]:
        """Discover via Home first, falling back only when it is unsupported."""
        get_chargers = getattr(self._client, "async_get_chargers", None)
        if get_chargers is not None:
            try:
                return [charger_ref_from_charger(item) for item in await get_chargers()]
            except APIError as error:
                if not is_unsupported_api_error(error):
                    raise
        return [charger_ref_from_pod(item) for item in await self._client.async_get_all_pods()]

    async def async_start_boost(self, charger: ChargerRef, hours: int = 0,
                                minutes: int = 0, seconds: int = 0):
        """Start a timed boost using the charger's backing API."""
        self._require(charger, ChargerCapability.TIMED_BOOST)
        if charger.source is ChargerSource.HOME:
            return await self._client.async_create_charger_charge_override(
                charger.raw, hours=hours, minutes=minutes, seconds=seconds)
        return await self._client.async_set_charge_override(
            charger.raw, hours=hours, minutes=minutes, seconds=seconds)

    async def async_stop_boost(self, charger: ChargerRef):
        """Stop active boosts using the charger's backing API."""
        self._require(charger, ChargerCapability.TIMED_BOOST)
        if charger.source is ChargerSource.HOME:
            return await self._client.async_delete_charger_charge_overrides(charger.raw)
        return await self._client.async_delete_charge_override(charger.raw)

    async def async_get_state(self, charger: ChargerRef) -> ChargerState:
        """Fetch and normalize connectivity and charging state."""
        self._require(charger, ChargerCapability.CONNECTIVITY_STATE)
        try:
            if charger.source is ChargerSource.HOME:
                status: ConnectivityStatusV2 = (
                    await self._client.async_get_connectivity_status_v2(charger.raw)
                )
                return ChargerState(normalize_state(status.connection_state),
                                    normalize_state(status.charging_state))
            status: ConnectivityStatus = (
                await self._client.async_get_connectivity_status(charger.raw)
            )
            return ChargerState(normalize_state(status.connectivity_status),
                                normalize_state(status.charging_state))
        except APIError as error:
            if is_unsupported_api_error(error):
                raise UnsupportedCapabilityError(
                    ChargerCapability.CONNECTIVITY_STATE, charger.ppid
                ) from error
            raise

    async def async_get_firmware(self, charger: ChargerRef):
        """Get firmware through the legacy unit endpoint for either source."""
        self._require(charger, ChargerCapability.FIRMWARE)
        if charger.unit_id is None:
            raise UnsupportedCapabilityError(
                ChargerCapability.FIRMWARE, charger.ppid
            )
        try:
            # Charger and Pod both carry the unit_id consumed by this endpoint;
            # no synthetic low-level Pod is needed for Home chargers.
            return await self._client.async_get_firmware(charger.raw)
        except APIError as error:
            if is_unsupported_api_error(error):
                raise UnsupportedCapabilityError(
                    ChargerCapability.FIRMWARE, charger.ppid
                ) from error
            raise

    @staticmethod
    def _require(charger: ChargerRef, capability: ChargerCapability) -> None:
        if charger.capability(capability) is CapabilitySupport.UNSUPPORTED:
            raise UnsupportedCapabilityError(capability, charger.ppid)
