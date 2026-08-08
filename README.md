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

```bash
pip install "podpointclient @ git+https://github.com/NikNakk/podpointclient.git"
```

The `podpointclient` package from PyPI is maintained by the upstream project
and may not include this fork's Home API additions.

## Usage

The [Pod Point Client][pod_point_client] supports the following methods:

Method | Description
---|---
`async_credentials_verified()` | *Verify that the credentials we have can pull _atleast_ one Pod* - Returns `bool`.
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

Included in the project is `example.py` which walks through a common scenario: 

1. Get all pods
1. Get firmware and serial number data for one pod
1. Updating the schedule of an individual pod
1. Confirm that it worked
1. Get information from the last charge

> You must provide your email address and password to the script as detailed below:

```bash
python3 example.py --email PODPOINTEMAIL --password PODPOINTPASSWORD
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
