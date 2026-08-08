# Pod Point Client Changelog

## v1.7.0b9

* Avoid a redundant legacy Pod request by returning schedules retained by
  charger discovery, while retaining explicit and rediscovery-based refreshes.
* Expose tri-state account capability observations directly on
  `PodPointClient`.
* Derive canonical basic charging mode from Home or legacy `BoostState`, with
  optional state reuse to avoid duplicate override requests.

## v1.7.0b8

* Exclude unfinished Home-history records from canonical completed-session
  results.
* Add canonical last-seen and legacy RSSI diagnostics while retaining Home and
  legacy connection-quality values as separate, source-qualified measurements.

## v1.7.0b6

* Resolve live legacy charge sessions through a pod's unit ID while retaining
  pod-ID matching for completed legacy history.
* Publish validated wheel and source artifacts as a GitHub prerelease after a
  successful PyPI release.

## v1.7.0b5

* Qualify canonical charge-session IDs with explicit Home-history, legacy, or
  unknown source namespaces.
* Refresh legacy Pod-ID mappings when a later request contains a newly linked
  charger PPID.
* Partition and merge mixed Home/legacy completed-history requests while
  retaining independent source capability observations.
* Move package metadata to PEP 621, using an SPDX MIT license expression while
  removing the legacy `setup.py` entry point.
* Require Python 3.12 and replace `async-timeout`, third-party `StrEnum`, and
  `pytz` compatibility dependencies with standard-library equivalents, using
  Python's first-party `tzdata` package as a cross-platform timezone database.
* Clean up runtime pylint findings and enforce a clean pylint run in CI.

## v1.7.0b4

* Add Home-first domain credential verification for Home-only accounts.
* Treat Home completed history and legacy live charges as independently
  observed, complementary account capabilities.
* Add grouped completed and provisional session retrieval with deferred,
  in-memory legacy Pod-ID-to-PPID resolution.
* Add deterministic canonical charge-session reconciliation.
* Add canonical scheduled, always-on, and timed-boost basic charging modes.

## v1.7.0b3

* Retain runtime charger and account capability observations on a stable domain
  instance, with immutable public capability snapshots.
* Apply centralized 404/410 unsupported handling to every domain operation.
* Add domain operations for overrides, schedules, delegated smart charging,
  preferences, tariffs, remote lock, vehicles, history, and reward wallet.
* Add canonical `BoostState` and `ChargeSession` results and bulk account
  grouping by canonical PPID.
* Validate that every canonical charger has a non-empty PPID and normalize the
  complete known state vocabulary.

## v1.7.0b2

* Add a backward-compatible domain charger facade with canonical PPID identity.
* Add explicit tri-state capabilities and safe state normalization.
* Add Home-first discovery with legacy fallback only for HTTP 404/410.
* Add unified timed boost start/stop and connectivity state operations.
* Add unified firmware reads through the legacy unit endpoint for both charger sources.
* Add typed unsupported-capability errors and reliable API status extraction.
* Publish the maintained fork as the `podpointclient-niknakk` distribution,
  retaining Matthew Rayner as original author and Nick Kennedy as maintainer.
* Replace token-based release automation with PyPI Trusted Publishing.

## v1.6.0

* Add getting connection status from API:
  * `Client.async_get_connection_status` - @mattrayner
* Add support for charge override deletion:
  * Add `Client.async_delete_charge_override` - @mattrayner
* Add `ConnectivityStatus` - @mattrayner
* Add `Pod.offering_energy` - @mattrayner
* Add `Pod.last_message_at` - @mattrayner
* Add `Pod.charging_state` - @mattrayner
* Add `SUSPENDED_EV` to Pod state Enums - @mattrayner

## v1.5.0

* Add support for refreshing expired tokens, rather than grabbing new ones each time
* Update example.py to demonstrate token expiry

## v1.4.3

* Remove additional / from pod point api calls

## v1.4.2

* Fix an issue with `Session` inside of `Auth` causing token re-authentication to fail

## v1.4.1

* Add additional debug logs for testing new google auth

## v1.4.0

* Update auth system to new Google-based auth from Pod Point

## v1.3.1

* Add `pytz` as a dependency
* Fix `Pod.charge_mode` bug

## v1.3.0

* Migrate to API v5 - @mattrayner
* Add support for charge overrides:
  * Add `ChargeMode` enum - @mattrayner
  * Add `ChargeOverride` - @mattrayner
  * Add `Client.async_get_charge_override` - @mattrayner
  * Add `Client.async_set_charge_override` - @mattrayner
  * Add `Client.async_set_charge_mode_manual` - @mattrayner
  * Add `Client.async_set_charge_mode_smart` - @mattrayner
  * Add `Pod.charge_override` - @mattrayner
  * Add `Pod.charge_mode` - @mattrayner
* Add api wrapper delete support

## v1.2.0

* Add `User` - @mattrayner
* Add `Client.async_get_user_info` - @mattrayner

## v1.1.0

* Add `Firmware` to `Pod` - @mattrayner
* Add `Client.async_get_firmware` call - @mattrayner

## v1.0.0

* Add lightweight credential verification call - @mattrayner
* Add support for pagination rather than just adding 'perpage=all' - @mattrayner
* Updated README with new instructions - @mattrayner
* Fixed GitHub Actions - @mattrayner
  * Added code coverage artifacts, so you can download the cov report for a run
* Refactored code to improve dryness - @mattrayner
* Added additional testing dependencies - @mattrayner
* Add CD pipeline, when a new tag/release is pushed, auto-publish to PyPi - @mattrayner

## v0.3.0

* Add http_debug flag - @mattrayner
* When enabled, complete response bodies will be sent to logger.debug
* Restructured helpers and other classes so that they made more sense - @mattrayner
* Completed a pylon pass to standardize the code base - @mattrayner
* Improved test coverage - @mattrayner

## v0.2.2

* Make timestamp=XXX optional, and off by default
* Greatly improve test coverage

## v0.2.1

* Add charge duration seconds to Charge allowing for more granular tracking of charging time

## v0.2.0

* Add `ChargeDuration` to `Charge` as `charge.charge_duration`
  * Charge duration is the amount of time during a charge 'session' spent delivering power. Available as `raw` int duration and as `formatted` value e.g. '1 hour 32 minutes', '<5 minutes', '2 hours 5 minutes' etc.
  * String-ing a ChargeDuration returns the formatted string and Int-ing a ChargeDuration returns the raw value

## v0.1.3

* Stop supressing `AuthError` and `SessionError`. This allows upstream clients to correctly handle these.

## v0.1.2

* Add placeholder values for pods:
  * `.total_kwh`
  * `.current_kwh`
  * `.charges`

## v0.1.1

* Add `.home` attribute to `Pod` objects

## v0.1.0

* Add 'Charges' functionality
* Update README

## v0.0.9

* Fix issues with imports and testing

## v0.0.1

* Initial client with basic functionality for Home Assistant component
  * Get all user pods
  * Update schedules

* Created initial mapping classes:
  * Pod
  * Schedule
  * Charge

* Added initial base test coverage

* Setup initial README

* Added MIT License

* Created CHANGELOG
