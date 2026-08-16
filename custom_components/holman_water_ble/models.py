"""Data models for the Holman Water BLE integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DeviceInfo:
    """Parsed device information from the DEVICE_INFO characteristic."""

    firmware_version: int = 0
    protocol_version: int = 0
    device_type: int = 0
    dial_position: int = 0
    voltage_dc: float = 0.0
    voltage_ac: float = 0.0
    voltage_valve: float = 0.0
    is_watering: bool = False
    rain_sensor_on: bool = False
    rain_sensor_wet: bool = False
    is_dial_presented: bool = False
    mcu_v: int = 0
    valve_v: int = 0
    connected_valves: int = 0
    active_station: int = 0
    diagnostic: int = 0

    # Time info (read separately)
    year: int = 0
    month: int = 0
    day: int = 0
    weekday: int = 0
    hour: int = 0
    minute: int = 0
    second: int = 0


@dataclass
class ScanInfo:
    """Parsed information from BLE advertisement scan record."""

    device_type: int = 0
    firmware_version: int = 0
    power_dc: int = 0
    power_ac: int = 0
    mac_address: str = ""
    is_ac_powered: bool = False
    mcu_power: int = 0
    passcode: int = 0


@dataclass
class DeviceConfig:
    """Device configuration derived from device type."""

    model: str = ""
    name: str = ""
    total_zones: int = 1
    is_ac_device: bool = False


@dataclass
class PasscodeStore:
    """In-memory passcode store backed by a JSON file."""

    passcodes: dict[str, int] = field(default_factory=dict)

    def get(self, mac: str) -> Optional[int]:
        """Get passcode for a MAC address."""
        return self.passcodes.get(mac)

    def set(self, mac: str, passcode: int) -> None:
        """Set passcode for a MAC address."""
        self.passcodes[mac] = passcode

    def delete(self, mac: str) -> None:
        """Delete passcode for a MAC address."""
        self.passcodes.pop(mac, None)

    def has(self, mac: str) -> bool:
        """Check if a passcode exists for a MAC address."""
        return mac in self.passcodes
