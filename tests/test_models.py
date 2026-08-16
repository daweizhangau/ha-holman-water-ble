"""Tests for the Holman Water BLE models module."""

from __future__ import annotations

from custom_components.holman_water_ble.models import (
    DeviceConfig,
    DeviceInfo,
    PasscodeStore,
    ScanInfo,
)


class TestDeviceInfo:
    """Tests for DeviceInfo dataclass."""

    def test_default_values(self):
        """Test default values."""
        info = DeviceInfo()
        assert info.firmware_version == 0
        assert info.protocol_version == 0
        assert info.device_type == 0
        assert info.dial_position == 0
        assert info.voltage_dc == 0.0
        assert info.voltage_ac == 0.0
        assert info.voltage_valve == 0.0
        assert info.is_watering is False
        assert info.rain_sensor_on is False
        assert info.rain_sensor_wet is False
        assert info.is_dial_presented is False
        assert info.mcu_v == 0
        assert info.valve_v == 0
        assert info.connected_valves == 0
        assert info.active_station == 0
        assert info.diagnostic == 0

    def test_custom_values(self):
        """Test setting custom values."""
        info = DeviceInfo(
            firmware_version=3,
            protocol_version=2,
            device_type=100,
            dial_position=11,
            voltage_dc=5.2,
            is_watering=True,
            connected_valves=1,
        )
        assert info.firmware_version == 3
        assert info.protocol_version == 2
        assert info.device_type == 100
        assert info.dial_position == 11
        assert info.voltage_dc == 5.2
        assert info.is_watering is True
        assert info.connected_valves == 1


class TestScanInfo:
    """Tests for ScanInfo dataclass."""

    def test_default_values(self):
        """Test default values."""
        info = ScanInfo()
        assert info.device_type == 0
        assert info.firmware_version == 0
        assert info.power_dc == 0
        assert info.power_ac == 0
        assert info.mac_address == ""
        assert info.is_ac_powered is False
        assert info.mcu_power == 0
        assert info.passcode == 0


class TestDeviceConfig:
    """Tests for DeviceConfig dataclass."""

    def test_default_values(self):
        """Test default values."""
        config = DeviceConfig()
        assert config.model == ""
        assert config.name == ""
        assert config.total_zones == 1
        assert config.is_ac_device is False

    def test_bx1_config(self):
        """Test BX1 configuration."""
        config = DeviceConfig(
            model="BX1",
            name="BX1 Bluetooth Tap Timer",
            total_zones=1,
            is_ac_device=False,
        )
        assert config.model == "BX1"
        assert config.total_zones == 1
        assert config.is_ac_device is False

    def test_btx8_config(self):
        """Test BTX8 configuration."""
        config = DeviceConfig(
            model="BTX8",
            name="AC Controller (8 Zones)",
            total_zones=8,
            is_ac_device=True,
        )
        assert config.model == "BTX8"
        assert config.total_zones == 8
        assert config.is_ac_device is True


class TestPasscodeStore:
    """Tests for PasscodeStore."""

    def test_empty_store(self):
        """Test empty store."""
        store = PasscodeStore()
        assert store.get("AA:BB:CC:DD:EE:FF") is None
        assert store.has("AA:BB:CC:DD:EE:FF") is False

    def test_set_and_get(self):
        """Test setting and getting a passcode."""
        store = PasscodeStore()
        store.set("AA:BB:CC:DD:EE:FF", 12345)
        assert store.get("AA:BB:CC:DD:EE:FF") == 12345
        assert store.has("AA:BB:CC:DD:EE:FF") is True

    def test_delete(self):
        """Test deleting a passcode."""
        store = PasscodeStore()
        store.set("AA:BB:CC:DD:EE:FF", 12345)
        store.delete("AA:BB:CC:DD:EE:FF")
        assert store.get("AA:BB:CC:DD:EE:FF") is None
        assert store.has("AA:BB:CC:DD:EE:FF") is False

    def test_multiple_devices(self):
        """Test storing passcodes for multiple devices."""
        store = PasscodeStore()
        store.set("AA:BB:CC:DD:EE:01", 100)
        store.set("AA:BB:CC:DD:EE:02", 200)
        assert store.get("AA:BB:CC:DD:EE:01") == 100
        assert store.get("AA:BB:CC:DD:EE:02") == 200
        assert store.get("AA:BB:CC:DD:EE:03") is None

    def test_delete_nonexistent(self):
        """Test deleting a nonexistent passcode."""
        store = PasscodeStore()
        store.delete("AA:BB:CC:DD:EE:FF")  # Should not raise
        assert store.has("AA:BB:CC:DD:EE:FF") is False

    def test_passcodes_property(self):
        """Test the passcodes dict property."""
        store = PasscodeStore()
        store.set("AA:BB:CC:DD:EE:FF", 12345)
        assert store.passcodes == {"AA:BB:CC:DD:EE:FF": 12345}
