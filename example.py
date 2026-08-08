"""Demonstrate the API-independent Pod Point charger domain interface."""

import argparse
import asyncio
import time
from typing import Optional

import aiohttp

from podpointclient.client import PodPointClient
from podpointclient.domain import CapabilitySupport, ChargerCapability
from podpointclient.errors import UnsupportedCapabilityError


def describe_capabilities(charger) -> None:
    """Print the explicitly known capability state for a charger."""
    print("  Capabilities:")
    for capability in ChargerCapability:
        support = charger.capability(capability)
        print(f"    {capability.value}: {support.value}")


async def describe_state(client: PodPointClient, charger) -> None:
    """Fetch and print normalized state without inspecting a wire API model."""
    if (
        charger.capability(ChargerCapability.CONNECTIVITY_STATE)
        is CapabilitySupport.UNSUPPORTED
    ):
        print("  Connectivity state is unsupported")
        return

    try:
        state = await client.async_get_charger_state(charger)
    except UnsupportedCapabilityError:
        print("  Connectivity state endpoint is unsupported")
        return

    connection = state.connection.value
    charging = state.charging.value
    print(f"  Connection: {connection.value if connection else 'unavailable'}")
    print(f"  Charging: {charging.value if charging else 'unavailable'}")
    if not state.connection.known and state.connection.raw is not None:
        print(f"    Raw connection state: {state.connection.raw}")
    if not state.charging.known and state.charging.raw is not None:
        print(f"    Raw charging state: {state.charging.raw}")


async def describe_firmware(client: PodPointClient, charger) -> None:
    """Read firmware through the unified legacy-backed domain operation."""
    support = charger.capability(ChargerCapability.FIRMWARE)
    if support is CapabilitySupport.UNSUPPORTED:
        print("  Firmware status is unsupported")
        return
    if support is CapabilitySupport.UNKNOWN:
        print("  Firmware status is not yet determined")
        return

    try:
        firmwares = await client.async_get_charger_firmware(charger)
    except UnsupportedCapabilityError:
        print("  Firmware endpoint is unsupported")
        return

    if not firmwares:
        print("  Firmware: no status returned")
        return
    for firmware in firmwares:
        print(f"  Firmware: {firmware.firmware_version or 'unknown'}")
        print(f"    Serial: {firmware.serial_number or 'unknown'}")
        print(f"    Update available: {firmware.update_available}")


async def demonstrate_boost(
    client: PodPointClient, charger, boost_minutes: int
) -> None:
    """Optionally start and then stop a domain-level timed boost."""
    if boost_minutes <= 0:
        print("Boost demo skipped; pass --boost-minutes to enable it")
        return
    if (
        charger.capability(ChargerCapability.TIMED_BOOST)
        is not CapabilitySupport.SUPPORTED
    ):
        print("Timed boosts are not confirmed as supported for this charger")
        return

    print(f"Starting a {boost_minutes}-minute boost for {charger.ppid}")
    started = False
    try:
        await client.async_start_boost(charger, minutes=boost_minutes)
        started = True
        print("  Boost started")
    except UnsupportedCapabilityError:
        print("  Boost endpoint is unsupported")
    finally:
        if started:
            print("Stopping the boost")
            await client.async_stop_boost(charger)
            print("  Boost stopped")


async def main(
    username: str,
    password: str,
    http_debug: bool = False,
    boost_minutes: int = 0,
) -> None:
    """Discover chargers and demonstrate source-independent operations."""
    print(f"Logging into Pod Point with email: {username}")
    async with aiohttp.ClientSession() as session:
        client = PodPointClient(
            username=username,
            password=password,
            session=session,
            http_debug=http_debug,
        )

        chargers = await client.async_discover_chargers()
        print(f"Found {len(chargers)} charger(s)")
        if not chargers:
            return

        for charger in chargers:
            print(f"\nCharger {charger.ppid}")
            print(f"  Model: {charger.model_name or 'unknown'}")
            print(f"  Unit ID: {charger.unit_id or 'unknown'}")
            print(f"  Timezone: {charger.timezone or 'unknown'}")
            print(f"  Linked/commissioned: {charger.linked_at or 'unknown'}")
            # Source is useful for diagnostics, but no operation branches on it.
            print(f"  Diagnostic source: {charger.source.value}")
            describe_capabilities(charger)
            await describe_state(client, charger)
            await describe_firmware(client, charger)

        await demonstrate_boost(client, chargers[0], boost_minutes)


def positive_minutes(value: str) -> int:
    """Parse a non-negative boost duration for argparse."""
    minutes = int(value)
    if minutes < 0:
        raise argparse.ArgumentTypeError("boost minutes must not be negative")
    return minutes


def parse_args(args: Optional[list] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Demonstrate the Pod Point domain-level charger API.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-e", "--email", required=True, help="Pod Point email")
    parser.add_argument("-p", "--password", required=True, help="Pod Point password")
    parser.add_argument(
        "-d", "--debug", action="store_true", help="Enable HTTP debugging"
    )
    parser.add_argument(
        "--boost-minutes",
        type=positive_minutes,
        default=0,
        help="Start and immediately stop a boost; 0 leaves the charger unchanged",
    )
    return parser.parse_args(args)


if __name__ == "__main__":
    cli_args = parse_args()
    print("-- Pod Point domain API example --")
    start = time.perf_counter()
    asyncio.run(
        main(
            username=cli_args.email,
            password=cli_args.password,
            http_debug=cli_args.debug,
            boost_minutes=cli_args.boost_minutes,
        )
    )
    print(f"\nScript executed in {time.perf_counter() - start:0.2f} seconds")
