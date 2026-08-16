"""Packet builders and response parsers for the Holman Water BLE protocol.

All packet formats are derived from the decompiled iGardener Android app.
"""

from __future__ import annotations

import struct
from datetime import datetime
from typing import Optional

from .const import (
    CMD_DISCONNECT,
    CMD_KEEP_CONNECTION,
    DI_ACTIVE_STATION,
    DI_BITFIELD,
    DI_BIT_IS_DIAL_PRESENTED,
    DI_BIT_IS_WATERING,
    DI_BIT_MCU_V_PROTO1,
    DI_BIT_MCU_V_PROTO2,
    DI_BIT_RAIN_SENSOR_ON,
    DI_BIT_RAIN_SENSOR_WET,
    DI_CONNECTED_VALVES,
    DI_DEVICE_TYPE,
    DI_DIAGNOSTIC,
    DI_DIAL_POSITION,
    DI_FW_VERSION_HI,
    DI_FW_VERSION_LO,
    DI_PROTOCOL_VERSION,
    DI_UNUSED,
    DI_VOLTAGE_AC,
    DI_VOLTAGE_DC,
    DI_VOLTAGE_VALVE,
    PROFILE_PACKET_SIZE,
    PROFILE_MODE_DISABLED,
    SCAN_BITFIELD_OFFSET,
    SCAN_DEVICE_TYPE_OFFSET,
    SCAN_FIRMWARE_VERSION_OFFSET,
    SCAN_MAC_END_OFFSET,
    SCAN_MAC_START_OFFSET,
    SCAN_PASSCODE_HI_OFFSET,
    SCAN_PASSCODE_LO_OFFSET,
    SCAN_POWER_AC_OFFSET,
    SCAN_POWER_DC_OFFSET,
    TIME_PACKET_SIZE,
    WATERING_PACKET_SIZE,
    WATERING_FLAG_CYCLE,
    WATERING_FLAG_START,
)
from .models import DeviceInfo, ScanInfo


def build_passcode(passcode: int) -> bytes:
    """Build a 2-byte passcode packet (big-endian).

    Args:
        passcode: 16-bit passcode value (1-65534).

    Returns:
        2-byte payload for the PASSCODE characteristic.
    """
    return bytes([(passcode >> 8) & 0xFF, passcode & 0xFF])


def build_current_time() -> bytes:
    """Build an 8-byte current time packet.

    Format: [year_hi, year_lo, month, day, weekday, hour, min, sec]
    - year: big-endian 16-bit
    - month: 1-12
    - weekday: 0=Sunday, 6=Saturday

    Returns:
        8-byte payload for the TIME characteristic.
    """
    now = datetime.now()
    year = now.year
    month = now.month
    day = now.day
    # Python weekday: 0=Monday, 6=Sunday → convert to 0=Sunday, 6=Saturday
    weekday = (now.weekday() + 1) % 7
    hour = now.hour
    minute = now.minute
    second = now.second

    return bytes([
        (year >> 8) & 0xFF,
        year & 0xFF,
        month,
        day,
        weekday,
        hour,
        minute,
        second,
    ])


def build_watering_start(zone: int, duration_minutes: int) -> bytes:
    """Build a 10-byte watering start packet.

    Args:
        zone: 1-based zone number.
        duration_minutes: Manual watering duration in minutes.

    Returns:
        10-byte payload for the WATERING characteristic.
    """
    packet = bytearray(WATERING_PACKET_SIZE)
    packet[0] = WATERING_FLAG_START  # bit 0 = start
    packet[1] = zone - 1  # 0-based zone index
    packet[2] = 0  # manual hour (0 = use default)
    packet[3] = duration_minutes & 0xFF  # manual minute
    # Bytes 4-9: cycle run/delay time = 0 for manual watering
    return bytes(packet)


def build_watering_stop(zone: int) -> bytes:
    """Build a 10-byte watering stop packet.

    Args:
        zone: 1-based zone number.

    Returns:
        10-byte payload for the WATERING characteristic.
    """
    packet = bytearray(WATERING_PACKET_SIZE)
    packet[0] = 0  # bit 0 = 0 (stop)
    packet[1] = zone - 1  # 0-based zone index
    # All other bytes = 0
    return bytes(packet)


def build_disabled_profile() -> bytes:
    """Build a 20-byte disabled schedule profile.

    Mode=0 disables the schedule for the zone.

    Returns:
        20-byte payload for a PROFILE characteristic.
    """
    packet = bytearray(PROFILE_PACKET_SIZE)
    packet[0] = PROFILE_MODE_DISABLED
    return bytes(packet)


def build_keep_connection() -> bytes:
    """Build a 1-byte keep-alive heartbeat packet.

    Returns:
        1-byte payload for the COMMAND characteristic.
    """
    return bytes([CMD_KEEP_CONNECTION])


def build_disconnect() -> bytes:
    """Build a 1-byte disconnect packet.

    Returns:
        1-byte payload for the COMMAND characteristic.
    """
    return bytes([CMD_DISCONNECT])


def parse_device_info(data: bytes) -> DeviceInfo:
    """Parse a DEVICE_INFO response (17+ bytes).

    Args:
        data: Raw bytes from the DEVICE_INFO characteristic.

    Returns:
        Parsed DeviceInfo dataclass.
    """
    info = DeviceInfo()

    if len(data) < 12:
        return info

    # Firmware version: big-endian 16-bit
    info.firmware_version = (data[DI_FW_VERSION_HI] << 8) | data[DI_FW_VERSION_LO]

    # Protocol version
    info.protocol_version = data[DI_PROTOCOL_VERSION]

    # Device type
    info.device_type = data[DI_DEVICE_TYPE]

    # Dial position
    info.dial_position = data[DI_DIAL_POSITION]

    # Voltages (divide by 10)
    info.voltage_dc = data[DI_VOLTAGE_DC] / 10.0
    info.voltage_ac = data[DI_VOLTAGE_AC] / 10.0
    info.voltage_valve = data[DI_VOLTAGE_VALVE] / 10.0

    # Bitfield
    bitfield = data[DI_BITFIELD]
    info.is_watering = bool(bitfield & DI_BIT_IS_WATERING)
    info.rain_sensor_on = bool(bitfield & DI_BIT_RAIN_SENSOR_ON)
    info.rain_sensor_wet = bool(bitfield & DI_BIT_RAIN_SENSOR_WET)
    info.is_dial_presented = bool(bitfield & DI_BIT_IS_DIAL_PRESENTED)

    # MCU version depends on protocol version
    if info.protocol_version <= 1:
        info.mcu_v = (bitfield >> 6) & 1
    else:
        info.mcu_v = (bitfield >> 7) & 1

    # Connected valves
    info.connected_valves = data[DI_CONNECTED_VALVES]
    info.valve_v = data[DI_CONNECTED_VALVES] & 1

    # Active station
    info.active_station = data[DI_ACTIVE_STATION]

    # Diagnostic (only if length > 16)
    if len(data) > DI_DIAGNOSTIC:
        info.diagnostic = data[DI_DIAGNOSTIC]

    return info


def parse_time_response(data: bytes) -> tuple[int, int, int, int, int, int, int]:
    """Parse a TIME response (8 bytes).

    Args:
        data: Raw bytes from the TIME characteristic.

    Returns:
        Tuple of (year, month, day, weekday, hour, minute, second).
    """
    if len(data) < TIME_PACKET_SIZE:
        return (0, 0, 0, 0, 0, 0, 0)

    year = (data[0] << 8) | data[1]
    month = data[2]
    day = data[3]
    weekday = data[4]
    hour = data[5]
    minute = data[6]
    second = data[7]

    return (year, month, day, weekday, hour, minute, second)


def parse_scan_record(manufacturer_data: bytes) -> Optional[ScanInfo]:
    """Parse BLE advertisement scan record bytes.

    Args:
        manufacturer_data: Raw manufacturer data bytes from scan record.

    Returns:
        Parsed ScanInfo, or None if data is too short.
    """
    if not manufacturer_data or len(manufacturer_data) < 46:
        return None

    info = ScanInfo()
    info.device_type = manufacturer_data[SCAN_DEVICE_TYPE_OFFSET]
    info.firmware_version = manufacturer_data[SCAN_FIRMWARE_VERSION_OFFSET]
    info.power_dc = manufacturer_data[SCAN_POWER_DC_OFFSET]
    info.power_ac = manufacturer_data[SCAN_POWER_AC_OFFSET]

    # MAC address: bytes 37-42
    mac_bytes = manufacturer_data[SCAN_MAC_START_OFFSET:SCAN_MAC_END_OFFSET + 1]
    info.mac_address = ":".join(f"{b:02X}" for b in mac_bytes)

    # Bitfield
    bitfield = manufacturer_data[SCAN_BITFIELD_OFFSET]
    info.is_ac_powered = bool(bitfield & 0x08)  # bit 3
    info.mcu_power = (bitfield >> 6) & 1  # bit 6

    # Passcode: big-endian 16-bit
    info.passcode = (
        (manufacturer_data[SCAN_PASSCODE_HI_OFFSET] << 8)
        | manufacturer_data[SCAN_PASSCODE_LO_OFFSET]
    )

    return info


def get_profile_characteristic_uuid(zone: int) -> str:
    """Get the profile characteristic UUID for a given zone.

    Args:
        zone: 1-based zone number (1-8).

    Returns:
        Full UUID string for the zone's profile characteristic.
    """
    return f"0000E00{zone}-0000-1000-8000-00805F9B34FB"
