"""Tests for the Holman Water BLE client module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.holman_water_ble.holman_ble import HolmanBLE


@pytest.fixture
def mock_device():
    """Create a mock BLE device."""
    device = MagicMock()
    device.address = "AA:BB:CC:DD:EE:FF"
    device.name = "BX1"
    return device


@pytest.fixture
def mock_client():
    """Create a mock BleakClient."""
    client = MagicMock()
    client.is_connected = True
    client.connect = AsyncMock(return_value=True)
    client.disconnect = AsyncMock()
    client.read_gatt_char = AsyncMock()
    client.write_gatt_char = AsyncMock()
    client.services = MagicMock()
    return client


class TestHolmanBLE:
    """Tests for HolmanBLE."""

    def test_init(self, mock_device):
        """Test initialization."""
        ble = HolmanBLE(mock_device)
        assert ble._device == mock_device
        assert ble._client is None
        assert ble._characteristics == {}
        assert ble.is_connected is False

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.holman_ble.establish_connection")
    async def test_connect_success(
        self, mock_establish, mock_device, mock_client
    ):
        """Test successful connection."""
        mock_establish.return_value = mock_client

        ble = HolmanBLE(mock_device)
        result = await ble.connect()

        assert result is True
        assert ble.is_connected is True

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.holman_ble.establish_connection")
    async def test_connect_failure(self, mock_establish, mock_device):
        """Test connection failure."""
        mock_establish.side_effect = Exception("Connection failed")

        ble = HolmanBLE(mock_device)
        result = await ble.connect()

        assert result is False
        assert ble.is_connected is False

    def test_generate_passcode(self):
        """Test passcode generation."""
        passcode = HolmanBLE.generate_passcode()
        assert 1 <= passcode <= 65534

    def test_generate_passcode_multiple(self):
        """Test multiple passcode generations are not all the same."""
        passcodes = {HolmanBLE.generate_passcode() for _ in range(100)}
        assert len(passcodes) > 1  # At least some variety

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.holman_ble.establish_connection")
    async def test_disconnect(self, mock_establish, mock_device, mock_client):
        """Test disconnect."""
        mock_establish.return_value = mock_client

        ble = HolmanBLE(mock_device)
        await ble.connect()
        await ble.disconnect()

        assert ble.is_connected is False
        assert ble._client is None

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.holman_ble.establish_connection")
    async def test_disconnect_when_not_connected(self, mock_establish, mock_device):
        """Test disconnect when not connected."""
        ble = HolmanBLE(mock_device)
        await ble.disconnect()  # Should not raise

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.holman_ble.establish_connection")
    async def test_pair(self, mock_establish, mock_device, mock_client):
        """Test pairing."""
        mock_establish.return_value = mock_client

        ble = HolmanBLE(mock_device)
        await ble.connect()
        result = await ble.pair(12345)

        assert result is True
        mock_client.write_gatt_char.assert_called_with(
            "0000C002-0000-1000-8000-00805F9B34FB",
            bytes([0x30, 0x39]),  # 12345 = 0x3039
            response=True,
        )

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.holman_ble.establish_connection")
    async def test_authenticate(self, mock_establish, mock_device, mock_client):
        """Test authentication."""
        mock_establish.return_value = mock_client
        # Mock PASSCODE read returns matching passcode, so we write directly
        mock_client.read_gatt_char = AsyncMock(return_value=bytes([0x30, 0x39]))

        ble = HolmanBLE(mock_device)
        await ble.connect()
        result = await ble.authenticate(12345)

        assert result is True
        mock_client.write_gatt_char.assert_called_with(
            "0000C002-0000-1000-8000-00805F9B34FB",
            bytes([0x30, 0x39]),
            response=True,
        )

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.holman_ble.establish_connection")
    async def test_pair_read_failure(self, mock_establish, mock_device, mock_client):
        """Test pairing when passcode read fails."""
        mock_establish.return_value = mock_client
        # Mock PASSCODE read to return None (failure) — should still try to write
        mock_client.read_gatt_char = AsyncMock(return_value=None)

        ble = HolmanBLE(mock_device)
        await ble.connect()
        result = await ble.pair(12345)

        assert result is True

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.holman_ble.establish_connection")
    async def test_start_watering(self, mock_establish, mock_device, mock_client):
        """Test starting watering."""
        mock_establish.return_value = mock_client

        ble = HolmanBLE(mock_device)
        await ble.connect()
        result = await ble.start_watering(zone=1, duration_minutes=10)

        assert result is True
        mock_client.write_gatt_char.assert_called_with(
            "0000F006-0000-1000-8000-00805F9B34FB",
            bytes([0x01, 0x00, 0x00, 0x0A, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
            response=True,
        )

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.holman_ble.establish_connection")
    async def test_stop_watering(self, mock_establish, mock_device, mock_client):
        """Test stopping watering."""
        mock_establish.return_value = mock_client

        ble = HolmanBLE(mock_device)
        await ble.connect()
        result = await ble.stop_watering(zone=1)

        assert result is True
        mock_client.write_gatt_char.assert_called_with(
            "0000F006-0000-1000-8000-00805F9B34FB",
            bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
            response=True,
        )

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.holman_ble.establish_connection")
    async def test_unpair(self, mock_establish, mock_device, mock_client):
        """Test unpairing."""
        mock_establish.return_value = mock_client
        # Mock PASSCODE read returns 0, so we write 0 directly (no double-write)
        mock_client.read_gatt_char = AsyncMock(return_value=bytes([0x00, 0x00]))

        ble = HolmanBLE(mock_device)
        await ble.connect()
        result = await ble.unpair()

        assert result is True
        # Should write passcode 0
        mock_client.write_gatt_char.assert_called_with(
            "0000C002-0000-1000-8000-00805F9B34FB",
            bytes([0x00, 0x00]),
            response=True,
        )

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.holman_ble.establish_connection")
    async def test_read_device_info(self, mock_establish, mock_device, mock_client):
        """Test reading device info."""
        mock_establish.return_value = mock_client

        # Mock device info response
        mock_client.read_gatt_char = AsyncMock(side_effect=[
            bytes([0x00, 0x03, 0x02, 100, 11, 52, 0, 0, 0x00, 0x01, 0x00, 0x00,
                   0x00, 0x00, 0x00, 0x00, 0x00]),
            bytes([0x07, 0xE8, 8, 15, 6, 14, 30, 45]),
        ])

        ble = HolmanBLE(mock_device)
        await ble.connect()
        info = await ble.read_device_info()

        assert info is not None
        assert info.firmware_version == 3
        assert info.device_type == 100
        assert info.voltage_dc == 5.2
        assert info.year == 2024

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.holman_ble.establish_connection")
    async def test_clear_schedules(self, mock_establish, mock_device, mock_client):
        """Test clearing schedules."""
        mock_establish.return_value = mock_client

        ble = HolmanBLE(mock_device)
        await ble.connect()
        result = await ble.clear_schedules(num_zones=2)

        assert result is True
        # Should write to E001 and E002
        assert mock_client.write_gatt_char.call_count == 2

    @pytest.mark.asyncio
    @patch("custom_components.holman_water_ble.holman_ble.establish_connection")
    async def test_set_current_time(self, mock_establish, mock_device, mock_client):
        """Test setting current time."""
        mock_establish.return_value = mock_client

        ble = HolmanBLE(mock_device)
        await ble.connect()
        result = await ble.set_current_time()

        assert result is True
        mock_client.write_gatt_char.assert_called_once()
        args = mock_client.write_gatt_char.call_args[0]
        assert args[0] == "0000F005-0000-1000-8000-00805F9B34FB"
        assert len(args[1]) == 8

        ble = HolmanBLE(mock_device)
        import asyncio
        asyncio.run(ble.connect())
        result = asyncio.run(ble.clear_schedules(num_zones=2))

        assert result is True
        # Should write to E001 and E002
        assert mock_client.write_gatt_char.call_count == 2

    @patch("custom_components.holman_water_ble.holman_ble.establish_connection")
    def test_set_current_time(self, mock_establish, mock_device, mock_client):
        """Test setting current time."""
        mock_establish.return_value = mock_client

        ble = HolmanBLE(mock_device)
        import asyncio
        asyncio.run(ble.connect())
        result = asyncio.run(ble.set_current_time())

        assert result is True
        mock_client.write_gatt_char.assert_called_once()
        args = mock_client.write_gatt_char.call_args[0]
        assert args[0] == "0000F005-0000-1000-8000-00805F9B34FB"
        assert len(args[1]) == 8
