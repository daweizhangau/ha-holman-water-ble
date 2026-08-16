"""Tests for the Holman Water BLE coordinator module."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.holman_water_ble.coordinator import HolmanWaterCoordinator
from custom_components.holman_water_ble.models import DeviceConfig, DeviceInfo


@pytest.fixture
def temp_dir():
    """Create a temporary directory for passcode storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_ble_device():
    """Create a mock BLE device."""
    device = MagicMock()
    device.address = "AA:BB:CC:DD:EE:FF"
    device.name = "BX1"
    device.rssi = -70
    return device


@pytest.fixture
def device_config():
    """Create a BX1 device config."""
    return DeviceConfig(
        model="BX1",
        name="BX1 Bluetooth Tap Timer",
        total_zones=1,
        is_ac_device=False,
    )


@pytest.fixture
def coordinator(mock_ble_device, device_config, temp_dir):
    """Create a coordinator instance."""
    return HolmanWaterCoordinator(
        ble_device=mock_ble_device,
        device_config=device_config,
        hass_config_dir=temp_dir,
    )


class TestHolmanWaterCoordinator:
    """Tests for HolmanWaterCoordinator."""

    def test_init(self, coordinator, mock_ble_device, device_config):
        """Test initialization."""
        assert coordinator.ble_device == mock_ble_device
        assert coordinator.device_config == device_config
        assert coordinator.mac_address == "AA:BB:CC:DD:EE:FF"
        assert coordinator.device_info is None
        assert coordinator.has_passcode() is False
        assert coordinator.paired is False
        assert coordinator.available is False  # not paired yet
        assert coordinator.poll_interval_hours == 4
        assert coordinator.is_watering(1) is False
        assert coordinator.get_watering_end_time(1) is None

    def test_default_watering_duration(self, coordinator):
        """Test default watering duration."""
        assert coordinator.get_watering_duration(1) == 10

    def test_set_watering_duration(self, coordinator):
        """Test setting watering duration."""
        coordinator.set_watering_duration(1, 30)
        assert coordinator.get_watering_duration(1) == 30

    def test_watering_duration_per_zone(self, coordinator):
        """Test per-zone watering duration."""
        coordinator.set_watering_duration(1, 15)
        assert coordinator.get_watering_duration(1) == 15
        # Zone 2 doesn't exist (BX1 has 1 zone), but we can still set it
        coordinator.set_watering_duration(2, 30)
        assert coordinator.get_watering_duration(2) == 30

    def test_passcode_persistence(self, coordinator, temp_dir):
        """Test passcode persistence to file."""
        coordinator._passcode_store.set("AA:BB:CC:DD:EE:FF", 12345)
        coordinator._save_passcodes()

        # Verify file was written
        passcode_file = os.path.join(temp_dir, "holman_water_ble_passcodes.json")
        assert os.path.exists(passcode_file)

        with open(passcode_file) as f:
            data = json.load(f)
        assert data["AA:BB:CC:DD:EE:FF"] == 12345

    def test_passcode_loading(self, coordinator, temp_dir):
        """Test passcode loading from file."""
        # Write a passcode file
        passcode_file = os.path.join(temp_dir, "holman_water_ble_passcodes.json")
        with open(passcode_file, "w") as f:
            json.dump({"AA:BB:CC:DD:EE:FF": 12345}, f)

        # Create a new coordinator (should load from file)
        new_coordinator = HolmanWaterCoordinator(
            ble_device=coordinator.ble_device,
            device_config=coordinator.device_config,
            hass_config_dir=temp_dir,
        )

        assert new_coordinator.has_passcode() is True
        assert new_coordinator._passcode_store.get("AA:BB:CC:DD:EE:FF") == 12345

    @pytest.mark.asyncio
    async def test_watering_timer_lifecycle(self, coordinator):
        """Test watering timer lifecycle."""
        # Initially not watering
        assert coordinator.is_watering(1) is False
        assert coordinator.get_watering_end_time(1) is None

        # Manually set a timer
        coordinator._watering_timers[1] = asyncio.create_task(
            asyncio.sleep(999)
        )
        assert coordinator.is_watering(1) is True

        # Cancel the timer
        coordinator._cancel_watering_timer(1)
        assert coordinator.is_watering(1) is False

        # Clean up any remaining tasks
        coordinator.cancel_all_watering_timers()

    @pytest.mark.asyncio
    async def test_cancel_all_watering_timers(self, coordinator):
        """Test cancelling all watering timers."""
        coordinator._watering_timers[1] = asyncio.create_task(asyncio.sleep(999))
        coordinator._watering_timers[2] = asyncio.create_task(asyncio.sleep(999))
        assert len(coordinator._watering_timers) == 2

        coordinator.cancel_all_watering_timers()
        assert len(coordinator._watering_timers) == 0

    def test_poll_interval(self, coordinator):
        """Test poll interval get/set."""
        assert coordinator.poll_interval_hours == 4
        coordinator.set_poll_interval_hours(6)
        assert coordinator.poll_interval_hours == 6

    def test_availability(self, coordinator):
        """Test availability flag."""
        # Set a passcode so the device is considered paired
        coordinator._passcode_store.set("AA:BB:CC:DD:EE:FF", 12345)
        assert coordinator.available is True
        assert coordinator.paired is True
        coordinator._available = False
        assert coordinator.available is False

    def test_state_update_callbacks(self, coordinator):
        """Test state update callback registration."""
        calls = []
        def cb():
            calls.append(1)

        coordinator.register_state_update_callback(cb)
        coordinator._notify_state_update()
        assert len(calls) == 1

        coordinator.unregister_state_update_callback(cb)
        coordinator._notify_state_update()
        assert len(calls) == 1

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.coordinator.HolmanBLE")
    async def test_first_pair(self, mock_holman_ble_cls, coordinator):
        """Test first-time pairing."""
        mock_client = MagicMock()
        mock_client.connect = AsyncMock(return_value=True)
        mock_client.pair = AsyncMock(return_value=True)
        mock_client.disconnect = AsyncMock()
        mock_holman_ble_cls.return_value = mock_client
        mock_holman_ble_cls.generate_passcode = MagicMock(return_value=12345)

        result = await coordinator.first_pair()

        assert result is True
        assert coordinator.has_passcode() is True
        assert coordinator._passcode_store.get("AA:BB:CC:DD:EE:FF") == 12345

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.coordinator.HolmanBLE")
    async def test_first_pair_connect_failure(self, mock_holman_ble_cls, coordinator):
        """Test first-time pairing with connection failure."""
        mock_client = MagicMock()
        mock_client.connect = AsyncMock(return_value=False)
        mock_holman_ble_cls.return_value = mock_client

        result = await coordinator.first_pair()

        assert result is False
        assert coordinator.has_passcode() is False

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.coordinator.HolmanBLE")
    async def test_read_diagnostics(self, mock_holman_ble_cls, coordinator):
        """Test reading diagnostics."""
        mock_client = MagicMock()
        mock_client.connect = AsyncMock(return_value=True)
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.read_device_info = AsyncMock(return_value=DeviceInfo(
            firmware_version=3,
            protocol_version=2,
            device_type=100,
            voltage_dc=5.2,
        ))
        mock_client.clear_schedules = AsyncMock(return_value=True)
        mock_client.set_current_time = AsyncMock(return_value=True)
        mock_client.disconnect = AsyncMock()
        mock_holman_ble_cls.return_value = mock_client

        # Set a passcode so authentication is attempted
        coordinator._passcode_store.set("AA:BB:CC:DD:EE:FF", 12345)

        info = await coordinator.read_diagnostics()

        assert info is not None
        assert info.firmware_version == 3
        assert info.voltage_dc == 5.2
        assert coordinator.device_info is not None
        assert coordinator.device_info.firmware_version == 3

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.coordinator.HolmanBLE")
    async def test_start_watering(self, mock_holman_ble_cls, coordinator):
        """Test starting watering."""
        mock_client = MagicMock()
        mock_client.connect = AsyncMock(return_value=True)
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.start_watering = AsyncMock(return_value=True)
        mock_client.clear_schedules = AsyncMock(return_value=True)
        mock_client.set_current_time = AsyncMock(return_value=True)
        mock_client.disconnect = AsyncMock()
        mock_holman_ble_cls.return_value = mock_client

        coordinator._passcode_store.set("AA:BB:CC:DD:EE:FF", 12345)

        result = await coordinator.start_watering(zone=1)

        assert result is True
        mock_client.start_watering.assert_called_once_with(1, 10)
        # Watering should skip housekeeping
        mock_client.clear_schedules.assert_not_called()
        mock_client.set_current_time.assert_not_called()

        # Clean up the watering timer task
        coordinator.cancel_all_watering_timers()

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.coordinator.HolmanBLE")
    async def test_stop_watering(self, mock_holman_ble_cls, coordinator):
        """Test stopping watering."""
        mock_client = MagicMock()
        mock_client.connect = AsyncMock(return_value=True)
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.stop_watering = AsyncMock(return_value=True)
        mock_client.clear_schedules = AsyncMock(return_value=True)
        mock_client.set_current_time = AsyncMock(return_value=True)
        mock_client.disconnect = AsyncMock()
        mock_holman_ble_cls.return_value = mock_client

        coordinator._passcode_store.set("AA:BB:CC:DD:EE:FF", 12345)

        result = await coordinator.stop_watering(zone=1)

        assert result is True
        mock_client.stop_watering.assert_called_once_with(1)
        # Watering should skip housekeeping
        mock_client.clear_schedules.assert_not_called()
        mock_client.set_current_time.assert_not_called()

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.coordinator.HolmanBLE")
    async def test_unpair(self, mock_holman_ble_cls, coordinator):
        """Test unpairing."""
        mock_client = MagicMock()
        mock_client.connect = AsyncMock(return_value=True)
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.unpair = AsyncMock(return_value=True)
        mock_client.clear_schedules = AsyncMock(return_value=True)
        mock_client.set_current_time = AsyncMock(return_value=True)
        mock_client.disconnect = AsyncMock()
        mock_holman_ble_cls.return_value = mock_client

        coordinator._passcode_store.set("AA:BB:CC:DD:EE:FF", 12345)

        result = await coordinator.unpair()

        assert result is True
        assert coordinator.has_passcode() is False
        mock_client.unpair.assert_called_once()

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.coordinator.HolmanBLE")
    async def test_operation_without_passcode(self, mock_holman_ble_cls, coordinator):
        """Test operation when no passcode is stored."""
        mock_client = MagicMock()
        mock_client.connect = AsyncMock(return_value=True)
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.read_device_info = AsyncMock(return_value=DeviceInfo())
        mock_client.clear_schedules = AsyncMock(return_value=True)
        mock_client.set_current_time = AsyncMock(return_value=True)
        mock_client.disconnect = AsyncMock()
        mock_holman_ble_cls.return_value = mock_client

        # No passcode set - should skip authentication
        info = await coordinator.read_diagnostics()

        assert info is not None
        # authenticate should not be called since no passcode
        mock_client.authenticate.assert_not_called()
