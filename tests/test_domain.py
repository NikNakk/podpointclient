"""Tests for the API-independent charger domain facade."""

from datetime import date, datetime, timedelta, timezone
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from podpointclient.charge import Charge
from podpointclient.charge_history import ChargeHistory, ChargeHistoryItem
from podpointclient.charge_override import ChargeOverride
from podpointclient.charger import Charger
from podpointclient.charger_charge_override import ChargerChargeOverride
from podpointclient.client import PodPointClient
from podpointclient.connectivity_status import ConnectivityStatus
from podpointclient.connectivity_status_v2 import ConnectivityStatusV2
from podpointclient.domain import (
    AccountCapability, BasicChargingMode, BoostState, CapabilitySupport, ChargeSession,
    ChargeSessionSource, ChargerCapability, ChargerDomain, ChargerIdentityError,
    ChargerSchedule, ChargerSource, ConnectionQualityDiagnostic, StateValue,
    basic_charging_mode_from_boost, boost_state_from_home,
    boost_state_from_legacy, charger_ref_from_charger, charger_ref_from_pod,
    charge_session_from_home, charge_session_from_legacy,
    charger_schedule_from_home, charger_schedule_from_legacy, normalize_state,
    reconcile_charge_sessions,
)
from podpointclient.errors import (
    APIError, ApiConnectionError, AuthError, ChargeModeTransitionError,
    RequestValidationError, SessionError, UnsupportedCapabilityError,
    api_error_status,
)
from podpointclient.pod import Pod
from podpointclient.manual_schedule import ManualSchedule
from podpointclient.schedule import Schedule, ScheduleStatus


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
async def test_legacy_preferred_discovery_creates_legacy_refs_without_home_call():
    client = AsyncMock()
    client.async_get_all_pods.return_value = [legacy_pod("A"), legacy_pod("B")]

    refs = await ChargerDomain(client).async_discover_chargers(
        ChargerSource.LEGACY
    )

    assert [item.ppid for item in refs] == ["A", "B"]
    assert all(item.source is ChargerSource.LEGACY for item in refs)
    assert all(isinstance(item.raw, Pod) for item in refs)
    client.async_get_chargers.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 410])
async def test_legacy_preference_falls_back_to_home_only_when_absent(status):
    client = AsyncMock()
    client.async_get_all_pods.side_effect = APIError(status, "omitted")
    client.async_get_chargers.return_value = [home_charger()]

    refs = await ChargerDomain(client).async_discover_chargers(
        ChargerSource.LEGACY
    )

    assert refs[0].source is ChargerSource.HOME


@pytest.mark.asyncio
async def test_legacy_preference_does_not_mask_other_errors():
    client = AsyncMock()
    client.async_get_all_pods.side_effect = APIError(500, "failed")

    with pytest.raises(APIError):
        await ChargerDomain(client).async_discover_chargers(
            ChargerSource.LEGACY
        )
    client.async_get_chargers.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovery_rejects_invalid_preferred_protocol():
    with pytest.raises(TypeError, match="preferred_protocol"):
        await ChargerDomain(AsyncMock()).async_discover_chargers("legacy")


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
        "connectionState": "Online",
        "chargingState": "OutOfService",
        "connectionQuality": 3,
        "lastSeenAt": "2026-08-08T10:00:00Z",
    })
    client.async_get_firmware.return_value = ["firmware"]
    domain = ChargerDomain(client)
    state = await domain.async_get_state(charger)
    assert state.charging.value is StateValue.OUT_OF_SERVICE
    assert state.last_seen_at == datetime(2026, 8, 8, 10, tzinfo=timezone.utc)
    assert state.signal_strength_dbm is None
    assert state.connection_quality == ConnectionQualityDiagnostic(
        raw=3, source=ChargerSource.HOME
    )
    assert await domain.async_get_firmware(charger) == ["firmware"]
    assert charger.capability(ChargerCapability.FIRMWARE) is CapabilitySupport.SUPPORTED


@pytest.mark.asyncio
async def test_legacy_state_preserves_source_specific_diagnostics():
    client = AsyncMock()
    client.async_get_connectivity_status.return_value = ConnectivityStatus({
        "evses": [{
            "connectivityState": {
                "connectivityStatus": "ONLINE",
                "signalStrength": -68,
                "lastMessageAt": "2026-08-08T10:00:00Z",
                "connectionQuality": 4,
            },
            "connectors": [{"chargingState": "CHARGING"}],
        }]
    })

    state = await ChargerDomain(client).async_get_state(legacy_ref())

    assert state.connection.value is StateValue.ONLINE
    assert state.charging.value is StateValue.CHARGING
    assert state.last_seen_at == datetime(2026, 8, 8, 10, tzinfo=timezone.utc)
    assert state.signal_strength_dbm == -68
    assert state.connection_quality == ConnectionQualityDiagnostic(
        raw=4, source=ChargerSource.LEGACY
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("charger", "method", "status"),
    [
        (home_ref(), "async_get_connectivity_status_v2", ConnectivityStatusV2({})),
        (legacy_ref(), "async_get_connectivity_status", ConnectivityStatus({})),
    ],
)
async def test_state_diagnostics_are_optional(charger, method, status):
    client = AsyncMock()
    getattr(client, method).return_value = status

    state = await ChargerDomain(client).async_get_state(charger)

    assert state.last_seen_at is None
    assert state.signal_strength_dbm is None
    assert state.connection_quality is None


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
    legacy_model.charge_schedules = ["legacy schedule"]
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
    client.async_get_pod.assert_not_awaited()
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


def test_canonical_schedule_normalizes_both_apis_and_ignores_uid_for_equality():
    home = ManualSchedule({
        "uid": "HOME-UID", "startDay": 5, "startTime": "23:00:00",
        "endDay": 6, "endTime": "06:00:00", "status": {"isActive": True},
    })
    legacy = Schedule(
        uid="LEGACY-UID", start_day=5, start_time="23:00:00",
        end_day=6, end_time="06:00:00", status=ScheduleStatus(is_active=True),
    )

    normalized_home = charger_schedule_from_home(home)
    normalized_legacy = charger_schedule_from_legacy(legacy)

    assert normalized_home == normalized_legacy
    assert normalized_home.uid == "HOME-UID"
    assert normalized_legacy.uid == "LEGACY-UID"
    assert normalized_home.manual_dict == {
        "uid": "HOME-UID", "startDay": 5, "startTime": "23:00:00",
        "endDay": 6, "endTime": "06:00:00", "status": {"isActive": True},
    }


@pytest.mark.asyncio
async def test_canonical_schedule_reads_dispatch_and_normalize():
    client = AsyncMock()
    home_model = home_charger()
    legacy_model = legacy_pod()
    home_item = ManualSchedule({
        "uid": "H", "startDay": 1, "startTime": "01:00:00",
        "endDay": 1, "endTime": "02:00:00", "status": {"isActive": True},
    })
    legacy_item = Schedule(
        uid="L", start_day=2, start_time="03:00:00", end_day=2,
        end_time="04:00:00", status=ScheduleStatus(is_active=False),
    )
    legacy_model.charge_schedules = [legacy_item]
    client.async_get_manual_schedules.return_value = [home_item]
    domain = ChargerDomain(client)

    home_result = await domain.async_get_schedules(
        charger_ref_from_charger(home_model)
    )
    legacy_result = await domain.async_get_schedules(
        charger_ref_from_pod(legacy_model)
    )

    assert home_result == [
        ChargerSchedule(1, "01:00:00", 1, "02:00:00", True, "different")
    ]
    assert legacy_result == [
        ChargerSchedule(2, "03:00:00", 2, "04:00:00", False)
    ]
    client.async_get_manual_schedules.assert_awaited_once_with(home_model)
    client.async_get_pod.assert_not_awaited()


@pytest.mark.asyncio
async def test_canonical_schedule_replace_is_full_home_only_operation():
    client = AsyncMock()
    model = home_charger()
    charger = charger_ref_from_charger(model)
    schedules = [
        ChargerSchedule(day, "01:00:00", day, "02:00:00", True, f"old-{day}")
        for day in range(1, 8)
    ]
    client.async_set_manual_schedules.return_value = [
        ManualSchedule({
            **item.manual_dict,
            "uid": f"new-{item.start_day}",
        })
        for item in schedules
    ]
    client.async_get_delegated_control.return_value = SimpleNamespace(
        status="INACTIVE"
    )

    saved = await ChargerDomain(client).async_replace_schedules(charger, schedules)

    assert saved == schedules
    assert [item.uid for item in saved] == [f"new-{day}" for day in range(1, 8)]
    client.async_set_manual_schedules.assert_awaited_once_with(
        model, [item.manual_dict for item in schedules]
    )
    client.async_get_delegated_control.assert_awaited_once_with(model)
    assert charger.capability(
        ChargerCapability.FULL_SCHEDULE_REPLACEMENT
    ) is CapabilitySupport.SUPPORTED

    with pytest.raises(UnsupportedCapabilityError):
        await ChargerDomain(client).async_replace_schedules(legacy_ref(), schedules)


@pytest.mark.asyncio
async def test_canonical_schedule_replace_rejects_active_smart_charging():
    client = AsyncMock()
    client.async_get_delegated_control.return_value = SimpleNamespace(status="ACTIVE")
    schedules = [
        ChargerSchedule(day, "01:00:00", day, "02:00:00", True, f"uid-{day}")
        for day in range(1, 8)
    ]

    with pytest.raises(ChargeModeTransitionError):
        await ChargerDomain(client).async_replace_schedules(home_ref(), schedules)

    client.async_set_manual_schedules.assert_not_awaited()


@pytest.mark.asyncio
async def test_canonical_schedule_replace_requires_canonical_values():
    client = AsyncMock()
    with pytest.raises(RequestValidationError):
        await ChargerDomain(client).async_replace_schedules(home_ref(), [{}])
    client.async_set_manual_schedules.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_schedules_distinguish_empty_unsupported_and_transient():
    client = AsyncMock()
    legacy = legacy_ref()
    domain = ChargerDomain(client)

    assert await domain.async_get_legacy_schedules(legacy) == []
    assert legacy.capability(ChargerCapability.LEGACY_SCHEDULING) is (
        CapabilitySupport.SUPPORTED
    )

    with pytest.raises(UnsupportedCapabilityError):
        await domain.async_get_legacy_schedules(home_ref())
    client.async_get_pod.side_effect = APIError(500, "temporary")
    fresh_legacy = legacy_ref("LEGACY-2")
    with pytest.raises(APIError):
        await domain.async_get_legacy_schedules(fresh_legacy, refresh=True)
    assert fresh_legacy.capability(ChargerCapability.LEGACY_SCHEDULING) is (
        CapabilitySupport.UNKNOWN
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 410])
async def test_legacy_schedule_confirmed_absence_is_retained(status):
    client = AsyncMock()
    client.async_get_pod.side_effect = APIError(status, "missing")
    legacy = legacy_ref()
    domain = ChargerDomain(client)

    with pytest.raises(UnsupportedCapabilityError):
        await domain.async_get_legacy_schedules(legacy, refresh=True)
    with pytest.raises(UnsupportedCapabilityError):
        await domain.async_get_legacy_schedules(legacy, refresh=True)

    assert client.async_get_pod.await_count == 1
    assert legacy.capability(ChargerCapability.LEGACY_SCHEDULING) is (
        CapabilitySupport.UNSUPPORTED
    )


@pytest.mark.asyncio
async def test_legacy_schedule_snapshot_refreshes_on_rediscovery():
    client = AsyncMock()
    client.async_get_chargers.side_effect = APIError(404, "not available")
    first_pod = legacy_pod()
    second_pod = legacy_pod()
    first_pod.charge_schedules = ["old"]
    second_pod.charge_schedules = ["new"]
    client.async_get_all_pods.side_effect = [[first_pod], [second_pod]]
    domain = ChargerDomain(client)

    first = (await domain.async_discover_chargers())[0]
    second = (await domain.async_discover_chargers())[0]

    assert await domain.async_get_legacy_schedules(first) == ["old"]
    assert await domain.async_get_legacy_schedules(second) == ["new"]
    assert client.async_get_all_pods.await_count == 2
    client.async_get_pod.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_schedule_explicit_refresh_is_available():
    client = AsyncMock()
    stale = legacy_pod()
    current = legacy_pod()
    stale.charge_schedules = ["old"]
    current.charge_schedules = ["new"]
    client.async_get_pod.return_value = current
    domain = ChargerDomain(client)

    schedules = await domain.async_get_legacy_schedules(
        charger_ref_from_pod(stale), refresh=True
    )

    assert schedules == ["new"]
    client.async_get_pod.assert_awaited_once_with(stale.id)


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
    assert provisional.source is ChargeSessionSource.LEGACY
    assert completed.source is ChargeSessionSource.HOME_HISTORY
    assert provisional.correlation_key == completed.correlation_key
    assert completed.energy_kwh == 7.2 and completed.currency == "GBP"


@pytest.mark.asyncio
async def test_home_and_legacy_charge_history_are_attributed_and_filtered():
    client = AsyncMock()
    home = home_ref("HOME")
    legacy = charger_ref_from_pod(legacy_pod("LEGACY", pod_id=22))
    home_item = ChargeHistoryItem({
        "id": "H", "startedAt": "2026-08-01T10:00:00Z",
        "endedAt": "2026-08-01T11:00:00Z",
        "charger": {"id": "HOME"},
    })
    other_item = ChargeHistoryItem({
        "id": "O", "startedAt": "2026-08-01T10:00:00Z",
        "endedAt": "2026-08-01T11:00:00Z",
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
        "id": 3, "starts_at": "2026-08-01T10:00:00Z",
        "ends_at": "2026-08-01T11:00:00Z", "pod": {"id": 22}
    })
    other_charge = Charge({
        "id": 4, "starts_at": "2026-08-01T10:00:00Z",
        "ends_at": "2026-08-01T11:00:00Z", "pod": {"id": 99}
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
             "endedAt": "2026-08-01T10:30:00Z",
             "charger": {"id": "A"}},
            {"id": "2", "startedAt": "2026-08-01T11:00:00Z",
             "endedAt": "2026-08-01T11:30:00Z",
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


@pytest.mark.asyncio
async def test_domain_credentials_verify_home_without_legacy_call():
    client = AsyncMock()
    client.async_get_chargers.return_value = [home_charger()]

    assert await ChargerDomain(client).async_charger_credentials_verified()
    client.async_get_all_pods.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_exposes_new_domain_delegates():
    domain = AsyncMock(spec=ChargerDomain)
    domain.async_discover_chargers.return_value = [legacy_ref()]
    domain.async_charger_credentials_verified.return_value = True
    domain.async_get_basic_charging_mode.return_value = BasicChargingMode.SCHEDULED
    domain.async_get_schedules.return_value = ["schedule"]
    domain.async_replace_schedules.return_value = ["saved schedule"]
    domain.async_get_legacy_schedules.return_value = []
    domain.async_get_completed_charge_sessions.return_value = {"HOME": []}
    domain.async_get_live_charge_sessions.return_value = {"HOME": []}
    domain.account_capability.return_value = CapabilitySupport.UNKNOWN
    client = object.__new__(PodPointClient)
    client._domain = domain
    chargers = [home_ref("HOME")]
    boost = BoostState("HOME", active=False, timed=False)

    discovered = await client.async_discover_chargers(ChargerSource.LEGACY)
    assert discovered[0].source is ChargerSource.LEGACY
    domain.async_discover_chargers.assert_awaited_once_with(ChargerSource.LEGACY)
    assert await client.async_charger_credentials_verified()
    assert client.account_capability(AccountCapability.LEGACY_CHARGES) is (
        CapabilitySupport.UNKNOWN
    )
    assert await client.async_get_basic_charging_mode(
        chargers[0], boost_state=boost
    ) is (
        BasicChargingMode.SCHEDULED
    )
    assert await client.async_get_charger_legacy_schedules(
        chargers[0], refresh=True
    ) == []
    assert await client.async_get_charger_schedules(
        chargers[0], refresh=True
    ) == ["schedule"]
    assert await client.async_replace_charger_schedules(
        chargers[0], ["input"]
    ) == ["saved schedule"]
    assert await client.async_get_completed_charge_sessions(
        chargers, date(2026, 8, 1), date(2026, 8, 2)
    ) == {"HOME": []}
    assert await client.async_get_live_charge_sessions(
        chargers, per_page=10
    ) == {"HOME": []}
    domain.account_capability.assert_called_once_with(
        AccountCapability.LEGACY_CHARGES
    )
    domain.async_get_basic_charging_mode.assert_awaited_once_with(
        chargers[0], boost_state=boost
    )
    domain.async_get_legacy_schedules.assert_awaited_once_with(
        chargers[0], refresh=True
    )
    domain.async_get_schedules.assert_awaited_once_with(
        chargers[0], refresh=True
    )
    domain.async_replace_schedules.assert_awaited_once_with(
        chargers[0], ["input"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 410])
async def test_domain_credentials_verify_through_legacy_fallback(status):
    client = AsyncMock()
    client.async_get_chargers.side_effect = APIError(status, "missing")
    client.async_get_all_pods.return_value = [legacy_pod()]

    assert await ChargerDomain(client).async_charger_credentials_verified()
    client.async_get_all_pods.assert_awaited_once()


@pytest.mark.asyncio
async def test_domain_credentials_return_false_for_account_without_chargers():
    client = AsyncMock()
    client.async_get_chargers.return_value = []
    assert not await ChargerDomain(client).async_charger_credentials_verified()
    client.async_get_all_pods.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    APIError(401, "denied"), APIError(429, "limited"), APIError(500, "failed"),
    AuthError(401, "auth"), SessionError(401, "session"),
    ApiConnectionError("offline"),
])
async def test_domain_credentials_propagate_non_fallback_errors(error):
    client = AsyncMock()
    client.async_get_chargers.side_effect = error
    with pytest.raises(type(error)):
        await ChargerDomain(client).async_charger_credentials_verified()
    client.async_get_all_pods.assert_not_awaited()


def canonical_session(
    ppid, started_at, *, session_id=None, active=False, ended_at=None,
    source=ChargeSessionSource.UNKNOWN,
):
    """Build a compact canonical session fixture."""
    return ChargeSession(
        ppid=ppid,
        session_id=session_id,
        started_at=started_at,
        ended_at=ended_at,
        active=active,
        energy_kwh=None,
        duration_seconds=None,
        cost=None,
        currency=None,
        correlation_key=f"{ppid}:{started_at.isoformat()}",
        source=source,
    )


def test_charge_session_source_default_preserves_positional_raw_compatibility():
    raw = object()
    session = ChargeSession(
        "P", "1", None, None, False, None, None, None, None, "P:unknown", raw
    )
    assert session.raw is raw
    assert session.source is ChargeSessionSource.UNKNOWN


def test_reconcile_replaces_matches_deduplicates_and_orders():
    start = datetime(2026, 8, 1, 10, tzinfo=timezone.utc)
    earlier = canonical_session("A", start - timedelta(hours=1), session_id="E")
    final = canonical_session(
        "A", start + timedelta(seconds=60), session_id="H", ended_at=start
    )
    duplicate = canonical_session(
        "A", start + timedelta(seconds=60), session_id="H", ended_at=start
    )
    provisional = canonical_session("A", start, session_id="L", active=True)
    unmatched = canonical_session(
        "A", start + timedelta(minutes=5), session_id="U", active=True
    )

    result = reconcile_charge_sessions(
        [final, earlier, duplicate], [unmatched, provisional]
    )

    assert [item.session_id for item in result] == ["E", "H", "U"]
    assert len([item for item in result if item.session_id == "H"]) == 1


def test_reconcile_observes_tolerance_ppid_and_stable_identifiers():
    start = datetime(2026, 8, 1, 10, tzinfo=timezone.utc)
    final = canonical_session(
        "A", start, session_id="S", ended_at=start,
        source=ChargeSessionSource.HOME_HISTORY,
    )
    exact = canonical_session(
        "A", start + timedelta(seconds=60), session_id="different", active=True,
        source=ChargeSessionSource.LEGACY,
    )
    outside = canonical_session(
        "A", start + timedelta(seconds=61), session_id="outside", active=True
    )
    other = canonical_session("B", start, session_id="other", active=True)
    same_id = canonical_session(
        "A", start + timedelta(hours=1), session_id="S", active=True,
        source=ChargeSessionSource.HOME_HISTORY,
    )

    result = reconcile_charge_sessions(
        [final], [exact, outside, other, same_id], tolerance=timedelta(seconds=60)
    )

    assert {item.session_id for item in result} == {"S", "outside", "other"}


@pytest.mark.parametrize("source", [
    ChargeSessionSource.HOME_HISTORY, ChargeSessionSource.LEGACY,
])
def test_reconcile_same_source_ids_are_comparable_and_deduplicated(source):
    start = datetime(2026, 8, 1, 10, tzinfo=timezone.utc)
    final = canonical_session(
        "A", start, session_id="shared", ended_at=start, source=source
    )
    duplicate = canonical_session(
        "A", start + timedelta(hours=1), session_id="shared", ended_at=start,
        source=source,
    )
    provisional = canonical_session(
        "A", start + timedelta(hours=2), session_id="shared", active=True,
        source=source,
    )

    result = reconcile_charge_sessions([final, duplicate], [provisional])

    assert result == [final]


def test_reconcile_equal_cross_source_or_unknown_ids_are_not_authoritative():
    start = datetime(2026, 8, 1, 10, tzinfo=timezone.utc)
    final = canonical_session(
        "A", start, session_id="42", ended_at=start,
        source=ChargeSessionSource.HOME_HISTORY,
    )
    cross_source = canonical_session(
        "A", start + timedelta(minutes=5), session_id="42", active=True,
        source=ChargeSessionSource.LEGACY,
    )
    unknown = canonical_session(
        "A", start + timedelta(minutes=10), session_id="42", active=True,
    )

    result = reconcile_charge_sessions([final], [cross_source, unknown])

    assert result == [final, cross_source, unknown]


@pytest.mark.asyncio
async def test_completed_home_history_groups_multiple_chargers_once():
    client = AsyncMock()
    chargers = [home_ref("A"), home_ref("B")]
    client.async_get_charge_history.return_value = ChargeHistory({
        "data": {"charges": [
            {"id": "HA", "startedAt": "2026-08-01T10:00:00Z",
             "endedAt": "2026-08-01T11:00:00Z", "charger": {"id": "A"}},
            {"id": "HB", "startedAt": "2026-08-01T12:00:00Z",
             "endedAt": "2026-08-01T13:00:00Z", "charger": {"id": "B"}},
        ]}
    })
    domain = ChargerDomain(client)

    groups = await domain.async_get_completed_charge_sessions(
        chargers, date(2026, 8, 1), date(2026, 8, 2)
    )

    assert groups["A"][0].session_id == "HA"
    assert groups["B"][0].session_id == "HB"
    client.async_get_charge_history.assert_awaited_once()
    client.async_get_all_pods.assert_not_awaited()
    client.async_get_all_charges.assert_not_awaited()
    assert domain.account_capability(AccountCapability.HOME_CHARGE_HISTORY) is (
        CapabilitySupport.SUPPORTED
    )


@pytest.mark.asyncio
async def test_completed_home_history_excludes_unfinished_sessions():
    client = AsyncMock()
    chargers = [home_ref("A"), home_ref("B")]
    client.async_get_charge_history.return_value = ChargeHistory({
        "data": {"charges": [
            {
                "id": "COMPLETE",
                "startedAt": "2026-08-01T10:00:00Z",
                "endedAt": "2026-08-01T11:00:00Z",
                "charger": {"id": "A"},
            },
            {
                "id": "ACTIVE-A",
                "startedAt": "2026-08-01T12:00:00Z",
                "endedAt": None,
                "charger": {"id": "A"},
            },
            {
                "id": "ACTIVE-B",
                "startedAt": "2026-08-01T13:00:00Z",
                "charger": {"id": "B"},
            },
        ]}
    })

    groups = await ChargerDomain(client).async_get_completed_charge_sessions(
        chargers, date(2026, 8, 1), date(2026, 8, 2)
    )

    assert [session.session_id for session in groups["A"]] == ["COMPLETE"]
    assert groups["B"] == []


@pytest.mark.asyncio
async def test_mixed_completed_history_partitions_and_merges_once_per_source():
    client = AsyncMock()
    home = home_ref("HOME")
    legacy = charger_ref_from_pod(legacy_pod("LEGACY", pod_id=22))
    client.async_get_charge_history.return_value = ChargeHistory({
        "data": {"charges": [{
            "id": "H", "startedAt": "2026-08-01T10:00:00Z",
            "endedAt": "2026-08-01T11:00:00Z",
            "charger": {"id": "HOME"},
        }]}
    })
    client.async_get_all_charges.return_value = [Charge({
        "id": 7, "starts_at": "2026-08-01T12:00:00Z",
        "ends_at": "2026-08-01T13:00:00Z", "pod": {"id": 22},
    })]

    groups = await ChargerDomain(client).async_get_completed_charge_sessions(
        [home, legacy], date(2026, 8, 1), date(2026, 8, 2)
    )

    assert [item.session_id for item in groups["HOME"]] == ["H"]
    assert [item.session_id for item in groups["LEGACY"]] == ["7"]
    client.async_get_charge_history.assert_awaited_once()
    client.async_get_all_charges.assert_awaited_once()
    client.async_get_all_pods.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_home_success_survives_legacy_history_absence():
    client = AsyncMock()
    home = home_ref("HOME")
    legacy = charger_ref_from_pod(legacy_pod("LEGACY", pod_id=22))
    client.async_get_charge_history.return_value = ChargeHistory({
        "data": {"charges": [{
            "id": "H", "startedAt": "2026-08-01T10:00:00Z",
            "endedAt": "2026-08-01T11:00:00Z",
            "charger": {"id": "HOME"},
        }]}
    })
    client.async_get_all_charges.side_effect = APIError(404, "missing")
    domain = ChargerDomain(client)

    groups = await domain.async_get_completed_charge_sessions(
        [home, legacy], date(2026, 8, 1), date(2026, 8, 2)
    )

    assert [item.session_id for item in groups["HOME"]] == ["H"]
    assert groups["LEGACY"] == []
    assert domain.account_capability(AccountCapability.HOME_CHARGE_HISTORY) is (
        CapabilitySupport.SUPPORTED
    )
    assert domain.account_capability(AccountCapability.LEGACY_CHARGES) is (
        CapabilitySupport.UNSUPPORTED
    )
    assert domain.account_capability(AccountCapability.CHARGE_HISTORY) is (
        CapabilitySupport.SUPPORTED
    )


@pytest.mark.asyncio
async def test_home_history_absence_uses_one_legacy_fetch_for_all_refs():
    client = AsyncMock()
    home = home_ref("HOME")
    legacy = charger_ref_from_pod(legacy_pod("LEGACY", pod_id=22))
    client.async_get_charge_history.side_effect = APIError(404, "missing")
    client.async_get_all_pods.return_value = [
        legacy_pod("HOME", pod_id=21), legacy_pod("LEGACY", pod_id=22)
    ]
    client.async_get_all_charges.return_value = [
        Charge({"id": 1, "starts_at": "2026-08-01T10:00:00Z",
                "ends_at": "2026-08-01T11:00:00Z", "pod": {"id": 21}}),
        Charge({"id": 2, "starts_at": "2026-08-01T12:00:00Z",
                "ends_at": "2026-08-01T13:00:00Z", "pod": {"id": 22}}),
    ]

    groups = await ChargerDomain(client).async_get_completed_charge_sessions(
        [home, legacy], date(2026, 8, 1), date(2026, 8, 2)
    )

    assert [item.session_id for item in groups["HOME"]] == ["1"]
    assert [item.session_id for item in groups["LEGACY"]] == ["2"]
    client.async_get_charge_history.assert_awaited_once()
    client.async_get_all_charges.assert_awaited_once()
    client.async_get_all_pods.assert_awaited_once()


@pytest.mark.asyncio
async def test_equivalent_mixed_refs_do_not_duplicate_completed_session():
    client = AsyncMock()
    home = home_ref("SAME")
    legacy = charger_ref_from_pod(legacy_pod("SAME", pod_id=22))
    client.async_get_charge_history.return_value = ChargeHistory({
        "data": {"charges": [{
            "id": "42", "startedAt": "2026-08-01T10:00:00Z",
            "endedAt": "2026-08-01T11:00:00Z", "charger": {"id": "SAME"},
        }]}
    })
    client.async_get_all_charges.return_value = [Charge({
        "id": 42, "starts_at": "2026-08-01T10:00:00Z",
        "ends_at": "2026-08-01T11:00:00Z", "pod": {"id": 22},
    })]

    groups = await ChargerDomain(client).async_get_completed_charge_sessions(
        [home, legacy, home], date(2026, 8, 1), date(2026, 8, 2)
    )

    assert len(groups["SAME"]) == 1
    assert groups["SAME"][0].source is ChargeSessionSource.HOME_HISTORY


@pytest.mark.asyncio
async def test_empty_completed_history_request_makes_no_calls():
    client = AsyncMock()
    assert await ChargerDomain(client).async_get_completed_charge_sessions(
        [], date(2026, 8, 1), date(2026, 8, 2)
    ) == {}
    client.async_get_charge_history.assert_not_awaited()
    client.async_get_all_charges.assert_not_awaited()
    client.async_get_all_pods.assert_not_awaited()


@pytest.mark.asyncio
async def test_home_charger_receives_legacy_live_session_and_caches_identity():
    client = AsyncMock()
    charger = home_ref("HOME")
    client.async_get_all_pods.return_value = [legacy_pod("HOME", pod_id=22)]
    client.async_get_charges.return_value = [Charge({
        "id": 7, "starts_at": "2026-08-01T10:00:00Z", "ends_at": None,
        "pod": {"id": 22},
    })]
    domain = ChargerDomain(client)

    first = await domain.async_get_live_charge_sessions([charger])
    second = await domain.async_get_live_charge_sessions([charger])

    assert first["HOME"][0].session_id == "7"
    assert second["HOME"][0].active
    client.async_get_all_pods.assert_awaited_once()
    assert client.async_get_charges.await_count == 2
    client.async_get_charge_history.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_live_session_resolves_charge_pod_id_as_unit_id():
    client = AsyncMock()
    charger = home_ref("HOME")
    client.async_get_all_pods.return_value = [
        legacy_pod("HOME", pod_id=12234, unit_id=123456)
    ]
    client.async_get_charges.return_value = [Charge({
        "id": 7,
        "starts_at": "2026-08-01T10:00:00Z",
        "ends_at": None,
        "pod": {"id": 123456},
    })]

    groups = await ChargerDomain(client).async_get_live_charge_sessions([charger])

    assert [session.session_id for session in groups["HOME"]] == ["7"]


@pytest.mark.asyncio
async def test_legacy_identity_mapping_refreshes_only_for_new_ppids():
    client = AsyncMock()
    charger_a = home_ref("A")
    charger_b = home_ref("B")
    client.async_get_all_pods.side_effect = [
        [legacy_pod("A", pod_id=21)],
        [legacy_pod("A", pod_id=21), legacy_pod("B", pod_id=22)],
    ]
    client.async_get_charges.return_value = [
        Charge({"id": 1, "starts_at": "2026-08-01T10:00:00Z",
                "ends_at": None, "pod": {"id": 21}}),
        Charge({"id": 2, "starts_at": "2026-08-01T11:00:00Z",
                "ends_at": None, "pod": {"id": 22}}),
    ]
    domain = ChargerDomain(client)

    first = await domain.async_get_live_charge_sessions([charger_a])
    await domain.async_get_live_charge_sessions([charger_a])
    refreshed = await domain.async_get_live_charge_sessions([charger_a, charger_b])
    await domain.async_get_live_charge_sessions([charger_a, charger_b])

    assert [item.session_id for item in first["A"]] == ["1"]
    assert [item.session_id for item in refreshed["A"]] == ["1"]
    assert [item.session_id for item in refreshed["B"]] == ["2"]
    assert client.async_get_all_pods.await_count == 2


@pytest.mark.asyncio
async def test_unresolved_new_ppid_is_not_misattributed_on_refresh():
    client = AsyncMock()
    charger_a = home_ref("A")
    charger_b = home_ref("B")
    client.async_get_all_pods.return_value = [legacy_pod("A", pod_id=21)]
    client.async_get_charges.return_value = [
        Charge({"id": 1, "starts_at": "2026-08-01T10:00:00Z",
                "ends_at": None, "pod": {"id": 21}}),
        Charge({"id": 2, "starts_at": "2026-08-01T11:00:00Z",
                "ends_at": None, "pod": {"id": 99}}),
    ]
    domain = ChargerDomain(client)

    groups = await domain.async_get_live_charge_sessions([charger_a, charger_b])

    assert [item.session_id for item in groups["A"]] == ["1"]
    assert groups["B"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 410])
async def test_home_history_confirmed_absence_falls_back_to_legacy(status):
    client = AsyncMock()
    charger = home_ref("HOME")
    client.async_get_charge_history.side_effect = APIError(status, "missing")
    client.async_get_all_pods.return_value = [legacy_pod("HOME", pod_id=22)]
    client.async_get_all_charges.return_value = [
        Charge({
            "id": 8, "starts_at": "2026-08-01T10:00:00Z",
            "ends_at": "2026-08-01T11:00:00Z", "pod": {"id": 22},
        }),
        Charge({
            "id": 9, "starts_at": "2026-07-01T10:00:00Z",
            "ends_at": "2026-07-01T11:00:00Z", "pod": {"id": 22},
        }),
    ]
    domain = ChargerDomain(client)

    groups = await domain.async_get_completed_charge_sessions(
        [charger], date(2026, 8, 1), date(2026, 8, 2)
    )
    await domain.async_get_completed_charge_sessions(
        [charger], date(2026, 8, 1), date(2026, 8, 2)
    )

    assert [item.session_id for item in groups["HOME"]] == ["8"]
    assert client.async_get_charge_history.await_count == 1
    assert domain.account_capability(AccountCapability.HOME_CHARGE_HISTORY) is (
        CapabilitySupport.UNSUPPORTED
    )
    assert domain.account_capability(AccountCapability.LEGACY_CHARGES) is (
        CapabilitySupport.SUPPORTED
    )


@pytest.mark.asyncio
async def test_home_history_transient_failure_does_not_fall_back():
    client = AsyncMock()
    client.async_get_charge_history.side_effect = APIError(500, "failed")
    domain = ChargerDomain(client)

    with pytest.raises(APIError):
        await domain.async_get_completed_charge_sessions(
            [home_ref()], date(2026, 8, 1), date(2026, 8, 2)
        )

    client.async_get_all_pods.assert_not_awaited()
    client.async_get_all_charges.assert_not_awaited()
    assert domain.account_capability(AccountCapability.HOME_CHARGE_HISTORY) is (
        CapabilitySupport.UNKNOWN
    )


@pytest.mark.asyncio
async def test_legacy_live_absence_does_not_invalidate_home_history():
    client = AsyncMock()
    charger = home_ref("HOME")
    client.async_get_charge_history.return_value = ChargeHistory({"data": {}})
    client.async_get_all_pods.return_value = [legacy_pod("HOME", pod_id=22)]
    client.async_get_charges.side_effect = APIError(404, "missing")
    domain = ChargerDomain(client)
    await domain.async_get_completed_charge_sessions(
        [charger], date(2026, 8, 1), date(2026, 8, 2)
    )

    with pytest.raises(UnsupportedCapabilityError):
        await domain.async_get_live_charge_sessions([charger])
    with pytest.raises(UnsupportedCapabilityError):
        await domain.async_get_live_charge_sessions([charger])

    assert client.async_get_all_pods.await_count == 1
    assert client.async_get_charges.await_count == 1
    assert domain.account_capability(AccountCapability.HOME_CHARGE_HISTORY) is (
        CapabilitySupport.SUPPORTED
    )
    assert domain.account_capability(AccountCapability.LEGACY_CHARGES) is (
        CapabilitySupport.UNSUPPORTED
    )


@pytest.mark.asyncio
async def test_mixed_refs_share_legacy_live_grouping_and_filter_completed():
    client = AsyncMock()
    home = home_ref("HOME")
    legacy = charger_ref_from_pod(legacy_pod("LEGACY", pod_id=23))
    client.async_get_all_pods.return_value = [
        legacy_pod("HOME", pod_id=22), legacy_pod("LEGACY", pod_id=23)
    ]
    client.async_get_charges.return_value = [
        Charge({"id": 1, "starts_at": "2026-08-01T10:00:00Z",
                "ends_at": None, "pod": {"id": 22}}),
        Charge({"id": 2, "starts_at": "2026-08-01T11:00:00Z",
                "ends_at": None, "pod": {"id": 23}}),
        Charge({"id": 3, "starts_at": "2026-08-01T12:00:00Z",
                "ends_at": "2026-08-01T13:00:00Z", "pod": {"id": 22}}),
    ]

    groups = await ChargerDomain(client).async_get_live_charge_sessions(
        [home, legacy], per_page=25
    )

    assert [item.session_id for item in groups["HOME"]] == ["1"]
    assert [item.session_id for item in groups["LEGACY"]] == ["2"]
    client.async_get_charges.assert_awaited_once_with(perpage=25, page=1)


@pytest.mark.asyncio
@pytest.mark.parametrize(("override", "expected"), [
    (None, BasicChargingMode.SCHEDULED),
    ({"id": "O", "requestedAt": "2026-08-01T10:00:00Z",
      "chargingStation": {"ppid": "HOME"}}, BasicChargingMode.ALWAYS_ON),
    ({"id": "T", "requestedAt": "2026-08-01T10:00:00Z",
      "endAt": "2026-08-01T11:00:00Z",
      "chargingStation": {"ppid": "HOME"}}, BasicChargingMode.TIMED_BOOST),
])
async def test_get_basic_charging_mode(override, expected):
    client = AsyncMock()
    client.async_get_charger_charge_overrides.return_value = (
        [ChargerChargeOverride(override)] if override else []
    )
    assert await ChargerDomain(client).async_get_basic_charging_mode(
        home_ref("HOME")
    ) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(("override", "expected"), [
    (None, BasicChargingMode.SCHEDULED),
    ({"ppid": "LEGACY", "requested_at": "2026-08-01T10:00:00Z",
      "received_at": "2026-08-01T10:00:01Z", "ends_at": None},
     BasicChargingMode.ALWAYS_ON),
    ({"ppid": "LEGACY", "requested_at": "2026-08-01T10:00:00Z",
      "received_at": "2026-08-01T10:00:01Z",
      "ends_at": "2099-08-01T11:00:00Z"}, BasicChargingMode.TIMED_BOOST),
])
async def test_get_basic_charging_mode_from_legacy_override(override, expected):
    client = AsyncMock()
    client.async_get_charge_override.return_value = (
        ChargeOverride(override) if override else None
    )
    charger = legacy_ref("LEGACY")

    assert await ChargerDomain(client).async_get_basic_charging_mode(
        charger
    ) is expected
    client.async_get_charger_charge_overrides.assert_not_awaited()
    assert charger.capability(ChargerCapability.BASIC_CHARGING_MODE) is (
        CapabilitySupport.SUPPORTED
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("state", "expected"), [
    (BoostState("HOME", active=False, timed=False), BasicChargingMode.SCHEDULED),
    (BoostState("HOME", active=True, timed=False), BasicChargingMode.ALWAYS_ON),
    (BoostState("HOME", active=True, timed=True), BasicChargingMode.TIMED_BOOST),
])
async def test_basic_mode_reuses_canonical_boost_without_request(state, expected):
    client = AsyncMock()
    charger = home_ref("HOME")

    assert basic_charging_mode_from_boost(state) is expected
    assert await ChargerDomain(client).async_get_basic_charging_mode(
        charger, boost_state=state
    ) is expected
    client.async_get_charger_charge_overrides.assert_not_awaited()
    client.async_get_charge_override.assert_not_awaited()


@pytest.mark.asyncio
async def test_basic_mode_rejects_boost_for_another_charger():
    client = AsyncMock()
    with pytest.raises(RequestValidationError):
        await ChargerDomain(client).async_get_basic_charging_mode(
            home_ref("HOME"),
            boost_state=BoostState("OTHER", active=False, timed=False),
        )
    client.async_get_charger_charge_overrides.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [
    BasicChargingMode.ALWAYS_ON, BasicChargingMode.SCHEDULED,
])
async def test_set_basic_charging_mode_dispatches_home_operations(mode):
    client = AsyncMock()
    charger_model = home_charger()
    charger = charger_ref_from_charger(charger_model)
    domain = ChargerDomain(client)

    assert await domain.async_set_basic_charging_mode(charger, mode) is mode
    if mode is BasicChargingMode.ALWAYS_ON:
        client.async_set_charger_charge_mode_always_on.assert_awaited_once_with(
            charger_model
        )
    else:
        client.async_set_charger_charge_mode_scheduled.assert_awaited_once_with(
            charger_model
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [
    BasicChargingMode.TIMED_BOOST, BasicChargingMode.UNKNOWN, "scheduled",
])
async def test_set_basic_charging_mode_rejects_nonpersistent_values(mode):
    client = AsyncMock()
    with pytest.raises(RequestValidationError):
        await ChargerDomain(client).async_set_basic_charging_mode(home_ref(), mode)
    client.async_set_charger_charge_mode_always_on.assert_not_awaited()
    client.async_set_charger_charge_mode_scheduled.assert_not_awaited()


@pytest.mark.asyncio
async def test_basic_mode_preserves_smart_charging_prerequisite_error():
    client = AsyncMock()
    client.async_set_charger_charge_mode_always_on.side_effect = (
        ChargeModeTransitionError("smart charging active")
    )
    charger = home_ref()
    with pytest.raises(ChargeModeTransitionError):
        await ChargerDomain(client).async_set_basic_charging_mode(
            charger, BasicChargingMode.ALWAYS_ON
        )
    assert charger.capability(ChargerCapability.BASIC_CHARGING_MODE) is (
        CapabilitySupport.UNKNOWN
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 410])
async def test_basic_mode_confirmed_absence_is_typed_and_retained(status):
    client = AsyncMock()
    client.async_get_charger_charge_overrides.side_effect = APIError(status, "missing")
    charger = home_ref()
    domain = ChargerDomain(client)

    with pytest.raises(UnsupportedCapabilityError):
        await domain.async_get_basic_charging_mode(charger)
    with pytest.raises(UnsupportedCapabilityError):
        await domain.async_get_basic_charging_mode(charger)

    assert client.async_get_charger_charge_overrides.await_count == 1
    assert charger.capability(ChargerCapability.BASIC_CHARGING_MODE) is (
        CapabilitySupport.UNSUPPORTED
    )


@pytest.mark.asyncio
async def test_basic_mode_transient_error_and_legacy_set_is_unsupported():
    client = AsyncMock()
    client.async_get_charger_charge_overrides.side_effect = APIError(500, "failed")
    home = home_ref()
    with pytest.raises(APIError):
        await ChargerDomain(client).async_get_basic_charging_mode(home)
    assert home.capability(ChargerCapability.BASIC_CHARGING_MODE) is (
        CapabilitySupport.UNKNOWN
    )

    legacy = legacy_ref()
    with pytest.raises(UnsupportedCapabilityError):
        await ChargerDomain(client).async_set_basic_charging_mode(
            legacy, BasicChargingMode.ALWAYS_ON
        )
    assert legacy.capability(ChargerCapability.BASIC_CHARGING_MODE) is (
        CapabilitySupport.UNKNOWN
    )
    client.async_set_charger_charge_mode_always_on.assert_not_awaited()
