"""BLE protocol client for Holman Water devices.

Provides a high-level interface for communicating with Holman BLE irrigation
devices using bleak. Handles connection, pairing, watering control, schedule
management, and diagnostics reading.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection

from .const import (
    CHAR_UUID_DEVICE_INFO,
    CHAR_UUID_MAC,
    CHAR_UUID_PASSCODE,
    CHAR_UUID_TIME,
    CHAR_UUID_WATERING,
    CONNECTION_TIMEOUT,
    MAX_ZONES,
    PASSCODE_MAX,
    PASSCODE_MIN,
)
from .models import DeviceInfo
from .parser import (
    build_current_time,
    build_disabled_profile,
    build_passcode,
    build_watering_start,
    build_watering_stop,
    get_profile_characteristic_uuid,
    parse_device_info,
    parse_time_response,
)

_LOGGER = logging.getLogger(__name__)


class HolmanBLE:
    """BLE protocol client for Holman Water devices.

    This class wraps a BleakClient and provides methods for all protocol
    operations. Connections are established on-demand and should be closed
    after each operation.
    """

    def __init__(self, device: BLEDevice) -> None:
        """Initialize the BLE client.

        Args:
            device: The BLE device to communicate with.
        """
        self._device = device
        self._client: Optional[BleakClient] = None
        self._characteristics: dict[str, str] = {}  # UUID → handle

    @property
    def is_connected(self) -> bool:
        """Check if the BLE client is currently connected."""
        return self._client is not None and self._client.is_connected

    async def connect(self, timeout: float = CONNECTION_TIMEOUT) -> bool:
        """Connect to the device and discover services.

        Attempts BLE-level pairing after connecting, as the device
        requires this before accepting GATT write commands.

        Args:
            timeout: Connection timeout in seconds.

        Returns:
            True if connection was successful.
        """
        if self.is_connected:
            return True

        try:
            self._client = await establish_connection(
                client_class=BleakClient,
                device=self._device,
                name=str(self._device.address),
                disconnected_callback=self._on_disconnect,
            )
            await self._discover_characteristics()

            # Attempt BLE-level pairing. The device may request a passkey;
            # bleak handles the pairing dialog automatically on macOS CoreBluetooth.
            try:
                await self._client.pair()
                _LOGGER.debug("BLE pairing successful")
            except Exception as exc:
                _LOGGER.debug("BLE pairing failed/not needed: %s", exc)

            _LOGGER.debug("Connected to %s", self._device.address)
            return True
        except Exception as exc:
            _LOGGER.error("Failed to connect to %s: %s", self._device.address, exc)
            self._client = None
            return False

    async def disconnect(self) -> None:
        """Disconnect from the device.

        Closes the BLE connection without unpairing (pairing
        persists across connections).
        """
        if not self.is_connected:
            return

        try:
            await self._client.disconnect()
        except Exception as exc:
            _LOGGER.debug("Error during disconnect: %s", exc)
        finally:
            self._client = None
            self._characteristics.clear()

    async def pair(self, passcode: int) -> bool:
        """Pair with the device by writing a new passcode.

        Writes the passcode directly without reading first.
        Used for first-time pairing and re-pairing — we always
        set a new passcode.

        Args:
            passcode: 16-bit passcode value (1-65534).

        Returns:
            True if the passcode was written successfully.
        """
        return await self._write_passcode(passcode)

    async def authenticate(self, passcode: int) -> bool:
        """Authenticate with the device using the stored passcode.

        Reads the device's current passcode first. If it doesn't match ours,
        writes 0 to clear the old one, then writes our passcode.

        Args:
            passcode: 16-bit passcode value.

        Returns:
            True if the passcode was written successfully.
        """
        return await self._write_passcode_safe(passcode)

    async def _write_passcode_safe(self, passcode: int) -> bool:
        """Write a passcode to the device, handling mismatches.

        Reads the device's current passcode first. If it doesn't match ours,
        writes 0 to clear, then writes our passcode.

        Args:
            passcode: 16-bit passcode value.

        Returns:
            True if successful.
        """
        if not self.is_connected:
            return False

        try:
            # Read current device passcode
            pc_data = await self._read_characteristic(CHAR_UUID_PASSCODE)
            device_passcode = None
            if pc_data and len(pc_data) >= 2:
                device_passcode = (pc_data[0] << 8) | pc_data[1]
                _LOGGER.debug(
                    "Device passcode: %d, our passcode: %d",
                    device_passcode, passcode,
                )

            # If device has a different non-zero passcode, clear it first
            if device_passcode is not None and device_passcode != 0 and device_passcode != passcode:
                _LOGGER.debug("Passcode mismatch, clearing old passcode")
                await self._write_passcode(0)
                await asyncio.sleep(0.1)

            # Write our passcode
            _LOGGER.debug("Writing passcode %d", passcode)
            await self._write_passcode(passcode)
            _LOGGER.debug("Passcode written to device")
            return True
        except Exception as exc:
            _LOGGER.error("Failed to write passcode: %s", exc)
            return False

    async def read_device_info(self) -> Optional[DeviceInfo]:
        """Read device information from the DEVICE_INFO characteristic.

        Returns:
            Parsed DeviceInfo, or None if the read failed.
        """
        if not self.is_connected:
            return None

        try:
            data = await self._read_characteristic(CHAR_UUID_DEVICE_INFO)
            if data is None:
                return None
            info = parse_device_info(data)

            # Also read the time
            time_data = await self._read_characteristic(CHAR_UUID_TIME)
            if time_data and len(time_data) >= 8:
                (
                    info.year,
                    info.month,
                    info.day,
                    info.weekday,
                    info.hour,
                    info.minute,
                    info.second,
                ) = parse_time_response(time_data)

            return info
        except Exception as exc:
            _LOGGER.error("Failed to read device info: %s", exc)
            return None

    async def read_mac_address(self) -> Optional[str]:
        """Read the device's MAC address from the MAC characteristic (F003).

        Returns:
            MAC address string (e.g. "AA:BB:CC:DD:EE:FF"), or None if failed.
        """
        if not self.is_connected:
            return None

        try:
            data = await self._read_characteristic(CHAR_UUID_MAC)
            if data is None or len(data) < 6:
                return None
            return ":".join(f"{b:02X}" for b in data[:6])
        except Exception as exc:
            _LOGGER.error("Failed to read MAC address: %s", exc)
            return None

    async def set_current_time(self) -> bool:
        """Set the device's current time to the host's current time.

        Returns:
            True if the write was successful.
        """
        if not self.is_connected:
            return False

        try:
            time_packet = build_current_time()
            await self._write_characteristic(CHAR_UUID_TIME, time_packet)
            _LOGGER.debug("Current time sent to device")
            return True
        except Exception as exc:
            _LOGGER.error("Failed to set current time: %s", exc)
            return False

    async def clear_schedules(self, num_zones: int) -> bool:
        """Clear all schedules by writing disabled profiles.

        Writes a disabled profile (mode=0) to each zone's profile
        characteristic.

        Args:
            num_zones: Number of zones to clear (1-8).

        Returns:
            True if all writes were successful.
        """
        if not self.is_connected:
            return False

        disabled_profile = build_disabled_profile()
        zones_to_clear = min(num_zones, MAX_ZONES)

        try:
            for zone in range(1, zones_to_clear + 1):
                uuid = get_profile_characteristic_uuid(zone)
                await self._write_characteristic(uuid, disabled_profile)
                _LOGGER.debug("Cleared schedule for zone %d", zone)
            return True
        except Exception as exc:
            _LOGGER.error("Failed to clear schedules: %s", exc)
            return False

    async def start_watering(self, zone: int, duration_minutes: int = 10) -> bool:
        """Start manual watering for a specific zone.

        Args:
            zone: 1-based zone number.
            duration_minutes: Watering duration in minutes.

        Returns:
            True if the write was successful.
        """
        if not self.is_connected:
            return False

        try:
            packet = build_watering_start(zone, duration_minutes)
            # Use response=True — the device requires acknowledged writes
            # for the watering characteristic to process the command.
            await self._write_characteristic(CHAR_UUID_WATERING, packet, response=True)
            _LOGGER.debug(
                "Started watering zone %d for %d minutes",
                zone,
                duration_minutes,
            )
            return True
        except Exception as exc:
            _LOGGER.error("Failed to start watering: %s", exc)
            return False

    async def stop_watering(self, zone: int) -> bool:
        """Stop manual watering for a specific zone.

        Args:
            zone: 1-based zone number.

        Returns:
            True if the write was successful.
        """
        if not self.is_connected:
            return False

        try:
            packet = build_watering_stop(zone)
            # Use response=True — the device requires acknowledged writes
            # for the watering characteristic to process the command.
            await self._write_characteristic(CHAR_UUID_WATERING, packet, response=True)
            _LOGGER.debug("Stopped watering zone %d", zone)
            return True
        except Exception as exc:
            _LOGGER.error("Failed to stop watering: %s", exc)
            return False

    async def unpair(self) -> bool:
        """Unpair the device by clearing the passcode.

        Writes passcode=0 to the PASSCODE characteristic, which allows
        the device to be re-paired with another app.

        Returns:
            True if the write was successful.
        """
        return await self._write_passcode(0)

    @staticmethod
    def generate_passcode() -> int:
        """Generate a random 16-bit passcode.

        Returns:
            A random passcode in the range [1, 65534].
        """
        return random.randint(PASSCODE_MIN, PASSCODE_MAX)

    async def _discover_characteristics(self) -> None:
        """Discover all GATT characteristics and cache their handles."""
        if self._client is None:
            return

        self._characteristics.clear()
        for service in self._client.services:
            for char in service.characteristics:
                self._characteristics[char.uuid] = char

    async def _read_characteristic(self, uuid: str) -> Optional[bytearray]:
        """Read data from a characteristic by UUID.

        Args:
            uuid: The characteristic UUID to read from.

        Returns:
            The read data, or None if the read failed.
        """
        if self._client is None:
            return None

        try:
            return await self._client.read_gatt_char(uuid)
        except Exception as exc:
            _LOGGER.error("Failed to read %s: %s", uuid, exc)
            return None

    async def _write_characteristic(self, uuid: str, data: bytes, response: bool = False) -> None:
        """Write data to a characteristic by UUID.

        Args:
            uuid: The characteristic UUID to write to.
            data: The data to write.
            response: Whether to use write with response (True) or
                write without response (False).
        """
        if self._client is None:
            raise RuntimeError("Not connected")

        await self._client.write_gatt_char(uuid, data, response=response)

    async def _write_passcode(self, passcode: int) -> bool:
        """Write a passcode to the PASSCODE characteristic.

        Args:
            passcode: 16-bit passcode value.

        Returns:
            True if the write was successful.
        """
        if not self.is_connected:
            return False

        try:
            packet = build_passcode(passcode)
            await self._write_characteristic(CHAR_UUID_PASSCODE, packet, response=True)
            _LOGGER.debug("Passcode written to device")
            return True
        except Exception as exc:
            _LOGGER.error("Failed to write passcode: %s", exc)
            return False

    def _on_disconnect(self, client: BleakClient) -> None:
        """Handle unexpected disconnection."""
        _LOGGER.debug("Device %s disconnected", self._device.address)
        self._client = None
        self._characteristics.clear()
