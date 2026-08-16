"""Number platform for Holman Water BLE watering duration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEFAULT_POLL_INTERVAL_HOURS,
    DEFAULT_WATERING_DURATION_MINUTES,
    DOMAIN,
    MANUFACTURER,
    MAX_POLL_INTERVAL_HOURS,
    MAX_WATERING_DURATION_MINUTES,
    MIN_POLL_INTERVAL_HOURS,
    MIN_WATERING_DURATION_MINUTES,
)
from .coordinator import HolmanWaterCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities.

    Args:
        hass: Home Assistant instance.
        entry: Config entry.
        async_add_entities: Callback to add entities.
    """
    coordinator: HolmanWaterCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for zone in range(1, coordinator.device_config.total_zones + 1):
        entities.append(HolmanWateringDuration(coordinator, entry, zone))

    # Add the poll interval entity
    entities.append(HolmanPollInterval(coordinator, entry))

    async_add_entities(entities)


class HolmanWateringDuration(NumberEntity):
    """Representation of a watering duration setting."""

    def __init__(
        self,
        coordinator: HolmanWaterCoordinator,
        entry: ConfigEntry,
        zone: int,
    ) -> None:
        """Initialize the watering duration number.

        Args:
            coordinator: Device coordinator.
            entry: Config entry.
            zone: 1-based zone number.
        """
        self._coordinator = coordinator
        self._entry = entry
        self._zone = zone
        self._attr_unique_id = f"{entry.entry_id}_duration_{zone}"
        self._attr_name = f"{coordinator.device_config.name} Valve {zone} Duration"
        self._attr_native_min_value = MIN_WATERING_DURATION_MINUTES
        self._attr_native_max_value = MAX_WATERING_DURATION_MINUTES
        self._attr_native_step = 1.0
        self._attr_native_unit_of_measurement = UnitOfTime.MINUTES
        self._attr_mode = NumberMode.SLIDER
        self._attr_icon = "mdi:timer-cog-outline"
        self._attr_native_value = float(
            coordinator.get_watering_duration(zone)
        )

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

    async def async_set_native_value(self, value: float) -> None:
        """Set the watering duration.

        Args:
            value: Duration in minutes.
        """
        duration = int(value)
        self._coordinator.set_watering_duration(self._zone, duration)
        self._attr_native_value = value
        self.async_write_ha_state()


class HolmanPollInterval(NumberEntity):
    """Representation of the periodic health check interval."""

    def __init__(
        self,
        coordinator: HolmanWaterCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the poll interval number.

        Args:
            coordinator: Device coordinator.
            entry: Config entry.
        """
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_poll_interval"
        self._attr_name = f"{coordinator.device_config.name} Poll Interval"
        self._attr_native_min_value = MIN_POLL_INTERVAL_HOURS
        self._attr_native_max_value = MAX_POLL_INTERVAL_HOURS
        self._attr_native_step = 1.0
        self._attr_native_unit_of_measurement = UnitOfTime.HOURS
        self._attr_mode = NumberMode.SLIDER
        self._attr_icon = "mdi:calendar-sync"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_value = float(
            coordinator.poll_interval_hours
        )

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

    async def async_set_native_value(self, value: float) -> None:
        """Set the poll interval.

        Args:
            value: Interval in hours.
        """
        hours = int(value)
        self._coordinator.set_poll_interval_hours(hours)
        self._attr_native_value = value
        self.async_write_ha_state()
