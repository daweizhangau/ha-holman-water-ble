"""Sensor platform for Holman Water BLE diagnostics."""

from __future__ import annotations

import logging
from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DIAL_POSITION_MAP, DOMAIN, MANUFACTURER
from .coordinator import HolmanWaterCoordinator

_LOGGER = logging.getLogger(__name__)

SENSOR_ICONS: dict[str, str] = {
    "battery_voltage": "mdi:battery-50",
    "voltage_dc": "mdi:lightning-bolt",
    "voltage_ac": "mdi:power-plug",
    "voltage_valve": "mdi:valve",
    "dial_position": "mdi:knob",
    "watering_status": "mdi:water",
    "rain_sensor": "mdi:weather-rainy",
    "active_station": "mdi:pipe-valve",
    "connected_valves": "mdi:pipe-valve",
    "firmware_version": "mdi:chip",
    "protocol_version": "mdi:code-tags",
    "diagnostic_byte": "mdi:bug",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up diagnostic sensor entities.

    Args:
        hass: Home Assistant instance.
        entry: Config entry.
        async_add_entities: Callback to add entities.
    """
    coordinator: HolmanWaterCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        HolmanDiagnosticSensor(
            coordinator,
            entry,
            "battery_voltage",
            "Battery Voltage",
            UnitOfElectricPotential.VOLT,
            lambda info: round(info.voltage_dc, 1) if info else None,
            numeric=True,
        ),
        HolmanDiagnosticSensor(
            coordinator,
            entry,
            "voltage_dc",
            "Voltage DC",
            UnitOfElectricPotential.VOLT,
            lambda info: round(info.voltage_dc, 1) if info else None,
            numeric=True,
        ),
        HolmanDiagnosticSensor(
            coordinator,
            entry,
            "voltage_ac",
            "Voltage AC",
            UnitOfElectricPotential.VOLT,
            lambda info: round(info.voltage_ac, 1) if info else None,
            numeric=True,
        ),
        HolmanDiagnosticSensor(
            coordinator,
            entry,
            "voltage_valve",
            "Voltage Valve",
            UnitOfElectricPotential.VOLT,
            lambda info: round(info.voltage_valve, 1) if info else None,
            numeric=True,
        ),
        HolmanDiagnosticSensor(
            coordinator,
            entry,
            "dial_position",
            "Dial Position",
            None,
            lambda info: DIAL_POSITION_MAP.get(
                info.dial_position, f"Unknown ({info.dial_position})"
            )
            if info
            else "—",
        ),
        HolmanDiagnosticSensor(
            coordinator,
            entry,
            "watering_status",
            "Watering Status",
            None,
            lambda info: "On" if info and info.is_watering else "Off",
        ),
        HolmanDiagnosticSensor(
            coordinator,
            entry,
            "rain_sensor",
            "Rain Sensor",
            None,
            lambda info: "Wet"
            if info and info.rain_sensor_wet
            else ("On" if info and info.rain_sensor_on else "Off"),
        ),
        HolmanDiagnosticSensor(
            coordinator,
            entry,
            "active_station",
            "Active Station",
            None,
            lambda info: info.active_station if info else None,
            numeric=True,
        ),
        HolmanDiagnosticSensor(
            coordinator,
            entry,
            "connected_valves",
            "Connected Valves",
            None,
            lambda info: info.connected_valves if info else None,
            numeric=True,
        ),
        HolmanDiagnosticSensor(
            coordinator,
            entry,
            "firmware_version",
            "Firmware Version",
            None,
            lambda info: info.firmware_version if info else None,
            numeric=True,
        ),
        HolmanDiagnosticSensor(
            coordinator,
            entry,
            "protocol_version",
            "Protocol Version",
            None,
            lambda info: info.protocol_version if info else None,
            numeric=True,
        ),
        HolmanDiagnosticSensor(
            coordinator,
            entry,
            "diagnostic_byte",
            "Diagnostic Byte",
            None,
            lambda info: info.diagnostic if info else None,
            numeric=True,
        ),
    ]

    async_add_entities(entities)


class HolmanDiagnosticSensor(SensorEntity):
    """Representation of a diagnostic sensor."""

    def __init__(
        self,
        coordinator: HolmanWaterCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        unit: Optional[str],
        value_fn: Any,
        numeric: bool = False,
    ) -> None:
        """Initialize the diagnostic sensor.

        Args:
            coordinator: Device coordinator.
            entry: Config entry.
            key: Unique key suffix.
            name: Display name.
            unit: Unit of measurement.
            value_fn: Function to extract value from DeviceInfo.
            numeric: Whether the sensor value is numeric (enables state class).
        """
        self._coordinator = coordinator
        self._entry = entry
        self._key = key
        self._value_fn = value_fn
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = f"{coordinator.device_config.name} {name}"
        self._attr_native_unit_of_measurement = unit
        self._attr_should_poll = False
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = SENSOR_ICONS.get(key)
        if numeric:
            self._attr_state_class = SensorStateClass.MEASUREMENT

        self._coordinator.register_state_update_callback(self._async_update)

    @property
    def available(self) -> bool:
        """Return whether the device is available."""
        return self._coordinator.available

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._coordinator.mac_address)},
            name=self._coordinator.device_config.name,
            manufacturer=MANUFACTURER,
            model=self._coordinator.device_config.model,
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        info = self._coordinator.device_info
        return self._value_fn(info)

    def _async_update(self) -> None:
        """Callback from coordinator when state might have changed."""
        self.async_write_ha_state()
