# Pod Point Client

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

![Project Maintenance][maintenance-shield]

_Unofficial API client for [Pod Point][pod_point_web] with a focus on home users._

This repository is a fork of [mattrayner/podpointclient][upstream] that adds
support for Pod Point's newer Home API, while retaining the original client
functionality. The original project and its maintainers deserve full credit for
the client on which this fork is based. See [Upstream and acknowledgement](#upstream-and-acknowledgement)
for links to the upstream repository.

## Installation

Python 3.12 or newer is required.

```bash
pip install podpointclient-niknakk
```

The distribution is named `podpointclient-niknakk`, while its Python import
package remains `podpointclient`. The `podpointclient` distribution on PyPI is
maintained by the upstream project and may not include this fork's Home API
additions. Do not install both distributions in the same environment because
they provide the same import package.

## Usage

### Domain-level charger API

For application code, the domain API provides stable charger identity,
capabilities, normalized results, scheduling, smart charging, tariffs, history,
and boost operations across both Pod Point wire APIs. It tries Home discovery
first and uses the legacy Pod API only when Home discovery is confirmed absent
(HTTP 404/410). Application code does not inspect `ChargerRef.source`, unwrap
`ChargerRef.raw`, or select endpoint-specific methods.

```python
from datetime import date

from podpointclient import (
    BasicChargingMode, CapabilitySupport, ChargerCapability,
    UnsupportedCapabilityError,
)

if not await client.async_charger_credentials_verified():
    raise RuntimeError("No chargers are accessible to this account")

chargers = await client.async_discover_chargers()
charger = chargers[0]  # ChargerRef; PPID is its stable identity

try:
    state = await client.async_get_charger_state(charger)
    boost = await client.async_get_active_boost(charger)
    tariffs = await client.async_get_charger_tariffs(charger)
    preferences = await client.async_get_charger_preferences(charger)
    remote_lock = await client.async_get_charger_remote_lock(charger)
    history = await client.async_get_charger_charge_history(
        charger, date(2026, 8, 1), date(2026, 8, 31)
    )
    basic_mode = await client.async_get_basic_charging_mode(charger)
except UnsupportedCapabilityError as error:
    print(f"{error.capability.value} is unavailable")

if charger.capability(ChargerCapability.TIMED_BOOST) is not CapabilitySupport.UNSUPPORTED:
    try:
        await client.async_start_boost(charger, hours=1)  # UNKNOWN is probed
        await client.async_stop_boost(charger)
    except UnsupportedCapabilityError:
        pass
```

Capability observations live in memory on the client's stable `domain` object:

- `UNKNOWN` means not yet probed or temporarily unavailable. Calls are allowed.
- A successful call changes the capability to `SUPPORTED`.
- HTTP 404/410 changes it to `UNSUPPORTED` and raises
  `UnsupportedCapabilityError` carrying the PPID and capability. Later calls
  fail immediately without another endpoint request.
- Authentication, transport, rate-limit, and unexpected API errors leave the
  observation unchanged and retain their original exception type.

`ChargerRef.capabilities` is an immutable snapshot; query the latest observation
with `charger.capability(...)`. Unknown state spellings retain their original
wire value and normalize safely to `StateValue.UNKNOWN`.

Delegated vehicles, charge history, and the reward wallet are account-level
features. Their support is exposed through
`client.account_capability(AccountCapability.X)`. This returns the same
`SUPPORTED`, `UNSUPPORTED`, or `UNKNOWN` semantics as charger capabilities,
without requiring consumers to access the domain implementation. Bulk grouping
methods fetch account data once and associate records by canonical PPID:

```python
vehicle_groups = await client.async_get_domain_delegated_vehicle_groups()
history_groups = await client.async_get_domain_charge_history_groups(
    chargers, date(2026, 8, 1), date(2026, 8, 31)
)
wallet = await client.async_get_account_reward_wallet()
```

New integrations should verify credentials with
`async_charger_credentials_verified()`. It authenticates through Home-first
domain discovery and only falls back to legacy Pods after a confirmed 404/410.
The older `async_credentials_verified()` remains available with its established
legacy-only behaviour.

### Completed and live charge sessions

Home history and legacy charges are complementary rather than permanent choices
based on how a charger was discovered. Home history is authoritative for
completed sessions, while the legacy recent-charge endpoint exposes
provisional sessions during charging:

```python
from podpointclient import reconcile_charge_sessions

# Fetch at startup and on a relatively slow reconciliation cadence.
completed = await client.async_get_completed_charge_sessions(
    chargers, date(2026, 8, 1), date(2026, 8, 31)
)

# Fetch more frequently only while chargers may have live sessions.
provisional = await client.async_get_live_charge_sessions(chargers)

sessions_by_ppid = {
    charger.ppid: reconcile_charge_sessions(
        completed[charger.ppid], provisional[charger.ppid]
    )
    for charger in chargers
}
```

Completed retrieval partitions mixed requests: Home references use one Home
history call and explicit legacy references use one legacy completed-history
call. If Home returns 404/410, that same single legacy fetch covers every
resolvable reference; other Home errors propagate without fallback. Live
retrieval resolves legacy Pod IDs to canonical PPIDs internally on first use,
retains known mappings in memory, and refreshes Pods if a later request contains
an unmapped PPID. It returns only active/incomplete records by default. Pass
`include_completed=True` when recent completed legacy records are explicitly
wanted.

Support is observed independently through
`AccountCapability.HOME_CHARGE_HISTORY` and
`AccountCapability.LEGACY_CHARGES`. A failure from one source does not invalidate
the other. This separation lets an integration retain its previously cached
completed or provisional data when an optional poll fails; the library does not
hide transient errors or impose a polling cadence.

Each `ChargeSession` identifies its namespace through `source`, using
`ChargeSessionSource.HOME_HISTORY`, `LEGACY`, or the backward-compatible
`UNKNOWN` default. `reconcile_charge_sessions()` deduplicates completed
sessions, replaces matching legacy provisional sessions with authoritative
completed records, and retains unmatched live sessions. Matching never crosses
PPIDs. Equal IDs are authoritative only inside the same known source namespace;
Home-to-legacy matching uses start times within a configurable 60-second
tolerance.

### Persistent basic charging mode

For both Home and legacy chargers, `async_get_basic_charging_mode()` returns
`BasicChargingMode.SCHEDULED`, `ALWAYS_ON`, or `TIMED_BOOST` from active override
state. The mapping is inactive boost to `SCHEDULED`, active open-ended boost to
`ALWAYS_ON`, and active timed boost to `TIMED_BOOST`. If the integration already
fetched `BoostState`, pass it as `boost_state=` to derive the mode without a
second request:

```python
boost = await client.async_get_active_boost(charger)
mode = await client.async_get_basic_charging_mode(charger, boost_state=boost)
```

Persistent transitions remain Home-only and use the canonical reference:

```python
await client.async_set_basic_charging_mode(
    charger, BasicChargingMode.ALWAYS_ON
)
await client.async_set_basic_charging_mode(
    charger, BasicChargingMode.SCHEDULED
)
```

`TIMED_BOOST` and `UNKNOWN` are observations and cannot be set through this
persistent-mode method. The existing smart-charging prerequisite checks remain
in force. A legacy set attempt raises `UnsupportedCapabilityError`; legacy mode
reads remain supported.

### Canonical schedules

Both Pod Point APIs expose the same underlying seven schedule records. Use
`async_get_charger_schedules(charger)` to receive `ChargerSchedule` entries
without selecting an API. Home-backed canonical chargers fetch the manual
schedule endpoint; legacy-backed chargers reuse the schedule snapshot retained
during discovery. Rediscover legacy chargers during a polling cycle to obtain a
new snapshot, or pass `refresh=True` for an explicit out-of-cycle refresh.

`ChargerSchedule` normalizes `start_day`, `start_time`, `end_day`, `end_time`,
and `is_active`. It also retains `uid` for endpoint round trips and diagnostics,
but replacement regenerates all seven UIDs. Equality therefore ignores `uid`;
do not use it as stable weekday or schedule identity.

Full read-modify-replace is supported for Home-backed canonical chargers:

```python
from dataclasses import replace

schedules = await client.async_get_charger_schedules(charger)
schedules[0] = replace(schedules[0], is_active=False)
saved = await client.async_replace_charger_schedules(charger, schedules)
```

Replacement requires all seven entries, including their fetched UIDs, and
delegated smart charging must be inactive. A legacy-backed canonical charger
raises `UnsupportedCapabilityError` for full replacement because the legacy
write endpoint only supports its historical all-week enable/disable reset.
That narrower operation remains available as
`async_set_charger_legacy_schedule(charger, enabled)`.

Validation permits one same-day or cross-midnight interval starting on each
day. An interval may end only on its start day or the immediately following day
and may not exceed 24 hours. A cross-midnight end must be no later than the
following day's start, including Sunday-to-Monday; equal boundary times are
valid. Invalid collections raise `RequestValidationError` rather than being
silently adjusted.

The endpoint-specific `async_get_charger_legacy_schedules(charger)` continues
to return the retained legacy snapshot without a duplicate Pod request.
Schedule values are not retained in a separate long-lived cache.

Boost reads return `BoostState`; charge history returns `ChargeSession`. These
small canonical models normalize the fields that differ between APIs while
retaining the raw source response for diagnostics. Tariffs, delegated controls,
preferences, remote locks, vehicles, and firmware continue
to return their focused endpoint models because those feature schemas do not
need false cross-API equivalents.

The endpoint-specific API remains fully supported. Existing `Pod`, `Charger`,
`ConnectivityStatusV2`, `ChargerChargeOverride`, and all existing client methods
are unchanged for callers that need wire-level data.

### API reference

#### Canonical domain API

These are the recommended methods for integrations. They accept canonical
`ChargerRef` objects, select the appropriate wire API inside the library, and
return canonical results where the Home and legacy representations differ.
Consumers using this section do not need to inspect `ChargerRef.raw` or branch
on its source.

Method | Description
---|---
`async_discover_chargers()` | *Discover canonical `ChargerRef` objects through Home-first, confirmed-unsupported fallback.*
`async_charger_credentials_verified()` | *Verify charger access using domain Home-first discovery.*
`async_start_boost(charger, hours=0, minutes=0, seconds=0)` | *Start a timed boost without selecting a wire API.*
`async_stop_boost(charger)` | *Stop active boosts without selecting a wire API.*
`async_get_active_boost(charger)` | *Get canonical active, timed, or open-ended `BoostState`.*
`account_capability(capability)` | *Get tri-state support for an account-level capability.*
`async_get_basic_charging_mode(charger, boost_state=None)` | *Get scheduled, always-on, or timed-boost basic mode across both APIs.*
`async_set_basic_charging_mode(charger, mode)` | *Set persistent scheduled or always-on Home basic mode.*
`async_get_charger_schedules(charger, refresh=False)` | *Get canonical schedule entries through either backing API.*
`async_replace_charger_schedules(charger, schedules)` | *Replace all seven schedules for a Home-backed canonical charger.*
`async_get_charger_state(charger)` | *Get normalized state, last-seen time, legacy RSSI, and source-qualified connection quality.*
`async_get_charger_firmware(charger)` | *Get firmware through the legacy unit endpoint for any canonical charger.*
`async_get_charger_legacy_schedules(charger, refresh=False)` | *Get the discovery schedule snapshot without a duplicate request, with explicit refresh available.*
`async_get_charger_manual_schedules(charger)` | *Get Home manual/basic schedules.*
`async_replace_charger_manual_schedules(charger, schedules)` | *Replace Home manual/basic schedules.*
`async_get_charger_smart_charging(charger)` | *Get delegated smart-charging configuration.*
`async_set_domain_smart_charging(charger, enabled)` | *Enable or disable delegated smart charging.*
`async_get_charger_preferences(charger)` | *Get smart-charging preferences.*
`async_set_charger_max_price(charger, max_price)` | *Update the smart-charging maximum price.*
`async_get_charger_tariffs(charger)` | *Get charger tariffs.*
`async_get_charger_remote_lock(charger)` | *Get remote lock/off-mode state.*
`async_get_charger_delegated_vehicles(charger)` | *Get account records associated with one PPID.*
`async_get_charger_charge_history(charger, from_date, to_date)` | *Get canonical `ChargeSession` records.*
`async_get_completed_charge_sessions(chargers, from_date, to_date)` | *Get grouped authoritative completed history with confirmed-absence fallback.*
`async_get_live_charge_sessions(chargers)` | *Get grouped legacy provisional/live sessions independently.*
`async_get_account_reward_wallet()` | *Get reward wallet with account capability semantics.*

#### Legacy Pod API

These endpoint-specific compatibility methods use legacy `Pod` models and
legacy response types. Existing consumers can continue to use them, but new
integrations should prefer the canonical methods above when an equivalent is
available.

Method | Description
---|---
`async_credentials_verified()` | *Verify that the credentials can retrieve at least one legacy Pod* - Returns `bool`.
`async_get_all_pods(includes=[])` | *Get all pods from a user's account* - Returns a list of `Pod` objects. Optional `includes` can be used to change what will be returned. Defaults to all data.
`async_get_pods(perpage=5, page=2, includes=[])` | *Get pods from a user's account* - Returns a list of `Pod` objects. `perpage` can be 'all', or a number. Can get additional pages with `page` attribute. `includes` is a list of additional information pulled for the Pod. Pass an empty list to `includes` for minimal information or `None` for full data (defaults to `None`).
`async_get_pod(pod_id=1234)` | *Gets an individual pod* - Returns a single `Pod`. *_NOTE: The Pod Point API does not support a single-pod return so this method gets all pods and filters._*
`async_set_schedule(enabled=False, pod=pod)` | *Updates a pod with a week of schedules that will enable or disable charging* - See setting charging schedules for more information on how this works.
`async_get_all_charges()` | *Get all charges from a user's account* - Returns a list of `Charge` objects.
`async_get_charges(perpage=5, page=2)` | *Get charges for a user* - Returns a list of `Charge` objects. `perpage` can be 'all', or a number. Can get additional pages with `page` attribute.
`async_get_firmware(pod=_Pod_)` | *Get firmware information for a pod* - Returns a list of `Firmware` objects.
`async_get_user(includes=[])` | *Get current user account information* - Returns a `User` object including account balance, units and vehicles. `includes` is a list of additional information pulled for a User. Pass an empty list to `includes` for minimal information or `None` for full data (defaults to `None`)
`async_get_charge_override(pod=_Pod_)` | *Get the current charge override for a pod* - Returns a `ChargeOverride` object.
`async_set_charge_override(pod=_Pod_, hours=0, minutes=0, seconds=0)` | *Set a timed charge override for a pod* - Returns a `ChargeOverride` object.
`async_delete_charge_override(pod=_Pod_)` | *Delete a charge override for a pod* - Returns a boolean.
`async_set_charge_mode_manual(pod=_Pod_)` | *Set a pod to manual charge mode* - Returns a boolean.
`async_set_charge_mode_smart(pod=_Pod_)` | *Set a pod to smart charge mode* - Returns a boolean.
`async_get_connectivity_status(pod=_Pod_)` | *Get the current connection status for a pod* - Returns a `ConnectivityStatus` object.

#### Home API

These endpoint-specific methods use newer Home API `Charger` models and Home
response types. They remain available for consumers that need functionality or
wire-level detail not represented by the canonical API.

Method | Description
---|---
`async_get_chargers()` | *Get chargers from the newer charger API* - Returns a list of `Charger` objects.
`async_get_charger(ppid="ABC-123456")` | *Get a charger by PPID* - Returns a `Charger` object or `None`.
`async_get_connectivity_status_v2(charger=_Charger_)` | *Get compact connectivity and charging state for a charger* - Returns a `ConnectivityStatusV2` object.
`async_get_tariffs(charger=_Charger_)` | *Get tariffs associated with a charger* - Returns a list of `Tariff` objects.
`async_get_manual_schedules(charger=_Charger_)` | *Get manual charging schedules associated with a charger* - Returns a list of `ManualSchedule` objects.
`async_set_manual_schedules(charger=_Charger_, schedules=[...])` | *Replace all seven manual charging schedules* - Returns the saved `ManualSchedule` objects.
`async_get_security_logs(charger=_Charger_, page_number=1)` | *Get charger security logs and pagination information* - Returns a `SecurityLogPage` object.
`async_get_charger_subscriptions(charger=_Charger_)` | *Get subscriptions associated with a charger* - Returns a list of `ChargerSubscription` objects.
`async_get_user_access_status()` | *Get the current user's charger access statuses* - Returns a list of `UserAccessStatus` objects.
`async_get_user_agreements()` | *Get the current user's accepted agreement versions* - Returns a `UserAgreements` object.
`async_get_delegated_vehicles()` | *Get chargers and vehicles using delegated smart charging* - Returns a list of `DelegatedCharger` objects.
`async_get_delegated_control(charger=_Charger_)` | *Get delegated smart-charging configuration for a charger* - Returns a `DelegatedControl` object.
`async_get_reward_wallet()` | *Get the current user's reward allowance, earnings, and payment totals* - Returns a `RewardWallet` object.
`async_get_reward_transactions(includes=None)` | *Get reward wallet transactions, optionally filtered by event types* - Returns a `RewardTransactionPage` object.
`async_get_energy_suppliers()` | *Get energy suppliers and their default tariff configuration* - Returns a list of `EnergySupplier` objects.
`async_get_remote_lock(charger=_Charger_)` | *Get remote lock/off-mode state for a charger* - Returns a `RemoteLock` object.
`async_get_subscriptions()` | *Get account subscriptions and their workflow state* - Returns a list of `Subscription` objects.
`async_get_charger_charge_overrides(charger=_Charger_, active_only=False)` | *Get current and deleted charger override history* - Returns a list of `ChargerChargeOverride` objects.
`async_get_smart_charging_preferences(charger=_Charger_)` | *Get mutable smart-charging preferences* - Returns a `SmartChargingPreferences` object.
`async_get_charge_history(from_date, to_date)` | *Get newer charger-centric charge history for a date range* - Returns a `ChargeHistory` object.
`async_get_charge_stats(from_date, to_date, interval="month")` | *Get aggregate and interval charge statistics* - Returns a `ChargeStats` object.
`async_get_notification_preferences()` | *Get the current user's notification switches* - Returns a `NotificationPreferences` object.
`async_create_charger_charge_override(charger, hours=0, minutes=0, seconds=0)` | *Create a timed charger override* - Returns a list of `ChargerChargeOverride` objects.
`async_delete_charger_charge_overrides(charger)` | *Delete active charger overrides* - Returns a boolean.
`async_set_charger_charge_mode_always_on(charger)` | *When smart charging is inactive, enable basic charging indefinitely using an open-ended override* - Returns a list of `ChargerChargeOverride` objects.
`async_set_charger_charge_mode_scheduled(charger)` | *When smart charging is inactive, end Always On and return to configured manual schedules* - Returns a boolean.
`async_set_charger_smart_charging(charger, enabled)` | *Enable or disable delegated smart charging explicitly* - Returns a boolean.
`async_set_vehicle_intents(charger, vehicle_link_id, intents)` | *Replace recurring delegated-vehicle charging targets* - Returns a `VehicleIntent` object.
`async_set_smart_charging_max_price(charger, max_price)` | *Set the smart-charging maximum unit price* - Returns a boolean.
`async_set_tariff(charger, supplier_id, tariff_info, effective_from, timezone_name)` | *Create or replace the charger's energy tariff* - Returns a `Tariff` object.

The charger mutation methods validate their inputs before making a request. They
raise `RequestValidationError` for invalid durations, dates, times, weekdays,
prices, or timezone names. Smart-charging updates first check the current status
and avoid sending a redundant update that the API would reject.

### Example

Included in the project is `example.py`, which demonstrates the domain-level
API without branching between `Pod` and `Charger`. It:

1. Discovers canonical chargers using Home-first fallback.
1. Prints identity and explicit capability states.
1. Gets normalized connectivity and charging state.
1. Gets firmware status through the unified legacy-backed operation.
1. Optionally starts and immediately stops a timed boost.

> You must provide your email address and password to the script as detailed below:

```bash
python3 example.py --email PODPOINTEMAIL --password PODPOINTPASSWORD
```

The example is read-only by default. To demonstrate unified boost dispatch for
the first charger, explicitly pass a duration:

```bash
python3 example.py --email PODPOINTEMAIL --password PODPOINTPASSWORD --boost-minutes 5
```

### Setting charging schedules

> **NOTE:** According to Pod Point, schedules can take up to 5 minutes to be recognised by a device. This applies to both updating of a schedule affecting a device, and the device recognising that it is active/inactive due to entering/exiting a schedule window.

Currently this client supports setting the same schedule across all days for the week. By default it is designed to be used as an on/off switch for charging and creates a schedule lasting 1 second, from 00:00:00 - 00:00:01.

Due to the delay in pods recognising that they are in/out of a schedule this realistically means charging is turned off when this schedule is enabled.

You are able to pass a start_time and end_time when setting schedules but these are set for all days and are in-day only. By which I mean passing `start_time="18:00"` and `end_time="00:15"` will fail as `00:15` is before the start time.


## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md).

## Upstream and acknowledgement

This fork is based on [Matt Rayner's original Pod Point Client][upstream]. For
the upstream source, releases, issues, and documentation, visit the
[upstream repository][upstream]. Changes specific to the newer Home API are
maintained in [this fork][pod_point_client]. If and when these new changes are incoproated into upstream, this fork will be deprecated.

You can also support the original maintainer here:
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

[pod_point_web]: https://pod-point.com
[pod_point_client]: https://github.com/NikNakk/podpointclient
[upstream]: https://github.com/mattrayner/podpointclient
[buymecoffee]: https://www.buymeacoffee.com/mattrayner
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/y/NikNakk/podpointclient.svg?style=for-the-badge
[commits]: https://github.com/NikNakk/podpointclient/commits/main
[license-shield]: https://img.shields.io/github/license/NikNakk/podpointclient.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-NikNakk-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/v/release/NikNakk/podpointclient?include_prereleases&style=for-the-badge
[releases]: https://github.com/NikNakk/podpointclient/releases
