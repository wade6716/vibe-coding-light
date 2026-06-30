# Vibecoding Signal Light — ESP8266

> A WiFi traffic light that shows your AI coding agent's status.

English | [中文](README_zh.md)

This is an ESP8266 port of [vibecoding-signal-light](https://github.com/starlight36/vibecoding-signal-light). It replaces USB GPIO (MCP2221A) with WiFi HTTP control — the ESP8266 drives the LEDs, and Python scripts send status notifications over the network.

## Demo

Place the signal light beside your laptop — no need to watch the terminal; a glance tells you what your agent is doing.

| Light Pattern | Agent Status | What to Do |
| --- | --- | --- |
| Solid green | Idle | Nothing |
| Slow green-yellow-red cycle | Thinking, running tools, editing files | Wait |
| Yellow flash | Needs your attention | Check when convenient |
| Red flash | Needs permission, blocked, or failed | Handle immediately |
| Green flash | Session ended | Nothing |
| All off | Auto-off after idle timeout | Nothing |

With Bark configured, `blocked`, `permission`, and `attention` signals are also pushed to your phone — you won't miss anything even when away from your desk.

## Supported Tools

- **Claude Code** — automatic notifications via hook adapter
- **Codex** — automatic notifications via hook adapter
- **Manual** — via the `signal-light` CLI

## Hardware

| Part | Description |
| --- | --- |
| ESP8266 (NodeMCU / Wemos D1 Mini) | WiFi microcontroller |
| Traffic light LED module | Red, yellow, green LEDs |
| 3× 220Ω–1kΩ resistors | Current limiting (not needed if module has built-in resistors) |
| USB cable | Power and initial flashing |

## Wiring

Active LOW wiring (common anode):

```
ESP8266 3.3V ───────────┬── Green anode
                        ├── Yellow anode
                        └── Red anode

Green cathode  ── 330Ω ── D5 (GPIO14)
Yellow cathode ── 330Ω ── D6 (GPIO12)
Red cathode    ── 330Ω ── D7 (GPIO13)
```

| Signal | ESP8266 Pin | GPIO | Notes |
| --- | --- | --- | --- |
| Green | D5 | GPIO14 | Idle |
| Yellow | D6 | GPIO12 | Attention needed |
| Red | D7 | GPIO13 | Permission / blocked / failed |
| Active level | LOW | — | `digitalWrite(pin, LOW)` = LED on |

### Why these pins?

D5/D6/D7 are reliable general-purpose GPIOs with PWM support (used for soft-pulse brightness effects) and no boot-mode conflicts.

Avoid: GPIO0 (boot mode), GPIO2 (boot mode), GPIO15 (needs pull-down at boot), GPIO16 (no PWM).

See [docs/wiring.md](docs/wiring.md) for detailed wiring instructions.

## Quick Start

### 1. Flash the firmware

```bash
cd firmware
# Install PlatformIO CLI (if not already installed)
pip install platformio

# Build and flash
pio run -t upload

# Monitor serial output
pio device monitor
```

### 2. Configure WiFi

On first boot (or when WiFi connection fails), the ESP8266 creates a hotspot:

- **Hotspot name**: `Signal-Light-Setup`
- A captive portal opens automatically after connecting
- Select your WiFi, enter the password
- The ESP8266 connects automatically after saving

### 3. Install the Python client

```bash
cd client
uv sync

# Test connection
uv run signal-light list
uv run signal-light status
```

### 4. Install hooks

```bash
# Install all supported agent hooks
cd client
uv run signal-light install-hooks --all -y

# Or just Claude Code
uv run signal-light install-hooks --agent claude-code -y

# Or just Codex
uv run signal-light install-hooks --agent codex -y
```

### 5. Configure Bark push notifications (optional)

[Bark](https://github.com/Finb/Bark) is an iOS push notification service. Once configured, critical signals are automatically pushed to your phone.

```bash
# Copy the template and fill in your Bark key
cp client/.env.example client/.env
# Edit client/.env, replace YOURKEY with your actual Bark key

# Test notifications
uv run signal-light bark-test
```

Shell scripts auto-load `client/.env` — no manual `export` needed. You can also override in the shell:

```bash
export BARK_SERVER_URL=https://api.day.app/YOURKEY
```

### 6. Usage

```bash
# Send signals manually
uv run signal-light play working
uv run signal-light play permission
uv run signal-light play idle

# Check status
uv run signal-light status

# Test red/yellow/green
uv run signal-light test

# Test Bark push
uv run signal-light bark-test

# Clear all state
uv run signal-light reset
```

## Device Discovery

The Python client finds the ESP8266 in this order:

1. **mDNS** — auto-resolves `signal-light.local` (requires ESP8266 and your computer on the same LAN)
2. **Environment variable** — `SIGNAL_LIGHT_HOST=<ip>` for manual override

```bash
# Manual IP override
export SIGNAL_LIGHT_HOST=192.168.1.100
uv run signal-light status
```

## HTTP API

The ESP8266 runs an HTTP server. Test it directly with `curl`:

```bash
# Send a signal
curl -X POST http://signal-light.local/signal \
  -H 'Content-Type: application/json' \
  -d '{"signal":"working","session_id":"test1"}'

# Get status
curl http://signal-light.local/status

# Reset
curl -X POST http://signal-light.local/reset
```

### POST /signal

```json
{
  "signal": "working",
  "session_id": "abc123"
}
```

Supported signals: `idle`, `thinking`, `working`, `tool_done`, `attention`, `permission`, `blocked`, `done`, `session_start`, `session_end`, `session_done`, `off`, `turn_end`

### GET /status

```json
{
  "aggregate": "working",
  "pattern": "work_cycle",
  "sessions": {
    "abc123": {"signal": "working", "age_seconds": 42}
  }
}
```

### POST /reset

Clears all sessions and turns off all LEDs.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `SIGNAL_LIGHT_HOST` | (empty) | Manual ESP8266 IP, used when mDNS is unavailable |
| `SIGNAL_LIGHT_USE_UV` | `0` | Set to `1` to run shell scripts via `uv run` |
| `BARK_SERVER_URL` | (empty) | Bark push URL, e.g. `https://api.day.app/YOURKEY` |
| `BARK_NOTIFY_SIGNALS` | `blocked,permission,attention` | Comma-separated signals that trigger Bark push |

Recommended: write these variables to `client/.env` — shell scripts load it automatically. Template: `client/.env.example`.

## Project Structure

```
vibe-coding-signal-light-esp8266/
├── firmware/
│   ├── platformio.ini          # PlatformIO config
│   ├── include/config.h        # Pin and timing constants
│   └── src/main.cpp            # ESP8266 firmware
├── client/
│   ├── pyproject.toml
│   ├── .env.example            # Environment variable template
│   ├── signal_light/
│   │   ├── agent_signals.py    # Signal definitions
│   │   ├── esp.py              # HTTP client + mDNS discovery
│   │   ├── bark.py             # Bark push notifications
│   │   ├── claude_code_hook.py # Claude Code hook adapter
│   │   ├── codex_hook.py       # Codex hook adapter
│   │   ├── hook_installer.py   # Hook installation wizard
│   │   └── cli.py              # CLI entry point
│   ├── scripts/                # Shell script wrappers
│   └── tests/                  # Unit tests
├── docs/
│   └── wiring.md               # Wiring guide
└── README.md
```

## Claude Code Integration

Claude Code sends JSON hook data via stdin:

```bash
echo '{"event":"PreToolUse","session_id":"demo"}' | ./scripts/claude-code-signal-hook
echo '{"event":"PermissionRequest","session_id":"demo"}' | ./scripts/claude-code-signal-hook
echo '{"event":"Notification","session_id":"demo"}' | ./scripts/claude-code-signal-hook
```

| Claude Code Event | Light Behavior |
| --- | --- |
| `SessionStart` | Solid green (idle) |
| `UserPromptSubmit` | Work cycle |
| `PreToolUse` | Work cycle |
| `PostToolUse` | Work cycle |
| `PostToolUseFailure` | Red flash |
| `Notification` | Yellow flash |
| `PermissionRequest` | Red flash |
| `Stop` | Clear work state |
| `SessionEnd` | Green flash (done) |

## Codex Integration

```bash
./scripts/codex-signal-hook UserPromptSubmit
./scripts/codex-signal-hook PreToolUse
./scripts/codex-signal-hook PermissionRequest
./scripts/codex-signal-hook Stop
```

| Codex Event | Light Behavior |
| --- | --- |
| `SessionStart` | Solid green (idle) |
| `UserPromptSubmit` | Work cycle |
| `PreToolUse` | Work cycle |
| `PostToolUse` | Work cycle |
| `PermissionRequest` | Red flash |
| `Stop` | Clear work state |
| `SessionEnd` | Green flash (done) |

## Multi-Session Behavior

The ESP8266 maintains per-session state and displays the highest priority:

```
Red flash > Yellow flash > Work cycle > Solid green
```

When one session is waiting for permission, the red flash won't be overridden even if another session starts working.

## WiFi Reset

To change WiFi networks:

1. Long-press the FLASH/RST button on the ESP8266
2. Or send a specific command via serial monitor to clear WiFi config
3. The ESP8266 re-enters hotspot provisioning mode

## Differences from Reference Project

| Aspect | Reference (MCP2221A) | This Project (ESP8266) |
| --- | --- | --- |
| Hardware control | Python EasyMCP2221, USB GPIO | HTTP POST to ESP8266 WiFi server |
| Animation | Python background worker | ESP8266 firmware millis() state machine |
| Session state | /tmp/signal-light/ JSON files | ESP8266 in-memory array |
| Python dependencies | EasyMCP2221 | None (stdlib only) |
| Device discovery | Local USB | mDNS + env var fallback |
| WiFi provisioning | None | WiFiManager captive portal |
| Brightness control | Boolean on/off | 10-bit PWM soft pulse |

## Running Tests

```bash
cd client
uv sync
uv run pytest tests/ -v
```

## License

[MIT](LICENSE)
