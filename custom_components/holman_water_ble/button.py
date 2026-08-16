"""Button platform for Holman Water BLE actions."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER
from .coordinator import HolmanWaterCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up action button entities.

    Args:
        hass: Home Assistant instance.
        entry: Config entry.
        async_add_entities: Callback to add entities.
    """
    coordinator: HolmanWaterCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        HolmanReadDiagnosticsButton(coordinator, entry),
        HolmanClearPairingButton(coordinator, entry),
        HolmanPairButton(coordinator, entry),
    ]

    async_add_entities(entities)


class HolmanReadDiagnosticsButton(ButtonEntity):
    """Button to trigger a diagnostics read from the device."""

    def __init__(
        self,
        coordinator: HolmanWaterCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the diagnostics button.

        Args:
            coordinator: Device coordinator.
            entry: Config entry.
        """
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_read_diagnostics"
        self._attr_name = f"{coordinator.device_config.name} Read Diagnostics"
        self._attr_icon = "mdi:refresh"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        self._coordinator.register_state_update_callback(self._async_update)

    @property
    def available(self) -> bool:
        """Only available when device is paired and reachable."""
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

    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.debug("Reading diagnostics")
        await self._coordinator.read_diagnostics()

    def _async_update(self) -> None:
        """Callback from coordinator when state might have changed."""
        self.async_write_ha_state()


class HolmanClearPairingButton(ButtonEntity):
    """Button to clear the device pairing (unpair)."""

    def __init__(
        self,
        coordinator: HolmanWaterCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the clear pairing button.

        Args:
            coordinator: Device coordinator.
            entry: Config entry.
        """
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_clear_pairing"
        self._attr_name = f"{coordinator.device_config.name} Clear Pairing"
        self._attr_icon = "mdi:link-off"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        self._coordinator.register_state_update_callback(self._async_update)

    @property
    def available(self) -> bool:
        """Only available when device is paired."""
        return self._coordinator.paired

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._coordinator.mac_address)},
            name=self._coordinator.device_config.name,
            manufacturer=MANUFACTURER,
            model=self._coordinator.device_config.model,
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.warning("Clearing pairing for %s", self._coordinator.mac_address)
        await self._coordinator.unpair()

    def _async_update(self) -> None:
        """Callback from coordinator when state might have changed."""
        self.async_write_ha_state()


class HolmanPairButton(ButtonEntity):
    """Button to re-pair an unpaired device."""

    def __init__(
        self,
        coordinator: HolmanWaterCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the pair button.

        Args:
            coordinator: Device coordinator.
            entry: Config entry.
        """
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pair"
        self._attr_name = f"{coordinator.device_config.name} Pair"
        self._attr_icon = "mdi:link-variant"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        self._coordinator.register_state_update_callback(self._async_update)

    @property
    def available(self) -> bool:
        """Only available when device is NOT paired."""
        return not self._coordinator.paired

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._coordinator.mac_address)},
            name=self._coordinator.device_config.name,
            manufacturer=MANUFACTURER,
            model=self._coordinator.device_config.model,
        )

    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.info("Pairing device %s", self._coordinator.mac_address)
        await self._coordinator.re_pair()

    def _async_update(self) -> None:
        """Callback from coordinator when state might have changed."""
        self.async_write_ha_state()
