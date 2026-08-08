"""Tests for charger mode and manual-schedule workflows observed in the app."""
from datetime import datetime, timedelta, timezone

import aiohttp
from aiohttp import hdrs
from aioresponses import aioresponses
import pytest
from yarl import URL

from podpointclient.charger import Charger
from podpointclient.client import PodPointClient
from podpointclient.endpoints import (
    CHARGERS, CHARGE_OVERRIDES, DELEGATED_CONTROLS, MANUAL_SCHEDULES,
    MOBILE_API_BASE_URL,
)
from podpointclient.errors import ChargeModeTransitionError, RequestValidationError
from podpointclient.manual_schedule import ManualSchedule


def authenticated_client(session):
    client = PodPointClient("user@example.invalid", "password", session=session)
    client.auth.access_token = "access-token"
    client.auth.access_token_expiry = datetime.now() + timedelta(hours=1)
    return client


def captured_schedules():
    """Return the seven-day shape observed in the sanitized app capture."""
    values = []
    for day in range(1, 8):
        values.append({
            "uid": f"schedule-{day}",
            "startDay": day,
            "startTime": "02:30:00",
            "endDay": day,
            "endTime": "05:00:00",
            "status": {"isActive": True},
        })
    values[4].update({
        "startTime": "23:00:00", "endDay": 6, "endTime": "06:00:00"
    })
    values[5].update({
        "startTime": "23:00:00", "endDay": 7, "endTime": "06:00:00"
    })
    values[6].update({"startTime": "06:15:00", "endTime": "06:15:00"})
    return values


@pytest.mark.asyncio
async def test_captured_charger_mode_sequence():
    charger = Charger({"ppid": "TEST-PPID-1"})
    requested_at = datetime(2026, 8, 6, 21, 56, 3, 354473, tzinfo=timezone.utc)
    delegated_url = f"{MOBILE_API_BASE_URL}{DELEGATED_CONTROLS}/{charger.ppid}"
    override_url = (
        f"{MOBILE_API_BASE_URL}{CHARGERS}/{charger.ppid}{CHARGE_OVERRIDES}"
    )
    schedules_url = (
        f"{MOBILE_API_BASE_URL}{CHARGERS}/{charger.ppid}{MANUAL_SCHEDULES}"
    )
    schedules = captured_schedules()
    override_response = [{
        "id": "OVERRIDE-1",
        "requestedAt": "2026-08-06T21:56:03.354Z",
        "receivedAt": "2026-08-06T21:56:03.778Z",
        "evse": {"door": "A", "ocppEvseId": 1},
        "chargingStation": {"ppid": charger.ppid},
    }]

    with aioresponses() as mocked:
        mocked.patch(delegated_url, status=204, repeat=True)
        mocked.get(
            delegated_url,
            payload={"ppid": charger.ppid, "status": "ACTIVE"},
        )
        for _ in range(3):
            mocked.get(
                delegated_url,
                payload={"ppid": charger.ppid, "status": "INACTIVE"},
            )
        mocked.post(override_url, payload=override_response, status=201)
        mocked.delete(override_url, status=200)
        mocked.put(schedules_url, payload=schedules, status=200)

        async with aiohttp.ClientSession() as session:
            client = authenticated_client(session)
            basic = await client.async_set_charger_smart_charging(
                charger, enabled=False
            )
            overrides = await client.async_set_charger_charge_mode_always_on(
                charger, requested_at=requested_at
            )
            scheduled = await client.async_set_charger_charge_mode_scheduled(charger)
            updated = await client.async_set_manual_schedules(
                charger, [ManualSchedule(item) for item in schedules]
            )
            smart = await client.async_set_charger_smart_charging(
                charger, enabled=True
            )

        patch_calls = mocked.requests[(hdrs.METH_PATCH, URL(delegated_url))]
        post_call = mocked.requests[(hdrs.METH_POST, URL(override_url))][0]
        put_call = mocked.requests[(hdrs.METH_PUT, URL(schedules_url))][0]

    assert basic and scheduled and smart
    assert overrides[0].end_at is None
    assert len(updated) == 7
    assert [call.kwargs["json"] for call in patch_calls] == [
        {"status": "INACTIVE"},
        {"status": "ACTIVE"},
    ]
    assert post_call.kwargs["json"] == {
        "requestedAt": "2026-08-06T21:56:03.354473Z"
    }
    assert put_call.kwargs["json"] == {"schedules": schedules}


@pytest.mark.asyncio
async def test_schedule_replacement_requires_all_seven_valid_days():
    charger = Charger({"ppid": "TEST-PPID-1"})
    async with aiohttp.ClientSession() as session:
        client = authenticated_client(session)
        with pytest.raises(RequestValidationError):
            await client.async_set_manual_schedules(charger, captured_schedules()[:6])

        invalid = captured_schedules()
        invalid[6]["startDay"] = 6
        with pytest.raises(RequestValidationError):
            await client.async_set_manual_schedules(charger, invalid)

        with pytest.raises(RequestValidationError):
            await client.async_set_charger_smart_charging(charger, enabled="yes")


@pytest.mark.parametrize(("change_day", "updates", "message"), [
    (1, {"endDay": 3}, "startDay or the following day"),
    (1, {"startTime": "23:00:00", "endTime": "06:00:00"},
     "must end on the following day"),
    (1, {"startTime": "06:00:00", "endDay": 2, "endTime": "07:00:00"},
     "must not span more than 24 hours"),
    (5, {"startTime": "23:00:00", "endDay": 6, "endTime": "06:00:00"},
     "following day's startTime"),
    (7, {"startTime": "23:00:00", "endDay": 1, "endTime": "03:00:00"},
     "following day's startTime"),
])
def test_schedule_replacement_rejects_invalid_duration_and_overlap(
    change_day,
    updates,
    message,
):
    schedules = captured_schedules()
    schedules[change_day - 1].update(updates)
    if change_day == 5:
        schedules[5]["startTime"] = "05:00:00"
    if change_day == 7:
        schedules[0]["startTime"] = "02:30:00"

    with pytest.raises(RequestValidationError, match=message):
        PodPointClient._validate_manual_schedules(schedules)


def test_schedule_replacement_accepts_boundaries_and_sunday_wraparound():
    schedules = captured_schedules()
    schedules[4].update({
        "startTime": "23:00:00", "endDay": 6, "endTime": "06:00:00",
    })
    schedules[5]["startTime"] = "06:00:00"
    schedules[6].update({
        "startTime": "23:00:00", "endDay": 1, "endTime": "02:30:00",
    })

    PodPointClient._validate_manual_schedules(schedules)


@pytest.mark.asyncio
async def test_always_on_stops_without_changing_active_smart_charging():
    charger = Charger({"ppid": "TEST-PPID-1"})
    delegated_url = f"{MOBILE_API_BASE_URL}{DELEGATED_CONTROLS}/{charger.ppid}"
    override_url = (
        f"{MOBILE_API_BASE_URL}{CHARGERS}/{charger.ppid}{CHARGE_OVERRIDES}"
    )
    with aioresponses() as mocked:
        mocked.get(
            delegated_url,
            payload={"ppid": charger.ppid, "status": "ACTIVE"},
        )
        mocked.post(override_url, payload=[], status=201)
        async with aiohttp.ClientSession() as session:
            client = authenticated_client(session)
            with pytest.raises(ChargeModeTransitionError):
                await client.async_set_charger_charge_mode_always_on(charger)

        assert (hdrs.METH_POST, URL(override_url)) not in mocked.requests
        assert (hdrs.METH_PATCH, URL(delegated_url)) not in mocked.requests


@pytest.mark.asyncio
async def test_scheduled_stops_without_changing_active_smart_charging():
    charger = Charger({"ppid": "TEST-PPID-1"})
    delegated_url = f"{MOBILE_API_BASE_URL}{DELEGATED_CONTROLS}/{charger.ppid}"
    override_url = (
        f"{MOBILE_API_BASE_URL}{CHARGERS}/{charger.ppid}{CHARGE_OVERRIDES}"
    )
    with aioresponses() as mocked:
        mocked.get(
            delegated_url,
            payload={"ppid": charger.ppid, "status": "ACTIVE"},
        )
        mocked.delete(override_url, status=200)
        async with aiohttp.ClientSession() as session:
            client = authenticated_client(session)
            with pytest.raises(ChargeModeTransitionError):
                await client.async_set_charger_charge_mode_scheduled(charger)

        assert (hdrs.METH_DELETE, URL(override_url)) not in mocked.requests
        assert (hdrs.METH_PATCH, URL(delegated_url)) not in mocked.requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled,current_status",
    [(True, "ACTIVE"), (False, "INACTIVE")]
)
async def test_setting_current_smart_charging_status_is_a_noop(
    enabled,
    current_status
):
    charger = Charger({"ppid": "TEST-PPID-1"})
    delegated_url = f"{MOBILE_API_BASE_URL}{DELEGATED_CONTROLS}/{charger.ppid}"
    with aioresponses() as mocked:
        mocked.get(
            delegated_url,
            payload={"ppid": charger.ppid, "status": current_status},
        )
        async with aiohttp.ClientSession() as session:
            client = authenticated_client(session)
            result = await client.async_set_charger_smart_charging(
                charger,
                enabled=enabled
            )

        assert result is True
        assert (hdrs.METH_PATCH, URL(delegated_url)) not in mocked.requests
