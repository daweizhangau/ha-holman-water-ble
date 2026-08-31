"""Init for Holman Water BLE integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from .const import (
    DEFAULT_DEVICE_NAME,
    DEVICE_TYPE_MAP,
    DOMAIN,
    MANUFACTURER,
    PLATFORMS,
    SERVICE_UNPAIR,
)
from .coordinator import HolmanWaterCoordinator
from .models import DeviceConfig

_LOGGER = logging.getLogger(__name__)


def _device_config_from_type(device_type: int) -> DeviceConfig:
    """Build a DeviceConfig from a known device type.

    Args:
        device_type: A device type id present in DEVICE_TYPE_MAP.

    Returns:
        The DeviceConfig for that device type.
    """
    type_info = DEVICE_TYPE_MAP[device_type]
    return DeviceConfig(
        model=type_info[0],
        name=type_info[1],
        total_zones=type_info[2],
        is_ac_device=type_info[3],
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Holman Water BLE from a config entry.

    The device type is only known once the device has answered a diagnostics
    read. Until then we must NOT assume a model: we set up with the minimum
    (a single generic zone) and self-heal to the real device once its type is
    read from the DEVICE_INFO characteristic.

    Args:
        hass: Home Assistant instance.
        entry: Config entry for this device.

    Returns:
        True if setup was successful.
    """
    mac_address: str = entry.data[CONF_MAC]
    stored_type: int = entry.data.get("device_type", 0)
    device_name: str = entry.data.get("device_name", DEFAULT_DEVICE_NAME)

    # No assumptions: unknown type -> generic one-zone config, not a model.
    if stored_type in DEVICE_TYPE_MAP:
        device_config = _device_config_from_type(stored_type)
    else:
        _LOGGER.info(
            "Device type unknown for %s, setting up with generic single-zone "
            "config until diagnostics are read",
            mac_address,
        )
        device_config = DeviceConfig(
            model="",
            name=DEFAULT_DEVICE_NAME,
            total_zones=1,
            is_ac_device=False,
        )

    # Create a BLEDevice-like object from the MAC address
    # We need to resolve the BLE device at runtime
    from bleak import BleakScanner

    ble_device = await BleakScanner.find_device_by_address(
        mac_address, timeout=10.0
    )

    if ble_device is None:
        _LOGGER.error(
            "Could not find BLE device %s. "
            "Make sure it is powered on and in range.",
            mac_address,
        )
        return False

    coordinator = HolmanWaterCoordinator(
        ble_device=ble_device,
        device_config=device_config,
        hass_config_dir=hass.config.path(),
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Register device in device registry. Model/sw_version are only set when
    # the device type is actually known; an unknown type registers a generic
    # entry that gets enriched by the self-heal path below.
    device_registry = dr.async_get(hass)
    _register_device_in_registry(
        device_registry,
        entry,
        mac_address,
        device_name,
        device_config,
        stored_type,
    )
    # async_get_or_create does not rewrite model/sw_version for an existing
    # device, so sync them explicitly (this also fixes the registry after a
    # self-heal reload).
    _sync_registry_model(
        hass,
        mac_address,
        device_config,
        stored_type,
    )

    # Forward to entity platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Trigger an initial diagnostics read in the background. This both
    # populates the sensors and reveals the real device type, triggering a
    # config-entry + registry self-heal when it differs from the stored one.
    diag_task = hass.async_create_task(
        _initial_read_and_maybe_self_heal(hass, entry, coordinator)
    )
    coordinator.track_background_task(diag_task)

    # Start periodic health check polling
    coordinator.start_polling()

    # Register services
    _register_services(hass)

    return True


def _register_device_in_registry(
    device_registry: dr.DeviceRegistry,
    entry: ConfigEntry,
    mac_address: str,
    device_name: str,
    device_config: DeviceConfig,
    stored_type: int,
) -> None:
    """Create or update the device registry entry.

    Args:
        device_registry: The device registry.
        entry: Config entry owning the device.
        mac_address: MAC address of the device.
        device_name: User-visible device name.
        device_config: Device configuration (may be generic when type unknown).
        stored_type: Device type stored in the config entry (0 if unknown).
    """
    model = device_config.model or None
    sw_version = (
        f"Type {stored_type} ({device_config.model})"
        if stored_type in DEVICE_TYPE_MAP
        else None
    )
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(dr.CONNECTION_BLUETOOTH, mac_address)},
        identifiers={(DOMAIN, mac_address)},
        manufacturer=MANUFACTURER,
        name=device_name,
        model=model,
        sw_version=sw_version,
    )


def _sync_registry_model(
    hass: HomeAssistant,
    mac_address: str,
    device_config: DeviceConfig,
    stored_type: int,
) -> None:
    """Sync the device registry model/sw_version with the known device type.

    async_get_or_create does not rewrite model/sw_version for an existing
    device, so update them explicitly when they differ. This runs on every
    setup, which also fixes the registry after a self-heal reload.

    Args:
        hass: Home Assistant instance.
        mac_address: MAC address of the device.
        device_config: Device configuration for the stored type.
        stored_type: Device type stored in the config entry (0 if unknown).
    """
    if stored_type not in DEVICE_TYPE_MAP:
        return
    expected_sw_version = f"Type {stored_type} ({device_config.model})"
    device_registry = dr.async_get(hass)
    device_info = device_registry.async_get_device(
        identifiers={(DOMAIN, mac_address)}
    )
    if device_info is not None and (
        device_info.model != device_config.model
        or device_info.sw_version != expected_sw_version
    ):
        device_registry.async_update_device(
            device_info.id,
            name=device_config.name,
            model=device_config.model,
            sw_version=expected_sw_version,
        )


async def _initial_read_and_maybe_self_heal(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: HolmanWaterCoordinator,
) -> None:
    """Perform the initial diagnostics read and self-heal a wrong type.

    The read_diagnostics call populates the sensors. If the device reports a
    device type different from the one stored in the config entry, we persist
    the corrected type and reload the entry so per-zone entities match the
    real device.

    Args:
        hass: Home Assistant instance.
        entry: Config entry for this device.
        coordinator: The coordinator for this device.
    """
    mac_address: str = entry.data[CONF_MAC]
    try:
        info = await coordinator.read_diagnostics()
    except Exception as exc:
        _LOGGER.warning(
            "Initial diagnostics read failed for %s: %s",
            mac_address,
            exc,
        )
        return

    if info is None or info.device_type <= 0:
        _LOGGER.debug(
            "No device info received for %s, cannot verify device type",
            mac_address,
        )
        return

    stored_type = entry.data.get("device_type", 0)
    corrected_type = info.device_type

    if corrected_type == stored_type:
        return

    if corrected_type not in DEVICE_TYPE_MAP:
        _LOGGER.warning(
            "Device %s reports unknown device type %d, keeping stored type %d",
            mac_address,
            corrected_type,
            stored_type,
        )
        return

    _LOGGER.info(
        "Device %s corrected from type %d to %d (%s); reloading entry",
        mac_address,
        stored_type,
        corrected_type,
        DEVICE_TYPE_MAP[corrected_type][0],
    )
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, "device_type": corrected_type},
    )
    # Schedule the reload as a separate task. Awaiting it here would be
    # cancelled by async_unload_entry (which cancels this tracked background
    # task), aborting the reload. The reloaded setup re-runs
    # _sync_registry_model with the corrected type.
    hass.async_create_task(
        hass.config_entries.async_reload(entry.entry_id)
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Args:
        hass: Home Assistant instance.
        entry: Config entry to unload.

    Returns:
        True if unload was successful.
    """
    coordinator: HolmanWaterCoordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        # Set shutdown flag so no new operations start
        coordinator._shutdown = True
        # Cancel all background tasks (initial diagnostics, etc.)
        await coordinator._cancel_all_background_tasks()
        # Stop periodic polling
        await coordinator.stop_polling()
        # Cancel watering timers (will detect shutdown)
        coordinator.cancel_all_watering_timers()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


def _register_services(hass: HomeAssistant) -> None:
    """Register custom services for the integration."""

    async def handle_unpair(call: Any) -> None:
        """Handle the unpair service call."""
        mac_address = call.data.get("mac_address")
        if not mac_address:
            _LOGGER.error("mac_address is required for unpair service")
            return

        for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
            if coordinator.mac_address == mac_address:
                await coordinator.unpair()
                return

        _LOGGER.error("Device %s not found", mac_address)

    hass.services.async_register(DOMAIN, SERVICE_UNPAIR, handle_unpair)
