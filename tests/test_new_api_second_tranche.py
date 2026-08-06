"""Tests for the second tranche of newer read-only API methods."""
import json
from datetime import datetime, timedelta

import aiohttp
from aioresponses import aioresponses
import pytest

from podpointclient.charger import Charger
from podpointclient.client import PodPointClient
from podpointclient.endpoints import (
    DELEGATED_CONTROLS,
    DELEGATED_VEHICLES,
    ENERGY_SUPPLIERS,
    MOBILE_API_BASE_URL,
    REMOTE_LOCK,
    REWARD_WALLET,
    SUBSCRIPTIONS,
    TRANSACTIONS,
)
from podpointclient.energy_supplier import EnergySupplier
from podpointclient.remote_lock import RemoteLock
from podpointclient.reward_wallet import RewardTransactionPage, RewardWallet
from podpointclient.smart_charging import DelegatedCharger, DelegatedControl
from podpointclient.subscription import Subscription


def load_new_api_fixture():
    with open("./tests/fixtures/new_api.json") as fixture:
        return json.load(fixture)


def authenticated_client(session):
    client = PodPointClient("user@example.invalid", "password", session=session)
    client.auth.access_token = "access-token"
    client.auth.access_token_expiry = datetime.now() + timedelta(hours=1)
    return client


@pytest.mark.asyncio
async def test_second_tranche_read_methods():
    fixture = load_new_api_fixture()
    charger = Charger(fixture["chargers"][0])

    with aioresponses() as mocked:
        mocked.get(
            f"{MOBILE_API_BASE_URL}{DELEGATED_VEHICLES}",
            payload=fixture["delegated_chargers"],
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{DELEGATED_CONTROLS}/{charger.ppid}",
            payload=fixture["delegated_control"],
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{REWARD_WALLET}",
            payload=fixture["reward_wallet"],
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{REWARD_WALLET}{TRANSACTIONS}"
            "?include=MILES_CHARGED&include=PAYOUT&include=PAYOUT_REFUNDED"
            "&include=BONUS_MILES",
            payload=fixture["reward_transactions"],
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{ENERGY_SUPPLIERS}",
            payload=fixture["energy_suppliers"],
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{REMOTE_LOCK}/{charger.ppid}",
            payload=fixture["remote_lock"],
        )
        mocked.get(
            f"{MOBILE_API_BASE_URL}{SUBSCRIPTIONS}",
            payload=fixture["subscriptions"],
        )

        async with aiohttp.ClientSession() as session:
            client = authenticated_client(session)
            delegated_chargers = await client.async_get_delegated_vehicles()
            delegated_control = await client.async_get_delegated_control(charger)
            wallet = await client.async_get_reward_wallet()
            transactions = await client.async_get_reward_transactions()
            suppliers = await client.async_get_energy_suppliers()
            remote_lock = await client.async_get_remote_lock(charger)
            subscriptions = await client.async_get_subscriptions()

    assert len(delegated_chargers) == 1
    assert isinstance(delegated_chargers[0], DelegatedCharger)
    vehicle_link = delegated_chargers[0].vehicles[0]
    assert vehicle_link.vehicle.charge_state.battery_level_percent == 50.0
    assert vehicle_link.intents.details[0]["dayOfWeek"] == "MONDAY"

    assert isinstance(delegated_control, DelegatedControl)
    assert delegated_control.status == "ACTIVE"
    assert delegated_control.preferences["maxPrice"] == 0.2

    assert isinstance(wallet, RewardWallet)
    assert wallet.rewards["balancePoints"] == 500

    assert isinstance(transactions, RewardTransactionPage)
    assert transactions.transactions[0].charge_id == "CHARGE-1"
    assert transactions.last_key == "CONTINUATION-1"

    assert isinstance(suppliers[0], EnergySupplier)
    assert suppliers[0].default_tariff_info[0].price == 0.1

    assert isinstance(remote_lock, RemoteLock)
    assert remote_lock.off_mode is None

    assert isinstance(subscriptions[0], Subscription)
    assert subscriptions[0].actions[0].data["ppid"] == "TEST-PPID-1"


def test_second_tranche_models_serialize_to_json():
    fixture = load_new_api_fixture()
    models = (
        DelegatedCharger(fixture["delegated_chargers"][0]),
        DelegatedControl(fixture["delegated_control"]),
        RewardWallet(fixture["reward_wallet"]),
        RewardTransactionPage(fixture["reward_transactions"]),
        EnergySupplier(fixture["energy_suppliers"][0]),
        RemoteLock(fixture["remote_lock"]),
        Subscription(fixture["subscriptions"]["data"][0]),
    )

    for model in models:
        assert isinstance(model.to_json(), str)
