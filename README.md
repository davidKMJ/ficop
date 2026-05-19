# ficop

![Static Badge](https://img.shields.io/badge/status-in_progress-orange?style=for-the-badge)
![Static Badge](https://img.shields.io/badge/type-research-purple?style=for-the-badge)

Fiber coupling optimization automation project for quantum computing experiments.

## Setup

```bash
# Clone the repository
git clone https://github.com/davidKMJ/ficop.git
cd ficop

# Install dependencies
uv sync # To install uv: https://docs.astral.sh/uv/getting-started/installation/

# Run the application
uv run ficop.py
```

### SCServo setup

TODO

### Logger setup — oscilloscope

TODO (NI-VISA)

### Logger setup — PicoLog

TODO

## Library: `cua`

Python package layout: `cua/scservo`, `cua/logger`, `cua/ficop`.

### SCServo (`cua.scservo`)

**Features:** This wraps the SCServo SDK. It opens a serial port. It pings and scans IDs. It reads positions. It writes goal positions. It sets torque, acceleration, and speed.

Protocol selection uses `protocol_end`. Use `0` for STS/SMS. Use `1` for SCS.

Interactive debugger: run `examples/scservo_debug_console.py`. Or call `cua.scservo.debug.run_interactive_console()`. Enter `help` for commands.

Related paths:

```
ficop/
├── cua/scservo/
│   ├── servo.py                    # study: ServoController, scan/ping, motion API
│   ├── debug.py                    # study: interactive console, port helpers
│   └── sdk/                        # study: protocol and packet details
├── examples/scservo_debug_console.py # study: runnable console entry point
└── originals/scservo/              # reference: upstream/vendor snapshots
```

### Loggers (`cua.logger`)

**Features:** Read a scalar merit signal from hardware. Use it in optimizers or plot it live.

All loggers share `BaseLogger`. Key methods are `connect`, `disconnect`, and `get_current_value(channel)`.

Pass the 1-based channel number to each read call (not to the constructor). Use `BaseLogger.plot_stream(channel)` for a quick live plot.

Oscilloscope logger: `cua.logger.Oscilloscope`. It uses PyVISA. It can read waveforms. It can auto-configure.

PicoLog logger: `cua.logger.PicoLogger`. It uses `picosdk`. It streams samples. Pass the channel to `get_current_value(channel)` or `get_values(channel)`.

Related paths:

```
ficop/
├── cua/logger/
│   ├── logger.py                   # study: BaseLogger, plot_stream
│   ├── oscilloscope/oscilloscope.py # study: VISA oscilloscope implementation
│   └── picolog/pico_logger.py      # study: PicoLog PL1000 implementation
└── originals/
    ├── oscilloscope.py             # reference: older oscilloscope script
    ├── pico_single.py              # reference: Pico read examples
    ├── pico_multichannel.py        # reference: multichannel Pico example
    └── pico_streaming.py           # reference: streaming Pico example
```

To upgrade:

- Subclass `BaseLogger` in `logger.py` for a new instrument type, or extend `Oscilloscope` / `PicoLogger` for device-specific SCPI or sampling.

### Optimization core (`cua.ficop`)

**Features:**: Configures optimizers. Takes a servo controller and logger as properties.

`BaseOptimizer` ties a `BaseLogger` to a `ServoController`. It moves servos. It waits. It reads merit via `value_fn`.

Built-ins: `ManualOptimizer`, `TwoKnobOptimizer`, and `Compose`.

Helpers: `default_value_fn(channel)` and `oscilloscope_mean_value_fn(channel=…)`.

Related paths:

```
ficop/
├── cua/ficop/
│   ├── optimizer.py                # study: BaseOptimizer, Manual, TwoKnob, Compose
│   └── dummy.py                    # study: dummy controller/logger
└── examples/ficop_dummy_example.py # study: minimal scripted pipeline
```

To upgrade:

- Subclass `BaseOptimizer` (see `cua/ficop/optimizer.py`), then expose it via `ficop.py`: register in `CUSTOM_OPTIMIZERS` (~183), or set a step `type` to `module.path:Class` (`_resolve_custom_class`, ~798–806). `_build_pipeline` (~750–779) constructs each step with merged `optimizer.base` (minus `restore_on_stop`) plus that step’s `args`. For custom steps only, extra `args` JSON is parsed by `_parse_extra_args` (~270–276).

## Ficop desktop application

Entry point: `python ficop.py` (or `uv run ficop.py`) from the repository root. UI state is stored in `~/.ficop/ui_config.json`.

Related paths:

```
ficop/
└── ficop.py                        # study: UI, defaults, presets, custom optimizers
```

### Quick start

1. Run `python ficop.py` (or `uv run ficop.py`).
2. Open Settings. Select port, baudrate, and `protocol_end`. Add or scan servo IDs.
3. Select a logger. Use dummy for dry-run. Use PicoLog or oscilloscope for hardware.
4. Configure optimization steps. Set position limits and read delay.
5. Click Check. Then click Run.

For a scripted run, see `examples/ficop_dummy_example.py`.

### Features

Settings: Open the Settings tab/dialog for detailed scservo and loggers configurations.

Servos and pairs: On the main window, maintain the servo list and two-knob pairs. Use Scan or Add ID.

Optimization tab: Edit the Steps. Use Add / Edit / Remove and reorder steps. Save or load a preset file from this tab (`*.ficop-preset.json`).

Run: Click Check before Run when you change wiring. Watch the log and merit plot during a run.

Names: Rename a servo from the servo list or a pair from the pair list.

Records: Can record current positions manually when setting positions. Automatically stores positions when optimization started and ended.

Defaults: Restore defaults clears most UI config but keeps existing records.
