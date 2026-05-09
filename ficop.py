"""
Ficop — fiber coupling optimizer UI (uses ``dummy.py`` for simulation; hardware path TBD).
Run from repo root:  python main/ficop.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

# Resolve imports when launched as a script
_MAIN_DIR = Path(__file__).resolve().parent
if str(_MAIN_DIR) not in sys.path:
    sys.path.insert(0, str(_MAIN_DIR))

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QGuiApplication, QPalette, QColor, QActionGroup
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

import dummy


def _pair_combo_row(
    parent: QWidget,
    form: QFormLayout,
    label: str,
    default_a: int,
    default_b: int,
) -> tuple[QComboBox, QComboBox]:
    a = QComboBox(parent)
    b = QComboBox(parent)
    for j, sid in enumerate(dummy.SERVO_IDS):
        a.addItem(f"Knob {j} (id {sid})", j)
        b.addItem(f"Knob {j} (id {sid})", j)
    a.setCurrentIndex(default_a)
    b.setCurrentIndex(default_b)
    row = QHBoxLayout()
    row.addWidget(QLabel("A:"))
    row.addWidget(a, 1)
    row.addWidget(QLabel("B:"))
    row.addWidget(b, 1)
    w = QWidget()
    w.setLayout(row)
    form.addRow(label, w)
    return a, b


# --- Theme (Fusion + palette) ---


def _set_fusion_app_palette(app: QApplication, mode: str) -> None:
    app.setStyle("Fusion")
    if mode == "system":
        st = QGuiApplication.styleHints()
        if hasattr(st, "colorScheme") and st.colorScheme() is not None:
            is_dark = st.colorScheme() == Qt.ColorScheme.Dark
        else:
            win = app.palette().color(QPalette.ColorRole.Window)
            is_dark = win.lightness() < 128
        _set_fusion_app_palette(app, "dark" if is_dark else "light")
        return
    p = QPalette()
    if mode == "dark":
        c_window = QColor(50, 52, 55)
        c_text = QColor(240, 240, 240)
        c_base = QColor(32, 33, 36)
        c_alternate = QColor(42, 44, 48)
        c_button = QColor(58, 60, 64)
        c_highlight = QColor(43, 110, 160)
        p.setColor(QPalette.ColorRole.Window, c_window)
        p.setColor(QPalette.ColorRole.WindowText, c_text)
        p.setColor(QPalette.ColorRole.Base, c_base)
        p.setColor(QPalette.ColorRole.AlternateBase, c_alternate)
        p.setColor(QPalette.ColorRole.Text, c_text)
        p.setColor(QPalette.ColorRole.Button, c_button)
        p.setColor(QPalette.ColorRole.ButtonText, c_text)
        p.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
        p.setColor(QPalette.ColorRole.Highlight, c_highlight)
        p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(150, 150, 150))
    else:
        p = QPalette()  # standard
    app.setPalette(p)


class _OptimizeWorker(QObject):
    """Applies Ficop settings to ``dummy`` and runs :func:`dummy.optimization` (full pipeline)."""

    log_line = pyqtSignal(str)
    # Do not name this "finished" — QThread has a 0-arg ``finished``; wrong slots get invoked.
    optimizationCompleted = pyqtSignal(float, float)  # seconds, final merit (may be NaN on failure to read)
    failed = pyqtSignal(str)

    def __init__(
        self,
        pairs: list[tuple[int, int]],
        manual_iter: int,
        one_knob_iter: int,
        two_knob_iter: int,
        fine_manual_iter: int,
        two_knob_step: int,
        two_knob_dui: int,
        no_update: int,
        wait_osc: float,
        verbose: bool,
        oscilloscope_channel: int,
    ) -> None:
        super().__init__()
        if len(pairs) < 1:
            raise ValueError("need at least one two-knob pair")
        self._pairs = [tuple(p) for p in pairs]
        self._man = max(0, int(manual_iter))
        self._onek = max(0, int(one_knob_iter))
        self._twok = max(0, int(two_knob_iter))
        self._fine = max(0, int(fine_manual_iter))
        self._tk_step = int(two_knob_step)
        dui = int(two_knob_dui)
        self._tk_dui_arg = 0 if dui <= 0 else dui
        self._no_update = int(no_update)
        self._wait_osc = float(wait_osc)
        self._verbose = bool(verbose)
        self._osc_ch = int(oscilloscope_channel)

    @pyqtSlot()
    def run(self) -> None:
        try:
            dummy.set_log_handler(lambda m: self.log_line.emit(str(m)))
            dummy.OSCILLOSCOPE_CHANNEL = self._osc_ch
            dummy.WAIT_FOR_OSCILLOSCOPE = self._wait_osc
            dummy.NO_UPDATE_COUNT_THRESHOLD = self._no_update
            dummy.TWO_KNOB_PAIRS = [tuple(p) for p in self._pairs]
            dummy.MANUAL_SEARCH_ITERATIONS = self._man
            dummy.ONE_KNOB_SEARCH_ITERATIONS = self._onek
            dummy.TWO_KNOB_SEARCH_ITERATIONS = self._twok
            dummy.FINE_MANUAL_SEARCH_ITERATIONS = self._fine

            duration, final = dummy.optimization(
                verbose=self._verbose,
                two_knob_step=self._tk_step,
                two_knob_direction_update_interval=self._tk_dui_arg,
            )
            self.optimizationCompleted.emit(float(duration), float(final))
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")
        finally:
            dummy.set_log_handler(None)


class FicopMainWindow(QMainWindow):
    VOLTAGE_LABELS = [
        "CH1 (0)",
        "CH2 (1)",
        "CH3 (2)",
        "CH4 (3)",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Ficop")
        self.resize(820, 720)
        self._connected = False
        self._opt_thread: QThread | None = None
        self._opt_worker: _OptimizeWorker | None = None

        root = QWidget()
        layout = QVBoxLayout(root)
        # Toolbar: appearance
        tb = QToolBar("Appearance", self)
        self._add_appearance_menu(tb)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)

        # 1) Connection
        g_conn = QGroupBox("1. Connection")
        tbd = QLabel(
            "Transport is TBD for real hardware. The dummy path connects immediately "
            "in-process (``dummy.py``) with no network or serial I/O to real devices."
        )
        tbd.setWordWrap(True)
        self._status = QLabel("Disconnected")
        b_connect = QPushButton("Connect")
        b_connect.clicked.connect(self._on_connect)
        b_disconnect = QPushButton("Disconnect")
        b_disconnect.clicked.connect(self._on_disconnect)
        row = QHBoxLayout()
        row.addWidget(b_connect)
        row.addWidget(b_disconnect)
        v = QVBoxLayout()
        v.addWidget(tbd)
        v.addWidget(self._status)
        v.addLayout(row)
        g_conn.setLayout(v)
        inner_layout.addWidget(g_conn)

        # 2) Two two-knob pairs (disjoint axes, same default as ``dummy.TWO_KNOB_PAIRS``)
        g_knob = QGroupBox("2. Two-knob walking (two independent pairs)")
        kfl = QFormLayout()
        (self._cb_p1a, self._cb_p1b) = _pair_combo_row(self, kfl, "Pair 1:", 0, 3)
        (self._cb_p2a, self._cb_p2b) = _pair_combo_row(self, kfl, "Pair 2:", 1, 2)
        p_hint = QLabel(
            "Write-through to dummy.TWO_KNOB_PAIRS for the two-knob stage. "
            "Each pair is two servos; use four distinct knob indices."
        )
        p_hint.setWordWrap(True)
        kfl.addRow(p_hint)
        g_knob.setLayout(kfl)
        inner_layout.addWidget(g_knob)

        # 3) Output
        g_out = QGroupBox("3. Output (oscilloscope voltage / scope channel index)")
        ol = QVBoxLayout()
        self._ch_combo = QComboBox()
        for j, name in enumerate(self.VOLTAGE_LABELS):
            self._ch_combo.addItem(f"{name}", j)
        self._ch_combo.setCurrentIndex(int(dummy.OSCILLOSCOPE_CHANNEL or 0))
        hint = QLabel(
            f"In dummy mode, only channel index {dummy.SIGNAL_CARRYING_CHANNEL} carries a synthetic "
            "merit; other selections read as zero (as if the signal is not on that BNC input)."
        )
        hint.setWordWrap(True)
        ol.addWidget(self._ch_combo)
        ol.addWidget(hint)
        g_out.setLayout(ol)
        inner_layout.addWidget(g_out)

        # 4) Parameters: dummy iteration globals and two-knob args to optimization()
        g_params = QGroupBox("4. Parameters (full dummy.optimization pipeline)")
        pfl = QFormLayout()
        self._sp_man = QSpinBox()
        self._sp_man.setRange(0, 200)
        self._sp_man.setValue(int(dummy.MANUAL_SEARCH_ITERATIONS))
        self._sp_onek = QSpinBox()
        self._sp_onek.setRange(0, 200)
        self._sp_onek.setValue(int(dummy.ONE_KNOB_SEARCH_ITERATIONS))
        self._sp_twok = QSpinBox()
        self._sp_twok.setRange(0, 200)
        self._sp_twok.setValue(int(dummy.TWO_KNOB_SEARCH_ITERATIONS))
        self._sp_fine = QSpinBox()
        self._sp_fine.setRange(0, 200)
        self._sp_fine.setValue(int(dummy.FINE_MANUAL_SEARCH_ITERATIONS))
        pfl.addRow("Manual search rounds (per ``dummy``):", self._sp_man)
        pfl.addRow("One-knob search outer rounds:", self._sp_onek)
        pfl.addRow("Two-knob search outer rounds:", self._sp_twok)
        pfl.addRow("Fine manual search outer rounds:", self._sp_fine)
        self._sp_step = QSpinBox()
        self._sp_step.setRange(1, 200)
        self._sp_step.setValue(10)
        self._sp_dui = QSpinBox()
        self._sp_dui.setRange(0, 1000)
        self._sp_dui.setSpecialValueText("off (no periodic recalc)")
        self._sp_dui.setValue(5)
        self._sp_noup = QSpinBox()
        self._sp_noup.setRange(1, 200)
        self._sp_noup.setValue(int(dummy.NO_UPDATE_COUNT_THRESHOLD))
        self._sp_wait = QDoubleSpinBox()
        self._sp_wait.setRange(0.0, 5.0)
        self._sp_wait.setSingleStep(0.05)
        self._sp_wait.setValue(float(dummy.WAIT_FOR_OSCILLOSCOPE))
        pfl.addRow("Two-knob step (encoder units, two-knob phase only):", self._sp_step)
        pfl.addRow("Two-knob direction recompute interval (iter, 0 = off):", self._sp_dui)
        pfl.addRow("Stall: no improvement count (two/one-knob, manual):", self._sp_noup)
        pfl.addRow("Oscilloscope wait (s):", self._sp_wait)
        ph = QLabel(
            "Order of stages: coarser manual (if rounds > 0) → one-knob (if > 0) → two-knob on both pairs (with early "
            "stopping in dummy) → fine manual (if > 0). Margins and steps in manual, one-knob, and fine stages are "
            "fixed in dummy, same as main."
        )
        ph.setWordWrap(True)
        pfl.addRow(ph)
        g_params.setLayout(pfl)
        inner_layout.addWidget(g_params)

        # Verbose
        self._ck_verbose = QCheckBox("Verbose (stream optimization lines to the log below)")
        self._ck_verbose.setChecked(True)
        inner_layout.addWidget(self._ck_verbose)

        # 5) Optimize
        g_opt = QGroupBox("5. Optimize")
        ovl = QVBoxLayout()
        row_opt = QHBoxLayout()
        self._btn_opt = QPushButton("Run full optimization (like dummy.py)")
        self._btn_opt.setEnabled(False)
        self._btn_opt.clicked.connect(self._on_optimize)
        self._merit = QLabel("Last merit: —")
        self._duration = QLabel("Last run: —")
        b_sample = QPushButton("Sample merit (once)")
        b_sample.clicked.connect(self._on_sample_merit)
        b_sample.setObjectName("btnSample")
        row_opt.addWidget(self._btn_opt)
        row_opt.addWidget(b_sample)
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setVisible(False)
        ovl.addLayout(row_opt)
        ovl.addWidget(self._merit)
        ovl.addWidget(self._duration)
        ovl.addWidget(self._bar)
        g_opt.setLayout(ovl)
        inner_layout.addWidget(g_opt)

        # Log
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(220)
        self._log.setPlaceholderText("Optimization and connection messages…")
        inner_layout.addWidget(QLabel("Log"))
        inner_layout.addWidget(self._log)
        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll)
        self.setCentralWidget(root)

    def _add_appearance_menu(self, tb: QToolBar) -> None:
        app = QApplication.instance()
        assert app is not None
        a_light = QAction("Light", self)
        a_dark = QAction("Dark", self)
        a_sys = QAction("Follow system", self)
        ag = QActionGroup(self)
        ag.setExclusionPolicy(QActionGroup.ExclusionPolicy.Exclusive)
        for a in (a_light, a_dark, a_sys):
            ag.addAction(a)
            a.setCheckable(True)
        a_sys.setChecked(True)
        a_light.triggered.connect(lambda: _set_fusion_app_palette(app, "light"))
        a_dark.triggered.connect(lambda: _set_fusion_app_palette(app, "dark"))
        a_sys.triggered.connect(lambda: _set_fusion_app_palette(app, "system"))
        tb.addAction(a_light)
        tb.addAction(a_dark)
        tb.addAction(a_sys)

    def _apply_oscilloscope_index(self) -> int:
        ch = int(self._ch_combo.currentData())
        dummy.OSCILLOSCOPE_CHANNEL = ch
        return ch

    def _set_pair_and_channel_controls_enabled(self, enabled: bool) -> None:
        self._ch_combo.setEnabled(enabled)
        for w in (self._cb_p1a, self._cb_p1b, self._cb_p2a, self._cb_p2b):
            w.setEnabled(enabled)

    @pyqtSlot()
    def _on_connect(self) -> None:
        try:
            # Motor before oscilloscope (``DummyOscilloscope`` holds a ref to the motor)
            self._append_log("Connecting (dummy)…")
            dummy.setup_motor_controller()
            dummy.setup_oscilloscope()
        except Exception as e:
            QMessageBox.critical(self, "Connect failed", str(e))
            self._append_log(f"Connect failed: {e}")
            return
        self._connected = True
        self._status.setText("Connected (dummy — motor + oscilloscope)")
        self._btn_opt.setEnabled(True)
        self._append_log("Connected.")
        self.statusBar().showMessage("Connected")

    @pyqtSlot()
    def _on_disconnect(self) -> None:
        if self._connected or dummy.motor_controller is not None:
            try:
                dummy.disconnect_devices()
            except Exception as e:
                self._append_log(f"Disconnect: {e}")
        self._connected = False
        self._status.setText("Disconnected")
        self._btn_opt.setEnabled(False)
        self._merit.setText("Last merit: —")
        self._append_log("Disconnected.")
        self.statusBar().showMessage("Disconnected")

    def _validate_two_pairs(self) -> list[tuple[int, int]] | None:
        a1, b1 = int(self._cb_p1a.currentData()), int(self._cb_p1b.currentData())
        a2, b2 = int(self._cb_p2a.currentData()), int(self._cb_p2b.currentData())
        if a1 == b1 or a2 == b2:
            QMessageBox.warning(
                self,
                "Invalid pair",
                "Within each pair, choose two different knob indices.",
            )
            return None
        if len({a1, b1, a2, b2}) < 4:
            QMessageBox.warning(
                self,
                "Invalid pairs",
                "The two pairs must use four different knobs (no axis shared between pair 1 and pair 2).",
            )
            return None
        return [(a1, b1), (a2, b2)]

    @pyqtSlot()
    def _on_optimize(self) -> None:
        if not self._connected:
            return
        pairs = self._validate_two_pairs()
        if pairs is None:
            return
        osc_ch = self._apply_oscilloscope_index()
        self._btn_opt.setEnabled(False)
        self._set_pair_and_channel_controls_enabled(False)
        self._bar.setVisible(True)
        self._log.clear()
        dui = int(self._sp_dui.value())
        self._opt_thread = QThread()
        self._opt_worker = _OptimizeWorker(
            pairs,
            int(self._sp_man.value()),
            int(self._sp_onek.value()),
            int(self._sp_twok.value()),
            int(self._sp_fine.value()),
            int(self._sp_step.value()),
            dui,
            int(self._sp_noup.value()),
            float(self._sp_wait.value()),
            self._ck_verbose.isChecked(),
            osc_ch,
        )
        self._opt_worker.moveToThread(self._opt_thread)
        self._opt_thread.started.connect(self._opt_worker.run)
        self._opt_worker.optimizationCompleted.connect(self._on_opt_finished)
        self._opt_worker.failed.connect(self._on_opt_failed)
        self._opt_worker.optimizationCompleted.connect(self._opt_thread.quit)
        self._opt_worker.failed.connect(self._opt_thread.quit)
        self._opt_thread.finished.connect(self._cleanup_worker)
        self._opt_worker.log_line.connect(self._append_log)
        self._opt_thread.start()

    @pyqtSlot(float, float)
    def _on_opt_finished(self, dt: float, merit: float) -> None:
        if math.isfinite(merit):
            self._merit.setText(f"Last merit: {merit:.6f} (end of full pipeline)")
        else:
            self._merit.setText("Last merit: — (could not read after run)")
        self._duration.setText(
            f"Last run: {dt:.2f} s (full dummy.optimization, stages and early-stop as in dummy.py)"
        )
        self._bar.setVisible(False)
        self._btn_opt.setEnabled(True)
        self._set_pair_and_channel_controls_enabled(True)
        self.statusBar().showMessage("Optimization finished")

    @pyqtSlot(str)
    def _on_opt_failed(self, msg: str) -> None:
        self._bar.setVisible(False)
        self._btn_opt.setEnabled(True)
        self._set_pair_and_channel_controls_enabled(True)
        self._append_log("FAILED:\n" + msg)
        QMessageBox.critical(self, "Optimization failed", msg)
        self.statusBar().showMessage("Optimization failed")

    @pyqtSlot()
    def _cleanup_worker(self) -> None:
        if self._opt_worker is not None:
            self._opt_worker.deleteLater()
            self._opt_worker = None
        if self._opt_thread is not None:
            self._opt_thread.deleteLater()
            self._opt_thread = None

    @pyqtSlot()
    def _on_sample_merit(self) -> None:
        if not self._connected or dummy.oscilloscope is None:
            return
        self._apply_oscilloscope_index()
        try:
            v = dummy.get_value()
        except Exception as e:
            self._merit.setText(f"Last merit: (error) {e}")
            return
        self._merit.setText(f"Last merit: {v:.6f} (sample)")

    def _append_log(self, s: str) -> None:
        self._log.append(s.rstrip())

    def closeEvent(self, event) -> None:
        if self._connected:
            try:
                dummy.disconnect_devices()
            except Exception:
                pass
        if self._opt_thread is not None and self._opt_thread.isRunning():
            self._opt_thread.quit()
            self._opt_thread.wait(2000)
        return super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Ficop")
    _set_fusion_app_palette(app, "system")
    w = FicopMainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
