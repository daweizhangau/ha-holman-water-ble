# Developer Guide — Holman Water BLE

This document covers the architecture, development setup, testing, and contribution guidelines for the Holman Water BLE Home Assistant integration.

---

## Architecture

```
custom_components/holman_water_ble/
├── __init__.py        # Integration setup, service registration
├── const.py           # Constants: UUIDs, device types, defaults
├── models.py          # Data classes (DeviceInfo, ScanInfo, etc.)
├── parser.py          # Packet builders & response parsers
├── holman_ble.py      # BLE protocol client (bleak)
├── coordinator.py     # Per-device operation coordinator
├── config_flow.py     # Config flow (discovery, pairing)
├── switch.py          # Valve switch platform
├── number.py          # Watering duration number platform
├── button.py          # Action button platform
├── sensor.py          # Diagnostic sensor platform
├── strings.json       # Translation strings
└── manifest.json      # HACS manifest
```

### Data Flow

```
User Action (toggle switch, press button)
        │
        ▼
Entity Platform (switch.py, button.py, etc.)
        │
        ▼
Coordinator (coordinator.py)
  ┌─────┴─────┐
  │  Connect  │
  │    Auth   │
  │Clear Sched│
  │ Set Time  │
  │  Operate  │
  │ Disconnect│
  └─────┬─────┘
        │
        ▼
HolmanBLE (holman_ble.py) — bleak client
        │
        ▼
Physical Device (BLE GATT)
```

### Connection Lifecycle

Every operation follows this sequence:
1. **Connect** — BLE GATT connection via `bleak-retry-connector`
2. **Authenticate** — Write stored passcode to `C002` characteristic
3. **Clear Schedules** — Write disabled profile (20 zero bytes) to each `E00{N}` characteristic
4. **Set Time** — Write current time to `F005` characteristic
5. **Operate** — Perform the requested action (watering start/stop, read info, unpair)
6. **Disconnect** — Send disconnect command (`0x01`) to `C001`, then close BLE

---

## Protocol Reference

### GATT Service

| Service UUID | Description |
|---|---|
| `C521F000-0D70-4D4F-8E43-40D84C50AB38` | Holman Water BLE |

### Characteristics

| UUID | Name | Access | Size | Purpose |
|---|---|---|---|---|
| `0000F003-...` | MAC | Read | 6B | Device MAC address |
| `0000F004-...` | Device Info | Read/Notify | 17+B | Device status |
| `0000F005-...` | Time | Write (No Resp) | 8B | Set device time |
| `0000F006-...` | Watering | Write (No Resp) | 10B | Start/stop watering |
| `0000C001-...` | Command | Write | 1B | Heartbeat/disconnect |
| `0000C002-...` | Passcode | Read/Write | 2B | Pairing passcode |
| `E00{N}-...` | Profile N | Write (No Resp) | 20B | Schedule for zone N |

### Packet Formats

See `parser.py` for complete implementation. Key formats:

**Passcode** (2 bytes): Big-endian 16-bit `[hi][lo]`

**Watering Start** (10 bytes):
```
[0x01] [zone-1] [0] [duration_min] [0x00 x6]
```

**Watering Stop** (10 bytes):
```
[0x00] [zone-1] [0x00 x8]
```

**Disabled Profile** (20 bytes): All zeros (mode=0)

**Current Time** (8 bytes):
```
[year_hi][year_lo][month][day][weekday][hour][min][sec]
```

**Device Info Response** (17+ bytes): See `parse_device_info()` in `parser.py`

### Device Types

Defined in `const.py` as `DEVICE_TYPE_MAP`. Key mapping:
- 100 = BX1 (1 zone, battery)
- 6 = BX2 (2 zones, battery)
- 7 = BX4 (4 zones, battery)
- 8 = BTX8 (8 zones, AC)
- etc.

---

## Development Setup

### Prerequisites

- Python 3.12+
- Home Assistant development environment
- A Holman BLE device for testing (optional)

### Local Setup

```bash
# Clone the repository
git clone https://github.com/daweizhangau/ha-holman-water-ble.git
cd ha-holman-water-ble

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install development dependencies
pip install -r requirements-test.txt
pip install pytest pytest-asyncio pytest-homeassistant-custom-component
```

### Running Tests

```bash
# Run all unit tests
python3 -m pytest tests/ -v

# Run specific test file
python3 -m pytest tests/test_parser.py -v

# Run with coverage
python3 -m pytest tests/ --cov=custom_components.holman_water_ble
```

### Integration Tests (requires real device)

The tests auto-discover your Holman device by scanning for the service UUID.
No MAC address needed — just make sure the device is powered on and in range.

```bash
# 1. Activate the conda environment with BLE support
conda activate ble-explore

# 2. Install test dependencies
pip install -r requirements-test.txt

# 3. Enable integration tests (they are skipped by default)
export HOLMAN_BLE_INTEGRATION=1

# 4. Run the integration tests
python3 -m pytest tests/test_integration.py -s -m integration
```

Optionally, set a specific MAC to skip the discovery scan:
```bash
export HOLMAN_BLE_MAC="AA:BB:CC:DD:EE:FF"
```

**What the integration tests do:**

| Test | Description |
|---|---|
| `test_connect_and_read_info` | Connects to the device, reads device info (firmware, voltages, dial position, etc.), prints it to console |
| `test_set_time` | Sets the device clock to the host's current time |
| `test_pair_and_watering` | Generates a new passcode, pairs with the device, starts watering for 1 minute, stops watering. **Saves passcode to a local file for reuse** |
| `test_authenticate_and_control` | Uses the saved passcode, authenticates, clears schedules, sets time, starts/stops watering |
| `test_unpair` | Authenticates with saved passcode, clears the passcode (writes 0x0000). **Removes passcode from file** — run this last |

**Typical workflow:**
```bash
# First run — pair and test watering
export HOLMAN_BLE_INTEGRATION=1
python3 -m pytest tests/test_integration.py \
  -k "test_connect_and_read_info or test_set_time or test_pair_and_watering" \
  -v -m integration

# Later — authenticate with saved passcode and control
python3 -m pytest tests/test_integration.py \
  -k "test_authenticate_and_control" \
  -v -m integration

# Cleanup — unpair the device
python3 -m pytest tests/test_integration.py \
  -k "test_unpair" \
  -v -m integration
```

Passcodes are saved to a local file during testing.

---

## Code Style

- Follow [Home Assistant development guidelines](https://developers.home-assistant.io/docs/development_guidelines/)
- Use type hints for all functions
- Write docstrings for all public methods
- Use `_LOGGER` for logging (not `print`)
- Keep functions focused and single-purpose

### Naming Conventions

- Classes: `PascalCase` (e.g., `HolmanBLE`, `DeviceInfo`)
- Functions/methods: `snake_case` (e.g., `build_passcode`, `parse_device_info`)
- Constants: `UPPER_CASE` (e.g., `SERVICE_UUID`, `MAX_ZONES`)
- Private methods: `_leading_underscore` (e.g., `_write_passcode`)

---

## Testing Guidelines

### Unit Tests

- Test all packet builders with known inputs/outputs
- Test all response parsers with sample data
- Test edge cases (empty data, short data, boundary values)
- Mock BLE connections using `AsyncMock` and `MagicMock`
- Use `pytest.mark.asyncio` for async test functions

### Integration Tests

- Mark with `@pytest.mark.integration`
- Skip by default (require `HOLMAN_BLE_MAC` and `HOLMAN_BLE_INTEGRATION`)
- Test end-to-end with a real device
- Save/restore passcodes for multi-test workflows

---

## Deployment

### To Home Assistant

```bash
# Deploy via SSH to your HA server
scp -r custom_components/holman_water_ble user@ha-server:/path/to/config/custom_components/

# Or copy locally if running HA on this machine
cp -r custom_components/holman_water_ble /path/to/ha/config/custom_components/
```

After deployment, restart Home Assistant to pick up changes.

---

## Troubleshooting

### Common Issues

| Issue | Likely Cause | Solution |
|---|---|---|
| Device not discovered | Out of range / not powered | Move closer, check batteries |
| Connection fails | Device busy / interference | Wait and retry |
| Authentication fails | Passcode mismatch | Use Clear Pairing button, then re-add |
| Watering doesn't start | Device in LOCK/OFF dial position | Check dial position sensor |
| Schedules not clearing | Connection interrupted | Retry the operation |

### Debug Logging

Enable debug logging in HA `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.holman_water_ble: debug
```


---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Write tests for your changes
4. Ensure all tests pass
5. Submit a pull request

### What Needs Work

- Support for reading/displaying schedules (currently disabled)
- Rain sensor support for AC controllers
- Cycle mode watering support
- Additional device type testing
- HA device automations/blueprints

---

## License

MIT License — see [LICENSE](LICENSE)
