"""Switch platform for Holman Water BLE valves."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER
from .coordinator import HolmanWaterCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up valve switch entities.

    Args:
        hass: Home Assistant instance.
        entry: Config entry.
        async_add_entities: Callback to add entities.
    """
    coordinator: HolmanWaterCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for zone in range(1, coordinator.device_config.total_zones + 1):
        entities.append(HolmanValveSwitch(coordinator, entry, zone))

    async_add_entities(entities)


class HolmanValveSwitch(SwitchEntity):
    """Representation of a Holman Water valve switch."""

    def __init__(
        self,
        coordinator: HolmanWaterCoordinator,
        entry: ConfigEntry,
        zone: int,
    ) -> None:
        """Initialize the valve switch.

        Args:
            coordinator: Device coordinator.
            entry: Config entry.
            zone: 1-based zone number.
        """
        self._coordinator = coordinator
        self._entry = entry
        self._zone = zone
        self._attr_unique_id = f"{entry.entry_id}_valve_{zone}"
        self._attr_name = f"{coordinator.device_config.name} Valve {zone}"
        self._attr_icon = "mdi:valve"
        self._attr_should_poll = False

        # Register for state updates
        self._coordinator.register_state_update_callback(self._async_update)

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
    def is_on(self) -> bool:
        """Return whether the valve is watering."""
        return self._coordinator.is_watering(self._zone)

    @property
    def available(self) -> bool:
        """Return whether the device is available."""
        return self._coordinator.available

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the valve on (start watering).

        Args:
            kwargs: Additional arguments.
        """
        _LOGGER.debug("Turning on valve %d", self._zone)
        result = await self._coordinator.start_watering(self._zone)
        if result:
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the valve off (stop watering).

        Cancels the watering timer and sends the stop command.

        Args:
            kwargs: Additional arguments.
        """
        _LOGGER.debug("Turning off valve %d", self._zone)
        result = await self._coordinator.stop_watering(self._zone)
        if result:
            self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh state from the coordinator."""
        self.async_write_ha_state()

    def _async_update(self) -> None:
        """Callback from coordinator when state might have changed."""
        self.async_write_ha_state()
