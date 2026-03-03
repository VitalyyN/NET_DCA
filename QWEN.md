# NetDCA - Grid Trading Bot for QUIK

## Project Overview

**NetDCA** is an automated grid trading bot (сеточный робот) designed for the **QUIK** trading terminal. It implements a Dollar-Cost Averaging (DCA) grid strategy using Python and the **QuikPy** library as a bridge to QUIK's Lua scripting environment.

### Purpose
The bot automatically:
- Places limit orders in a grid pattern around a base price
- Adjusts the grid as positions are filled
- Tracks position changes and updates the base price upon level execution
- Persists state between restarts via `state.txt`
- Operates within configurable trading hours

### Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   main.py       │────▶│   QuikPy        │────▶│   QUIK Terminal │
│   (Grid Bot)    │     │   (Python Lib)  │     │   (Lua Scripts) │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  settings.py    │     │  NetDCA.lua     │     │  QuikSharp.lua  │
│  (Config)       │     │  (Lua Bot v2.1) │     │  (Connector)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### Key Components

| File | Description |
|------|-------------|
| `main.py` | Main Python grid bot implementation |
| `settings.py` | Configuration parameters (instrument, grid settings, trading hours) |
| `NetDCA.lua` | Alternative Lua-based grid bot (v2.1) with tracked orders |
| `state.txt` | Persistence file storing the base price between restarts |
| `test_position.py` | Utility script to monitor futures positions |
| `QuikPy/` | Python wrapper library for QUIK Lua integration |

## Building and Running

### Prerequisites

1. **QUIK Trading Terminal** installed and configured
2. **Python 3.x** virtual environment (located in `env/`)
3. **QuikSharp Lua scripts** installed in QUIK:
   - Copy `lua/` folder to QUIK installation directory
   - Copy `socket/` folder to QUIK installation directory
   - Enable `QuikSharp.lua` via QUIK menu: **Сервисы → LUA скрипты**

### Setup

```bash
# Activate the virtual environment
env\Scripts\activate

# Install dependencies (if requirements.txt exists)
pip install -r requirements.txt
```

### Running the Bot

```bash
# Activate virtual environment first
env\Scripts\activate

# Run the main grid bot
python main.py

# Or run the position monitoring utility
python test_position.py
```

### Running the Lua Bot (Alternative)

1. Place `NetDCA.lua` in QUIK's Lua scripts directory
2. Launch via QUIK: **Сервисы → LUA скрипты → NetDCA.lua → Запустить**

## Configuration

Edit `settings.py` to customize bot behavior:

```python
CLASS = "FUTSPREAD"           # Trading venue code
SECCODE = "TBH6TBM6"          # Futures ticker symbol
BASE_ASSET_CODE = "TBM6"      # Base asset code for position tracking
ACCOUNT = "762Bzxm"           # Trading account
CLIENT_CODE = ""              # Client code (empty for futures)

LOT_PER_LEVEL = 1             # Lots per grid level
LEVELS = 4                    # Number of grid levels each side
GRID_STEP = 3                 # Grid step (price ticks)
MAX_LOTS_TOTAL = 5            # Maximum total lots

START_TIME = "10:00"          # Trading start time (HH:MM)
END_TIME = "23:50"            # Trading end time (HH:MM)
POLL_MS = 1                   # Polling interval (seconds)
```

## Development Conventions

### Code Style
- **Python**: Follows PEP 8 conventions
- **Lua**: Uses standard Lua conventions with Russian comments
- **Documentation**: Docstrings for functions (Google-style for Python)
- **Naming**: snake_case for Python, lower_case for Lua variables

### Error Handling
- Main loop catches exceptions and limits consecutive errors to 3 before exit
- Graceful shutdown on `Ctrl+C` with order cancellation
- State persistence ensures recovery after restarts

### Testing Practices
- `test_position.py` provides real-time position monitoring
- Manual testing via QUIK terminal required for order execution
- State file (`state.txt`) enables testing across sessions

## Key Features

### Grid Strategy
1. **Initial Setup**: Places buy/sell limit orders at grid levels around base price
2. **Position Tracking**: Monitors futures positions via `GetFuturesHoldings()`
3. **Level Execution**: Updates base price when position reaches `LOT_PER_LEVEL` multiples
4. **Grid Rebalancing**: Cancels and replaces orders when position changes

### State Management
- Base price persisted to `state.txt`
- First-start logic handles existing positions
- Automatic grid alignment on restart

### Time-Based Control
- Bot only trades within `START_TIME` to `END_TIME` window
- Uses QUIK server time for consistency

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| `core.dll` errors | Try different versions from QUIKSharp repository |
| Lua script errors | Update Lua scripts to match QUIK version |
| Connection refused | Ensure QuikSharp.lua is running in QUIK |
| Position not detected | Verify `BASE_ASSET_CODE` matches futures leg |

### Debug Output
- Bot prints base price updates with timestamps
- Exception tracebacks shown on errors
- `❗` prefix indicates exceptions in main loop

## References

- [QuikPy Documentation](QuikPy/README.md)
- [QUIK Lua Documentation](https://arqatech.com/ru/support/files/)
- [QUIKSharp Project](https://github.com/finsight/QUIKSharp)
- [Финансовая Лаборатория](https://finlab.vip/) - Project author's resources

## Author

**Vitaliy Novozhilov** - Grid bot implementation
**Игорь Чечет** - QuikPy library author
