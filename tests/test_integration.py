"""Integration tests for Holman Water BLE protocol.

These tests require a real Holman Water BLE device and the `ble-explore`
conda environment. They are skipped by default.

Usage:
    conda activate ble-explore
    export HOLMAN_BLE_INTEGRATION=1
    pytest tests/test_integration.py -v -m integration

The device is auto-discovered by scanning for the Holman service UUID.
Optionally set HOLMAN_BLE_MAC to skip discovery:
    export HOLMAN_BLE_MAC="AA:BB:CC:DD:EE:FF"

The passcode is saved to a local file and reused on subsequent runs.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from typing import Optional

import pytest
import pytest_asyncio
from bleak import BleakScanner

from custom_components.holman_water_ble.const import DEVICE_TYPE_MAP, SERVICE_UUID
from custom_components.holman_water_ble.holman_ble import HolmanBLE
from custom_components.holman_water_ble.parser import (
    build_disabled_profile,
    build_passcode,
    build_watering_start,
    build_watering_stop,
    get_profile_characteristic_uuid,
    parse_device_info,
)

# Path for passcode storage during testing
TEST_PASSCODE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "tmp",
    "test_passcodes.json",
)

# Get MAC address from environment variable (optional — will auto-discover if not set)
TEST_MAC = os.environ.get("HOLMAN_BLE_MAC", "")

# Skip condition: not in integration mode
pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("HOLMAN_BLE_INTEGRATION"),
        reason="Set HOLMAN_BLE_INTEGRATION=1 for integration tests",
    ),
    pytest.mark.asyncio,
]


async def discover_device(timeout: float = 15.0) -> Optional[str]:
    """Discover a Holman Water BLE device by scanning for the service UUID.

    Args:
        timeout: Scan duration in seconds.

    Returns:
        MAC address of the first discovered device, or None.
    """
    print(f"\nScanning for Holman Water devices (timeout={timeout}s)...")

    def _match_device(device, advertisement_data):
        service_uuids = [u.lower() for u in advertisement_data.service_uuids]
        return SERVICE_UUID.lower() in service_uuids

    device = await BleakScanner.find_device_by_filter(
        _match_device, timeout=timeout
    )

    if device is not None:
        print(f"  Found device: {device.name} ({device.address})")
        return device.address

    # Fallback: try direct address if provided
    if TEST_MAC:
        print(f"  Trying direct address: {TEST_MAC}")
        device = await BleakScanner.find_device_by_address(TEST_MAC, timeout=10.0)
        if device is not None:
            return TEST_MAC

    return None


async def get_device(mac: Optional[str] = None) -> Optional[str]:
    """Get a device MAC address, either from param, env var, or auto-discovery.

    Args:
        mac: Optional explicit MAC address.

    Returns:
        MAC address of a discovered device, or None.
    """
    if mac:
        return mac
    if TEST_MAC:
        return TEST_MAC
    return await discover_device()


def _load_passcode(mac: str) -> Optional[int]:
    """Load a stored passcode for a device.

    Args:
        mac: MAC address of the device.

    Returns:
        Stored passcode, or None if not found.
    """
    try:
        if os.path.exists(TEST_PASSCODE_FILE):
            with open(TEST_PASSCODE_FILE) as f:
                data = json.load(f)
            return data.get(mac)
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _save_passcode(mac: str, passcode: int) -> None:
    """Save a passcode for a device.

    Args:
        mac: MAC address of the device.
        passcode: Passcode to save.
    """
    data = {}
    try:
        if os.path.exists(TEST_PASSCODE_FILE):
            with open(TEST_PASSCODE_FILE) as f:
                data = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass

    data[mac] = passcode

    os.makedirs(os.path.dirname(TEST_PASSCODE_FILE), exist_ok=True)
    with open(TEST_PASSCODE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _delete_passcode(mac: str) -> None:
    """Delete a stored passcode for a device.

    Args:
        mac: MAC address of the device.
    """
    try:
        if os.path.exists(TEST_PASSCODE_FILE):
            with open(TEST_PASSCODE_FILE) as f:
                data = json.load(f)
            data.pop(mac, None)
            with open(TEST_PASSCODE_FILE, "w") as f:
                json.dump(data, f, indent=2)
    except (json.JSONDecodeError, OSError):
        pass


@pytest_asyncio.fixture
async def ble_client():
    """Create and yield a connected HolmanBLE client.

    Auto-discovers the device by scanning for the Holman service UUID.
    Cleans up by disconnecting after the test.
    """
    mac = await get_device()
    assert mac is not None, (
        "No Holman Water device found. "
        "Make sure the device is powered on and in range."
    )

    device = await BleakScanner.find_device_by_address(mac, timeout=10.0)
    assert device is not None, f"Device {mac} not found after discovery"

    client = HolmanBLE(device)
    connected = await client.connect()
    assert connected, f"Failed to connect to {mac}"

    yield client

    await client.disconnect()


@pytest.mark.integration
class TestIntegrationConnect:
    """Integration tests for connecting and reading device info."""

    async def test_connect_and_read_info(self, ble_client: HolmanBLE):
        """Test connecting and reading device information."""
        info = await ble_client.read_device_info()
        assert info is not None, "Failed to read device info"

        # Read the real MAC address from the device's MAC characteristic
        mac = await ble_client.read_mac_address()

        print(f"\nDevice Info:")
        print(f"  MAC Address: {mac}")
        print(f"  Firmware Version: {info.firmware_version}")
        print(f"  Protocol Version: {info.protocol_version}")
        print(f"  Device Type: {info.device_type}")
        type_info = DEVICE_TYPE_MAP.get(info.device_type)
        model = type_info[0] if type_info else "Unknown"
        name = type_info[1] if type_info else "Unknown"
        print(f"  Model: {model} ({name})")
        print(f"  Dial Position: {info.dial_position}")
        print(f"  Voltage DC: {info.voltage_dc}V")
        print(f"  Voltage AC: {info.voltage_ac}V")
        print(f"  Voltage Valve: {info.voltage_valve}V")
        print(f"  Is Watering: {info.is_watering}")
        print(f"  Connected Valves: {info.connected_valves}")
        print(f"  Active Station: {info.active_station}")
        print(f"  Device Time: {info.year}-{info.month:02d}-{info.day:02d} "
              f"{info.hour:02d}:{info.minute:02d}:{info.second:02d}")

        # Basic sanity checks
        assert info.device_type > 0, "Device type should be non-zero"
        assert info.firmware_version >= 0, "Firmware version should be valid"

    async def test_set_time(self, ble_client: HolmanBLE):
        """Test setting the device time."""
        result = await ble_client.set_current_time()
        assert result, "Failed to set current time"

        # Read back to verify
        info = await ble_client.read_device_info()
        assert info is not None
        print(f"\nDevice time after set: {info.year}-{info.month:02d}-{info.day:02d} "
              f"{info.hour:02d}:{info.minute:02d}:{info.second:02d}")


@pytest.mark.integration
class TestIntegrationPairing:
    """Integration tests for pairing and watering."""

    async def test_pair_and_watering(self):
        """Test pairing and watering cycle.

        This test:
        1. Connects to the device
        2. Generates and writes a passcode (pairing)
        3. Starts watering for a short duration
        4. Stops watering
        5. Saves the passcode for cleanup
        """
        mac = await get_device()
        assert mac is not None, "No Holman Water device found"

        device = await BleakScanner.find_device_by_address(mac, timeout=10.0)
        assert device is not None

        client = HolmanBLE(device)
        connected = await client.connect()
        assert connected

        try:
            # Generate a new passcode
            passcode = HolmanBLE.generate_passcode()
            print(f"\nPairing with passcode: {passcode}")

            # Write passcode to device
            paired = await client.pair(passcode)
            assert paired, "Failed to pair"

            # Save passcode for cleanup
            _save_passcode(mac, passcode)

            # Start watering (short duration for testing)
            print("Starting watering...")
            started = await client.start_watering(zone=1, duration_minutes=1)
            assert started, "Failed to start watering"

            # Wait a moment
            await asyncio.sleep(2)

            # Stop watering
            print("Stopping watering...")
            stopped = await client.stop_watering(zone=1)
            assert stopped, "Failed to stop watering"

            print("Watering test completed successfully")
        finally:
            await client.disconnect()

    async def test_authenticate_and_control(self):
        """Test authenticating with stored passcode and controlling the valve.

        This test uses the passcode saved from test_pair_and_watering.
        """
        mac = await get_device()
        assert mac is not None, "No Holman Water device found"

        passcode = _load_passcode(mac)
        if passcode is None:
            pytest.skip("No stored passcode found. Run test_pair_and_watering first.")

        device = await BleakScanner.find_device_by_address(mac, timeout=10.0)
        assert device is not None

        client = HolmanBLE(device)
        connected = await client.connect()
        assert connected

        try:
            # Authenticate with stored passcode
            authenticated = await client.authenticate(passcode)
            assert authenticated, "Authentication failed"

            # Clear schedules
            cleared = await client.clear_schedules(num_zones=1)
            assert cleared, "Failed to clear schedules"

            # Set time
            time_set = await client.set_current_time()
            assert time_set, "Failed to set time"

            # Start watering
            started = await client.start_watering(zone=1, duration_minutes=2)
            assert started, "Failed to start watering"

            await asyncio.sleep(2)

            # Stop watering
            stopped = await client.stop_watering(zone=1)
            assert stopped, "Failed to stop watering"

            print("Authentication and control test completed successfully")
        finally:
            await client.disconnect()


@pytest.mark.integration
class TestIntegrationCleanup:
    """Integration tests for cleanup (unpairing)."""

    async def test_unpair(self):
        """Test unpairing the device.

        This clears the passcode so the device can be re-paired with
        another app. Run this last as it resets the device state.
        """
        mac = await get_device()
        assert mac is not None, "No Holman Water device found"

        passcode = _load_passcode(mac)
        if passcode is None:
            pytest.skip("No stored passcode found.")

        device = await BleakScanner.find_device_by_address(mac, timeout=10.0)
        assert device is not None

        client = HolmanBLE(device)
        connected = await client.connect()
        assert connected

        try:
            # Authenticate first
            authenticated = await client.authenticate(passcode)
            assert authenticated, "Authentication failed"

            # Unpair (clear passcode)
            unpaired = await client.unpair()
            assert unpaired, "Failed to unpair"

            # Remove stored passcode
            _delete_passcode(mac)

            print("Device unpaired successfully")
        finally:
            await client.disconnect()
