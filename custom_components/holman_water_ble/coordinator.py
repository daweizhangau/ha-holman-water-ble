"""Coordinator for Holman Water BLE device operations.

Manages the lifecycle of BLE connections and coordinates operations
across multiple entity platforms.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from bleak.backends.device import BLEDevice

from .const import (
    DEFAULT_POLL_INTERVAL_HOURS,
    DEFAULT_WATERING_DURATION_MINUTES,
    DOMAIN,
    PASSCODE_FILENAME,
    WATERING_COMPLETION_MARGIN_SECONDS,
)
from .holman_ble import HolmanBLE
from .models import DeviceConfig, DeviceInfo, PasscodeStore

_LOGGER = logging.getLogger(__name__)


class HolmanWaterCoordinator:
    """Coordinator for a single Holman Water BLE device.

    Handles connection lifecycle, passcode management, watering timers,
    periodic health checks, and dispatching operations to the BLE client.
    """

    def __init__(
        self,
        ble_device: BLEDevice,
        device_config: DeviceConfig,
        hass_config_dir: str,
    ) -> None:
        """Initialize the coordinator.

        Args:
            ble_device: The BLE device to manage.
            device_config: Device configuration (model, zones, etc.).
            hass_config_dir: Path to the HA config directory for passcode storage.
        """
        self._ble_device = ble_device
        self._device_config = device_config
        self._passcode_store = PasscodeStore()
        self._passcode_file = os.path.join(hass_config_dir, PASSCODE_FILENAME)
        self._client: Optional[HolmanBLE] = None
        self._lock = asyncio.Lock()
        self._watering_durations: dict[int, int] = {}
        self._device_info: Optional[DeviceInfo] = None
        self._available: bool = True
        self._poll_interval_hours: float = DEFAULT_POLL_INTERVAL_HOURS
        self._poll_task: Optional[asyncio.Task] = None
        self._shutdown: bool = False
        self._background_tasks: set[asyncio.Task] = set()

        # Watering timers: zone -> asyncio.Task handle
        self._watering_timers: dict[int, asyncio.Task] = {}
        # Watering end times: zone -> datetime
        self._watering_end_times: dict[int, datetime] = {}
        # Callbacks to notify entities of state changes
        self._state_update_callbacks: list[Callable] = []

        # Initialize default durations
        for zone in range(1, device_config.total_zones + 1):
            self._watering_durations[zone] = DEFAULT_WATERING_DURATION_MINUTES

        # Load passcodes from file
        self._load_passcodes()

    @property
    def ble_device(self) -> BLEDevice:
        """Get the BLE device."""
        return self._ble_device

    @property
    def device_config(self) -> DeviceConfig:
        """Get the device configuration."""
        return self._device_config

    @property
    def device_info(self) -> Optional[DeviceInfo]:
        """Get the last known device info."""
        return self._device_info

    @property
    def mac_address(self) -> str:
        """Get the device MAC address."""
        return self._ble_device.address

    @property
    def available(self) -> bool:
        """Whether the device is considered available (paired + reachable)."""
        return self._available and self.has_passcode()

    @property
    def paired(self) -> bool:
        """Whether the device has a stored passcode (is paired)."""
        return self.has_passcode()

    @property
    def poll_interval_hours(self) -> float:
        """Get the periodic poll interval in hours."""
        return self._poll_interval_hours

    def set_poll_interval_hours(self, hours: float) -> None:
        """Set the periodic poll interval and restart the task.

        Args:
            hours: Interval in hours (1-24).
        """
        self._poll_interval_hours = hours
        self._restart_poll_task()

    def is_watering(self, zone: int) -> bool:
        """Check if a zone is currently watering.

        Args:
            zone: 1-based zone number.

        Returns:
            True if the watering timer is still active.
        """
        return zone in self._watering_timers

    def get_watering_end_time(self, zone: int) -> Optional[datetime]:
        """Get the expected end time for a zone's watering.

        Args:
            zone: 1-based zone number.

        Returns:
            Expected end time, or None if not watering.
        """
        return self._watering_end_times.get(zone)

    def get_watering_duration(self, zone: int) -> int:
        """Get the watering duration for a zone.

        Args:
            zone: 1-based zone number.

        Returns:
            Duration in minutes.
        """
        return self._watering_durations.get(zone, DEFAULT_WATERING_DURATION_MINUTES)

    def set_watering_duration(self, zone: int, duration: int) -> None:
        """Set the watering duration for a zone.

        Args:
            zone: 1-based zone number.
            duration: Duration in minutes.
        """
        self._watering_durations[zone] = duration

    def has_passcode(self) -> bool:
        """Check if a passcode is stored for this device."""
        return self._passcode_store.has(self.mac_address)

    def register_state_update_callback(self, callback: Callable) -> None:
        """Register a callback to be called when entity state may have changed.

        Args:
            callback: A callable with no arguments.
        """
        self._state_update_callbacks.append(callback)

    def unregister_state_update_callback(self, callback: Callable) -> None:
        """Unregister a previously registered callback.

        Args:
            callback: The callback to remove.
        """
        self._state_update_callbacks.remove(callback)

    def _notify_state_update(self) -> None:
        """Notify all registered callbacks of a state change."""
        for cb in self._state_update_callbacks:
            try:
                cb()
            except Exception as exc:
                _LOGGER.warning("State callback error: %s", exc)

    def start_polling(self) -> None:
        """Start the periodic health check poll loop."""
        if self._poll_task is not None:
            return
        self._poll_task = asyncio.create_task(self._poll_loop())
        _LOGGER.debug(
            "Polling started for %s (interval=%dh)",
            self.mac_address,
            self._poll_interval_hours,
        )

    async def stop_polling(self) -> None:
        """Stop the periodic health check poll loop."""
        self._shutdown = True
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
            _LOGGER.debug("Polling stopped for %s", self.mac_address)

    def _restart_poll_task(self) -> None:
        """Restart the poll loop with the current interval."""
        was_running = self._poll_task is not None and not self._poll_task.done()
        if was_running:
            asyncio.create_task(self._stop_and_start_polling())

    async def _stop_and_start_polling(self) -> None:
        """Stop and restart the poll loop."""
        await self.stop_polling()
        self.start_polling()

    async def _poll_loop(self) -> None:
        """Periodic health check loop.

        Connects to the device every N hours, reads diagnostics,
        and updates availability.
        """
        try:
            while True:
                await asyncio.sleep(self._poll_interval_hours * 3600)
                _LOGGER.debug("Running periodic health check for %s", self.mac_address)
                info = await self.read_diagnostics()
                if info is None:
                    _LOGGER.warning(
                        "Health check failed for %s, marking unavailable",
                        self.mac_address,
                    )
                    self._available = False
                else:
                    if not self._available:
                        _LOGGER.info(
                            "Device %s is back online",
                            self.mac_address,
                        )
                    self._available = True
                    self._device_info = info
                self._notify_state_update()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            _LOGGER.error("Poll loop error for %s: %s", self.mac_address, exc)

    async def first_pair(self) -> bool:
        """Perform first-time pairing with the device.

        Connects, generates a passcode, writes it to the device,
        and saves it to the passcode store.

        Returns:
            True if pairing was successful.
        """
        async with self._lock:
            client = await self._create_client()
            if client is None:
                return False

            try:
                passcode = HolmanBLE.generate_passcode()
                if not await client.pair(passcode):
                    _LOGGER.error("Failed to write passcode during pairing")
                    return False

                self._passcode_store.set(self.mac_address, passcode)
                self._save_passcodes()
                _LOGGER.info(
                    "Device %s paired with passcode %d",
                    self.mac_address,
                    passcode,
                )
                self._notify_state_update()
                return True
            finally:
                await client.disconnect()

    async def read_diagnostics(self) -> Optional[DeviceInfo]:
        """Read device diagnostics.

        Connects, authenticates, reads device info, and disconnects.

        Returns:
            DeviceInfo if successful, None otherwise.
        """
        if self._shutdown:
            return None

        async def _read(client: HolmanBLE) -> Optional[DeviceInfo]:
            info = await client.read_device_info()
            if info is not None:
                self._device_info = info
            return info

        result = await self._operate(_read)
        if result is not None:
            self._notify_state_update()
        return result

    async def start_watering(self, zone: int) -> bool:
        """Start watering for a specific zone.

        Connects, authenticates, sends the watering start command,
        and starts a timer to auto-stop after the duration.

        Args:
            zone: 1-based zone number.

        Returns:
            True if successful.
        """
        # Cancel any existing timer for this zone
        self._cancel_watering_timer(zone)

        duration = self.get_watering_duration(zone)

        async def _start(client: HolmanBLE) -> bool:
            return await client.start_watering(zone, duration)

        result = await self._operate(_start, skip_housekeeping=True)
        if result:
            self._watering_end_times[zone] = datetime.now() + timedelta(
                minutes=duration, seconds=WATERING_COMPLETION_MARGIN_SECONDS
            )
            self._watering_timers[zone] = asyncio.create_task(
                self._watering_timer(zone, duration)
            )
            # Update device info directly — we know watering started
            if self._device_info is not None:
                self._device_info.is_watering = True
            self._notify_state_update()
        return result if isinstance(result, bool) else False

    async def stop_watering(self, zone: int) -> bool:
        """Stop watering for a specific zone.

        Cancels the watering timer and sends the stop command.

        Args:
            zone: 1-based zone number.

        Returns:
            True if successful.
        """
        # Cancel the timer regardless of BLE success
        self._cancel_watering_timer(zone)

        async def _stop(client: HolmanBLE) -> bool:
            return await client.stop_watering(zone)

        result = await self._operate(_stop, skip_housekeeping=True)
        if result:
            if self._device_info is not None:
                self._device_info.is_watering = False
            self._notify_state_update()
        return result if isinstance(result, bool) else False

    async def _watering_timer(self, zone: int, duration_minutes: int) -> None:
        """Background task that waits for watering to complete and updates state.

        Args:
            zone: 1-based zone number.
            duration_minutes: The watering duration in minutes.
        """
        try:
            # Wait for the duration plus a margin
            wait_seconds = duration_minutes * 60 + WATERING_COMPLETION_MARGIN_SECONDS
            await asyncio.sleep(wait_seconds)

            # If shutting down, don't try to reconnect
            if self._shutdown:
                return

            # Verify the device has stopped watering
            info = await self.read_diagnostics()
            if info is not None:
                if info.is_watering:
                    _LOGGER.debug(
                        "Device still watering after timer for zone %d, forcing stop",
                        zone,
                    )
                    await self.stop_watering(zone)
                else:
                    _LOGGER.debug("Watering completed for zone %d", zone)
            else:
                _LOGGER.debug(
                    "Could not verify watering status for zone %d", zone
                )

            self._watering_timers.pop(zone, None)
            self._watering_end_times.pop(zone, None)
            self._notify_state_update()
        except asyncio.CancelledError:
            self._watering_timers.pop(zone, None)
            self._watering_end_times.pop(zone, None)
            raise

    def _cancel_watering_timer(self, zone: int) -> None:
        """Cancel a watering timer for a zone if one exists.

        Args:
            zone: 1-based zone number.
        """
        task = self._watering_timers.pop(zone, None)
        if task is not None and not task.done():
            task.cancel()
        self._watering_end_times.pop(zone, None)

    def cancel_all_watering_timers(self) -> None:
        """Cancel all watering timers. Called on shutdown."""
        for zone in list(self._watering_timers.keys()):
            self._cancel_watering_timer(zone)

    async def unpair(self) -> bool:
        """Unpair the device by clearing the passcode.

        Connects, writes passcode=0, removes the stored passcode,
        and marks the device as unpaired. All entities become unavailable
        except the pair button.

        Returns:
            True if successful.
        """
        async def _unpair(client: HolmanBLE) -> bool:
            return await client.unpair()

        result = await self._operate(_unpair)
        if result:
            self._passcode_store.delete(self.mac_address)
            self._save_passcodes()
            self._available = False
            self.cancel_all_watering_timers()
            _LOGGER.info("Device %s unpaired", self.mac_address)
            self._notify_state_update()
        return isinstance(result, bool) and result

    async def re_pair(self) -> bool:
        """Re-pair an unpaired device.

        Connects, generates a new passcode, writes it to the device,
        saves it, and marks the device as paired again.

        Returns:
            True if successful.
        """
        async with self._lock:
            client = await self._create_client()
            if client is None:
                return False

            try:
                passcode = HolmanBLE.generate_passcode()
                if not await client.pair(passcode):
                    _LOGGER.error("Failed to write passcode during re-pairing")
                    return False

                self._passcode_store.set(self.mac_address, passcode)
                self._save_passcodes()
                self._available = True
                _LOGGER.info(
                    "Device %s re-paired with passcode %d",
                    self.mac_address,
                    passcode,
                )

                # Refresh diagnostics
                info = await client.read_device_info()
                if info is not None:
                    self._device_info = info

                self._notify_state_update()
                return True
            finally:
                await client.disconnect()

    async def _operate(self, operation: Callable, skip_housekeeping: bool = False) -> Any:
        """Execute an operation within a connect-authenticate-disconnect cycle.

        Args:
            operation: Async callable that takes a HolmanBLE client and returns a result.
            skip_housekeeping: If True, skip clearing schedules and setting time.
                Used for watering operations where these writes could interfere.

        Returns:
            The result of the operation, or None if connection/auth failed.
        """
        async with self._lock:
            client = await self._create_client()
            if client is None:
                return None

            try:
                # Authenticate if we have a passcode
                if self.has_passcode():
                    passcode = self._passcode_store.get(self.mac_address)
                    if passcode is not None:
                        if not await client.authenticate(passcode):
                            _LOGGER.error(
                                "Authentication failed for %s",
                                self.mac_address,
                            )
                            return None

                # Clear schedules and set time (best-effort, skip for watering)
                if not skip_housekeeping:
                    try:
                        await client.clear_schedules(self._device_config.total_zones)
                    except Exception:
                        _LOGGER.debug("Failed to clear schedules (non-fatal)")

                    try:
                        await client.set_current_time()
                    except Exception:
                        _LOGGER.debug("Failed to set time (non-fatal)")

                # Execute the actual operation
                return await operation(client)
            finally:
                await client.disconnect()

    async def _create_client(self) -> Optional[HolmanBLE]:
        """Create and connect a BLE client.

        Returns:
            Connected HolmanBLE client, or None if connection failed or shutting down.
        """
        if self._shutdown:
            _LOGGER.debug("Shutdown in progress, not connecting to %s", self.mac_address)
            return None

        client = HolmanBLE(self._ble_device)
        if not await client.connect():
            _LOGGER.error("Failed to connect to %s", self.mac_address)
            return None
        return client

    def track_background_task(self, task: asyncio.Task) -> None:
        """Track a background task for cancellation on shutdown."""
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _cancel_all_background_tasks(self) -> None:
        """Cancel all tracked background tasks."""
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

    def _load_passcodes(self) -> None:
        """Load passcodes from the JSON file."""
        try:
            if os.path.exists(self._passcode_file):
                with open(self._passcode_file) as f:
                    data = json.load(f)
                for mac, code in data.items():
                    self._passcode_store.set(mac, code)
                _LOGGER.debug("Loaded %d passcodes", len(data))
        except Exception as exc:
            _LOGGER.error("Failed to load passcodes: %s", exc)

    def _save_passcodes(self) -> None:
        """Save passcodes to the JSON file."""
        try:
            data = dict(self._passcode_store.passcodes)
            with open(self._passcode_file, "w") as f:
                json.dump(data, f, indent=2)
            _LOGGER.debug("Saved %d passcodes", len(data))
        except Exception as exc:
            _LOGGER.error("Failed to save passcodes: %s", exc)
