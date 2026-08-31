"""Config flow for Holman Water BLE integration."""

from __future__ import annotations

import logging
from typing import Any, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_MAC
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DEFAULT_DEVICE_NAME,
    DEVICE_TYPE_MAP,
    DOMAIN,
    MANUFACTURER,
    SERVICE_UUID,
)

_LOGGER = logging.getLogger(__name__)


class HolmanWaterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Holman Water BLE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: Optional[BluetoothServiceInfoBleak] = None
        self._mac_address: Optional[str] = None
        self._device_name: Optional[str] = None
        self._device_type: Optional[int] = None
        self._detect_attempted: bool = False

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the Bluetooth discovery step.

        Args:
            discovery_info: Bluetooth discovery information.

        Returns:
            Flow result.
        """
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self._mac_address = discovery_info.address
        self._device_name = discovery_info.name or DEFAULT_DEVICE_NAME

        # If we have manufacturer data, try to show more context
        # at the confirm step
        if self._discovery_info and self._discovery_info.manufacturer_data:
            for mfr_data in self._discovery_info.manufacturer_data.values():
                if len(mfr_data) > 33:
                    self._device_type = mfr_data[33]
                    break

        self.context["title_placeholders"] = {
            "name": self._device_name,
            "address": self._mac_address,
        }

        # Show a confirmation dialog instead of auto-creating.
        # This prevents the device from being re-added automatically after deletion.
        return await self.async_step_confirm()

    async def async_step_user(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the user step to pick from discovered devices.

        Args:
            user_input: User input from the form.

        Returns:
            Flow result.
        """
        if user_input is not None:
            mac = user_input[CONF_MAC]
            await self.async_set_unique_id(mac)
            self._abort_if_unique_id_configured()
            self._mac_address = mac
            self._device_name = user_input.get("name", DEFAULT_DEVICE_NAME)
            self._device_type = user_input.get("device_type")
            return await self.async_step_confirm()

        # Show discovered devices
        discovered = await self._async_get_discovered_devices()
        if not discovered:
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAC): vol.In(discovered),
                }
            ),
        )

    async def async_step_manual(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Handle manual MAC address entry.

        Args:
            user_input: User input from the form.

        Returns:
            Flow result.
        """
        if user_input is not None:
            mac = user_input[CONF_MAC]
            await self.async_set_unique_id(mac)
            self._abort_if_unique_id_configured()
            self._mac_address = mac
            self._device_name = user_input.get("name", DEFAULT_DEVICE_NAME)
            return await self.async_step_confirm()

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAC): str,
                    vol.Optional("name", default=DEFAULT_DEVICE_NAME): str,
                }
            ),
        )

    async def async_step_confirm(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Confirm the device setup.

        Args:
            user_input: User input from the form.

        Returns:
            Flow result.
        """
        if user_input is not None:
            return self._create_entry()

        # If the device type is unknown, connect to the device and read it
        # from the DEVICE_INFO characteristic before showing the confirm step.
        if not self._device_type or self._device_type not in DEVICE_TYPE_MAP:
            if not self._detect_attempted:
                return await self.async_step_detect()
            # Detection already attempted and failed; show the confirm form
            # with whatever info we have rather than looping back to detect.

        return self._show_confirm_form()

    def _show_confirm_form(self) -> FlowResult:
        """Show the confirm form with the currently known device info.

        Returns:
            The confirm flow form.
        """
        type_info = None
        if self._device_type and self._device_type in DEVICE_TYPE_MAP:
            type_info = DEVICE_TYPE_MAP[self._device_type]

        type_name = type_info[1] if type_info else "Unknown"
        zones_str = f"{type_info[2]} zone(s)" if type_info else "Unknown zones"
        if type_info:
            power_str = "AC-powered" if type_info[3] else "Battery-powered"
        else:
            power_str = "Unknown"

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._device_name or DEFAULT_DEVICE_NAME,
                "address": self._mac_address or "",
                "model": type_name,
                "zones": zones_str,
                "power": power_str,
            },
        )

    async def async_step_detect(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Connect to the device and detect its real device type.

        The advertisement manufacturer data is not always present or reliable,
        so when the type is unknown we connect to the device and read the
        DEVICE_INFO characteristic, which always reports the real type.

        Args:
            user_input: User input from the form.

        Returns:
            Flow result.
        """
        if user_input is not None:
            return self._create_entry()

        if not self._mac_address:
            return self.async_abort(reason="no_devices_found")

        self._detect_attempted = True

        # Connect to the device and read its real device type.
        detected_type = await self._detect_device_type()
        if detected_type is not None:
            self._device_type = detected_type
            _LOGGER.info(
                "Detected device type %d for %s",
                detected_type,
                self._mac_address,
            )
        else:
            _LOGGER.warning(
                "Could not detect device type for %s, falling back to generic config",
                self._mac_address,
            )

        return self._show_confirm_form()

    async def _detect_device_type(self) -> Optional[int]:
        """Connect to the device and read its device type.

        Returns:
            The device type id, or None if the device could not be reached.
        """
        from bleak import BleakScanner

        from .holman_ble import HolmanBLE

        try:
            ble_device = await BleakScanner.find_device_by_address(
                self._mac_address, timeout=10.0
            )
            if ble_device is None:
                _LOGGER.error(
                    "Could not find BLE device %s during config flow",
                    self._mac_address,
                )
                return None

            client = HolmanBLE(ble_device)
            if not await client.connect():
                _LOGGER.error(
                    "Could not connect to %s during config flow",
                    self._mac_address,
                )
                return None

            try:
                info = await client.read_device_info()
                if info is not None and info.device_type > 0:
                    return info.device_type
                _LOGGER.warning(
                    "Device %s did not report a valid device type",
                    self._mac_address,
                )
                return None
            finally:
                await client.disconnect()
        except Exception as exc:
            _LOGGER.error(
                "Failed to detect device type for %s: %s",
                self._mac_address,
                exc,
            )
            return None

    def _create_entry(self) -> FlowResult:
        """Create the config entry.

        Returns:
            Flow result for created entry.
        """
        data = {
            CONF_MAC: self._mac_address,
            "device_name": self._device_name or DEFAULT_DEVICE_NAME,
            "device_type": self._device_type or 0,
        }

        title = f"{self._device_name or DEFAULT_DEVICE_NAME} ({self._mac_address})"

        return self.async_create_entry(title=title, data=data)

    async def _async_get_discovered_devices(self) -> dict[str, str]:
        """Get discovered Holman Water BLE devices.

        Returns:
            Dictionary mapping MAC address to display name.
        """
        discovered = {}
        for info in async_discovered_service_info(self.hass):
            if SERVICE_UUID.lower() in [
                uuid.lower() for uuid in info.advertisement.service_uuids
            ]:
                name = info.name or DEFAULT_DEVICE_NAME
                discovered[info.address] = f"{name} ({info.address})"
        return discovered
