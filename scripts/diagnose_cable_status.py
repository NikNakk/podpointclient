#!/usr/bin/env python3
"""Compare Pod Point Home and legacy charger state without making changes."""

import argparse
import asyncio
from datetime import datetime, timezone
import getpass
import json
import os
from typing import Any

import aiohttp

from podpointclient import PodPointClient


def iso(value: Any) -> Any:
    """Make model values safe to include in JSON output."""
    return value.isoformat() if isinstance(value, datetime) else value


def home_payload(status: Any) -> dict[str, Any]:
    """Return the complete state exposed by connectivity-status-v2."""
    return {
        "connectionState": status.connection_state,
        "connectionQuality": status.connection_quality,
        "chargingState": status.charging_state,
        "lastSeenAt": iso(status.last_seen_at),
    }


def legacy_payload(status: Any) -> dict[str, Any]:
    """Return live state for every legacy EVSE and connector."""
    evses = []
    for evse in status.evses:
        connectivity = evse.connectivity_state
        offer = evse.energy_offer_status
        evses.append({
            "id": evse.id,
            "architecture": evse.architecture,
            "connectivityState": {
                "protocol": connectivity.protocol,
                "connectivityStatus": connectivity.connectivity_status,
                "signalStrength": connectivity.signal_strength,
                "lastMessageAt": iso(connectivity.last_message_at),
                "connectionStartedAt": iso(connectivity.connection_started_at),
                "connectionQuality": connectivity.connection_quality,
            },
            "connectors": [connector.dict for connector in evse.connectors],
            "energyOfferStatus": {
                "isOfferingEnergy": offer.is_offering_energy,
                "reason": offer.reason,
                "until": iso(offer.until),
                "randomDelay": offer.random_delay,
                "doNotCache": offer.do_not_cache,
            },
        })
    return {
        "ppid": status.ppid,
        "connectedComponents": status.connected_components,
        "evses": evses,
    }


def pod_snapshot(pod: Any) -> dict[str, Any]:
    """Return the status cached in legacy Pod discovery."""
    return {
        "lastContactAt": iso(pod.last_contact_at),
        "statuses": [status.dict for status in pod.statuses],
        "connectors": [connector.dict for connector in pod.unit_connectors],
    }


async def captured(call, transform) -> dict[str, Any]:
    """Capture one API read so a failure on one side does not hide the other."""
    try:
        value = await call()
        return {"ok": True, "data": transform(value)}
    # Diagnostic tool: a failure on one endpoint must not hide the other result.
    except Exception as error:  # pylint: disable=broad-exception-caught
        return {
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
        }


def findings(report: dict[str, Any]) -> list[str]:
    """Call out the most useful cross-API contradictions."""
    notes = []
    home = report["homeConnectivityV2"]
    legacy = report["legacyConnectivity"]
    if not home["ok"] or not legacy["ok"]:
        failed = []
        if not home["ok"]:
            failed.append("Home")
        if not legacy["ok"]:
            failed.append("legacy")
        notes.append(f"Could not compare both APIs ({', '.join(failed)} read failed).")
        return notes

    home_state = home["data"]["chargingState"]
    legacy_states = [
        connector["chargingState"]
        for evse in legacy["data"]["evses"]
        for connector in evse["connectors"]
    ]
    if home_state not in legacy_states:
        notes.append(
            "Charging-state mismatch: Home reports "
            f"{home_state!r}; legacy connector(s) report {legacy_states!r}."
        )
    if "CHARGING" in legacy_states and home_state != "CHARGING":
        notes.append(
            "Legacy live telemetry says CHARGING, so the Home compact state is "
            "probably stale or incorrectly aggregated."
        )

    offering = [
        evse["energyOfferStatus"]["isOfferingEnergy"]
        for evse in legacy["data"]["evses"]
    ]
    if "CHARGING" in legacy_states and True in offering:
        notes.append("Legacy connector and energy-offer telemetry both support active charging.")

    snapshot = report.get("legacyPodSnapshot")
    if snapshot:
        snapshot_states = [status["key_name"] for status in snapshot["statuses"]]
        if "charging" in snapshot_states:
            notes.append("The older Pod discovery snapshot also says charging.")
        if any(connector.get("has_cable") for connector in snapshot["connectors"]):
            notes.append(
                "Legacy has_cable describes a tethered charger, not whether a car "
                "is currently plugged in."
            )
    return notes


async def discover(client: PodPointClient) -> tuple[list[Any], list[Any]]:
    """Discover both representations independently."""
    home_result, legacy_result = await asyncio.gather(
        captured(client.async_get_chargers, lambda value: value),
        captured(client.async_get_all_pods, lambda value: value),
    )
    for name, result in (("Home", home_result), ("legacy", legacy_result)):
        if not result["ok"]:
            print(f"Warning: {name} discovery failed: {result['error']}")
    return (
        home_result.get("data", []),
        legacy_result.get("data", []),
    )


async def sample(client: PodPointClient, ppid: str, api_object: Any, pod: Any):
    """Take near-simultaneous read-only samples from both state endpoints."""
    home, legacy = await asyncio.gather(
        captured(
            lambda: client.async_get_connectivity_status_v2(api_object),
            home_payload,
        ),
        captured(
            lambda: client.async_get_connectivity_status(api_object),
            legacy_payload,
        ),
    )
    report = {
        "sampledAt": datetime.now(timezone.utc).isoformat(),
        "ppid": ppid,
        "homeConnectivityV2": home,
        "legacyConnectivity": legacy,
        "legacyPodSnapshot": pod_snapshot(pod) if pod is not None else None,
    }
    report["findings"] = findings(report)
    return report


def print_report(report: dict[str, Any], as_json: bool) -> None:
    """Print either machine-readable JSON Lines or readable diagnostics."""
    if as_json:
        print(json.dumps(report, separators=(",", ":")))
        return
    print(f"\n[{report['sampledAt']}] {report['ppid']}")
    print(json.dumps({
        "homeConnectivityV2": report["homeConnectivityV2"],
        "legacyConnectivity": report["legacyConnectivity"],
        "legacyPodSnapshot": report["legacyPodSnapshot"],
    }, indent=2))
    if report["findings"]:
        print("Findings:")
        for note in report["findings"]:
            print(f"  - {note}")


async def main(args: argparse.Namespace) -> None:
    """Run the requested number of read-only comparisons."""
    password = os.environ.get("PODPOINT_PASSWORD") or getpass.getpass(
        "Pod Point password: "
    )
    async with aiohttp.ClientSession() as session:
        client = PodPointClient(args.email, password, session=session)
        home_chargers, legacy_pods = await discover(client)

        objects = {item.ppid: item for item in legacy_pods}
        objects.update({item.ppid: item for item in home_chargers})
        pods = {item.ppid: item for item in legacy_pods}
        ppids = [args.ppid] if args.ppid else sorted(objects)
        if not ppids:
            raise SystemExit("No chargers were returned by either API.")
        missing = [ppid for ppid in ppids if ppid not in objects]
        if missing:
            raise SystemExit(f"Unknown PPID(s): {', '.join(missing)}")

        for iteration in range(args.count):
            reports = await asyncio.gather(*(
                sample(client, ppid, objects[ppid], pods.get(ppid))
                for ppid in ppids
            ))
            for report in reports:
                print_report(report, args.json)
            if iteration + 1 < args.count:
                await asyncio.sleep(args.interval)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Compare read-only cable/charging evidence from Pod Point's Home "
            "and legacy APIs."
        )
    )
    parser.add_argument(
        "--email", default=os.environ.get("PODPOINT_EMAIL"), required=False,
        help="account email (or set PODPOINT_EMAIL)",
    )
    parser.add_argument("--ppid", help="only sample this charger")
    parser.add_argument("--count", type=int, default=1, help="number of samples")
    parser.add_argument(
        "--interval", type=float, default=5.0, help="seconds between samples"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit one compact JSON object per sample"
    )
    args = parser.parse_args()
    if not args.email:
        parser.error("--email or PODPOINT_EMAIL is required")
    if args.count < 1:
        parser.error("--count must be at least 1")
    if args.interval < 0:
        parser.error("--interval cannot be negative")
    return args


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
