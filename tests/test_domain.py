"""Tests for the API-independent charger domain facade."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from podpointclient.charger import Charger
from podpointclient.connectivity_status_v2 import ConnectivityStatusV2
from podpointclient.domain import (
    CapabilitySupport, ChargerCapability, ChargerDomain, ChargerSource,
    StateValue, charger_ref_from_charger, charger_ref_from_pod, normalize_state,
)
from podpointclient.errors import (
    APIError, AuthError, UnsupportedCapabilityError, api_error_status,
)
from podpointclient.pod import Pod


def home_charger(ppid="HOME-1"):
    return Charger({
        "ppid": ppid, "unitId": 12, "timezone": "Europe/London",
        "linkedAt": "2025-01-01T00:00:00Z",
        "modelInfo": {"architecture": "arch5", "style": "SOCKETED"},
    })


def legacy_pod(ppid="LEGACY-1"):
    return Pod({
        "ppid": ppid, "unit_id": 34, "timezone": "Europe/London",
        "commissioned_at": "2024-01-01T00:00:00Z",
        "model": {"name": "Solo 3"},
    })


@pytest.mark.asyncio
async def test_home_first_discovery_and_canonical_conversion():
    client = AsyncMock()
    client.async_get_chargers.return_value = [home_charger("A"), home_charger("B")]

    refs = await ChargerDomain(client).async_discover_chargers()

    client.async_get_all_pods.assert_not_awaited()
    assert [item.ppid for item in refs] == ["A", "B"]
    assert refs[0].source is ChargerSource.HOME
    assert refs[0].unit_id == 12
    assert refs[0].model_name == "arch5 SOCKETED"
    assert refs[0].linked_at == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert refs[0].raw.ppid == refs[0].ppid


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 410])
async def test_discovery_falls_back_only_for_absent_home_endpoint(status):
    client = AsyncMock()
    client.async_get_chargers.side_effect = APIError(status, "omitted")
    client.async_get_all_pods.return_value = [legacy_pod()]

    refs = await ChargerDomain(client).async_discover_chargers()

    assert refs[0].source is ChargerSource.LEGACY
    assert refs[0].ppid == "LEGACY-1"
    assert refs[0].model_name == "Solo 3"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    APIError(401, "omitted"), APIError(429, "omitted"),
    APIError(500, "omitted"), AuthError(401, "omitted"),
])
async def test_discovery_does_not_mask_other_errors(error):
    client = AsyncMock()
    client.async_get_chargers.side_effect = error
    with pytest.raises(type(error)):
        await ChargerDomain(client).async_discover_chargers()
    client.async_get_all_pods.assert_not_awaited()


def test_capabilities_distinguish_supported_unsupported_and_unknown():
    home = charger_ref_from_charger(home_charger())
    legacy = charger_ref_from_pod(legacy_pod())
    assert home.capability(ChargerCapability.TIMED_BOOST) is CapabilitySupport.SUPPORTED
    assert home.capability(ChargerCapability.LEGACY_SCHEDULING) is CapabilitySupport.UNSUPPORTED
    assert home.capability(ChargerCapability.FIRMWARE) is CapabilitySupport.SUPPORTED
    assert legacy.capability(ChargerCapability.FIRMWARE) is CapabilitySupport.SUPPORTED
    assert legacy.capability(ChargerCapability.TARIFFS) is CapabilitySupport.UNSUPPORTED

    no_unit_id = charger_ref_from_charger(Charger({"ppid": "NO-UNIT"}))
    assert no_unit_id.capability(ChargerCapability.FIRMWARE) is CapabilitySupport.UNKNOWN


def test_ppid_is_stable_identity_across_wire_models():
    home = charger_ref_from_charger(home_charger("SAME-PPID"))
    legacy = charger_ref_from_pod(legacy_pod("SAME-PPID"))
    assert home == legacy
    assert hash(home) == hash(legacy)


@pytest.mark.parametrize(("raw", "expected"), [
    ("SuspendedEVSE", StateValue.SUSPENDED_EVSE),
    ("SUSPENDED_EVSE", StateValue.SUSPENDED_EVSE),
    ("suspended-evse", StateValue.SUSPENDED_EVSE),
    ("Charging", StateValue.CHARGING),
    (None, None),
    ("FUTURE_QUANTUM_STATE", StateValue.UNKNOWN),
])
def test_state_normalization_is_safe_and_preserves_raw(raw, expected):
    result = normalize_state(raw)
    assert result.value is expected
    assert result.raw == raw


@pytest.mark.asyncio
async def test_unified_boost_and_state_dispatch():
    client = AsyncMock()
    home = charger_ref_from_charger(home_charger())
    legacy = charger_ref_from_pod(legacy_pod())
    client.async_get_connectivity_status_v2.return_value = ConnectivityStatusV2({
        "connectionState": "Online", "chargingState": "SuspendedEVSE"
    })
    facade = ChargerDomain(client)

    await facade.async_start_boost(home, hours=1)
    await facade.async_stop_boost(home)
    await facade.async_start_boost(legacy, minutes=30)
    await facade.async_stop_boost(legacy)
    state = await facade.async_get_state(home)

    client.async_create_charger_charge_override.assert_awaited_once_with(
        home.raw, hours=1, minutes=0, seconds=0)
    client.async_delete_charger_charge_overrides.assert_awaited_once_with(home.raw)
    client.async_set_charge_override.assert_awaited_once_with(
        legacy.raw, hours=0, minutes=30, seconds=0)
    client.async_delete_charge_override.assert_awaited_once_with(legacy.raw)
    assert state.connection.value is StateValue.ONLINE
    assert state.charging.value is StateValue.SUSPENDED_EVSE


@pytest.mark.asyncio
async def test_unsupported_capability_has_typed_error():
    legacy = charger_ref_from_pod(legacy_pod())
    with pytest.raises(UnsupportedCapabilityError) as raised:
        ChargerDomain._require(legacy, ChargerCapability.TARIFFS)
    assert raised.value.capability is ChargerCapability.TARIFFS
    assert raised.value.ppid == legacy.ppid


@pytest.mark.asyncio
async def test_unified_firmware_uses_legacy_endpoint_for_both_sources():
    client = AsyncMock()
    client.async_get_firmware.side_effect = [["home firmware"], ["legacy firmware"]]
    facade = ChargerDomain(client)
    home = charger_ref_from_charger(home_charger())
    legacy = charger_ref_from_pod(legacy_pod())

    assert await facade.async_get_firmware(home) == ["home firmware"]
    assert await facade.async_get_firmware(legacy) == ["legacy firmware"]
    assert client.async_get_firmware.await_args_list[0].args == (home.raw,)
    assert client.async_get_firmware.await_args_list[1].args == (legacy.raw,)


@pytest.mark.asyncio
async def test_firmware_absence_has_typed_error_but_other_errors_survive():
    client = AsyncMock()
    facade = ChargerDomain(client)
    home = charger_ref_from_charger(home_charger())
    client.async_get_firmware.side_effect = APIError(404, "omitted")
    with pytest.raises(UnsupportedCapabilityError):
        await facade.async_get_firmware(home)

    client.async_get_firmware.side_effect = APIError(500, "omitted")
    with pytest.raises(APIError) as raised:
        await facade.async_get_firmware(home)
    assert api_error_status(raised.value) == 500


def test_api_error_status_is_reliable_for_new_and_legacy_shapes():
    assert api_error_status(APIError(410, "omitted")) == 410
    assert api_error_status(APIError("API failed (404)")) == 404
    assert api_error_status(APIError("transport failed")) is None
