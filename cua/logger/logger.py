from __future__ import annotations

import sys
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Union

Number = Union[int, float]


class BaseLogger(ABC):
    """
    Abstract logger: hardware subclasses implement connect/disconnect/get_current_value.
    """

    def __init__(self, device_name: Optional[str] = None) -> None:
        self.device_name = device_name
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @abstractmethod
    def connect(self) -> None:
        """Open the device / session."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the device / session."""

    @abstractmethod
    def get_current_value(self) -> Tuple[Number, Optional[str]]:
        """
        Sample the current reading.

        Returns:
            (value, unit): unit is a short string (e.g. ``\"mV\"``) or ``None`` if unknown / dimensionless.
        """

    def __enter__(self) -> BaseLogger:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.disconnect()
        return False

    def plot_stream(
        self,
        log: bool = False,
        log_path: Optional[Union[str, Path]] = None,
        update_interval_s: float = 0.05,
        max_plot_points: int = 2000,
    ) -> None:
        """
        Live plot (time in ms vs value) until ``Q`` is pressed in the plot window.
        Prints the latest value on one terminal line.
        If ``log`` is True, append each (time_ms, value) pair and write a tab-separated text file.
        """
        import matplotlib.pyplot as plt

        opened_here = False
        if not self._connected:
            self.connect()
            opened_here = True

        log_rows: list[tuple[float, float]] = []
        t0 = time.perf_counter()
        running = True

        fig, ax = plt.subplots()
        (line,) = ax.plot([], [], lw=1)
        ax.set_xlabel("Time (ms)")

        def _ylabel(u: Optional[str]) -> str:
            if u:
                return f"Value ({u})"
            return "Value"

        last_unit: Optional[str] = None

        def on_key(event) -> None:
            nonlocal running
            if event.key and str(event.key).lower() == "q":
                running = False
                plt.close(fig)

        fig.canvas.mpl_connect("key_press_event", on_key)
        fig.suptitle("Press Q in this window to stop")

        times_ms: list[float] = []
        values: list[float] = []

        try:
            plt.ion()
            plt.show(block=False)

            while running and plt.fignum_exists(fig.number):
                val, unit = self.get_current_value()
                t_ms = (time.perf_counter() - t0) * 1000.0
                fv = float(val)

                times_ms.append(t_ms)
                values.append(fv)
                if len(times_ms) > max_plot_points:
                    times_ms = times_ms[-max_plot_points:]
                    values = values[-max_plot_points:]

                if unit != last_unit:
                    ax.set_ylabel(_ylabel(unit))
                    last_unit = unit

                line.set_data(times_ms, values)
                ax.relim()
                ax.autoscale_view()
                fig.canvas.draw_idle()
                fig.canvas.flush_events()
                plt.pause(update_interval_s)

                udisp = f" {unit}" if unit else ""
                msg = f"\r{fv:.6g}{udisp}    "
                sys.stdout.write(msg)
                sys.stdout.flush()

                if log:
                    log_rows.append((t_ms, fv))

        finally:
            sys.stdout.write("\n")
            sys.stdout.flush()
            plt.ioff()
            try:
                plt.close(fig)
            except Exception:
                pass

            if log and log_rows:
                path = (
                    Path(log_path)
                    if log_path is not None
                    else Path(
                        f"logger_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    )
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8") as f:
                    f.write("time_ms\tvalue\n")
                    for tm, vv in log_rows:
                        f.write(f"{tm}\t{vv}\n")

            if opened_here:
                self.disconnect()
