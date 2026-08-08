"""Tests for the API-independent charger domain facade."""

from datetime import date, datetime, timezone
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from podpointclient.charge import Charge
from podpointclient.charge_history import ChargeHistory, ChargeHistoryItem
from podpointclient.charge_override import ChargeOverride
from podpointclient.charger import Charger
from podpointclient.charger_charge_override import ChargerChargeOverride
from podpointclient.client import PodPointClient
from podpointclient.connectivity_status_v2 import ConnectivityStatusV2
from podpointclient.domain import (
    AccountCapability, CapabilitySupport, ChargerCapability, ChargerDomain,
    ChargerIdentityError, ChargerSource, StateValue, boost_state_from_home,
    boost_state_from_legacy, charger_ref_from_charger, charger_ref_from_pod,
    charge_session_from_home, charge_session_from_legacy, normalize_state,
)
from podpointclient.errors import (
    APIError, ApiConnectionError, AuthError, SessionError,
    UnsupportedCapabilityError, api_error_status,
)
from podpointclient.pod import Pod


def home_charger(ppid="HOME-1", unit_id=12):
    return Charger({
        "ppid": ppid, "unitId": unit_id, "timezone": "Europe/London",
        "linkedAt": "2025-01-01T00:00:00Z",
        "modelInfo": {"architecture": "arch5", "style": "SOCKETED"},
    })


def legacy_pod(ppid="LEGACY-1", pod_id=2, unit_id=34):
    return Pod({
        "id": pod_id, "ppid": ppid, "unit_id": unit_id,
        "timezone": "Europe/London", "commissioned_at": "2024-01-01T00:00:00Z",
        "model": {"name": "Solo 3"},
    })


def home_ref(ppid="HOME-1"):
    return charger_ref_from_charger(home_charger(ppid))


def legacy_ref(ppid="LEGACY-1"):
    return charger_ref_from_pod(legacy_pod(ppid))


@pytest.mark.asyncio
async def test_home_first_discovery_multiple_chargers_and_retained_state():
    client = AsyncMock()
    client.async_get_chargers.return_value = [home_charger("A"), home_charger("B")]
    domain = ChargerDomain(client)

    first = await domain.async_discover_chargers()
    client.async_get_connectivity_status_v2.return_value = ConnectivityStatusV2({
        "connectionState": "ONLINE", "chargingState": "IDLE"
    })
    await domain.async_get_state(first[0])
    second = await domain.async_discover_chargers()

    assert [item.ppid for item in first] == ["A", "B"]
    assert second[0].capability(ChargerCapability.CONNECTIVITY_STATE) is (
        CapabilitySupport.SUPPORTED
    )
    client.async_get_all_pods.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 410])
async def test_discovery_falls_back_only_for_absent_home_endpoint(status):
    client = AsyncMock()
    client.async_get_chargers.side_effect = APIError(status, "omitted")
    client.async_get_all_pods.return_value = [legacy_pod()]
    refs = await ChargerDomain(client).async_discover_chargers()
    assert refs[0].ppid == "LEGACY-1"


@pytest.mark.asyncio
async def test_discovery_falls_back_when_home_method_is_unavailable():
    client = SimpleNamespace(async_get_all_pods=AsyncMock(return_value=[legacy_pod()]))
    refs = await ChargerDomain(client).async_discover_chargers()
    assert refs[0].ppid == "LEGACY-1"


@pytest.mark.asyncio
async def test_discovery_rejects_missing_ppid_without_legacy_fallback():
    client = AsyncMock()
    client.async_get_chargers.return_value = [home_charger(None)]
    with pytest.raises(ChargerIdentityError):
        await ChargerDomain(client).async_discover_chargers()
    client.async_get_all_pods.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    APIError(401, "omitted"), APIError(429, "omitted"), APIError(500, "omitted"),
    AuthError(401, "omitted"), SessionError(401, "omitted"),
    ApiConnectionError("offline"),
])
async def test_discovery_does_not_mask_other_errors(error):
    client = AsyncMock()
    client.async_get_chargers.side_effect = error
    with pytest.raises(type(error)):
        await ChargerDomain(client).async_discover_chargers()
    client.async_get_all_pods.assert_not_awaited()


def test_identity_is_validated_and_stable_across_sources():
    with pytest.raises(ChargerIdentityError):
        charger_ref_from_charger(home_charger(None))
    with pytest.raises(ChargerIdentityError):
        charger_ref_from_pod(legacy_pod(""))
    home = home_ref("SAME")
    legacy = legacy_ref("SAME")
    assert home == legacy and hash(home) == hash(legacy)


def test_capability_initial_state_and_immutable_snapshot():
    home = home_ref()
    legacy = legacy_ref()
    assert home.capability(ChargerCapability.TARIFFS) is CapabilitySupport.UNKNOWN
    assert home.capability(ChargerCapability.LEGACY_SCHEDULING) is (
        CapabilitySupport.UNSUPPORTED
    )
    assert legacy.capability(ChargerCapability.MANUAL_SCHEDULING) is (
        CapabilitySupport.UNSUPPORTED
    )
    assert isinstance(home.capabilities, MappingProxyType)
    with pytest.raises(TypeError):
        home.capabilities[ChargerCapability.TARIFFS] = CapabilitySupport.SUPPORTED


@pytest.mark.asyncio
async def test_capability_success_and_unsupported_are_retained():
    client = AsyncMock()
    client.async_get_tariffs.return_value = ["tariff"]
    charger = home_ref()
    domain = ChargerDomain(client)

    assert await domain.async_get_tariffs(charger) == ["tariff"]
    assert charger.capability(ChargerCapability.TARIFFS) is CapabilitySupport.SUPPORTED

    client.async_get_remote_lock.side_effect = APIError(410, "gone")
    with pytest.raises(UnsupportedCapabilityError) as raised:
        await domain.async_get_remote_lock(charger)
    assert raised.value.ppid == charger.ppid
    assert raised.value.capability is ChargerCapability.REMOTE_LOCK
    assert charger.capability(ChargerCapability.REMOTE_LOCK) is CapabilitySupport.UNSUPPORTED
    await_count = client.async_get_remote_lock.await_count
    with pytest.raises(UnsupportedCapabilityError):
        await domain.async_get_remote_lock(charger)
    assert client.async_get_remote_lock.await_count == await_count


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    APIError(401, "omitted"), APIError(429, "omitted"), APIError(500, "omitted"),
    AuthError(401, "omitted"), SessionError(401, "omitted"),
    ApiConnectionError("offline"),
])
async def test_other_errors_leave_capability_unknown(error):
    client = AsyncMock()
    client.async_get_tariffs.side_effect = error
    charger = home_ref()
    with pytest.raises(type(error)):
        await ChargerDomain(client).async_get_tariffs(charger)
    assert charger.capability(ChargerCapability.TARIFFS) is CapabilitySupport.UNKNOWN


def test_client_domain_is_stable():
    client = object.__new__(PodPointClient)
    client._domain = None
    assert client.domain is client.domain


@pytest.mark.parametrize(("raw", "expected"), [
    ("ONLINE", StateValue.ONLINE), ("offline", StateValue.OFFLINE),
    ("Available", StateValue.AVAILABLE), ("idle", StateValue.IDLE),
    ("UNAVAILABLE", StateValue.UNAVAILABLE),
    ("OutOfService", StateValue.OUT_OF_SERVICE),
    ("out of service", StateValue.OUT_OF_SERVICE),
    ("Charging", StateValue.CHARGING),
    ("SuspendedEV", StateValue.SUSPENDED_EV),
    ("SuspendedEVSE", StateValue.SUSPENDED_EVSE),
    ("suspended-evse", StateValue.SUSPENDED_EVSE),
    ("PREPARING", StateValue.PREPARING), ("finishing", StateValue.FINISHING),
    ("Faulted", StateValue.FAULTED), (None, None),
    ("FUTURE_QUANTUM_STATE", StateValue.UNKNOWN),
])
def test_state_normalization(raw, expected):
    result = normalize_state(raw)
    assert result.value is expected and result.raw == raw


@pytest.mark.asyncio
async def test_state_and_firmware_use_capability_lifecycle():
    client = AsyncMock()
    charger = home_ref()
    client.async_get_connectivity_status_v2.return_value = ConnectivityStatusV2({
        "connectionState": "Online", "chargingState": "OutOfService"
    })
    client.async_get_firmware.return_value = ["firmware"]
    domain = ChargerDomain(client)
    state = await domain.async_get_state(charger)
    assert state.charging.value is StateValue.OUT_OF_SERVICE
    assert await domain.async_get_firmware(charger) == ["firmware"]
    assert charger.capability(ChargerCapability.FIRMWARE) is CapabilitySupport.SUPPORTED


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "low_level", "capability"), [
    ("async_get_state", "async_get_connectivity_status_v2",
     ChargerCapability.CONNECTIVITY_STATE),
    ("async_get_firmware", "async_get_firmware", ChargerCapability.FIRMWARE),
])
async def test_state_and_firmware_translate_confirmed_absence(
    method, low_level, capability
):
    client = AsyncMock()
    getattr(client, low_level).side_effect = APIError(404, "missing")
    charger = home_ref()
    with pytest.raises(UnsupportedCapabilityError):
        await getattr(ChargerDomain(client), method)(charger)
    assert charger.capability(capability) is CapabilitySupport.UNSUPPORTED


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 410])
async def test_boost_absence_is_typed_and_retained(status):
    client = AsyncMock()
    client.async_create_charger_charge_override.side_effect = APIError(status, "gone")
    charger = home_ref()
    domain = ChargerDomain(client)
    with pytest.raises(UnsupportedCapabilityError):
        await domain.async_start_boost(charger, minutes=5)
    assert charger.capability(ChargerCapability.TIMED_BOOST) is (
        CapabilitySupport.UNSUPPORTED
    )
    with pytest.raises(UnsupportedCapabilityError):
        await domain.async_stop_boost(charger)
    client.async_delete_charger_charge_overrides.assert_not_awaited()


@pytest.mark.asyncio
async def test_boost_dispatch_and_canonical_results_for_both_sources():
    client = AsyncMock()
    home_model = home_charger()
    legacy_model = legacy_pod()
    home = charger_ref_from_charger(home_model)
    legacy = charger_ref_from_pod(legacy_model)
    home_override = ChargerChargeOverride({
        "id": "H-1", "requestedAt": "2026-08-01T10:00:00Z",
        "receivedAt": "2026-08-01T10:00:01Z", "endAt": "2026-08-01T11:00:00Z",
        "chargingStation": {"ppid": home.ppid},
    })
    legacy_override = ChargeOverride({
        "ppid": legacy.ppid, "requested_at": "2026-08-01T10:00:00Z",
        "received_at": "2026-08-01T10:00:01Z", "ends_at": "2999-08-01T11:00:00Z",
    })
    client.async_create_charger_charge_override.return_value = [home_override]
    client.async_set_charge_override.return_value = legacy_override
    client.async_get_charger_charge_overrides.return_value = []
    client.async_delete_charger_charge_overrides.return_value = True
    client.async_delete_charge_override.return_value = True
    domain = ChargerDomain(client)

    home_state = await domain.async_start_boost(home, hours=1)
    legacy_state = await domain.async_start_boost(legacy, minutes=30)
    inactive = await domain.async_get_active_boost(home)
    assert await domain.async_stop_boost(home)
    assert await domain.async_stop_boost(legacy)

    assert home_state.timed and home_state.source_id == "H-1"
    assert legacy_state.active and legacy_state.timed
    assert not inactive.active
    client.async_create_charger_charge_override.assert_awaited_once_with(
        home_model, hours=1, minutes=0, seconds=0
    )
    client.async_set_charge_override.assert_awaited_once_with(
        legacy_model, hours=0, minutes=30, seconds=0
    )
    client.async_delete_charger_charge_overrides.assert_awaited_once_with(home_model)
    client.async_delete_charge_override.assert_awaited_once_with(legacy_model)


def test_override_converters_cover_open_ended_and_empty():
    legacy = ChargeOverride({
        "ppid": "P", "requested_at": "2026-01-01T00:00:00Z",
        "received_at": "2026-01-01T00:00:01Z", "ends_at": None,
    })
    home = ChargerChargeOverride({
        "id": "H", "requestedAt": "2026-01-01T00:00:00Z",
        "chargingStation": {"ppid": "P"},
    })
    assert boost_state_from_legacy("P", legacy).active
    assert not boost_state_from_legacy("P", legacy).timed
    assert boost_state_from_home("P", home).active
    assert not boost_state_from_home("P", home).timed
    assert not boost_state_from_home("P", None).active


@pytest.mark.asyncio
async def test_schedule_smart_preferences_tariff_and_lock_operations():
    client = AsyncMock()
    home_model = home_charger()
    legacy_model = legacy_pod()
    home = charger_ref_from_charger(home_model)
    legacy = charger_ref_from_pod(legacy_model)
    refreshed_pod = legacy_model
    refreshed_pod.charge_schedules = ["legacy schedule"]
    client.async_get_pod.return_value = refreshed_pod
    client.async_get_manual_schedules.return_value = ["manual schedule"]
    client.async_set_manual_schedules.return_value = ["saved schedule"]
    client.async_get_delegated_control.return_value = "control"
    client.async_set_charger_smart_charging.return_value = True
    client.async_get_smart_charging_preferences.return_value = "preferences"
    client.async_set_smart_charging_max_price.return_value = True
    client.async_get_tariffs.return_value = ["tariff"]
    client.async_get_remote_lock.return_value = "lock"
    domain = ChargerDomain(client)

    assert await domain.async_get_legacy_schedules(legacy) == ["legacy schedule"]
    assert await domain.async_get_manual_schedules(home) == ["manual schedule"]
    assert await domain.async_replace_manual_schedules(home, ["input"]) == ["saved schedule"]
    assert await domain.async_get_smart_charging(home) == "control"
    assert await domain.async_set_smart_charging(home, True)
    assert await domain.async_get_smart_charging_preferences(home) == "preferences"
    assert await domain.async_set_smart_charging_max_price(home, 0.2)
    assert await domain.async_get_tariffs(home) == ["tariff"]
    assert await domain.async_get_remote_lock(home) == "lock"
    client.async_get_manual_schedules.assert_awaited_with(home_model)
    client.async_get_delegated_control.assert_awaited_with(home_model)
    client.async_get_tariffs.assert_awaited_with(home_model)
    client.async_get_remote_lock.assert_awaited_with(home_model)


@pytest.mark.asyncio
async def test_structurally_impossible_operation_never_calls_endpoint():
    client = AsyncMock()
    with pytest.raises(UnsupportedCapabilityError):
        await ChargerDomain(client).async_get_tariffs(legacy_ref())
    client.async_get_tariffs.assert_not_awaited()


@pytest.mark.asyncio
async def test_account_capabilities_group_vehicles_and_wallet():
    client = AsyncMock()
    charger = home_ref()
    client.async_get_delegated_vehicles.return_value = [
        SimpleNamespace(ppid=charger.ppid), SimpleNamespace(ppid="OTHER")
    ]
    client.async_get_reward_wallet.return_value = "wallet"
    domain = ChargerDomain(client)
    records = await domain.async_get_delegated_vehicles(charger)
    assert len(records) == 1
    assert await domain.async_get_reward_wallet() == "wallet"
    assert domain.account_capability(AccountCapability.DELEGATED_VEHICLES) is (
        CapabilitySupport.SUPPORTED
    )
    assert domain.account_capability(AccountCapability.REWARD_WALLET) is (
        CapabilitySupport.SUPPORTED
    )


@pytest.mark.asyncio
async def test_account_vehicle_groups_fetch_once_for_multiple_chargers():
    client = AsyncMock()
    client.async_get_delegated_vehicles.return_value = [
        SimpleNamespace(ppid="A"), SimpleNamespace(ppid="B")
    ]
    groups = await ChargerDomain(client).async_get_delegated_vehicle_groups()
    assert set(groups) == {"A", "B"}
    client.async_get_delegated_vehicles.assert_awaited_once()


@pytest.mark.asyncio
async def test_account_unsupported_is_retained_without_ppid():
    client = AsyncMock()
    client.async_get_reward_wallet.side_effect = APIError(404, "missing")
    domain = ChargerDomain(client)
    with pytest.raises(UnsupportedCapabilityError) as raised:
        await domain.async_get_reward_wallet()
    assert raised.value.ppid is None
    assert raised.value.capability is AccountCapability.REWARD_WALLET
    with pytest.raises(UnsupportedCapabilityError):
        await domain.async_get_reward_wallet()
    assert client.async_get_reward_wallet.await_count == 1


@pytest.mark.asyncio
async def test_account_unexpected_error_keeps_unknown_support():
    client = AsyncMock()
    client.async_get_reward_wallet.side_effect = APIError(500, "failed")
    domain = ChargerDomain(client)
    with pytest.raises(APIError):
        await domain.async_get_reward_wallet()
    assert domain.account_capability(AccountCapability.REWARD_WALLET) is (
        CapabilitySupport.UNKNOWN
    )


def test_canonical_charge_session_converters_preserve_correlation():
    legacy = Charge({
        "id": 1, "starts_at": "2026-08-01T10:00:00Z", "ends_at": None,
        "kwh_used": 3.2, "duration": 1200,
        "billing_event": {"amount": 0.3, "currency": "GBP"},
    })
    home = ChargeHistoryItem({
        "id": "H-1", "startedAt": "2026-08-01T10:00:00Z",
        "endedAt": "2026-08-01T11:00:00Z", "duration": 3600,
        "energyTotal": 7.2, "cost": {"amount": 0.5, "currency": "GBP"},
        "charger": {"id": "P"},
    })
    provisional = charge_session_from_legacy("P", legacy)
    completed = charge_session_from_home("P", home)
    assert provisional.active and not completed.active
    assert provisional.correlation_key == completed.correlation_key
    assert completed.energy_kwh == 7.2 and completed.currency == "GBP"


@pytest.mark.asyncio
async def test_home_and_legacy_charge_history_are_attributed_and_filtered():
    client = AsyncMock()
    home = home_ref("HOME")
    legacy = charger_ref_from_pod(legacy_pod("LEGACY", pod_id=22))
    home_item = ChargeHistoryItem({
        "id": "H", "startedAt": "2026-08-01T10:00:00Z",
        "charger": {"id": "HOME"},
    })
    other_item = ChargeHistoryItem({
        "id": "O", "startedAt": "2026-08-01T10:00:00Z",
        "charger": {"id": "OTHER"},
    })
    client.async_get_charge_history.return_value = ChargeHistory({
        "data": {"count": 2, "charges": [home_item.dict, other_item.dict]}
    })
    domain = ChargerDomain(client)
    home_sessions = await domain.async_get_charge_history(
        home, date(2026, 8, 1), date(2026, 8, 2)
    )
    assert [item.ppid for item in home_sessions] == ["HOME"]

    legacy_charge = Charge({
        "id": 3, "starts_at": "2026-08-01T10:00:00Z", "pod": {"id": 22}
    })
    other_charge = Charge({
        "id": 4, "starts_at": "2026-08-01T10:00:00Z", "pod": {"id": 99}
    })
    client.async_get_all_charges.return_value = [legacy_charge, other_charge]
    legacy_sessions = await domain.async_get_charge_history(
        legacy, date(2026, 8, 1), date(2026, 8, 2)
    )
    assert [item.session_id for item in legacy_sessions] == ["3"]


@pytest.mark.asyncio
async def test_home_history_groups_multiple_chargers_with_one_account_call():
    client = AsyncMock()
    chargers = [home_ref("A"), home_ref("B")]
    client.async_get_charge_history.return_value = ChargeHistory({
        "data": {"count": 2, "charges": [
            {"id": "1", "startedAt": "2026-08-01T10:00:00Z",
             "charger": {"id": "A"}},
            {"id": "2", "startedAt": "2026-08-01T11:00:00Z",
             "charger": {"id": "B"}},
        ]}
    })
    groups = await ChargerDomain(client).async_get_charge_history_groups(
        chargers, date(2026, 8, 1), date(2026, 8, 2)
    )
    assert groups["A"][0].session_id == "1"
    assert groups["B"][0].session_id == "2"
    client.async_get_charge_history.assert_awaited_once()


def test_api_error_status_is_reliable_for_new_and_legacy_shapes():
    assert api_error_status(APIError(410, "omitted")) == 410
    assert api_error_status(APIError("API failed (404)")) == 404
    assert api_error_status(APIError("transport failed")) is None
