"""Tests for live-schema reads and safely validated charger mutations."""
from datetime import date, datetime, timedelta, timezone

import aiohttp
from aioresponses import aioresponses
import pytest

from podpointclient.charge_history import ChargeHistory, ChargeStats
from podpointclient.charger import Charger
from podpointclient.client import PodPointClient
from podpointclient.endpoints import (
    CHARGERS, CHARGE_OVERRIDES, CHARGES, DELEGATED_CONTROLS,
    MOBILE_API_BASE_URL, NOTIFICATION_PREFERENCES, PREFERENCES, STATS, TARIFFS,
)
from podpointclient.errors import RequestValidationError
from podpointclient.pod import Firmware
from podpointclient.preferences import NotificationPreferences, SmartChargingPreferences
from podpointclient.smart_charging import VehicleIntentDetail
from podpointclient.tariff import TariffPeriod


def authenticated_client(session):
    client = PodPointClient("user@example.invalid", "password", session=session)
    client.auth.access_token = "access-token"
    client.auth.access_token_expiry = datetime.now() + timedelta(hours=1)
    return client


@pytest.fixture
def charger():
    return Charger({"ppid": "TEST-PPID-1", "unitId": 1001})


OVERRIDE = {
    "id": "OVERRIDE-1",
    "requestedAt": "2026-08-06T10:00:00Z",
    "receivedAt": "2026-08-06T10:00:01Z",
    "endAt": "2026-08-06T11:00:00Z",
    "evse": {"door": 1, "ocppEvseId": 1},
    "chargingStation": {"ppid": "TEST-PPID-1"},
}

HISTORY = {
    "data": {
        "count": 1,
        "charges": [{
            "id": "CHARGE-1", "startedAt": "2026-08-01T10:00:00Z",
            "endedAt": "2026-08-01T11:00:00Z", "duration": 3600,
            "energyTotal": 7.2, "cost": {"amount": 0.46, "currency": "GBP"},
            "charger": {
                "type": "home", "id": "TEST-PPID-1", "door": 1,
                "pluggedInAt": "2026-08-01T09:55:00Z",
                "unpluggedAt": "2026-08-01T11:05:00Z",
                "pluggedInDuration": 4200,
            },
            "rewards": {"eligibleEnergy": 7.2},
        }],
    },
    "meta": {"params": {"From": "2026-08-01", "To": "2026-08-06"}},
}

STATS_RESPONSE = {
    "data": {
        "summary": {"energy": {"total": {"total": 7.2}}},
        "intervals": [{"from": "2026-08-01", "to": "2026-08-06", "stats": {}}],
    },
    "meta": {"params": {"Interval": "month"}},
}

INTENT_RESPONSE = {
    "id": "INTENT-1",
    "delegatedControlChargingStationVehicleId": "LINK-1",
    "intentDetails": [
        {"chargeByTime": "08:10:00", "chargeKWh": 61.6, "dayOfWeek": "MONDAY"}
    ],
    "maxPrice": None,
    "createdAt": "2026-08-06T10:00:00Z",
    "updatedAt": "2026-08-06T10:00:00Z",
}

TARIFF_RESPONSE = {
    "id": "TARIFF-1", "ppid": "TEST-PPID-1", "supplierId": "SUPPLIER-1",
    "smartChargingSupported": True,
    "tariffInfo": [{"days": [7], "start": "23:00:00", "end": "06:00:00", "price": 0.0649}],
    "timezone": "Europe/London", "effectiveFrom": "2026-08-06",
    "cheapestUnitPrice": 0.0649, "maxChargePrice": 0.3025,
}


@pytest.mark.asyncio
async def test_live_schema_reads(charger):
    deleted = dict(OVERRIDE, deletedAt="2026-08-06T10:30:00Z")
    with aioresponses() as mocked:
        mocked.get(
            f"{MOBILE_API_BASE_URL}{CHARGERS}/{charger.ppid}{CHARGE_OVERRIDES}",
            payload=[OVERRIDE, deleted],
            repeat=True,
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{DELEGATED_CONTROLS}/{charger.ppid}{PREFERENCES}",
            payload={"maxPrice": 0.3025},
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{CHARGES}?from=2026-08-01&to=2026-08-06",
            payload=HISTORY,
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{CHARGES}{STATS}"
            "?from=2026-08-01&to=2026-08-06&interval=month",
            payload=STATS_RESPONSE,
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{NOTIFICATION_PREFERENCES}",
            payload={"preferences": {"VEHICLE_INTERVENTION": True}},
        )
        async with aiohttp.ClientSession() as session:
            client = authenticated_client(session)
            overrides = await client.async_get_charger_charge_overrides(charger)
            active = await client.async_get_charger_charge_overrides(charger, active_only=True)
            preferences = await client.async_get_smart_charging_preferences(charger)
            history = await client.async_get_charge_history(date(2026, 8, 1), date(2026, 8, 6))
            stats = await client.async_get_charge_stats(date(2026, 8, 1), date(2026, 8, 6))
            notifications = await client.async_get_notification_preferences()

    assert len(overrides) == 2
    assert len(active) == 1 and active[0].active
    assert isinstance(preferences, SmartChargingPreferences)
    assert preferences.max_price == 0.3025
    assert isinstance(history, ChargeHistory) and history.charges[0].energy_total == 7.2
    assert isinstance(stats, ChargeStats) and stats.summary["energy"]["total"]["total"] == 7.2
    assert isinstance(notifications, NotificationPreferences)
    assert notifications.enabled("VEHICLE_INTERVENTION")


@pytest.mark.asyncio
async def test_confirmed_mutation_workflows(charger):
    requested_at = datetime(2026, 8, 6, 10, tzinfo=timezone.utc)
    intent = VehicleIntentDetail({
        "chargeByTime": "08:10:00", "chargeKWh": 61.6, "dayOfWeek": "MONDAY"
    })
    period = TariffPeriod({
        "days": [7], "start": "23:00:00", "end": "06:00:00", "price": 0.0649
    })
    override_url = f"{MOBILE_API_BASE_URL}{CHARGERS}/{charger.ppid}{CHARGE_OVERRIDES}"
    preferences_url = (
        f"{MOBILE_API_BASE_URL}{DELEGATED_CONTROLS}/{charger.ppid}{PREFERENCES}"
    )
    intent_url = (
        f"{MOBILE_API_BASE_URL}{DELEGATED_CONTROLS}/{charger.ppid}"
        "/vehicles/LINK-1/intents"
    )
    tariff_url = f"{MOBILE_API_BASE_URL}{CHARGERS}/{charger.ppid}{TARIFFS}"

    with aioresponses() as mocked:
        mocked.post(override_url, payload=[OVERRIDE], status=201)
        mocked.delete(override_url, status=200)
        mocked.put(intent_url, payload=INTENT_RESPONSE)
        mocked.patch(preferences_url, status=204)
        mocked.post(tariff_url, payload=TARIFF_RESPONSE)
        async with aiohttp.ClientSession() as session:
            client = authenticated_client(session)
            overrides = await client.async_create_charger_charge_override(
                charger, hours=1, requested_at=requested_at
            )
            deleted = await client.async_delete_charger_charge_overrides(charger)
            saved_intent = await client.async_set_vehicle_intents(charger, "LINK-1", [intent])
            saved_price = await client.async_set_smart_charging_max_price(charger, 0.3025)
            tariff = await client.async_set_tariff(
                charger, "SUPPLIER-1", [period], date(2026, 8, 6), "Europe/London"
            )

    assert overrides[0].end_at.hour == 11
    assert deleted and saved_price
    assert saved_intent.intent_details[0].day_of_week == "MONDAY"
    assert tariff.effective_from == date(2026, 8, 6)


@pytest.mark.asyncio
async def test_mutations_reject_invalid_values_before_request(charger):
    async with aiohttp.ClientSession() as session:
        client = authenticated_client(session)
        with pytest.raises(RequestValidationError):
            await client.async_create_charger_charge_override(charger)
        with pytest.raises(RequestValidationError):
            await client.async_set_smart_charging_max_price(charger, -0.1)
        with pytest.raises(RequestValidationError):
            await client.async_set_vehicle_intents(charger, "LINK-1", [{
                "chargeByTime": "25:00:00", "chargeKWh": 10, "dayOfWeek": "MONDAY"
            }])
        with pytest.raises(RequestValidationError):
            await client.async_get_charge_stats(
                date(2026, 8, 6), date(2026, 8, 1), interval="month"
            )


def test_firmware_accepts_live_camel_case_schema():
    firmware = Firmware({
        "serialNumber": "SERIAL-1",
        "versionInfo": {
            "architecture": "arch5", "manifestId": "manifest-1",
            "details": {"dspVersion": "dsp-1", "wifiVersion": "wifi-1"},
        },
        "updateStatus": {"isUpdateAvailable": True},
    })
    assert firmware.serial_number == "SERIAL-1"
    assert firmware.firmware_version == "manifest-1"
    assert firmware.version_info.architecture == "arch5"
    assert firmware.version_info.dsp_version == "dsp-1"
    assert firmware.update_available is True
