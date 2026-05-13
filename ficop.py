"""
Ficop - fiber coupling optimizer UI.

Run from the repository root:
    python ficop.py
"""

from __future__ import annotations

import importlib
import inspect
import json
import math
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QEvent, QObject, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QActionGroup, QColor, QGuiApplication, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

import pyqtgraph as pg

from cua.ficop import Compose, ManualOptimizer, TwoKnobOptimizer, default_value_fn
from cua.ficop.dummy import DummyController, DummyLogger
from cua.logger import BaseLogger, Oscilloscope, PicoLogger
from cua.scservo import ServoController, scan_scservo_ids
from cua.scservo.debug import get_available_serial_ports

try:
    import pyvisa as visa
except Exception:  # pragma: no cover - optional at runtime
    visa = None


DUMMY_PORT = "<dummy>"
APP_DIR = Path.home() / ".ficop"
APP_CONFIG_PATH = APP_DIR / "ui_config.json"
PRESET_SUFFIX = ".ficop-preset.json"


DEFAULT_CONFIG: dict[str, Any] = {
    "scservo": {
        "port": DUMMY_PORT,
        "baudrate": 1_000_000,
        "protocol_end": 0,
        "scan_min": 1,
        "scan_max": 252,
        "acceleration": 0,
        "speed": 0,
        "hold_torque_on_disconnect": False,
        "dummy_servo_ids": [1, 2, 3, 4],
        "servo_ids": [],
        "servo_names": {},
        "pairs": [],
        "position_records": [],
        "shiver_amplitude": 100,
        "shiver_duration_s": 2.0,
    },
    "logger": {
        "style": "dummy",
        "channel": 1,
        "devices": {
            "dummy": DUMMY_PORT,
            "picolog": "pl1000",
            "oscilloscope": "",
        },
        "channel_names": {
            "dummy": {},
            "picolog": {},
            "oscilloscope": {},
        },
        "dummy": {
            "center": "0, 0, 0, 0",
            "sigma": "100",
            "noise": 0.001,
            "unit": "",
        },
        "picolog": {
            "input_range_mv": 2500,
            "stream_samples_per_channel": 1000,
            "stream_us_per_block": 1_000_000,
        },
        "oscilloscope": {
            "timeout": 30000,
            "auto_configure": True,
            "memory_depth": 12000,
            "waveform_mode": "NORM",
            "waveform_format": "WORD",
            "time_mode": "ROLL",
            "time_scale": 0.001,
            "unit": "V",
            "mean_waveform": True,
            "offset": 0.0,
            "scale": 1.0,
        },
    },
    "optimizer": {
        "base": {
            "min_position": -15000,
            "max_position": 15000,
            "position_threshold": 5,
            "position_timeout": 5.0,
            "wait_for_value": 0.1,
            "value_threshold": -1.0e100,
            "verbose": True,
            "restore_on_stop": True,
        },
        "items": [
            {
                "type": "manual",
                "name": "Coarse manual sweep",
                "servo_ids": [],
                "args": {
                    "iterations": 1,
                    "margin": 500,
                    "step": 10,
                    "margin_decay": 1.5,
                    "no_update_count_early_stop": False,
                    "no_update_count_threshold": 10,
                },
            },
            {
                "type": "two_knob",
                "name": "Two-knob walk",
                "pairs": [],
                "args": {
                    "iterations": 10,
                    "step": 5,
                    "direction_update_interval": 5,
                    "no_update_count_threshold": 10,
                },
            },
            {
                "type": "manual",
                "name": "Fine manual sweep",
                "servo_ids": [],
                "args": {
                    "iterations": 5,
                    "margin": 50,
                    "step": 2,
                    "margin_decay": 1.0,
                    "no_update_count_early_stop": True,
                    "no_update_count_threshold": 5,
                },
            },
        ],
    },
}


CUSTOM_OPTIMIZERS: dict[str, type] = {}

OPTIMIZER_TYPES: dict[str, dict[str, Any]] = {
    "manual": {
        "label": "Manual servo sweep",
        "class": ManualOptimizer,
        "defaults": DEFAULT_CONFIG["optimizer"]["items"][0]["args"],
    },
    "two_knob": {
        "label": "Two-knob pair walk",
        "class": TwoKnobOptimizer,
        "defaults": DEFAULT_CONFIG["optimizer"]["items"][1]["args"],
    },
}


def _deep_update(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_update(out[key], value)
        else:
            out[key] = value
    return out


def _migrate_logger_devices(config: dict[str, Any]) -> dict[str, Any]:
    """Move the legacy ``logger.device_name`` field into ``logger.devices``."""
    lc = config.get("logger")
    if not isinstance(lc, dict):
        return config
    devices = lc.setdefault(
        "devices", deepcopy(DEFAULT_CONFIG["logger"]["devices"])
    )
    legacy = lc.pop("device_name", None)
    if legacy:
        style = str(lc.get("style", "dummy"))
        devices.setdefault(style, legacy)
    lc.setdefault(
        "channel_names",
        deepcopy(DEFAULT_CONFIG["logger"]["channel_names"]),
    )
    return config


def _load_config() -> dict[str, Any]:
    if not APP_CONFIG_PATH.exists():
        return deepcopy(DEFAULT_CONFIG)
    try:
        data = json.loads(APP_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(DEFAULT_CONFIG)
    if not isinstance(data, dict):
        return deepcopy(DEFAULT_CONFIG)
    return _migrate_logger_devices(_deep_update(DEFAULT_CONFIG, data))


def _save_config(config: dict[str, Any]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    APP_CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _parse_number_list(text: str) -> list[float] | float:
    parts = [p.strip() for p in text.replace(",", " ").split() if p.strip()]
    if not parts:
        return 0.0
    nums = [float(p) for p in parts]
    return nums[0] if len(nums) == 1 else nums


def _parse_int_list(text: str) -> list[int]:
    parts = [p.strip() for p in text.replace(",", " ").split() if p.strip()]
    out: list[int] = []
    seen: set[int] = set()
    for p in parts:
        value = int(p)
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _format_int_list(values: list[int]) -> str:
    return ", ".join(str(int(v)) for v in values)


def _parse_extra_args(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Additional arguments must be a JSON object")
    return parsed


def _port_label(port: dict[str, str]) -> str:
    device = port.get("device", "")
    description = port.get("description", "")
    manufacturer = port.get("manufacturer", "")
    extras = " ".join(x for x in (description, manufacturer) if x)
    return f"{device} - {extras}" if extras else device


def _list_visa_devices() -> list[str]:
    if visa is None:
        return []
    try:
        rm = visa.ResourceManager()
        return list(rm.list_resources())
    except Exception:
        return []


def _build_dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(50, 52, 55))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(240, 240, 240))
    palette.setColor(QPalette.ColorRole.Base, QColor(32, 33, 36))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(42, 44, 48))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(50, 52, 55))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(240, 240, 240))
    palette.setColor(QPalette.ColorRole.Text, QColor(240, 240, 240))
    palette.setColor(QPalette.ColorRole.Button, QColor(58, 60, 64))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(240, 240, 240))
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(QPalette.ColorRole.Highlight, QColor(43, 110, 160))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Link, QColor(102, 178, 255))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(140, 140, 140))
    return palette


def _build_light_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(245, 245, 247))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(20, 20, 22))
    palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(238, 238, 240))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 220))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(20, 20, 22))
    palette.setColor(QPalette.ColorRole.Text, QColor(20, 20, 22))
    palette.setColor(QPalette.ColorRole.Button, QColor(232, 232, 235))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(20, 20, 22))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(200, 30, 30))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 120, 215))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Link, QColor(0, 102, 204))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(140, 140, 145))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(150, 150, 155))
    return palette


def _set_fusion_app_palette(app: QApplication, mode: str) -> None:
    app.setStyle("Fusion")
    if mode == "system":
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorScheme") and hints.colorScheme() is not None:
            is_dark = hints.colorScheme() == Qt.ColorScheme.Dark
        else:
            is_dark = app.palette().color(QPalette.ColorRole.Window).lightness() < 128
        _set_fusion_app_palette(app, "dark" if is_dark else "light")
        return
    palette = _build_dark_palette() if mode == "dark" else _build_light_palette()
    app.setPalette(palette)


class _StopRequested(Exception):
    """Raised inside an optimizer run when the user asks to stop."""


_DUMMY_POSITIONS: dict[int, int] = {}


def _resolve_merit_unit(config: dict[str, Any]) -> str:
    """Return the merit unit string for the currently configured logger."""
    lc = config.get("logger", {})
    style = str(lc.get("style", "dummy"))
    if style == "picolog":
        return "mV"
    if style == "dummy":
        return str(lc.get("dummy", {}).get("unit", "") or "").strip()
    if style == "oscilloscope":
        return str(lc.get("oscilloscope", {}).get("unit", "") or "").strip()
    return ""


def _build_servo_controller(config: dict[str, Any]) -> Any:
    """Build (but do not connect) a controller based on the current config."""
    sc = config["scservo"]
    servo_ids = [int(sid) for sid in sc.get("servo_ids", [])]
    if not servo_ids:
        raise ValueError("No servos configured.")
    if sc.get("port") == DUMMY_PORT:
        initial = [int(_DUMMY_POSITIONS.get(int(sid), 0)) for sid in servo_ids]
        return DummyController(servo_ids=servo_ids, initial_positions=initial)
    return ServoController(
        device_name=str(sc["port"]),
        servo_ids=servo_ids,
        baudrate=int(sc.get("baudrate", 1_000_000)),
        protocol_end=int(sc.get("protocol_end", 0)),
    )


def _snapshot_dummy(controller: Any) -> None:
    """Capture the dummy controller's positions so the next instance can restore them."""
    if not isinstance(controller, DummyController):
        return
    try:
        positions = controller.read_positions()
    except Exception:
        return
    for sid, pos in zip(controller.servo_ids, positions):
        _DUMMY_POSITIONS[int(sid)] = int(pos)


def _disconnect_controller(controller: Any, hold_torque: bool) -> None:
    _snapshot_dummy(controller)
    try:
        controller.disconnect(hold_torque=hold_torque)
    except TypeError:
        controller.disconnect()


def _timestamp_label(prefix: str) -> str:
    return f"{prefix} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


class _ServoActionWorker(QObject):
    """Generic worker that connects a controller, runs a callable, then disconnects."""

    log_line = pyqtSignal(str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        config: dict[str, Any],
        fn: Callable[["_ServoActionWorker", Any], Any],
    ) -> None:
        super().__init__()
        self._config = deepcopy(config)
        self._fn = fn
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    @pyqtSlot()
    def run(self) -> None:
        controller = None
        try:
            controller = _build_servo_controller(self._config)
            controller.connect()
            result = self._fn(self, controller)
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            if controller is not None:
                hold = bool(
                    self._config["scservo"].get("hold_torque_on_disconnect", False)
                )
                try:
                    _disconnect_controller(controller, hold)
                except Exception:
                    pass


class _ScanWorker(QObject):
    progress = pyqtSignal(str)
    completed = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(
        self,
        port: str,
        baudrate: int,
        protocol_end: int,
        id_min: int,
        id_max: int,
        dummy_ids: list[int],
    ) -> None:
        super().__init__()
        self._port = port
        self._baudrate = baudrate
        self._protocol_end = protocol_end
        self._id_min = id_min
        self._id_max = id_max
        self._dummy_ids = list(dummy_ids)

    @pyqtSlot()
    def run(self) -> None:
        try:
            if self._port == DUMMY_PORT:
                visible = [
                    sid
                    for sid in self._dummy_ids
                    if self._id_min <= int(sid) <= self._id_max
                ]
                self.progress.emit(f"Dummy scan returned {len(visible)} id(s).")
                self.completed.emit([{"id": int(sid), "model": 0} for sid in visible])
                return

            def _on_progress(sid: int, step: int, total: int) -> None:
                self.progress.emit(f"Scanning id {sid} ({step}/{total})")

            found = scan_scservo_ids(
                self._port,
                baudrate=self._baudrate,
                protocol_end=self._protocol_end,
                id_min=self._id_min,
                id_max=self._id_max,
                on_progress=_on_progress,
            )
            self.completed.emit(found)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class _OptimizeWorker(QObject):
    log_line = pyqtSignal(str)
    completed = pyqtSignal(float, float, bool)  # seconds, merit, was_stopped
    failed = pyqtSignal(str)
    recorded = pyqtSignal(dict)  # auto-record of start/end positions
    sample = pyqtSignal(int, float, float)  # index, value, best_so_far
    stage = pyqtSignal(int, str)  # stage_index, stage_name
    unit = pyqtSignal(str)  # merit unit (e.g. "mV", "V", "")

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self._config = deepcopy(config)
        self._controller: Any = None
        self._logger: BaseLogger | None = None
        self._stop_requested = False
        self._start_positions: list[int] | None = None
        self._sample_index = 0
        self._best_value = float("-inf")

    def request_stop(self) -> None:
        self._stop_requested = True

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    @pyqtSlot()
    def run(self) -> None:
        was_stopped = False
        merit = float("nan")
        elapsed = 0.0
        self._sample_index = 0
        self._best_value = float("-inf")
        try:
            self._controller = self._build_controller()
            self._logger = self._build_logger(self._controller)
            self.unit.emit(_resolve_merit_unit(self._config))
            self._controller.connect()
            if hasattr(self._controller, "configure_servos"):
                sc = self._config["scservo"]
                self._controller.configure_servos(
                    acc=int(sc.get("acceleration", 0)),
                    speed=int(sc.get("speed", 0)),
                )
            self._logger.connect()
            self._configure_logger_after_connect()

            self._start_positions = list(self._controller.read_positions())
            self.log_line.emit(f"Start positions: {self._start_positions}")
            self._emit_record("Run start", self._start_positions)

            pipeline = self._build_pipeline(self._logger, self._controller)
            started = time.perf_counter()
            try:
                merit = float(pipeline.run())
            except _StopRequested:
                was_stopped = True
                self.log_line.emit("Optimization stopped by user.")
                if (
                    bool(self._config["optimizer"]["base"].get("restore_on_stop", True))
                    and self._start_positions
                ):
                    try:
                        self._controller.set_positions(self._start_positions)
                        self.log_line.emit("Restored start positions.")
                    except Exception as exc:
                        self.log_line.emit(f"Restore failed: {exc}")
            elapsed = time.perf_counter() - started

            try:
                end_positions = list(self._controller.read_positions())
                tag = "Run stopped" if was_stopped else "Run end"
                self.log_line.emit(f"{tag} positions: {end_positions}")
                self._emit_record(tag, end_positions)
            except Exception as exc:
                self.log_line.emit(f"Could not read end positions: {exc}")

            self.completed.emit(float(elapsed), float(merit), bool(was_stopped))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self._disconnect_quietly()

    def _emit_record(self, name_prefix: str, positions: list[int]) -> None:
        servo_ids = [int(s) for s in self._config["scservo"].get("servo_ids", [])]
        self.recorded.emit(
            {
                "name": _timestamp_label(name_prefix),
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "positions": {
                    str(sid): int(pos) for sid, pos in zip(servo_ids, positions)
                },
            }
        )

    def _wrap_optimizer_for_stop(self, optimizer: Any) -> None:
        original_blackbox = optimizer.blackbox
        worker = self

        def patched(positions, _orig=original_blackbox):
            if worker._stop_requested:
                raise _StopRequested()
            value = _orig(positions)
            try:
                fvalue = float(value)
            except (TypeError, ValueError):
                return value
            if math.isfinite(fvalue) and fvalue > worker._best_value:
                worker._best_value = fvalue
            worker._sample_index += 1
            best = worker._best_value if math.isfinite(worker._best_value) else fvalue
            worker.sample.emit(worker._sample_index, fvalue, best)
            return value

        optimizer.blackbox = patched

    def _disconnect_quietly(self) -> None:
        if self._logger is not None:
            try:
                self._logger.disconnect()
            except Exception as exc:
                self.log_line.emit(f"Logger disconnect: {exc}")
        if self._controller is not None:
            try:
                hold = bool(
                    self._config["scservo"].get("hold_torque_on_disconnect", False)
                )
                _disconnect_controller(self._controller, hold)
            except Exception as exc:
                self.log_line.emit(f"Servo disconnect: {exc}")

    def _configure_logger_after_connect(self) -> None:
        if self._config["logger"].get("style") != "oscilloscope":
            return
        if self._logger is None:
            return
        scope = self._config["logger"].get("oscilloscope", {})
        if not bool(scope.get("auto_configure", True)):
            return
        self._logger.configure(  # type: ignore[attr-defined]
            memory_depth=int(scope.get("memory_depth", 12000)),
            waveform_mode=str(scope.get("waveform_mode", "NORM")),
            waveform_format=str(scope.get("waveform_format", "WORD")),
            time_mode=str(scope.get("time_mode", "ROLL")),
            start_acquisition=True,
            time_scale=float(scope.get("time_scale", 0.001)),
        )

    def _build_controller(self) -> Any:
        sc = self._config["scservo"]
        servo_ids = [int(sid) for sid in sc.get("servo_ids", [])]
        if not servo_ids:
            raise ValueError("Add or scan at least one servo ID before running.")
        if sc.get("port") == DUMMY_PORT:
            dummy_ids = {int(x) for x in sc.get("dummy_servo_ids", []) or []}
            if dummy_ids:
                missing = [sid for sid in servo_ids if sid not in dummy_ids]
                if missing:
                    raise ValueError(
                        "Servos "
                        + ", ".join(str(s) for s in missing)
                        + " are not in the dummy ID list."
                    )
        return _build_servo_controller(self._config)

    def _build_logger(self, controller: Any) -> BaseLogger:
        lc = self._config["logger"]
        style = str(lc.get("style", "dummy"))
        channel = int(lc.get("channel", 1))
        if style == "dummy":
            if self._config["scservo"].get("port") != DUMMY_PORT:
                raise ValueError(
                    "Dummy logger is only available with the dummy servo controller."
                )
            dummy = lc.get("dummy", {})
            unit = str(dummy.get("unit", "")).strip() or None
            return DummyLogger(
                controller,
                center=_parse_number_list(str(dummy.get("center", "0"))),
                sigma=_parse_number_list(str(dummy.get("sigma", "100"))),
                noise=float(dummy.get("noise", 0.0)),
                unit=unit,
            )
        if style == "picolog":
            pico = lc.get("picolog", {})
            return PicoLogger(
                device_name="pl1000",
                channel=channel,
                input_range_mv=int(pico.get("input_range_mv", 2500)),
                stream_samples_per_channel=int(
                    pico.get("stream_samples_per_channel", 1000)
                ),
                stream_us_per_block=int(pico.get("stream_us_per_block", 1_000_000)),
            )
        if style == "oscilloscope":
            scope = lc.get("oscilloscope", {})
            devices_cfg = lc.get("devices") or {}
            device_name = str(
                devices_cfg.get("oscilloscope") or lc.get("device_name") or ""
            )
            if not device_name:
                raise ValueError(
                    "Select an oscilloscope device (Logger → Device)."
                )
            osc = Oscilloscope(
                device_name=device_name,
                timeout=int(scope.get("timeout", 30000)),
                channel=channel,
                auto_configure=False,
            )
            if bool(scope.get("mean_waveform", True)):
                offset = float(scope.get("offset", 0.0))
                scale = float(scope.get("scale", 1.0)) or 1.0

                def value_fn(logger: BaseLogger) -> float:
                    xy = logger.read_values(channel=channel)  # type: ignore[attr-defined]
                    return (float(sum(xy[1])) / max(len(xy[1]), 1) - offset) / scale

                osc._ficop_value_fn = value_fn  # type: ignore[attr-defined]
            return osc
        raise ValueError(f"Unknown logger style: {style}")

    def _build_pipeline(self, logger: BaseLogger, controller: Any) -> Compose:
        servo_ids = [int(sid) for sid in self._config["scservo"].get("servo_ids", [])]
        id_to_index = {sid: i for i, sid in enumerate(servo_ids)}
        base = deepcopy(self._config["optimizer"].get("base", {}))
        base.pop("restore_on_stop", None)
        base["log_fn"] = lambda msg: self.log_line.emit(str(msg))
        if hasattr(logger, "_ficop_value_fn"):
            base["value_fn"] = getattr(logger, "_ficop_value_fn")
        else:
            base["value_fn"] = default_value_fn
        optimizers = []
        for item in self._config["optimizer"].get("items", []):
            opt_type = str(item.get("type", "manual"))
            args = deepcopy(item.get("args", {}))
            name = str(item.get("name") or opt_type)
            self.log_line.emit(f"Queued {name}")
            if opt_type == "manual":
                selected_ids = [int(sid) for sid in item.get("servo_ids", servo_ids)]
                args["servo_indices"] = [
                    id_to_index[sid] for sid in selected_ids if sid in id_to_index
                ]
                if not args["servo_indices"]:
                    raise ValueError(f"{name}: choose at least one servo")
                cls = ManualOptimizer
            elif opt_type == "two_knob":
                pairs = item.get("pairs") or [
                    [p["a"], p["b"]] for p in self._config["scservo"].get("pairs", [])
                ]
                args["pairs"] = [
                    (id_to_index[int(a)], id_to_index[int(b)])
                    for a, b in pairs
                    if int(a) in id_to_index and int(b) in id_to_index
                ]
                if not args["pairs"]:
                    raise ValueError(f"{name}: choose at least one valid servo pair")
                cls = TwoKnobOptimizer
            elif opt_type in CUSTOM_OPTIMIZERS:
                cls = CUSTOM_OPTIMIZERS[opt_type]
            else:
                cls = _resolve_custom_class(opt_type)
            opt = cls(logger=logger, servo_controller=controller, **base, **args)
            self._wrap_optimizer_for_stop(opt)
            self._wrap_optimizer_for_stage(opt, len(optimizers), name)
            optimizers.append(opt)
        if not optimizers:
            raise ValueError("Add at least one optimization before running.")
        return Compose(optimizers, log_fn=lambda msg: self.log_line.emit(str(msg)))

    def _wrap_optimizer_for_stage(self, optimizer: Any, index: int, name: str) -> None:
        original_run = optimizer.run
        worker = self

        def patched(*args, **kwargs):
            worker.stage.emit(int(index), str(name))
            return original_run(*args, **kwargs)

        optimizer.run = patched


def _resolve_custom_class(opt_type: str) -> type:
    if ":" not in opt_type:
        raise ValueError(f"No optimizer registered for '{opt_type}'")
    module_name, class_name = opt_type.split(":", 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    if not inspect.isclass(cls):
        raise ValueError(f"{opt_type} does not resolve to a class")
    return cls


def _add_line(
    form: QFormLayout, widgets: dict[str, QWidget], key: str, label: str, value: str
) -> None:
    w = QLineEdit(value)
    widgets[key] = w
    form.addRow(label, w)


def _add_spin(
    form: QFormLayout,
    widgets: dict[str, QWidget],
    key: str,
    label: str,
    value: int,
    minimum: int,
    maximum: int,
) -> None:
    w = QSpinBox()
    w.setRange(minimum, maximum)
    w.setValue(value)
    widgets[key] = w
    form.addRow(label, w)


def _add_double(
    form: QFormLayout,
    widgets: dict[str, QWidget],
    key: str,
    label: str,
    value: float,
    minimum: float,
    maximum: float,
    step: float,
) -> None:
    w = QDoubleSpinBox()
    w.setRange(minimum, maximum)
    w.setDecimals(6)
    w.setSingleStep(step)
    w.setValue(value)
    widgets[key] = w
    form.addRow(label, w)


class _ScservoSettingsTab(QWidget):
    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self._config = config
        sc = config["scservo"]
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._baud = QSpinBox()
        self._baud.setRange(1, 10_000_000)
        self._baud.setValue(int(sc.get("baudrate", 1_000_000)))
        self._protocol = QComboBox()
        self._protocol.addItem("STS / SMS", 0)
        self._protocol.addItem("SCS", 1)
        self._protocol.setCurrentIndex(int(sc.get("protocol_end", 0)))
        self._scan_min = QSpinBox()
        self._scan_min.setRange(1, 252)
        self._scan_min.setValue(int(sc.get("scan_min", 1)))
        self._scan_max = QSpinBox()
        self._scan_max.setRange(1, 252)
        self._scan_max.setValue(int(sc.get("scan_max", 252)))
        self._acc = QSpinBox()
        self._acc.setRange(0, 255)
        self._acc.setValue(int(sc.get("acceleration", 0)))
        self._speed = QSpinBox()
        self._speed.setRange(0, 4095)
        self._speed.setValue(int(sc.get("speed", 0)))
        self._hold = QCheckBox("Keep torque on disconnect")
        self._hold.setChecked(bool(sc.get("hold_torque_on_disconnect", False)))
        self._dummy_ids = QLineEdit(_format_int_list(sc.get("dummy_servo_ids", [])))
        self._dummy_ids.setPlaceholderText("1, 2, 3, 4")
        form.addRow("Baudrate", self._baud)
        form.addRow("Protocol", self._protocol)
        form.addRow("Scan from ID", self._scan_min)
        form.addRow("Scan to ID", self._scan_max)
        form.addRow("Acceleration", self._acc)
        form.addRow("Speed", self._speed)
        form.addRow("Dummy IDs", self._dummy_ids)
        form.addRow("", self._hold)
        layout.addLayout(form)
        layout.addStretch(1)

    def commit(self) -> None:
        try:
            dummy_ids = _parse_int_list(self._dummy_ids.text())
        except ValueError as exc:
            raise ValueError(f"Dummy IDs: {exc}") from exc
        if not dummy_ids:
            dummy_ids = list(DEFAULT_CONFIG["scservo"]["dummy_servo_ids"])
        self._config["scservo"].update(
            {
                "baudrate": int(self._baud.value()),
                "protocol_end": int(self._protocol.currentData()),
                "scan_min": int(self._scan_min.value()),
                "scan_max": int(self._scan_max.value()),
                "acceleration": int(self._acc.value()),
                "speed": int(self._speed.value()),
                "hold_torque_on_disconnect": self._hold.isChecked(),
                "dummy_servo_ids": dummy_ids,
            }
        )

    def restore_defaults(self) -> None:
        defaults = DEFAULT_CONFIG["scservo"]
        self._baud.setValue(int(defaults["baudrate"]))
        self._protocol.setCurrentIndex(int(defaults["protocol_end"]))
        self._scan_min.setValue(int(defaults["scan_min"]))
        self._scan_max.setValue(int(defaults["scan_max"]))
        self._acc.setValue(int(defaults["acceleration"]))
        self._speed.setValue(int(defaults["speed"]))
        self._hold.setChecked(bool(defaults["hold_torque_on_disconnect"]))
        self._dummy_ids.setText(_format_int_list(defaults["dummy_servo_ids"]))


class _LoggerSectionPanel(QWidget):
    def __init__(self, config: dict[str, Any], section: str) -> None:
        super().__init__()
        self._config = config
        self._section = section
        self._widgets: dict[str, QWidget] = {}
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        section_config = config["logger"][section]
        if section == "dummy":
            _add_line(
                form,
                self._widgets,
                "center",
                "Peak center",
                str(section_config.get("center", "0")),
            )
            _add_line(
                form,
                self._widgets,
                "sigma",
                "Peak width",
                str(section_config.get("sigma", "100")),
            )
            _add_double(
                form,
                self._widgets,
                "noise",
                "Noise",
                float(section_config.get("noise", 0.0)),
                0.0,
                100.0,
                0.001,
            )
            _add_line(
                form, self._widgets, "unit", "Unit", str(section_config.get("unit", ""))
            )
        elif section == "picolog":
            _add_spin(
                form,
                self._widgets,
                "input_range_mv",
                "Input range (mV)",
                int(section_config.get("input_range_mv", 2500)),
                1,
                100000,
            )
            _add_spin(
                form,
                self._widgets,
                "stream_samples_per_channel",
                "Samples per channel",
                int(section_config.get("stream_samples_per_channel", 1000)),
                1,
                1_000_000,
            )
            _add_spin(
                form,
                self._widgets,
                "stream_us_per_block",
                "Block duration (us)",
                int(section_config.get("stream_us_per_block", 1_000_000)),
                1,
                60_000_000,
            )
        elif section == "oscilloscope":
            _add_spin(
                form,
                self._widgets,
                "timeout",
                "Timeout (ms)",
                int(section_config.get("timeout", 30000)),
                100,
                300000,
            )
            auto = QCheckBox("Auto-configure on connect")
            auto.setChecked(bool(section_config.get("auto_configure", True)))
            self._widgets["auto_configure"] = auto
            form.addRow("", auto)
            mean = QCheckBox("Use waveform mean as merit")
            mean.setChecked(bool(section_config.get("mean_waveform", True)))
            self._widgets["mean_waveform"] = mean
            form.addRow("", mean)
            _add_spin(
                form,
                self._widgets,
                "memory_depth",
                "Memory depth",
                int(section_config.get("memory_depth", 12000)),
                1,
                100_000_000,
            )
            _add_line(
                form,
                self._widgets,
                "waveform_mode",
                "Waveform mode",
                str(section_config.get("waveform_mode", "NORM")),
            )
            _add_line(
                form,
                self._widgets,
                "waveform_format",
                "Waveform format",
                str(section_config.get("waveform_format", "WORD")),
            )
            _add_line(
                form,
                self._widgets,
                "time_mode",
                "Time mode",
                str(section_config.get("time_mode", "ROLL")),
            )
            _add_double(
                form,
                self._widgets,
                "time_scale",
                "Time scale",
                float(section_config.get("time_scale", 0.001)),
                0.000001,
                1000.0,
                0.001,
            )
            _add_double(
                form,
                self._widgets,
                "offset",
                "Merit offset",
                float(section_config.get("offset", 0.0)),
                -1e12,
                1e12,
                0.1,
            )
            _add_double(
                form,
                self._widgets,
                "scale",
                "Merit scale",
                float(section_config.get("scale", 1.0)),
                -1e12,
                1e12,
                0.1,
            )
            _add_line(
                form,
                self._widgets,
                "unit",
                "Unit",
                str(section_config.get("unit", "V")),
            )
        layout.addLayout(form)
        layout.addStretch(1)

    def commit(self) -> None:
        section_config = self._config["logger"][self._section]
        for key, widget in self._widgets.items():
            if isinstance(widget, QLineEdit):
                section_config[key] = widget.text()
            elif isinstance(widget, QCheckBox):
                section_config[key] = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                section_config[key] = widget.value()

    def restore_defaults(self) -> None:
        defaults = DEFAULT_CONFIG["logger"][self._section]
        for key, widget in self._widgets.items():
            value = defaults.get(key)
            if isinstance(widget, QLineEdit):
                widget.setText(str(value or ""))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.setValue(value)


class _LoggerSettingsTab(QWidget):
    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._tabs = QTabWidget()
        self._panels: dict[str, _LoggerSectionPanel] = {
            "dummy": _LoggerSectionPanel(config, "dummy"),
            "picolog": _LoggerSectionPanel(config, "picolog"),
            "oscilloscope": _LoggerSectionPanel(config, "oscilloscope"),
        }
        self._tabs.addTab(self._panels["dummy"], "Dummy")
        self._tabs.addTab(self._panels["picolog"], "PicoLog")
        self._tabs.addTab(self._panels["oscilloscope"], "Oscilloscope")
        layout.addWidget(self._tabs)
        layout.addStretch(1)

    def commit(self) -> None:
        for panel in self._panels.values():
            panel.commit()

    def restore_defaults(self) -> None:
        key = list(self._panels.keys())[self._tabs.currentIndex()]
        self._panels[key].restore_defaults()


class SettingsDialog(QDialog):
    def __init__(self, config: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(520, 460)
        self._config = deepcopy(config)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._tabs = QTabWidget()
        self._scservo_tab = _ScservoSettingsTab(self._config)
        self._logger_tab = _LoggerSettingsTab(self._config)
        self._tabs.addTab(self._scservo_tab, "SCServo")
        self._tabs.addTab(self._logger_tab, "Logger")
        layout.addWidget(self._tabs, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.RestoreDefaults
            | QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            self._restore_defaults
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _restore_defaults(self) -> None:
        if self._tabs.currentIndex() == 0:
            self._scservo_tab.restore_defaults()
        else:
            self._logger_tab.restore_defaults()

    def _accept(self) -> None:
        try:
            self._scservo_tab.commit()
            self._logger_tab.commit()
        except ValueError as exc:
            QMessageBox.warning(self, "Settings", str(exc))
            return
        self.accept()

    def config(self) -> dict[str, Any]:
        return self._config


class OptimizerDialog(QDialog):
    def __init__(
        self,
        config: dict[str, Any],
        item: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Optimization Step")
        self.setMinimumWidth(420)
        self._config = deepcopy(config)
        self._editing = deepcopy(item)
        self._servo_checks: list[QCheckBox] = []
        self._pair_checks: list[QCheckBox] = []
        self._arg_widgets: dict[str, QWidget] = {}
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._name = QLineEdit()
        self._type = QComboBox()
        for key, meta in OPTIMIZER_TYPES.items():
            self._type.addItem(meta["label"], key)
        for key, cls in CUSTOM_OPTIMIZERS.items():
            self._type.addItem(getattr(cls, "__name__", key), key)
        self._type.addItem("Custom (import path)", "custom_path")
        form.addRow("Name", self._name)
        form.addRow("Optimizer", self._type)
        layout.addLayout(form)
        self._body = QVBoxLayout()
        self._body.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addLayout(self._body)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.RestoreDefaults
            | QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            self._restore_defaults
        )
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._type.currentIndexChanged.connect(self._rebuild_body)
        self._load_item()
        self._rebuild_body()

    def _load_item(self) -> None:
        item = self._editing or {}
        opt_type = str(item.get("type", "manual"))
        idx = self._type.findData(opt_type)
        if idx < 0 and ":" in opt_type:
            idx = self._type.findData("custom_path")
        self._type.setCurrentIndex(max(idx, 0))
        self._name.setText(str(item.get("name", "")))

    def _clear_body(self) -> None:
        while self._body.count():
            child = self._body.takeAt(0)
            if child.widget() is not None:
                child.widget().deleteLater()
            elif child.layout() is not None:
                while child.layout().count():
                    nested = child.layout().takeAt(0)
                    if nested.widget() is not None:
                        nested.widget().deleteLater()
        self._servo_checks = []
        self._pair_checks = []
        self._arg_widgets = {}

    def _rebuild_body(self) -> None:
        self._clear_body()
        opt_type = self._selected_type()
        item = self._editing or {}
        args = deepcopy(
            item.get("args") or OPTIMIZER_TYPES.get(opt_type, {}).get("defaults", {})
        )
        if opt_type == "manual":
            self._add_servo_selector(
                item.get("servo_ids") or self._config["scservo"].get("servo_ids", [])
            )
            self._add_int_arg(
                "iterations", "Rounds", int(args.get("iterations", 1)), 0, 10000
            )
            self._add_int_arg(
                "margin", "Search window", int(args.get("margin", 500)), 1, 1_000_000
            )
            self._add_int_arg(
                "step", "Step size", int(args.get("step", 10)), 1, 1_000_000
            )
            self._add_float_arg(
                "margin_decay",
                "Shrink by",
                float(args.get("margin_decay", 1.0)),
                0.0,
                1000.0,
            )
            self._add_bool_arg(
                "no_update_count_early_stop",
                "Early stop on stall",
                bool(args.get("no_update_count_early_stop", True)),
            )
            self._add_int_arg(
                "no_update_count_threshold",
                "Stall threshold",
                int(args.get("no_update_count_threshold", 10)),
                1,
                100000,
            )
        elif opt_type == "two_knob":
            self._add_pair_selector(
                item.get("pairs")
                or [[p["a"], p["b"]] for p in self._config["scservo"].get("pairs", [])]
            )
            self._add_int_arg(
                "iterations", "Rounds", int(args.get("iterations", 1)), 0, 10000
            )
            self._add_int_arg(
                "step", "Step size", int(args.get("step", 10)), 1, 1_000_000
            )
            self._add_int_arg(
                "direction_update_interval",
                "Recompute direction every (0=off)",
                int(args.get("direction_update_interval") or 0),
                0,
                100000,
            )
            self._add_int_arg(
                "no_update_count_threshold",
                "Stall threshold",
                int(args.get("no_update_count_threshold", 10)),
                1,
                100000,
            )
        else:
            self._add_custom_body(item)
        self.adjustSize()

    def _selected_type(self) -> str:
        data = str(self._type.currentData())
        if (
            data == "custom_path"
            and self._editing
            and ":" in str(self._editing.get("type", ""))
        ):
            return str(self._editing["type"])
        return data

    def _servo_label(self, sid: int) -> str:
        names = self._config["scservo"].get("servo_names", {})
        name = str(names.get(str(sid), "")).strip()
        return f"ID {sid} ({name})" if name else f"ID {sid}"

    def _add_servo_selector(self, selected: list[int]) -> None:
        box = QGroupBox("Servos")
        inner = QVBoxLayout(box)
        inner.setAlignment(Qt.AlignmentFlag.AlignTop)
        selected_set = {int(sid) for sid in selected}
        for sid in self._config["scservo"].get("servo_ids", []):
            cb = QCheckBox(self._servo_label(int(sid)))
            cb.setProperty("servo_id", int(sid))
            cb.setChecked(int(sid) in selected_set)
            self._servo_checks.append(cb)
            inner.addWidget(cb)
        self._body.addWidget(box)

    def _add_pair_selector(self, selected: list[list[int]]) -> None:
        box = QGroupBox("Pairs")
        inner = QVBoxLayout(box)
        inner.setAlignment(Qt.AlignmentFlag.AlignTop)
        selected_set = {tuple(map(int, pair)) for pair in selected}
        for pair in self._config["scservo"].get("pairs", []):
            pair_tuple = (int(pair["a"]), int(pair["b"]))
            label = f"{self._servo_label(pair_tuple[0])} + {self._servo_label(pair_tuple[1])}"
            if pair.get("name"):
                label += f" ({pair['name']})"
            cb = QCheckBox(label)
            cb.setProperty("pair", pair_tuple)
            cb.setChecked(pair_tuple in selected_set)
            self._pair_checks.append(cb)
            inner.addWidget(cb)
        self._body.addWidget(box)

    def _add_form_widget(self, label: str, key: str, widget: QWidget) -> None:
        if not self._arg_widgets:
            self._arg_form = QFormLayout()
            self._arg_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            self._body.addLayout(self._arg_form)
        self._arg_widgets[key] = widget
        self._arg_form.addRow(label, widget)

    def _add_int_arg(
        self, key: str, label: str, value: int, minimum: int, maximum: int
    ) -> None:
        w = QSpinBox()
        w.setRange(minimum, maximum)
        w.setValue(value)
        self._add_form_widget(label, key, w)

    def _add_float_arg(
        self, key: str, label: str, value: float, minimum: float, maximum: float
    ) -> None:
        w = QDoubleSpinBox()
        w.setRange(minimum, maximum)
        w.setDecimals(6)
        w.setValue(value)
        self._add_form_widget(label, key, w)

    def _add_bool_arg(self, key: str, label: str, value: bool) -> None:
        w = QCheckBox(label)
        w.setChecked(value)
        self._arg_widgets[key] = w
        self._body.addWidget(w)

    def _add_custom_body(self, item: dict[str, Any]) -> None:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        opt_type = str(self._type.currentData())
        self._custom_path = QLineEdit(
            str(item.get("type", "") if ":" in str(item.get("type", "")) else "")
        )
        self._custom_path.setPlaceholderText("package.module:OptimizerClass")
        self._custom_servos = QComboBox()
        self._custom_servos.addItem("All configured servos", "all")
        self._custom_servos.addItem("No servo argument", "none")
        self._custom_logger = QComboBox()
        self._custom_logger.addItem("Selected logger", "selected")
        self._custom_logger.addItem("No logger argument", "none")
        self._extra_args = QPlainTextEdit()
        self._extra_args.setPlaceholderText('{"iterations": 3, "step": 10}')
        self._extra_args.setPlainText(json.dumps(item.get("args", {}), indent=2))
        if opt_type == "custom_path" or ":" in str(item.get("type", "")):
            form.addRow("Import path", self._custom_path)
        else:
            form.addRow("Class", QLabel(opt_type))
        form.addRow("Servos", self._custom_servos)
        form.addRow("Logger", self._custom_logger)
        form.addRow("Arguments (JSON)", self._extra_args)
        self._body.addLayout(form)

    def _restore_defaults(self) -> None:
        opt_type = str(self._type.currentData())
        self._editing = {
            "type": opt_type,
            "name": "",
            "args": deepcopy(OPTIMIZER_TYPES.get(opt_type, {}).get("defaults", {})),
        }
        self._name.clear()
        self._rebuild_body()

    def _accept_checked(self) -> None:
        try:
            self.result_item()
        except Exception as exc:
            QMessageBox.warning(self, "Check optimization", str(exc))
            return
        self.accept()

    def _read_args(self) -> dict[str, Any]:
        args: dict[str, Any] = {}
        for key, widget in self._arg_widgets.items():
            if isinstance(widget, QCheckBox):
                args[key] = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                args[key] = widget.value()
        if (
            "direction_update_interval" in args
            and int(args["direction_update_interval"]) == 0
        ):
            args["direction_update_interval"] = None
        return args

    def result_item(self) -> dict[str, Any]:
        opt_type = str(self._type.currentData())
        item: dict[str, Any] = {
            "type": opt_type,
            "name": self._name.text().strip() or str(self._type.currentText()),
            "args": self._read_args(),
        }
        if opt_type == "manual":
            selected = [
                int(cb.property("servo_id"))
                for cb in self._servo_checks
                if cb.isChecked()
            ]
            if not selected:
                raise ValueError("Choose at least one servo.")
            item["servo_ids"] = selected
        elif opt_type == "two_knob":
            pairs = [
                list(cb.property("pair")) for cb in self._pair_checks if cb.isChecked()
            ]
            if not pairs:
                raise ValueError("Choose at least one pair.")
            item["pairs"] = pairs
        else:
            if opt_type == "custom_path":
                path = self._custom_path.text().strip()
                if not path:
                    raise ValueError("Enter an optimizer import path.")
                item["type"] = path
            item["args"] = _parse_extra_args(self._extra_args.toPlainText())
        return item


class ReadPositionsDialog(QDialog):
    """Read-only viewer that shows the most recent positions for each servo."""

    def __init__(
        self, servo_ids: list[int], names: dict[str, str], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Servo Positions")
        self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._list = QListWidget()
        layout.addWidget(self._list, 1)
        for sid in servo_ids:
            nick = names.get(str(sid), "")
            label = f"ID {sid} ({nick})" if nick else f"ID {sid}"
            item = QListWidgetItem(f"{label}: …")
            item.setData(Qt.ItemDataRole.UserRole, int(sid))
            self._list.addItem(item)
        self._status = QLabel("Reading…")
        layout.addWidget(self._status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def set_positions(self, positions: list[int]) -> None:
        for row, pos in enumerate(positions):
            if row >= self._list.count():
                break
            item = self._list.item(row)
            sid = int(item.data(Qt.ItemDataRole.UserRole))
            base = item.text().split(":")[0]
            item.setText(f"{base}: {int(pos)}")
            _ = sid
        self._status.setText(f"Read {len(positions)} servo(s).")

    def set_status(self, text: str) -> None:
        self._status.setText(text)


class SetPositionDialog(QDialog):
    """Set goal positions for the configured servos, with a saved-record book."""

    def __init__(self, config: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set Positions")
        self.setMinimumWidth(420)
        self._config = config
        sc = config["scservo"]
        sc.setdefault("position_records", [])
        self._records: list[dict[str, Any]] = sc["position_records"]
        self._servo_ids: list[int] = [int(s) for s in sc.get("servo_ids", [])]
        self._names: dict[str, str] = dict(sc.get("servo_names", {}))
        self._busy = False
        self._thread: QThread | None = None
        self._worker: _ServoActionWorker | None = None
        self._save_callback: Callable[[], None] | None = None
        self._build_ui()

    def set_save_callback(self, fn: Callable[[], None]) -> None:
        self._save_callback = fn

    def refresh_records(self) -> None:
        self._record_list.clear()
        for rec in self._records:
            item = QListWidgetItem(str(rec.get("name", "")))
            self._record_list.addItem(item)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        if not self._servo_ids:
            layout.addWidget(QLabel("No servos configured."))
            close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            close.rejected.connect(self.reject)
            layout.addWidget(close)
            return

        set_box = QGroupBox("Goal positions")
        set_form = QFormLayout(set_box)
        set_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._spins: dict[int, QSpinBox] = {}
        for sid in self._servo_ids:
            sp = QSpinBox()
            sp.setRange(-1_000_000, 1_000_000)
            sp.setValue(0)
            nick = self._names.get(str(sid), "")
            label = f"ID {sid} ({nick})" if nick else f"ID {sid}"
            set_form.addRow(label, sp)
            self._spins[sid] = sp
        layout.addWidget(set_box)

        action_row = QHBoxLayout()
        self._read_btn = QPushButton("Read current")
        self._read_btn.clicked.connect(self._do_read)
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.clicked.connect(self._do_apply)
        self._record_btn = QPushButton("Save as record")
        self._record_btn.clicked.connect(self._save_record)
        action_row.addWidget(self._read_btn)
        action_row.addWidget(self._apply_btn)
        action_row.addWidget(self._record_btn)
        layout.addLayout(action_row)

        rec_box = QGroupBox("Records")
        rec_layout = QVBoxLayout(rec_box)
        self._record_list = QListWidget()
        self._record_list.setMinimumHeight(140)
        self._record_list.itemDoubleClicked.connect(
            lambda _item: self._load_selected_record()
        )
        rec_layout.addWidget(self._record_list)
        rec_row = QHBoxLayout()
        load_btn = QPushButton("Load to form")
        load_btn.clicked.connect(self._load_selected_record)
        apply_rec_btn = QPushButton("Apply record")
        apply_rec_btn.clicked.connect(self._apply_selected_record)
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._delete_selected_record)
        rec_row.addWidget(load_btn)
        rec_row.addWidget(apply_rec_btn)
        rec_row.addWidget(del_btn)
        rec_layout.addLayout(rec_row)
        layout.addWidget(rec_box, 1)

        self._status = QLabel("")
        layout.addWidget(self._status)

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        close.accepted.connect(self.accept)
        layout.addWidget(close)

        self._action_buttons = [
            self._read_btn,
            self._apply_btn,
            self._record_btn,
            load_btn,
            apply_rec_btn,
            del_btn,
        ]
        self.refresh_records()

    def _set_busy(self, busy: bool, msg: str = "") -> None:
        self._busy = busy
        self._status.setText(msg)
        for btn in self._action_buttons:
            btn.setEnabled(not busy)

    def _start_worker(
        self,
        fn: Callable[[_ServoActionWorker, Any], Any],
        on_completed: Callable[[object], None],
        busy_message: str,
    ) -> None:
        if self._busy:
            return
        self._set_busy(True, busy_message)
        self._thread = QThread()
        self._worker = _ServoActionWorker(self._config, fn)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.completed.connect(on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.completed.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _cleanup_thread(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        self._set_busy(False, self._status.text())

    def _do_read(self) -> None:
        def fn(_worker: _ServoActionWorker, controller: Any) -> Any:
            return list(controller.read_positions())

        self._start_worker(fn, self._on_read_done, "Reading…")

    @pyqtSlot(object)
    def _on_read_done(self, positions: object) -> None:
        positions = list(positions)  # type: ignore[arg-type]
        for sid, pos in zip(self._servo_ids, positions):
            if sid in self._spins:
                self._spins[sid].setValue(int(pos))
        self._status.setText(f"Read {len(positions)} position(s).")

    def _do_apply(self) -> None:
        target = [int(self._spins[sid].value()) for sid in self._servo_ids]

        def fn(_worker: _ServoActionWorker, controller: Any) -> Any:
            controller.set_positions(target)
            return None

        self._start_worker(fn, self._on_apply_done, "Applying…")

    @pyqtSlot(object)
    def _on_apply_done(self, _result: object) -> None:
        self._status.setText("Applied.")

    @pyqtSlot(str)
    def _on_failed(self, message: str) -> None:
        self._status.setText(message)
        QMessageBox.warning(self, "Servo action failed", message)

    def _save_record(self) -> None:
        default_name = _timestamp_label("Record")
        text, ok = QInputDialog.getText(
            self, "Save record", "Record name:", text=default_name
        )
        if not ok:
            return
        name = text.strip() or default_name
        positions = {
            str(int(sid)): int(self._spins[sid].value()) for sid in self._servo_ids
        }
        self._records.append(
            {
                "name": name,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "positions": positions,
            }
        )
        self.refresh_records()
        if self._save_callback:
            self._save_callback()

    def _selected_record(self) -> dict[str, Any] | None:
        row = self._record_list.currentRow()
        if row < 0 or row >= len(self._records):
            return None
        return self._records[row]

    def _load_selected_record(self) -> None:
        rec = self._selected_record()
        if not rec:
            return
        positions = rec.get("positions", {})
        for sid in self._servo_ids:
            val = positions.get(str(sid))
            if val is not None:
                self._spins[sid].setValue(int(val))
        self._status.setText(f"Loaded '{rec.get('name', '')}'.")

    def _apply_selected_record(self) -> None:
        rec = self._selected_record()
        if not rec:
            return
        self._load_selected_record()
        self._do_apply()

    def _delete_selected_record(self) -> None:
        row = self._record_list.currentRow()
        if row < 0 or row >= len(self._records):
            return
        del self._records[row]
        self.refresh_records()
        if self._save_callback:
            self._save_callback()


class FicopMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Ficop")
        self.resize(1180, 760)
        self._config = _load_config()
        self._scan_thread: QThread | None = None
        self._scan_worker: _ScanWorker | None = None
        self._opt_thread: QThread | None = None
        self._opt_worker: _OptimizeWorker | None = None
        self._debug_thread: QThread | None = None
        self._debug_worker: _ServoActionWorker | None = None
        self._set_dialog: SetPositionDialog | None = None
        self._read_dialog: ReadPositionsDialog | None = None
        self._connected_preview = False
        self._optimization_running = False

        self._build_toolbar()
        self._build_ui()
        self._refresh_ports()
        self._refresh_logger_devices()
        self._refresh_all_lists()
        self._sync_logger_constraints()
        self._apply_merit_unit(_resolve_merit_unit(self._config))
        self._apply_plot_theme()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        action_settings = QAction("Settings", self)
        action_settings.triggered.connect(self._open_settings)
        action_defaults = QAction("Restore Defaults", self)
        action_defaults.triggered.connect(self._restore_all_defaults)
        toolbar.addAction(action_settings)
        toolbar.addAction(action_defaults)
        toolbar.addSeparator()
        self._add_appearance_actions(toolbar)

    def _add_appearance_actions(self, toolbar: QToolBar) -> None:
        app = QApplication.instance()
        assert app is not None
        group = QActionGroup(self)
        group.setExclusionPolicy(QActionGroup.ExclusionPolicy.Exclusive)

        def set_mode(mode: str) -> None:
            _set_fusion_app_palette(app, mode)
            if hasattr(self, "_plot_widget"):
                self._apply_plot_theme()

        for label, mode in (
            ("Light", "light"),
            ("Dark", "dark"),
            ("Follow system", "system"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, m=mode: set_mode(m))
            group.addAction(action)
            toolbar.addAction(action)
            if mode == "system":
                action.setChecked(True)

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        columns = QHBoxLayout(inner)
        left = QVBoxLayout()
        right = QVBoxLayout()
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        left.addWidget(self._build_scservo_group())
        left.addWidget(self._build_logger_group())
        left.addStretch(1)
        right.addWidget(self._build_optimizer_group())
        right.addWidget(self._build_run_group())
        right.addWidget(self._build_log_group(), 1)
        scroll.setWidget(inner)
        root_layout.addWidget(scroll)
        self.setCentralWidget(root)

    def _build_scservo_group(self) -> QGroupBox:
        group = QGroupBox("SCServo")
        layout = QVBoxLayout(group)
        port_row = QHBoxLayout()
        self._port_combo = QComboBox()
        self._port_combo.currentIndexChanged.connect(self._on_port_changed)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_ports)
        port_row.addWidget(QLabel("Port"))
        port_row.addWidget(self._port_combo, 1)
        port_row.addWidget(refresh)
        layout.addLayout(port_row)

        scan_row = QHBoxLayout()
        self._scan_button = QPushButton("Search IDs")
        self._scan_button.clicked.connect(self._start_scan)
        self._scan_status = QLabel("")
        scan_row.addWidget(self._scan_button)
        scan_row.addWidget(self._scan_status, 1)
        layout.addLayout(scan_row)

        layout.addWidget(QLabel("Servos"))
        self._servo_list = QListWidget()
        self._servo_list.setMinimumHeight(120)
        layout.addWidget(self._servo_list)
        servo_buttons = QHBoxLayout()
        add_servo = QPushButton("Add")
        rename_servo = QPushButton("Rename")
        remove_servo = QPushButton("Remove")
        add_servo.clicked.connect(self._add_servo)
        rename_servo.clicked.connect(self._rename_selected_servo)
        remove_servo.clicked.connect(self._remove_selected_servo)
        for btn in (add_servo, rename_servo, remove_servo):
            servo_buttons.addWidget(btn)
        layout.addLayout(servo_buttons)

        debug_row = QHBoxLayout()
        self._shiver_btn = QPushButton("Shiver")
        self._shiver_btn.setToolTip("Wiggle the selected servo to identify it.")
        self._shiver_btn.clicked.connect(self._shiver_selected_servo)
        self._read_pos_btn = QPushButton("Read positions")
        self._read_pos_btn.clicked.connect(self._read_positions)
        self._set_pos_btn = QPushButton("Set positions")
        self._set_pos_btn.clicked.connect(self._open_set_positions)
        for btn in (self._shiver_btn, self._read_pos_btn, self._set_pos_btn):
            debug_row.addWidget(btn)
        layout.addLayout(debug_row)

        layout.addWidget(QLabel("Pairs"))
        self._pair_list = QListWidget()
        self._pair_list.setMinimumHeight(100)
        layout.addWidget(self._pair_list)
        pair_buttons = QHBoxLayout()
        add_pair = QPushButton("Add")
        rename_pair = QPushButton("Rename")
        remove_pair = QPushButton("Remove")
        add_pair.clicked.connect(self._add_pair)
        rename_pair.clicked.connect(self._rename_selected_pair)
        remove_pair.clicked.connect(self._remove_selected_pair)
        for btn in (add_pair, rename_pair, remove_pair):
            pair_buttons.addWidget(btn)
        layout.addLayout(pair_buttons)
        return group

    def _build_logger_group(self) -> QGroupBox:
        group = QGroupBox("Logger")
        layout = QFormLayout(group)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._logger_style = QComboBox()
        self._logger_style.addItem("Dummy", "dummy")
        self._logger_style.addItem("PicoLog PL1000", "picolog")
        self._logger_style.addItem("Oscilloscope", "oscilloscope")
        self._logger_style.currentIndexChanged.connect(self._on_logger_changed)
        self._logger_device = QComboBox()
        self._logger_device.setEditable(True)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_logger_devices)
        device_row = QHBoxLayout()
        device_row.addWidget(self._logger_device, 1)
        device_row.addWidget(refresh)
        device_widget = QWidget()
        device_widget.setLayout(device_row)
        self._logger_channel = QSpinBox()
        self._logger_channel.setRange(1, 16)
        self._logger_channel.valueChanged.connect(self._save_from_controls)
        self._logger_channel.valueChanged.connect(self._refresh_channel_label)
        self._channel_name_label = QLabel("")
        self._channel_name_label.setStyleSheet("color: gray;")
        name_btn = QPushButton("Name…")
        name_btn.clicked.connect(self._rename_current_channel)
        channel_row = QHBoxLayout()
        channel_row.addWidget(self._logger_channel)
        channel_row.addWidget(self._channel_name_label, 1)
        channel_row.addWidget(name_btn)
        channel_widget = QWidget()
        channel_widget.setLayout(channel_row)
        layout.addRow("Type", self._logger_style)
        layout.addRow("Device", device_widget)
        layout.addRow("Channel", channel_widget)
        return group

    def _refresh_channel_label(self) -> None:
        if not hasattr(self, "_channel_name_label"):
            return
        lc = self._config["logger"]
        style = str(lc.get("style", "dummy"))
        ch = int(self._logger_channel.value())
        names = lc.get("channel_names", {}).get(style, {}) or {}
        nick = str(names.get(str(ch), "")).strip()
        self._channel_name_label.setText(f"({nick})" if nick else "")

    def _rename_current_channel(self) -> None:
        lc = self._config["logger"]
        style = str(lc.get("style", "dummy"))
        ch = int(self._logger_channel.value())
        names_map = lc.setdefault(
            "channel_names", deepcopy(DEFAULT_CONFIG["logger"]["channel_names"])
        )
        per_style = names_map.setdefault(style, {})
        current = str(per_style.get(str(ch), ""))
        text, ok = QInputDialog.getText(
            self,
            "Channel name",
            f"Nickname for {style} channel {ch}:",
            text=current,
        )
        if not ok:
            return
        text = text.strip()
        if text:
            per_style[str(ch)] = text
        else:
            per_style.pop(str(ch), None)
        self._refresh_channel_label()
        _save_config(self._config)

    def _build_optimizer_group(self) -> QGroupBox:
        group = QGroupBox("Optimization")
        layout = QVBoxLayout(group)
        base = self._config["optimizer"]["base"]
        base_form = QFormLayout()
        base_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._min_pos = QSpinBox()
        self._min_pos.setRange(-1_000_000, 1_000_000)
        self._min_pos.setValue(int(base.get("min_position", -15000)))
        self._max_pos = QSpinBox()
        self._max_pos.setRange(-1_000_000, 1_000_000)
        self._max_pos.setValue(int(base.get("max_position", 15000)))
        self._wait_value = QDoubleSpinBox()
        self._wait_value.setRange(0.0, 60.0)
        self._wait_value.setSingleStep(0.05)
        self._wait_value.setValue(float(base.get("wait_for_value", 0.1)))
        threshold_value = float(base.get("value_threshold", -1.0e100))
        self._value_threshold_enabled = QCheckBox("Stop if merit below")
        self._value_threshold_enabled.setChecked(threshold_value > -1.0e99)
        self._value_threshold = QDoubleSpinBox()
        self._value_threshold.setDecimals(6)
        self._value_threshold.setRange(-1.0e9, 1.0e9)
        self._value_threshold.setSingleStep(0.01)
        self._value_threshold.setValue(
            threshold_value if threshold_value > -1.0e99 else 0.0
        )
        self._value_threshold.setEnabled(self._value_threshold_enabled.isChecked())
        threshold_row = QHBoxLayout()
        threshold_row.addWidget(self._value_threshold_enabled)
        threshold_row.addWidget(self._value_threshold, 1)
        threshold_widget = QWidget()
        threshold_widget.setLayout(threshold_row)
        self._value_threshold_enabled.toggled.connect(self._value_threshold.setEnabled)
        self._value_threshold_enabled.toggled.connect(self._save_from_controls)
        self._verbose = QCheckBox("Verbose log")
        self._verbose.setChecked(bool(base.get("verbose", True)))
        for widget in (
            self._min_pos,
            self._max_pos,
            self._wait_value,
            self._value_threshold,
        ):
            widget.valueChanged.connect(self._save_from_controls)
        self._verbose.stateChanged.connect(self._save_from_controls)
        base_form.addRow("Min position", self._min_pos)
        base_form.addRow("Max position", self._max_pos)
        base_form.addRow("Read delay (s)", self._wait_value)
        base_form.addRow("Threshold", threshold_widget)
        base_form.addRow("", self._verbose)
        layout.addLayout(base_form)

        layout.addWidget(QLabel("Steps"))
        self._opt_list = QListWidget()
        self._opt_list.setMinimumHeight(220)
        layout.addWidget(self._opt_list, 1)
        row = QHBoxLayout()
        add = QPushButton("Add")
        edit = QPushButton("Edit")
        remove = QPushButton("Remove")
        up = QPushButton("↑")
        down = QPushButton("↓")
        save = QPushButton("Save")
        load = QPushButton("Load")
        add.clicked.connect(self._add_optimization)
        edit.clicked.connect(self._edit_optimization)
        remove.clicked.connect(self._remove_optimization)
        up.clicked.connect(lambda: self._move_optimization(-1))
        down.clicked.connect(lambda: self._move_optimization(1))
        save.clicked.connect(self._save_preset)
        load.clicked.connect(self._load_preset)
        for btn in (add, edit, remove, up, down, save, load):
            row.addWidget(btn)
        layout.addLayout(row)
        return group

    def _build_run_group(self) -> QGroupBox:
        group = QGroupBox("Run")
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        self._connect_button = QPushButton("Check")
        self._connect_button.clicked.connect(self._check_setup)
        self._run_button = QPushButton("Run")
        self._run_button.clicked.connect(self._on_run_button)
        row.addWidget(self._connect_button)
        row.addWidget(self._run_button)
        layout.addLayout(row)
        base = self._config["optimizer"]["base"]
        self._restore_on_stop = QCheckBox("Restore start position on stop")
        self._restore_on_stop.setChecked(bool(base.get("restore_on_stop", True)))
        self._restore_on_stop.stateChanged.connect(self._save_from_controls)
        layout.addWidget(self._restore_on_stop)
        self._run_status = QLabel("")
        self._last_result = QLabel("")
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._run_status)
        layout.addWidget(self._last_result)
        layout.addWidget(self._progress)
        return group

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("Progress")
        layout = QVBoxLayout(group)
        tabs = QTabWidget()
        plot_tab = QWidget()
        plot_layout = QVBoxLayout(plot_tab)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        pg.setConfigOptions(antialias=True)
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.showGrid(x=True, y=True, alpha=0.25)
        self._plot_widget.setLabel("bottom", "Iteration")
        self._plot_widget.setLabel("left", "Merit")
        self._plot_widget.getAxis("left").enableAutoSIPrefix(False)
        self._plot_widget.getAxis("bottom").enableAutoSIPrefix(False)
        self._merit_unit = ""
        self._legend = self._plot_widget.addLegend(offset=(10, 10))
        self._curve_sample = self._plot_widget.plot(
            [],
            [],
            pen=pg.mkPen(color=(120, 180, 255), width=1),
            symbol="o",
            symbolSize=4,
            symbolBrush=(120, 180, 255, 150),
            symbolPen=None,
            name="value",
        )
        self._curve_best = self._plot_widget.plot(
            [],
            [],
            pen=pg.mkPen(color=(255, 170, 80), width=2),
            name="best",
        )
        self._plot_best_label = pg.TextItem(anchor=(1, 0))
        self._plot_widget.addItem(self._plot_best_label)
        self._plot_xs: list[int] = []
        self._plot_ys: list[float] = []
        self._plot_best: list[float] = []
        plot_layout.addWidget(self._plot_widget)
        self._best_label = QLabel("Best: —    Last: —    Samples: 0")
        plot_layout.addWidget(self._best_label)
        tabs.addTab(plot_tab, "Plot")
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_layout.setContentsMargins(0, 0, 0, 0)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        log_layout.addWidget(self._log)
        tabs.addTab(log_tab, "Log")
        layout.addWidget(tabs)
        return group

    def _reset_progress_plot(self) -> None:
        self._plot_xs = []
        self._plot_ys = []
        self._plot_best = []
        self._curve_sample.setData([], [])
        self._curve_best.setData([], [])
        self._plot_best_label.setText("")
        self._best_label.setText("Best: —    Last: —    Samples: 0")
        for region in list(getattr(self, "_stage_regions", [])):
            self._plot_widget.removeItem(region)
        self._stage_regions: list[Any] = []

    def _palette_is_dark(self) -> bool:
        app = QApplication.instance()
        palette = app.palette() if app is not None else self.palette()
        return palette.color(QPalette.ColorRole.Window).lightness() < 128

    def _plot_theme(self) -> dict[str, Any]:
        app = QApplication.instance()
        palette = app.palette() if app is not None else self.palette()
        bg = palette.color(QPalette.ColorRole.Base)
        if self._palette_is_dark():
            return {
                "bg": bg,
                "fg": QColor(220, 220, 220),
                "muted": QColor(140, 140, 140),
                "grid_alpha": 0.25,
                "legend_brush": pg.mkBrush(0, 0, 0, 90),
                "sample": (120, 180, 255),
                "best": (255, 170, 80),
            }
        return {
            "bg": bg,
            "fg": QColor(30, 30, 30),
            "muted": QColor(110, 110, 110),
            "grid_alpha": 0.35,
            "legend_brush": pg.mkBrush(255, 255, 255, 200),
            "sample": (30, 110, 200),
            "best": (210, 110, 30),
        }

    def _apply_plot_theme(self) -> None:
        if not hasattr(self, "_plot_widget"):
            return
        theme = self._plot_theme()
        self._plot_widget.setBackground(theme["bg"])
        fg_pen = pg.mkPen(color=theme["fg"])
        for side in ("left", "bottom"):
            axis = self._plot_widget.getAxis(side)
            axis.setPen(fg_pen)
            axis.setTextPen(fg_pen)
        self._plot_widget.showGrid(x=True, y=True, alpha=theme["grid_alpha"])
        if hasattr(self, "_legend") and self._legend is not None:
            self._legend.setBrush(theme["legend_brush"])
            self._legend.setLabelTextColor(theme["fg"])
        self._curve_sample.setPen(pg.mkPen(color=theme["sample"], width=1))
        self._curve_sample.setSymbolBrush((*theme["sample"], 150))
        self._curve_best.setPen(pg.mkPen(color=theme["best"], width=2))
        self._plot_best_label.setColor(theme["fg"])
        for line in getattr(self, "_stage_regions", []):
            line.setPen(
                pg.mkPen(color=theme["muted"], style=Qt.PenStyle.DashLine)
            )

    def _unit_suffix(self) -> str:
        return f" {self._merit_unit}" if self._merit_unit else ""

    def _format_merit(self, value: float) -> str:
        if not math.isfinite(value):
            return "—"
        return f"{value:.6g}{self._unit_suffix()}"

    @pyqtSlot(str)
    def _apply_merit_unit(self, unit: str) -> None:
        self._merit_unit = (unit or "").strip()
        self._plot_widget.setLabel(
            "left", "Merit", units=self._merit_unit or None
        )
        self._value_threshold.setSuffix(self._unit_suffix())

    @pyqtSlot(int, float, float)
    def _on_sample(self, index: int, value: float, best: float) -> None:
        self._plot_xs.append(int(index))
        self._plot_ys.append(float(value))
        self._plot_best.append(float(best))
        self._curve_sample.setData(self._plot_xs, self._plot_ys)
        self._curve_best.setData(self._plot_xs, self._plot_best)
        best_text = self._format_merit(best)
        last_text = self._format_merit(value)
        self._best_label.setText(
            f"Best: {best_text}    Last: {last_text}    Samples: {index}"
        )
        self._plot_best_label.setText(f"best = {best_text}")
        self._plot_best_label.setPos(index, best)

    @pyqtSlot(int, str)
    def _on_stage(self, stage_index: int, name: str) -> None:
        x = self._plot_xs[-1] if self._plot_xs else float(stage_index * 0)
        line = pg.InfiniteLine(
            pos=x,
            angle=90,
            pen=pg.mkPen(color=(150, 150, 150), style=Qt.PenStyle.DashLine),
            label=name,
            labelOpts={"position": 0.95, "color": (170, 170, 170)},
        )
        self._plot_widget.addItem(line)
        if not hasattr(self, "_stage_regions"):
            self._stage_regions = []
        self._stage_regions.append(line)

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self._config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._config = dialog.config()
            self._save_and_refresh()

    def _restore_all_defaults(self) -> None:
        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setWindowTitle("Restore defaults")
        confirm.setText("Reset every setting to defaults?")
        confirm.setInformativeText(
            "This will wipe servo IDs, nicknames, pairs, baudrate, logger and "
            "optimizer settings, and all optimization steps. Save them as a "
            "preset first if you want them back. Position records are kept."
        )
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        confirm.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return
        preserved_records = deepcopy(
            self._config.get("scservo", {}).get("position_records", [])
        )
        self._config = deepcopy(DEFAULT_CONFIG)
        self._config["scservo"]["position_records"] = preserved_records
        self._save_and_refresh()

    def _refresh_ports(self) -> None:
        current = self._config["scservo"].get("port", DUMMY_PORT)
        self._port_combo.blockSignals(True)
        self._port_combo.clear()
        self._port_combo.addItem(DUMMY_PORT, DUMMY_PORT)
        for port in get_available_serial_ports():
            self._port_combo.addItem(_port_label(port), port["device"])
        idx = self._port_combo.findData(current)
        self._port_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._port_combo.blockSignals(False)

    def _refresh_logger_devices(self) -> None:
        lc = self._config["logger"]
        style = str(lc.get("style", "dummy"))
        devices_cfg = lc.setdefault(
            "devices", deepcopy(DEFAULT_CONFIG["logger"]["devices"])
        )
        current = str(devices_cfg.get(style, "") or "")
        self._logger_device.blockSignals(True)
        self._logger_device.clear()
        if style == "dummy":
            self._logger_device.addItem(DUMMY_PORT, DUMMY_PORT)
            current = DUMMY_PORT
        elif style == "picolog":
            self._logger_device.addItem("PL1000", "pl1000")
            current = "pl1000"
        else:
            devices = _list_visa_devices()
            for dev in devices:
                self._logger_device.addItem(dev, dev)
            if current and current not in devices:
                self._logger_device.addItem(current, current)
            if not current and devices:
                current = devices[0]
        idx = self._logger_device.findData(current)
        self._logger_device.setCurrentIndex(idx if idx >= 0 else 0)
        devices_cfg[style] = current
        self._logger_device.blockSignals(False)
        self._refresh_channel_label()

    def _refresh_all_lists(self) -> None:
        self._refresh_servo_list()
        self._refresh_pair_list()
        self._refresh_optimizer_list()
        self._load_controls_from_config()

    def _load_controls_from_config(self) -> None:
        logger = self._config["logger"]
        idx = self._logger_style.findData(logger.get("style", "dummy"))
        self._logger_style.blockSignals(True)
        self._logger_style.setCurrentIndex(max(idx, 0))
        self._logger_style.blockSignals(False)
        self._logger_channel.blockSignals(True)
        self._logger_channel.setValue(int(logger.get("channel", 1)))
        self._logger_channel.blockSignals(False)
        base = self._config["optimizer"]["base"]
        self._min_pos.blockSignals(True)
        self._max_pos.blockSignals(True)
        self._wait_value.blockSignals(True)
        self._verbose.blockSignals(True)
        self._min_pos.setValue(int(base.get("min_position", -15000)))
        self._max_pos.setValue(int(base.get("max_position", 15000)))
        self._wait_value.setValue(float(base.get("wait_for_value", 0.1)))
        self._verbose.setChecked(bool(base.get("verbose", True)))
        self._min_pos.blockSignals(False)
        self._max_pos.blockSignals(False)
        self._wait_value.blockSignals(False)
        self._verbose.blockSignals(False)

    def _refresh_servo_list(self) -> None:
        self._servo_list.clear()
        for sid in self._config["scservo"].get("servo_ids", []):
            item = QListWidgetItem(self._servo_label(int(sid)))
            item.setData(Qt.ItemDataRole.UserRole, int(sid))
            self._servo_list.addItem(item)

    def _refresh_pair_list(self) -> None:
        self._pair_list.clear()
        for pair in self._config["scservo"].get("pairs", []):
            a, b = int(pair["a"]), int(pair["b"])
            name = str(pair.get("name", "")).strip()
            label = f"{self._servo_label(a)} + {self._servo_label(b)}"
            if name:
                label += f" ({name})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, pair)
            self._pair_list.addItem(item)

    def _refresh_optimizer_list(self) -> None:
        self._opt_list.clear()
        for idx, item in enumerate(self._config["optimizer"].get("items", []), start=1):
            label = self._optimizer_label(idx, item)
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self._opt_list.addItem(list_item)

    def _servo_short_label(self, sid: int) -> str:
        """Compact servo label for the optimizer list: nickname if set, else 'ID N'."""
        names = self._config["scservo"].get("servo_names", {})
        name = str(names.get(str(sid), "")).strip()
        return name if name else f"ID {sid}"

    def _optimizer_label(self, idx: int, item: dict[str, Any]) -> str:
        name = str(item.get("name") or item.get("type"))
        opt_type = str(item.get("type"))
        if opt_type == "manual":
            servos = ", ".join(
                self._servo_short_label(int(sid)) for sid in item.get("servo_ids", [])
            )
            detail = f"servos: {servos}"
        elif opt_type == "two_knob":
            pair_names: dict[tuple[int, int], str] = {}
            for sp in self._config["scservo"].get("pairs", []):
                try:
                    a, b = int(sp["a"]), int(sp["b"])
                except (KeyError, TypeError, ValueError):
                    continue
                nick = str(sp.get("name", "")).strip()
                if nick:
                    pair_names[(a, b)] = nick
                    pair_names[(b, a)] = nick
            labels: list[str] = []
            for raw in item.get("pairs", []):
                try:
                    a, b = int(raw[0]), int(raw[1])
                except (TypeError, ValueError, IndexError):
                    continue
                nick = pair_names.get((a, b))
                if nick:
                    labels.append(nick)
                else:
                    labels.append(
                        f"{self._servo_short_label(a)} + {self._servo_short_label(b)}"
                    )
            detail = "pairs: " + (", ".join(labels) if labels else "—")
        else:
            detail = "custom arguments"
        return f"{idx}. {name} - {detail}"

    def _servo_label(self, sid: int) -> str:
        names = self._config["scservo"].get("servo_names", {})
        name = str(names.get(str(sid), "")).strip()
        return f"ID {sid} ({name})" if name else f"ID {sid}"

    def _on_port_changed(self) -> None:
        self._config["scservo"]["port"] = self._port_combo.currentData()
        self._sync_logger_constraints()
        self._save_and_refresh()

    def _on_logger_changed(self) -> None:
        self._config["logger"]["style"] = self._logger_style.currentData()
        self._refresh_logger_devices()
        self._sync_logger_constraints()
        self._save_from_controls()

    def _sync_logger_constraints(self) -> None:
        is_dummy_controller = self._config["scservo"].get("port") == DUMMY_PORT
        dummy_idx = self._logger_style.findData("dummy")
        item = self._logger_style.model().item(dummy_idx)
        if item is not None:
            item.setEnabled(is_dummy_controller)
        if not is_dummy_controller and self._config["logger"].get("style") == "dummy":
            self._config["logger"]["style"] = "oscilloscope"
            idx = self._logger_style.findData("oscilloscope")
            self._logger_style.setCurrentIndex(max(idx, 0))

    def _save_from_controls(self) -> None:
        if not hasattr(self, "_logger_style"):
            return
        lc = self._config["logger"]
        lc["style"] = self._logger_style.currentData()
        devices_cfg = lc.setdefault(
            "devices", deepcopy(DEFAULT_CONFIG["logger"]["devices"])
        )
        devices_cfg[str(lc["style"])] = (
            self._logger_device.currentData() or self._logger_device.currentText()
        )
        lc["channel"] = int(self._logger_channel.value())
        base = self._config["optimizer"]["base"]
        base["min_position"] = int(self._min_pos.value())
        base["max_position"] = int(self._max_pos.value())
        base["wait_for_value"] = float(self._wait_value.value())
        base["verbose"] = self._verbose.isChecked()
        if hasattr(self, "_value_threshold_enabled"):
            if self._value_threshold_enabled.isChecked():
                base["value_threshold"] = float(self._value_threshold.value())
            else:
                base["value_threshold"] = -1.0e100
        if hasattr(self, "_restore_on_stop"):
            base["restore_on_stop"] = bool(self._restore_on_stop.isChecked())
        _save_config(self._config)
        if hasattr(self, "_plot_widget"):
            self._apply_merit_unit(_resolve_merit_unit(self._config))

    def _save_and_refresh(self) -> None:
        _save_config(self._config)
        self._refresh_ports()
        self._refresh_logger_devices()
        self._refresh_all_lists()
        if hasattr(self, "_plot_widget"):
            self._apply_merit_unit(_resolve_merit_unit(self._config))

    def _start_scan(self) -> None:
        self._save_from_controls()
        if self._scan_thread is not None:
            return
        sc = self._config["scservo"]
        self._scan_button.setEnabled(False)
        self._scan_status.setText("Scanning...")
        self._scan_thread = QThread()
        dummy_ids = [int(sid) for sid in sc.get("dummy_servo_ids", []) or []]
        if not dummy_ids:
            dummy_ids = list(DEFAULT_CONFIG["scservo"]["dummy_servo_ids"])
        self._scan_worker = _ScanWorker(
            str(sc.get("port", DUMMY_PORT)),
            int(sc.get("baudrate", 1_000_000)),
            int(sc.get("protocol_end", 0)),
            int(sc.get("scan_min", 1)),
            int(sc.get("scan_max", 252)),
            dummy_ids,
        )
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.progress.connect(self._scan_status.setText)
        self._scan_worker.completed.connect(self._on_scan_completed)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.completed.connect(self._scan_thread.quit)
        self._scan_worker.failed.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._cleanup_scan)
        self._scan_thread.start()

    @pyqtSlot(list)
    def _on_scan_completed(self, found: list[dict[str, Any]]) -> None:
        ids = [int(row["id"]) for row in found]
        if not ids:
            self._scan_status.setText("No servos found.")
            return
        names = self._config["scservo"].setdefault("servo_names", {})
        for sid in ids:
            names.setdefault(str(sid), "")
        self._config["scservo"]["servo_ids"] = ids
        self._config["scservo"]["pairs"] = [
            p
            for p in self._config["scservo"].get("pairs", [])
            if int(p["a"]) in ids and int(p["b"]) in ids
        ]
        self._scan_status.setText(f"Found {len(ids)} servo(s).")
        self._save_and_refresh()

    @pyqtSlot(str)
    def _on_scan_failed(self, message: str) -> None:
        self._scan_status.setText("Scan failed.")
        QMessageBox.warning(self, "Servo search failed", message)

    @pyqtSlot()
    def _cleanup_scan(self) -> None:
        self._scan_button.setEnabled(True)
        if self._scan_worker is not None:
            self._scan_worker.deleteLater()
            self._scan_worker = None
        if self._scan_thread is not None:
            self._scan_thread.deleteLater()
            self._scan_thread = None

    def _selected_servo_id(self) -> int | None:
        item = self._servo_list.currentItem()
        return None if item is None else int(item.data(Qt.ItemDataRole.UserRole))

    def _add_servo(self) -> None:
        sid, ok = QInputDialog.getInt(self, "Add Servo", "Servo ID:", 1, 1, 252)
        if not ok:
            return
        ids = [int(x) for x in self._config["scservo"].get("servo_ids", [])]
        if sid not in ids:
            ids.append(sid)
            self._config["scservo"]["servo_ids"] = ids
            self._config["scservo"].setdefault("servo_names", {}).setdefault(
                str(sid), ""
            )
            self._save_and_refresh()

    def _rename_selected_servo(self) -> None:
        sid = self._selected_servo_id()
        if sid is None:
            return
        names = self._config["scservo"].setdefault("servo_names", {})
        text, ok = QInputDialog.getText(
            self,
            "Servo Name",
            f"Nickname for servo ID {sid}:",
            text=str(names.get(str(sid), "")),
        )
        if ok:
            names[str(sid)] = text.strip()
            self._save_and_refresh()

    def _remove_selected_servo(self) -> None:
        sid = self._selected_servo_id()
        if sid is None:
            return
        self._config["scservo"]["servo_ids"] = [
            x for x in self._config["scservo"].get("servo_ids", []) if int(x) != sid
        ]
        self._config["scservo"]["pairs"] = [
            p
            for p in self._config["scservo"].get("pairs", [])
            if int(p["a"]) != sid and int(p["b"]) != sid
        ]
        self._save_and_refresh()

    def _add_pair(self) -> None:
        ids = [int(x) for x in self._config["scservo"].get("servo_ids", [])]
        if len(ids) < 2:
            QMessageBox.warning(self, "Add pair", "Add at least two servo IDs first.")
            return
        labels = [self._servo_label(sid) for sid in ids]
        first, ok = QInputDialog.getItem(
            self, "Pair first servo", "First servo:", labels, 0, False
        )
        if not ok:
            return
        second, ok = QInputDialog.getItem(
            self,
            "Pair second servo",
            "Second servo:",
            labels,
            0,
            False,
        )
        if not ok:
            return
        a, b = ids[labels.index(first)], ids[labels.index(second)]
        if a == b:
            QMessageBox.warning(self, "Add pair", "Choose two different servos.")
            return
        name, _ok = QInputDialog.getText(self, "Pair name", "Optional pair name:")
        self._config["scservo"].setdefault("pairs", []).append(
            {"a": a, "b": b, "name": name.strip()}
        )
        self._save_and_refresh()

    def _rename_selected_pair(self) -> None:
        row = self._pair_list.currentRow()
        if row < 0:
            return
        pair = self._config["scservo"]["pairs"][row]
        text, ok = QInputDialog.getText(
            self, "Pair Name", "Pair name:", text=str(pair.get("name", ""))
        )
        if ok:
            pair["name"] = text.strip()
            self._save_and_refresh()

    def _remove_selected_pair(self) -> None:
        row = self._pair_list.currentRow()
        if row < 0:
            return
        del self._config["scservo"]["pairs"][row]
        self._save_and_refresh()

    def _add_optimization(self) -> None:
        self._save_from_controls()
        dialog = OptimizerDialog(self._config, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._config["optimizer"].setdefault("items", []).append(
                dialog.result_item()
            )
            self._save_and_refresh()

    def _edit_optimization(self) -> None:
        row = self._opt_list.currentRow()
        if row < 0:
            return
        dialog = OptimizerDialog(
            self._config, self._config["optimizer"]["items"][row], self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._config["optimizer"]["items"][row] = dialog.result_item()
            self._save_and_refresh()

    def _remove_optimization(self) -> None:
        row = self._opt_list.currentRow()
        if row < 0:
            return
        del self._config["optimizer"]["items"][row]
        self._save_and_refresh()

    def _move_optimization(self, delta: int) -> None:
        row = self._opt_list.currentRow()
        items = self._config["optimizer"]["items"]
        new_row = row + delta
        if row < 0 or new_row < 0 or new_row >= len(items):
            return
        items[row], items[new_row] = items[new_row], items[row]
        self._save_and_refresh()
        self._opt_list.setCurrentRow(new_row)

    def _save_preset(self) -> None:
        self._save_from_controls()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Preset",
            str(Path.home() / f"ficop-preset{PRESET_SUFFIX}"),
            f"Ficop presets (*{PRESET_SUFFIX});;JSON files (*.json)",
        )
        if not path:
            return
        scservo = deepcopy(self._config.get("scservo", {}))
        scservo.pop("position_records", None)
        logger = deepcopy(self._config.get("logger", {}))
        data = {
            "scservo": scservo,
            "logger": logger,
            "optimizer": deepcopy(self._config["optimizer"]),
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_preset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Preset",
            str(Path.home()),
            f"Ficop presets (*{PRESET_SUFFIX});;JSON files (*.json)",
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Preset must be a JSON object.")
            optimizer = data.get("optimizer", data)
            if not isinstance(optimizer, dict):
                raise ValueError("Preset does not contain an optimizer object.")
            self._config["optimizer"] = _deep_update(
                DEFAULT_CONFIG["optimizer"], optimizer
            )
            scservo = data.get("scservo")
            if isinstance(scservo, dict):
                scservo = deepcopy(scservo)
                scservo.pop("position_records", None)
                self._config["scservo"] = _deep_update(
                    self._config.get("scservo", DEFAULT_CONFIG["scservo"]), scservo
                )
            logger = data.get("logger")
            if isinstance(logger, dict):
                self._config["logger"] = _deep_update(
                    self._config.get("logger", DEFAULT_CONFIG["logger"]),
                    deepcopy(logger),
                )
                _migrate_logger_devices(self._config)
        except Exception as exc:
            QMessageBox.warning(self, "Load preset failed", str(exc))
            return
        self._save_and_refresh()

    def _check_setup(self) -> None:
        self._save_from_controls()
        problems: list[str] = []
        if not self._config["scservo"].get("servo_ids"):
            problems.append("Add or search for at least one servo ID.")
        if (
            self._config["logger"].get("style") == "dummy"
            and self._config["scservo"].get("port") != DUMMY_PORT
        ):
            problems.append("Dummy logger requires the dummy controller.")
        if not self._config["optimizer"].get("items"):
            problems.append("Add at least one optimization step.")
        if problems:
            self._connected_preview = False
            QMessageBox.warning(self, "Setup", "\n".join(problems))
            self._run_status.setText("Setup invalid")
            return
        self._connected_preview = True
        self._run_status.setText("Ready")

    def _on_run_button(self) -> None:
        if self._optimization_running:
            self._stop_optimization()
        else:
            self._run_optimization()

    def _run_optimization(self) -> None:
        self._save_from_controls()
        self._check_setup()
        if not self._connected_preview or self._opt_thread is not None:
            return
        self._optimization_running = True
        self._run_button.setText("Stop")
        self._progress.setVisible(True)
        self._set_debug_buttons_enabled(False)
        self._log.clear()
        self._reset_progress_plot()
        self._opt_thread = QThread()
        self._opt_worker = _OptimizeWorker(self._config)
        self._opt_worker.moveToThread(self._opt_thread)
        self._opt_thread.started.connect(self._opt_worker.run)
        self._opt_worker.log_line.connect(self._append_log)
        self._opt_worker.recorded.connect(self._on_run_record)
        self._opt_worker.sample.connect(self._on_sample)
        self._opt_worker.stage.connect(self._on_stage)
        self._opt_worker.unit.connect(self._apply_merit_unit)
        self._opt_worker.completed.connect(self._on_optimization_completed)
        self._opt_worker.failed.connect(self._on_optimization_failed)
        self._opt_worker.completed.connect(self._opt_thread.quit)
        self._opt_worker.failed.connect(self._opt_thread.quit)
        self._opt_thread.finished.connect(self._cleanup_optimizer)
        self._opt_thread.start()
        self._run_status.setText("Running")

    def _stop_optimization(self) -> None:
        if self._opt_worker is None:
            return
        self._opt_worker.request_stop()
        self._run_button.setEnabled(False)
        self._run_status.setText("Stopping…")

    @pyqtSlot(dict)
    def _on_run_record(self, record: dict) -> None:
        records = self._config["scservo"].setdefault("position_records", [])
        records.append(record)
        _save_config(self._config)
        if self._set_dialog is not None:
            self._set_dialog.refresh_records()

    @pyqtSlot(float, float, bool)
    def _on_optimization_completed(
        self, seconds: float, merit: float, was_stopped: bool
    ) -> None:
        self._progress.setVisible(False)
        self._run_button.setEnabled(True)
        self._run_button.setText("Run")
        self._optimization_running = False
        self._set_debug_buttons_enabled(True)
        if was_stopped:
            self._last_result.setText(f"Stopped after {seconds:.2f} s")
            self._run_status.setText("Stopped")
            return
        self._last_result.setText(
            f"Merit {self._format_merit(merit)} in {seconds:.2f} s"
        )
        self._run_status.setText("Done")

    @pyqtSlot(str)
    def _on_optimization_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self._run_button.setEnabled(True)
        self._run_button.setText("Run")
        self._optimization_running = False
        self._set_debug_buttons_enabled(True)
        self._run_status.setText("Failed")
        self._append_log(message)
        QMessageBox.critical(self, "Optimization failed", message)

    @pyqtSlot()
    def _cleanup_optimizer(self) -> None:
        if self._opt_worker is not None:
            self._opt_worker.deleteLater()
            self._opt_worker = None
        if self._opt_thread is not None:
            self._opt_thread.deleteLater()
            self._opt_thread = None

    @pyqtSlot(str)
    def _append_log(self, message: str) -> None:
        self._log.append(message.rstrip())

    def _set_debug_buttons_enabled(self, enabled: bool) -> None:
        for attr in ("_shiver_btn", "_read_pos_btn", "_set_pos_btn"):
            btn = getattr(self, attr, None)
            if btn is not None:
                btn.setEnabled(enabled)

    def _start_debug_worker(
        self,
        fn: Callable[[_ServoActionWorker, Any], Any],
        on_completed: Callable[[object], None],
        busy_message: str,
    ) -> bool:
        if self._optimization_running:
            QMessageBox.warning(self, "Busy", "Stop optimization first.")
            return False
        if self._debug_thread is not None:
            QMessageBox.warning(self, "Busy", "Another servo action is running.")
            return False
        if not self._config["scservo"].get("servo_ids"):
            QMessageBox.warning(self, "No servos", "Add or scan a servo ID first.")
            return False
        self._save_from_controls()
        self._set_debug_buttons_enabled(False)
        self._append_log(busy_message)
        self._debug_thread = QThread()
        self._debug_worker = _ServoActionWorker(self._config, fn)
        self._debug_worker.moveToThread(self._debug_thread)
        self._debug_thread.started.connect(self._debug_worker.run)
        self._debug_worker.log_line.connect(self._append_log)
        self._debug_worker.completed.connect(on_completed)
        self._debug_worker.failed.connect(self._on_debug_failed)
        self._debug_worker.completed.connect(self._debug_thread.quit)
        self._debug_worker.failed.connect(self._debug_thread.quit)
        self._debug_thread.finished.connect(self._cleanup_debug)
        self._debug_thread.start()
        return True

    @pyqtSlot()
    def _cleanup_debug(self) -> None:
        if self._debug_worker is not None:
            self._debug_worker.deleteLater()
            self._debug_worker = None
        if self._debug_thread is not None:
            self._debug_thread.deleteLater()
            self._debug_thread = None
        if not self._optimization_running:
            self._set_debug_buttons_enabled(True)

    @pyqtSlot(str)
    def _on_debug_failed(self, message: str) -> None:
        self._append_log(message)
        QMessageBox.warning(self, "Servo action failed", message)

    def _shiver_selected_servo(self) -> None:
        sid = self._selected_servo_id()
        if sid is None:
            QMessageBox.information(
                self, "Shiver", "Select a servo from the list first."
            )
            return
        sc = self._config["scservo"]
        amplitude = int(sc.get("shiver_amplitude", 100))
        duration = float(sc.get("shiver_duration_s", 2.0))
        target_id = int(sid)

        def fn(worker: _ServoActionWorker, controller: Any) -> Any:
            ids = list(getattr(controller, "servo_ids", []))
            if target_id not in ids:
                raise ValueError(f"Servo {target_id} not connected.")
            idx = ids.index(target_id)
            current = list(controller.read_positions())
            origin = int(current[idx])
            half_period = 0.12
            deadline = time.time() + duration
            sign = 1
            while time.time() < deadline:
                if worker.stop_requested:
                    break
                target = current.copy()
                target[idx] = origin + sign * amplitude
                controller.set_positions(target)
                time.sleep(half_period)
                sign = -sign
            controller.set_positions(current[:idx] + [origin] + current[idx + 1 :])
            return target_id

        self._start_debug_worker(fn, self._on_shiver_done, f"Shivering ID {sid}…")

    @pyqtSlot(object)
    def _on_shiver_done(self, sid: object) -> None:
        self._append_log(f"Shiver finished (ID {sid}).")

    def _read_positions(self) -> None:
        sc = self._config["scservo"]
        servo_ids = [int(s) for s in sc.get("servo_ids", [])]
        names = dict(sc.get("servo_names", {}))
        dialog = ReadPositionsDialog(servo_ids, names, self)
        self._read_dialog = dialog

        def fn(_worker: _ServoActionWorker, controller: Any) -> Any:
            return list(controller.read_positions())

        def on_done(positions: object) -> None:
            try:
                dialog.set_positions(list(positions))  # type: ignore[arg-type]
            except RuntimeError:
                pass

        if not self._start_debug_worker(fn, on_done, "Reading positions…"):
            return
        dialog.exec()
        self._read_dialog = None

    def _open_set_positions(self) -> None:
        if self._optimization_running:
            QMessageBox.warning(self, "Busy", "Stop optimization first.")
            return
        if not self._config["scservo"].get("servo_ids"):
            QMessageBox.warning(self, "No servos", "Add or scan a servo ID first.")
            return
        dialog = SetPositionDialog(self._config, self)
        dialog.set_save_callback(lambda: _save_config(self._config))
        self._set_dialog = dialog
        try:
            dialog.exec()
        finally:
            self._set_dialog = None
        _save_config(self._config)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "_plot_widget"):
            self._apply_plot_theme()
        return super().changeEvent(event)

    def closeEvent(self, event) -> None:
        _save_config(self._config)
        for thread in (self._scan_thread, self._opt_thread, self._debug_thread):
            if thread is not None and thread.isRunning():
                thread.quit()
                thread.wait(2000)
        return super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Ficop")
    _set_fusion_app_palette(app, "system")
    window = FicopMainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
