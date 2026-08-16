"""Diagnostics support for Holman Water BLE."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DEVICE_TYPE_MAP, DOMAIN
from .coordinator import HolmanWaterCoordinator


def _obscure_mac(mac: str) -> str:
    """Obscure a MAC address, keeping first 2 and last 2 characters.

    Args:
        mac: The MAC address to obscure.

    Returns:
        Obscured MAC address like "E5:**:**:**:**:E0".
    """
    if len(mac) < 5:
        return mac
    parts = mac.split(":")
    if len(parts) < 3:
        return mac
    obscured = [parts[0]] + ["**"] * (len(parts) - 2) + [parts[-1]]
    return ":".join(obscured)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Args:
        hass: Home Assistant instance.
        entry: Config entry.

    Returns:
        A dictionary of diagnostic information.
    """
    coordinator: HolmanWaterCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Device registry info (already has obscured MAC via connections)
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(
        identifiers={(DOMAIN, coordinator.mac_address)}
    )

    device_info = coordinator.device_info
    device_config = coordinator.device_config

    diagnostics: dict[str, Any] = {
        "device": {
            "mac_address": _obscure_mac(coordinator.mac_address),
            "name": device_config.name,
            "model": device_config.model,
            "total_zones": device_config.total_zones,
            "is_ac_device": device_config.is_ac_device,
            "paired": coordinator.paired,
            "available": coordinator.available,
            "poll_interval_hours": coordinator.poll_interval_hours,
        },
        "device_registry": (
            {
                "name": device.name,
                "model": device.model,
                "manufacturer": device.manufacturer,
                "sw_version": device.sw_version,
                "connections": [
                    (conn_type, _obscure_mac(conn_id))
                    if conn_type == "bluetooth"
                    else (conn_type, conn_id)
                    for conn_type, conn_id in device.connections
                ],
            }
            if device
            else None
        ),
        "last_device_info": (
            {
                "firmware_version": device_info.firmware_version,
                "protocol_version": device_info.protocol_version,
                "device_type": device_info.device_type,
                "device_model": DEVICE_TYPE_MAP.get(
                    device_info.device_type, ("Unknown", "Unknown", 0, False)
                )[0],
                "dial_position": device_info.dial_position,
                "voltage_dc": round(device_info.voltage_dc, 1),
                "voltage_ac": round(device_info.voltage_ac, 1),
                "voltage_valve": round(device_info.voltage_valve, 1),
                "is_watering": device_info.is_watering,
                "rain_sensor_on": device_info.rain_sensor_on,
                "rain_sensor_wet": device_info.rain_sensor_wet,
                "is_dial_presented": device_info.is_dial_presented,
                "connected_valves": device_info.connected_valves,
                "active_station": device_info.active_station,
                "diagnostic": device_info.diagnostic,
                "time": (
                    f"{device_info.year}-{device_info.month:02d}-"
                    f"{device_info.day:02d} "
                    f"{device_info.hour:02d}:{device_info.minute:02d}:"
                    f"{device_info.second:02d}"
                ),
            }
            if device_info
            else None
        ),
    }

    return diagnostics
