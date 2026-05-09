from __future__ import annotations

import time

import matplotlib.pyplot as plt
import numpy as np

from cua.logger import Oscilloscope

DEVICE_NAME: str | None = "ASRL/dev/cu.usbserial-140::INSTR"
CHANNEL: int = 1


def example_single_waveform() -> None:
    """Connect, configure, grab one waveform, plot it, disconnect."""
    print("=" * 60)
    print("Example 1: read a single waveform")
    print("=" * 60)

    osc = Oscilloscope(device_name=DEVICE_NAME, channel=CHANNEL, auto_configure=True)
    osc.connect(verbose=True)
    try:
        print(f"Sample rate: {osc.get_sample_rate()} Sa/s")
        t_s, y = osc.read_values_with_time(channel=CHANNEL)
        print(f"Captured {len(y)} samples (mean = {float(np.mean(y)):.2f})")

        plt.figure()
        plt.plot(t_s, y, lw=1)
        plt.xlabel("Time (s)")
        plt.ylabel("ADC counts")
        plt.title(f"Channel {CHANNEL} waveform")
        plt.tight_layout()
        plt.show()
    finally:
        osc.disconnect()


def example_periodic_samples() -> None:
    """Use ``get_current_value`` (one scalar per call) for ~3 seconds."""
    print("=" * 60)
    print("Example 2: periodic single-value sampling")
    print("=" * 60)

    with Oscilloscope(device_name=DEVICE_NAME, channel=CHANNEL) as osc:
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 3.0:
            value, unit = osc.get_current_value()
            udisp = f" {unit}" if unit else ""
            print(f"  t={time.perf_counter() - t0:5.2f}s  value={value:.2f}{udisp}")
            time.sleep(0.25)


def example_plot_stream() -> None:
    """Live plot of the latest sample using ``BaseLogger.plot_stream``."""
    print("=" * 60)
    print("Example 3: live plot (press Q in the plot window to stop)")
    print("=" * 60)

    osc = Oscilloscope(device_name=DEVICE_NAME, channel=CHANNEL)
    osc.plot_stream(
        log=False,
        update_interval_s=0.05,
        max_plot_points=2000,
    )


def main() -> None:
    example_single_waveform()
    example_periodic_samples()
    example_plot_stream()


if __name__ == "__main__":
    main()
