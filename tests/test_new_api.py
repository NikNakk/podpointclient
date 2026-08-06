"""Tests for the newer, charger-centric API surface."""
import json
from datetime import datetime, timedelta, timezone

import aiohttp
from aioresponses import aioresponses
import pytest

from podpointclient.charger import Charger
from podpointclient.charger_subscription import ChargerSubscription
from podpointclient.client import PodPointClient
from podpointclient.connectivity_status_v2 import ConnectivityStatusV2
from podpointclient.endpoints import (
    ACCESS_STATUS,
    AGREEMENTS,
    CHARGERS,
    CONNECTIVITY_STATUS_V2,
    MANUAL_SCHEDULES,
    MOBILE_API_BASE_URL,
    SECURITY_LOGS,
    SUBSCRIPTIONS,
    TARIFFS,
    USERS,
)
from podpointclient.manual_schedule import ManualSchedule
from podpointclient.security_log import SecurityLogPage
from podpointclient.tariff import Tariff
from podpointclient.user_access import UserAccessStatus, UserAgreements


def load_new_api_fixture():
    with open("./tests/fixtures/new_api.json") as fixture:
        return json.load(fixture)


def authenticated_client(session):
    client = PodPointClient("user@example.invalid", "password", session=session)
    client.auth.access_token = "access-token"
    client.auth.access_token_expiry = datetime.now() + timedelta(hours=1)
    return client


@pytest.mark.asyncio
async def test_new_api_read_methods():
    fixture = load_new_api_fixture()
    ppid = "TEST-PPID-1"

    with aioresponses() as mocked:
        mocked.get(
            f"{MOBILE_API_BASE_URL}{CHARGERS}",
            payload=fixture["chargers"],
            repeat=True,
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{CHARGERS}/{ppid}{CONNECTIVITY_STATUS_V2}",
            payload=fixture["connectivity_status_v2"],
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{CHARGERS}/{ppid}{TARIFFS}",
            payload=fixture["tariffs"],
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{CHARGERS}/{ppid}{MANUAL_SCHEDULES}",
            payload=fixture["manual_schedules"],
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{CHARGERS}/{ppid}{SECURITY_LOGS}?pageNumber=1",
            payload=fixture["security_logs"],
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{CHARGERS}/{ppid}{SUBSCRIPTIONS}",
            payload=fixture["charger_subscriptions"],
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{USERS}{ACCESS_STATUS}",
            payload=fixture["access_status"],
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{USERS}{AGREEMENTS}",
            payload=fixture["agreements"],
        )

        async with aiohttp.ClientSession() as session:
            client = authenticated_client(session)

            chargers = await client.async_get_chargers()
            charger = await client.async_get_charger(ppid)
            connectivity = await client.async_get_connectivity_status_v2(charger)
            tariffs = await client.async_get_tariffs(charger)
            schedules = await client.async_get_manual_schedules(charger)
            security_logs = await client.async_get_security_logs(charger)
            subscriptions = await client.async_get_charger_subscriptions(charger)
            access_statuses = await client.async_get_user_access_status()
            agreements = await client.async_get_user_agreements()

    assert len(chargers) == 1
    assert isinstance(charger, Charger)
    assert charger.unit_id == 1001
    assert charger.linked_at == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert charger.model_info.architecture == "arch5"
    assert charger.subscription.is_subscription_owner is True

    assert isinstance(connectivity, ConnectivityStatusV2)
    assert connectivity.connection_state == "ONLINE"
    assert connectivity.connection_quality == 3

    assert len(tariffs) == 1
    assert isinstance(tariffs[0], Tariff)
    assert tariffs[0].tariff_info[0].days == ["MONDAY", "TUESDAY"]
    assert tariffs[0].smart_charging_supported is True

    assert len(schedules) == 1
    assert isinstance(schedules[0], ManualSchedule)
    assert schedules[0].start_day == 1

    assert isinstance(security_logs, SecurityLogPage)
    assert security_logs.data == []
    assert security_logs.current_page == 1

    assert len(subscriptions) == 1
    assert isinstance(subscriptions[0], ChargerSubscription)
    assert subscriptions[0].plan_type == "HOME"

    assert len(access_statuses) == 1
    assert isinstance(access_statuses[0], UserAccessStatus)
    assert access_statuses[0].subscription_id == "SUBSCRIPTION-1"

    assert isinstance(agreements, UserAgreements)
    assert agreements.privacy_notice_v1 == "2025-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_get_charger_returns_none_when_ppid_is_unknown():
    fixture = load_new_api_fixture()

    with aioresponses() as mocked:
        mocked.get(
            f"{MOBILE_API_BASE_URL}{CHARGERS}",
            payload=fixture["chargers"],
        )

        async with aiohttp.ClientSession() as session:
            client = authenticated_client(session)
            charger = await client.async_get_charger("UNKNOWN")

    assert charger is None


def test_new_api_models_serialize_to_json():
    fixture = load_new_api_fixture()

    charger = Charger(fixture["chargers"][0])
    connectivity = ConnectivityStatusV2(fixture["connectivity_status_v2"])
    tariff = Tariff(fixture["tariffs"]["data"][0])
    schedule = ManualSchedule(fixture["manual_schedules"]["data"][0])
    subscription = ChargerSubscription(
        fixture["charger_subscriptions"]["subscriptions"][0]
    )
    access_status = UserAccessStatus(fixture["access_status"][0])
    agreements = UserAgreements(fixture["agreements"])

    for model in (
        charger,
        connectivity,
        tariff,
        schedule,
        subscription,
        access_status,
        agreements,
    ):
        assert isinstance(model.to_json(), str)
