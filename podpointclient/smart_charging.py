"""Smart-charging and delegated vehicle models."""
import json
from datetime import datetime
from typing import Any, Dict

from .helpers.functions import lazy_convert_to_datetime, lazy_iso_format_datetime


class VehicleInformation:
    """Descriptive information for a delegated vehicle."""

    def __init__(self, data: Dict[str, Any]):
        self.brand: str = data.get("brand", None)
        self.model: str = data.get("model", None)
        self.model_variant: str = data.get("modelVariant", None)
        self.vehicle_registration_plate: str = data.get("vehicleRegistrationPlate", None)
        self.colour: str = data.get("colour", None)
        self.display_name: str = data.get("displayName", None)
        self.display_name_source: str = data.get("displayNameSource", None)
        self.ev_database_id: str = data.get("evDatabaseId", None)

    @property
    def dict(self):
        return {
            "brand": self.brand,
            "model": self.model,
            "modelVariant": self.model_variant,
            "vehicleRegistrationPlate": self.vehicle_registration_plate,
            "colour": self.colour,
            "displayName": self.display_name,
            "displayNameSource": self.display_name_source,
            "evDatabaseId": self.ev_database_id,
        }


class VehicleChargeState:
    """Latest charge state reported for a delegated vehicle."""

    def __init__(self, data: Dict[str, Any]):
        self.battery_capacity: float = data.get("batteryCapacity", None)
        self.battery_level_percent: float = data.get("batteryLevelPercent", None)
        self.charge_limit_percent: float = data.get("chargeLimitPercent", None)
        self.charge_limit_source: str = data.get("chargeLimitSource", None)
        self.charge_rate = data.get("chargeRate", None)
        self.charge_time_remaining = data.get("chargeTimeRemaining", None)
        self.is_charging: bool = data.get("isCharging", None)
        self.is_fully_charged: bool = data.get("isFullyCharged", None)
        self.is_plugged_in: bool = data.get("isPluggedIn", None)
        self.last_updated: datetime = lazy_convert_to_datetime(data.get("lastUpdated", None))
        self.max_current = data.get("maxCurrent", None)
        self.power_delivery_state: str = data.get("powerDeliveryState", None)
        self.range: float = data.get("range", None)
        self.charge_limit_settable: bool = data.get("chargeLimitSettable", None)

    @property
    def dict(self):
        return {
            "batteryCapacity": self.battery_capacity,
            "batteryLevelPercent": self.battery_level_percent,
            "chargeLimitPercent": self.charge_limit_percent,
            "chargeLimitSource": self.charge_limit_source,
            "chargeRate": self.charge_rate,
            "chargeTimeRemaining": self.charge_time_remaining,
            "isCharging": self.is_charging,
            "isFullyCharged": self.is_fully_charged,
            "isPluggedIn": self.is_plugged_in,
            "lastUpdated": lazy_iso_format_datetime(self.last_updated),
            "maxCurrent": self.max_current,
            "powerDeliveryState": self.power_delivery_state,
            "range": self.range,
            "chargeLimitSettable": self.charge_limit_settable,
        }


class DelegatedVehicle:
    """Vehicle state supplied by the delegated-control provider."""

    def __init__(self, data: Dict[str, Any]):
        self.id: str = data.get("id", None)
        self.last_seen: datetime = lazy_convert_to_datetime(data.get("lastSeen", None))
        self.enode_user_id: str = data.get("enodeUserId", None)
        self.enode_vehicle_id: str = data.get("enodeVehicleId", None)
        self.refresh_requested: bool = data.get("refreshRequested", None)
        information = data.get("vehicleInformation") or {}
        self.vehicle_information = VehicleInformation(information)
        charge_state = data.get("chargeState") or {}
        self.charge_state = VehicleChargeState(charge_state)
        odometer = data.get("odometer") or {}
        self.odometer_distance_km: float = odometer.get("distanceKm", None)
        self.odometer_last_updated: datetime = lazy_convert_to_datetime(
            odometer.get("lastUpdated", None)
        )
        self.interventions: Dict[str, Any] = data.get("interventions", {})
        self.learned_battery_efficiency_factor: float = data.get(
            "learnedBatteryEfficiencyFactor", None
        )
        self.efficiency_session_count: int = data.get("efficiencySessionCount", None)

    @property
    def dict(self):
        return {
            "id": self.id,
            "lastSeen": lazy_iso_format_datetime(self.last_seen),
            "enodeUserId": self.enode_user_id,
            "enodeVehicleId": self.enode_vehicle_id,
            "refreshRequested": self.refresh_requested,
            "vehicleInformation": self.vehicle_information.dict,
            "chargeState": self.charge_state.dict,
            "odometer": {
                "distanceKm": self.odometer_distance_km,
                "lastUpdated": lazy_iso_format_datetime(self.odometer_last_updated),
            },
            "interventions": self.interventions,
            "learnedBatteryEfficiencyFactor": self.learned_battery_efficiency_factor,
            "efficiencySessionCount": self.efficiency_session_count,
        }


class VehicleIntent:
    """Recurring charging intent attached to a vehicle link."""

    def __init__(self, data: Dict[str, Any]):
        self.id: str = data.get("id", None)
        raw_details = data.get("details", data.get("intentDetails", []))
        self.intent_details = [VehicleIntentDetail(item) for item in raw_details]
        self.details = [item.dict for item in self.intent_details]
        self.delegated_control_charging_station_vehicle_id: str = data.get(
            "delegatedControlChargingStationVehicleId", None
        )
        self.max_price = data.get("maxPrice", None)
        self.created_at: datetime = lazy_convert_to_datetime(data.get("createdAt", None))
        self.updated_at: datetime = lazy_convert_to_datetime(data.get("updatedAt", None))

    @property
    def dict(self):
        return {
            "id": self.id,
            "details": self.details,
            "maxPrice": self.max_price,
            "createdAt": lazy_iso_format_datetime(self.created_at),
            "updatedAt": lazy_iso_format_datetime(self.updated_at),
        }


class VehicleIntentDetail:
    """A recurring charge target for one day of the week."""

    def __init__(self, data: Dict[str, Any]):
        self.charge_by_time: str = data.get("chargeByTime", None)
        self.charge_kwh: float = data.get("chargeKWh", None)
        self.day_of_week: str = data.get("dayOfWeek", None)

    @property
    def dict(self):
        return {
            "chargeByTime": self.charge_by_time,
            "chargeKWh": self.charge_kwh,
            "dayOfWeek": self.day_of_week,
        }


class DelegatedVehicleLink:
    """Relationship between a charger and delegated vehicle."""

    def __init__(self, data: Dict[str, Any]):
        self.id: str = data.get("id", None)
        self.is_plugged_in_to_this_charger: bool = data.get(
            "isPluggedInToThisCharger", None
        )
        vehicle = data.get("vehicle") or {}
        self.vehicle = DelegatedVehicle(vehicle)
        intents = data.get("intents")
        self.intents = VehicleIntent(intents) if intents else None
        self.current_intent: Dict[str, Any] = data.get("currentIntent", None)
        self.is_primary: bool = data.get("isPrimary", None)

    @property
    def dict(self):
        return {
            "id": self.id,
            "isPluggedInToThisCharger": self.is_plugged_in_to_this_charger,
            "vehicle": self.vehicle.dict,
            "intents": self.intents.dict if self.intents else None,
            "currentIntent": self.current_intent,
            "isPrimary": self.is_primary,
        }


class DelegatedCharger:
    """Charger and vehicle links returned by the delegated-vehicles endpoint."""

    def __init__(self, data: Dict[str, Any]):
        self.ppid: str = data.get("ppid", None)
        self.vehicles = [DelegatedVehicleLink(item) for item in data.get("vehicles", [])]

    @property
    def dict(self):
        return {
            "ppid": self.ppid,
            "vehicles": [vehicle.dict for vehicle in self.vehicles],
        }

    def to_json(self):
        """JSON representation of a DelegatedCharger object."""
        return json.dumps(self.dict, ensure_ascii=False)


class DelegatedControl:
    """Delegated smart-charging configuration for a charger."""

    def __init__(self, data: Dict[str, Any]):
        self.id: str = data.get("id", None)
        self.ppid: str = data.get("ppid", None)
        self.status: str = data.get("status", None)
        self.status_effective_from: datetime = lazy_convert_to_datetime(
            data.get("statusEffectiveFrom", None)
        )
        self.preferences: Dict[str, Any] = data.get("preferences", {})
        self.created_at: datetime = lazy_convert_to_datetime(data.get("createdAt", None))
        self.vehicle_links = [
            DelegatedVehicleLink(item) for item in data.get("vehicleLinks", [])
        ]
        self.third_party_manager_provider_id: str = data.get(
            "thirdPartyManagerProviderId", None
        )
        self.is_deletable: bool = data.get("isDeletable", None)

    @property
    def dict(self):
        return {
            "id": self.id,
            "ppid": self.ppid,
            "status": self.status,
            "statusEffectiveFrom": lazy_iso_format_datetime(self.status_effective_from),
            "preferences": self.preferences,
            "createdAt": lazy_iso_format_datetime(self.created_at),
            "vehicleLinks": [link.dict for link in self.vehicle_links],
            "thirdPartyManagerProviderId": self.third_party_manager_provider_id,
            "isDeletable": self.is_deletable,
        }

    def to_json(self):
        """JSON representation of a DelegatedControl object."""
        return json.dumps(self.dict, ensure_ascii=False)
