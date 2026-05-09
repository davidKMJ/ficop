from __future__ import annotations

import matplotlib.pyplot as plt

from cua.logger import PicoLogger

CHANNEL_KEY = "PL1000_CHANNEL_1"
INPUT_RANGE_MV = 2500
STREAM_SAMPLES_PER_BLOCK = 1_000
STREAM_US_PER_BLOCK = 1_000_000


def example_single_value() -> None:
    """Open the unit, take 5 single-shot readings, close."""
    print("=" * 60)
    print("Example 1: single-shot readings")
    print("=" * 60)

    pico = PicoLogger(channel_key=CHANNEL_KEY, input_range_mv=INPUT_RANGE_MV)
    with pico:
        for i in range(5):
            value, unit = pico.get_current_value()
            print(f"  sample {i}: {value:.2f} {unit}")


def example_streaming_block() -> None:
    """Capture one streaming block and plot the resulting (time, mV) trace."""
    print("=" * 60)
    print("Example 2: capture one streaming block and plot")
    print("=" * 60)

    pico = PicoLogger(
        channel_key=CHANNEL_KEY,
        input_range_mv=INPUT_RANGE_MV,
        stream_samples_per_channel=STREAM_SAMPLES_PER_BLOCK,
        stream_us_per_block=STREAM_US_PER_BLOCK,
    )
    pico.connect()
    try:
        block = pico.get_values()
        time_ms, mv = block[0], block[1]
        print(f"  got {len(mv)} samples ({mv.min():.1f}..{mv.max():.1f} mV)")

        pico.stop_streaming()

        plt.figure()
        plt.plot(time_ms, mv, lw=1)
        plt.xlabel("Time (ms)")
        plt.ylabel("Voltage (mV)")
        plt.title(f"PicoLog block from {CHANNEL_KEY}")
        plt.tight_layout()
        plt.show()
    finally:
        pico.disconnect()


def example_plot_stream() -> None:
    """Live plot of single-shot readings using ``BaseLogger.plot_stream``."""
    print("=" * 60)
    print("Example 3: live plot of single-shot readings")
    print("=" * 60)

    pico = PicoLogger(channel_key=CHANNEL_KEY, input_range_mv=INPUT_RANGE_MV)
    pico.plot_stream(
        log=True,
        log_path="picolog_run.txt",
        update_interval_s=0.05,
        max_plot_points=2000,
    )


def main() -> None:
    example_single_value()
    example_streaming_block()
    example_plot_stream()


if __name__ == "__main__":
    main()
