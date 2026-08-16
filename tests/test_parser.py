"""Tests for the Holman Water BLE parser module."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from custom_components.holman_water_ble.models import DeviceInfo, ScanInfo
from custom_components.holman_water_ble.parser import (
    build_current_time,
    build_disabled_profile,
    build_disconnect,
    build_keep_connection,
    build_passcode,
    build_watering_start,
    build_watering_stop,
    get_profile_characteristic_uuid,
    parse_device_info,
    parse_scan_record,
    parse_time_response,
)


class TestBuildPasscode:
    """Tests for build_passcode."""

    def test_build_passcode_zero(self):
        """Test building a zero passcode (unpair)."""
        result = build_passcode(0)
        assert result == bytes([0x00, 0x00])

    def test_build_passcode_typical(self):
        """Test building a typical passcode."""
        result = build_passcode(0x1234)
        assert result == bytes([0x12, 0x34])

    def test_build_passcode_max(self):
        """Test building the maximum passcode."""
        result = build_passcode(65534)
        assert result == bytes([0xFF, 0xFE])

    def test_build_passcode_min(self):
        """Test building the minimum passcode."""
        result = build_passcode(1)
        assert result == bytes([0x00, 0x01])


class TestBuildCurrentTime:
    """Tests for build_current_time."""

    @patch("custom_components.holman_water_ble.parser.datetime")
    def test_build_current_time_format(self, mock_datetime):
        """Test the time packet format."""
        mock_now = MagicMock()
        mock_now.year = 2026
        mock_now.month = 8
        mock_now.day = 15
        mock_now.hour = 14
        mock_now.minute = 30
        mock_now.second = 45
        # Aug 15, 2026 is a Saturday → Python weekday=5 → protocol weekday=6
        mock_now.weekday.return_value = 5
        mock_datetime.now.return_value = mock_now

        result = build_current_time()

        assert len(result) == 8
        # Year 2026 = 0x07EA
        assert result[0] == 0x07
        assert result[1] == 0xEA
        assert result[2] == 8  # Month
        assert result[3] == 15  # Day
        assert result[4] == 6  # Saturday (protocol: 0=Sunday, 6=Saturday)
        assert result[5] == 14  # Hour
        assert result[6] == 30  # Minute
        assert result[7] == 45  # Second


class TestBuildWatering:
    """Tests for watering packet builders."""

    def test_build_watering_start(self):
        """Test building a watering start packet."""
        result = build_watering_start(zone=1, duration_minutes=10)

        assert len(result) == 10
        assert result[0] == 0x01  # Start flag
        assert result[1] == 0x00  # Zone 0 (0-based)
        assert result[2] == 0x00  # Manual hour
        assert result[3] == 10  # Manual minute
        # Bytes 4-9 should be zero
        assert all(b == 0 for b in result[4:])

    def test_build_watering_start_zone_4(self):
        """Test building a watering start for zone 4."""
        result = build_watering_start(zone=4, duration_minutes=30)

        assert result[0] == 0x01
        assert result[1] == 0x03  # Zone 3 (0-based)
        assert result[3] == 30

    def test_build_watering_stop(self):
        """Test building a watering stop packet."""
        result = build_watering_stop(zone=1)

        assert len(result) == 10
        assert result[0] == 0x00  # Stop flag
        assert result[1] == 0x00  # Zone 0 (0-based)
        assert all(b == 0 for b in result[2:])

    def test_build_watering_stop_zone_8(self):
        """Test building a watering stop for zone 8."""
        result = build_watering_stop(zone=8)

        assert result[0] == 0x00
        assert result[1] == 0x07  # Zone 7 (0-based)


class TestBuildProfile:
    """Tests for profile packet builders."""

    def test_build_disabled_profile(self):
        """Test building a disabled profile."""
        result = build_disabled_profile()

        assert len(result) == 20
        assert result[0] == 0x00  # Mode = 0 (disabled)
        assert all(b == 0 for b in result)


class TestBuildCommand:
    """Tests for command packet builders."""

    def test_build_keep_connection(self):
        """Test building a keep-connection heartbeat."""
        result = build_keep_connection()
        assert result == bytes([0x03])

    def test_build_disconnect(self):
        """Test building a disconnect command."""
        result = build_disconnect()
        assert result == bytes([0x01])


class TestParseDeviceInfo:
    """Tests for parse_device_info."""

    def test_parse_device_info_bx1(self):
        """Test parsing a BX1 device info response."""
        # Simulate BX1: fw=3.0, proto=2, type=100, dial=11(RUN),
        # DC=5.2V, AC=0V, valve=0V, not watering, no rain sensor
        data = bytes([
            0x00, 0x03,  # Firmware version 3
            0x02,        # Protocol version 2
            100,         # Device type BX1
            11,          # Dial position RUN
            52,          # Voltage DC (5.2V)
            0,           # Voltage AC (0V)
            0,           # Voltage Valve (0V)
            0x00,        # Bitfield: not watering, no rain
            0x01,        # Connected valves: 1
            0x00,        # Unused
            0x00,        # Active station
            0x00, 0x00, 0x00, 0x00,  # Padding
            0x00,        # Diagnostic
        ])

        info = parse_device_info(data)

        assert info.firmware_version == 3
        assert info.protocol_version == 2
        assert info.device_type == 100
        assert info.dial_position == 11
        assert info.voltage_dc == 5.2
        assert info.voltage_ac == 0.0
        assert info.voltage_valve == 0.0
        assert info.is_watering is False
        assert info.rain_sensor_on is False
        assert info.rain_sensor_wet is False
        assert info.is_dial_presented is False
        assert info.connected_valves == 1
        assert info.valve_v == 1
        assert info.active_station == 0
        assert info.diagnostic == 0

    def test_parse_device_info_watering(self):
        """Test parsing device info when watering is active."""
        data = bytes([
            0x00, 0x05,  # Firmware version 5
            0x02,        # Protocol version 2
            100,         # Device type BX1
            1,           # Dial position Valve 1
            49,          # Voltage DC (4.9V)
            0,           # Voltage AC
            30,          # Voltage Valve (3.0V)
            0x01,        # Bitfield: is_watering=1
            0x01,        # Connected valves
            0x00,
            0x01,        # Active station = 1
            0x00, 0x00, 0x00, 0x00,
            0x00,
        ])

        info = parse_device_info(data)

        assert info.firmware_version == 5
        assert info.is_watering is True
        assert info.active_station == 1
        assert info.voltage_valve == 3.0

    def test_parse_device_info_rain_sensor(self):
        """Test parsing device info with rain sensor."""
        data = bytes([
            0x00, 0x03, 0x02, 8, 11,
            52, 0, 0,
            0x06,  # Bitfield: rain_sensor_on=1, rain_sensor_wet=1
            0x01, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00,
            0x00,
        ])

        info = parse_device_info(data)

        assert info.rain_sensor_on is True
        assert info.rain_sensor_wet is True
        assert info.device_type == 8  # BTX8 (AC controller with rain sensor)

    def test_parse_device_info_short_data(self):
        """Test parsing truncated device info."""
        data = bytes([0x00, 0x03, 0x02])  # Only 3 bytes

        info = parse_device_info(data)

        # Data too short (< 12 bytes), returns defaults
        assert info.firmware_version == 0
        assert info.protocol_version == 0

    def test_parse_device_info_empty(self):
        """Test parsing empty data."""
        info = parse_device_info(bytes())
        assert info.firmware_version == 0

    def test_parse_device_info_dial_presented(self):
        """Test parsing device info with dial presented flag."""
        data = bytes([
            0x00, 0x03, 0x02, 100, 11,
            52, 0, 0,
            0x20,  # Bitfield: is_dial_presented=1
            0x01, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00,
            0x00,
        ])

        info = parse_device_info(data)
        assert info.is_dial_presented is True

    def test_parse_device_info_mcu_v_proto1(self):
        """Test MCU version parsing with protocol <= 1."""
        data = bytes([
            0x00, 0x03, 0x01, 100, 11,  # proto=1
            52, 0, 0,
            0x40,  # Bitfield: bit 6 = MCU version
            0x01, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00,
            0x00,
        ])

        info = parse_device_info(data)
        assert info.mcu_v == 1  # bit 6 for proto <= 1

    def test_parse_device_info_mcu_v_proto2(self):
        """Test MCU version parsing with protocol > 1."""
        data = bytes([
            0x00, 0x03, 0x02, 100, 11,  # proto=2
            52, 0, 0,
            0x80,  # Bitfield: bit 7 = MCU version
            0x01, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00,
            0x00,
        ])

        info = parse_device_info(data)
        assert info.mcu_v == 1  # bit 7 for proto > 1


class TestParseTimeResponse:
    """Tests for parse_time_response."""

    def test_parse_time_response(self):
        """Test parsing a time response."""
        # Year 2024 = 0x07E8, Month 8, Day 15, Weekday 6 (Sat),
        # Hour 14, Minute 30, Second 45
        data = bytes([0x07, 0xE8, 8, 15, 6, 14, 30, 45])

        result = parse_time_response(data)

        assert result == (2024, 8, 15, 6, 14, 30, 45)

    def test_parse_time_response_short(self):
        """Test parsing truncated time response."""
        data = bytes([0x07, 0xE8, 8])  # Only 3 bytes

        result = parse_time_response(data)

        assert result == (0, 0, 0, 0, 0, 0, 0)


class TestParseScanRecord:
    """Tests for parse_scan_record."""

    def test_parse_scan_record_bx1(self):
        """Test parsing a BX1 scan record."""
        data = bytearray(46)
        data[33] = 100  # Device type BX1
        data[34] = 3    # Firmware version 3
        data[35] = 80   # Power DC (80%)
        data[36] = 0    # Power AC
        # MAC: AA:BB:CC:DD:EE:FF
        data[37] = 0xAA
        data[38] = 0xBB
        data[39] = 0xCC
        data[40] = 0xDD
        data[41] = 0xEE
        data[42] = 0xFF
        data[43] = 0x00  # Bitfield: DC powered
        data[44] = 0x12  # Passcode hi
        data[45] = 0x34  # Passcode lo

        info = parse_scan_record(bytes(data))

        assert info is not None
        assert info.device_type == 100
        assert info.firmware_version == 3
        assert info.power_dc == 80
        assert info.power_ac == 0
        assert info.mac_address == "AA:BB:CC:DD:EE:FF"
        assert info.is_ac_powered is False
        assert info.passcode == 0x1234

    def test_parse_scan_record_ac_powered(self):
        """Test parsing an AC-powered device scan record."""
        data = bytearray(46)
        data[33] = 8   # Device type BTX8
        data[34] = 17  # Firmware version
        data[35] = 0   # Power DC
        data[36] = 240  # Power AC
        data[37:43] = [0x11, 0x22, 0x33, 0x44, 0x55, 0x66]
        data[43] = 0x08  # Bitfield: AC powered (bit 3)
        data[44] = 0x00
        data[45] = 0x00

        info = parse_scan_record(bytes(data))

        assert info is not None
        assert info.is_ac_powered is True
        assert info.power_ac == 240
        assert info.power_dc == 0

    def test_parse_scan_record_too_short(self):
        """Test parsing a truncated scan record."""
        data = bytes([0] * 30)
        info = parse_scan_record(data)
        assert info is None

    def test_parse_scan_record_none(self):
        """Test parsing None."""
        info = parse_scan_record(None)
        assert info is None


class TestGetProfileCharacteristicUUID:
    """Tests for get_profile_characteristic_uuid."""

    def test_zone_1(self):
        """Test zone 1 UUID."""
        uuid = get_profile_characteristic_uuid(1)
        assert uuid == "0000E001-0000-1000-8000-00805F9B34FB"

    def test_zone_4(self):
        """Test zone 4 UUID."""
        uuid = get_profile_characteristic_uuid(4)
        assert uuid == "0000E004-0000-1000-8000-00805F9B34FB"

    def test_zone_8(self):
        """Test zone 8 UUID."""
        uuid = get_profile_characteristic_uuid(8)
        assert uuid == "0000E008-0000-1000-8000-00805F9B34FB"
