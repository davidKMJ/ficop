import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import pyvisa as visa
import numpy as np

MAX_DURATION = 100


class StreamingPlot:
    def __init__(self, root):
        self.root = root
        self.data = np.array([[], []])  # [[x1, x2, ...], [y1, y2, ...]]

        fig = Figure()
        self.ax = fig.add_subplot(111)
        (self.line,) = self.ax.plot([], [])

        self.canvas = FigureCanvasTkAgg(fig, master=root)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.update_plot()

    def update_plot(self):
        # Simulated streaming data
        self.data = values()

        if len(self.data[0]) / sample_rate > MAX_DURATION:
            cutoff = round(MAX_DURATION * sample_rate)
            self.data = self.data[:, -cutoff:]

        self.line.set_data(*self.data)
        self.ax.relim()
        self.ax.autoscale_view()

        self.canvas.draw()
        self.root.after(10, self.update_plot)  # first argument is update period


rm = visa.ResourceManager()
devices = rm.list_resources()
print(devices)
# assert len(devices) == 1
device = rm.open_resource(devices[0])

device.timeout = 30000

print("Device Identification Number:", device.query("*IDN?"))

# Note: To find exact supported values for your oscilloscope model, you can query:
#   - device.query("ACQ:MDEP?")  # Query current memory depth
#   - device.query("WAV:MODE?")   # Query current waveform mode
#   - device.query("WAV:FORM?")   # Query current waveform format
#   - device.query("TIM:MODE?")   # Query current timebase mode
# Consult your oscilloscope's programmer's reference manual for complete list of supported values.

device.write("*CLS")  # Clear Event Register

device.write("RUN")  # Start reading

# ACQ:MDEP - Acquisition Memory Depth
# Possible values: Numeric values (e.g., 12000, 2000, 10000, 100000, 1000000, etc.)
# Some scopes support: AUTO, MAX
device.write("ACQ:MDEP 12000")  # Memory depth for the sample

# WAV:MODE - Waveform Mode (how waveform data is sampled and processed)
# Possible values (vendor-dependent, common examples):
#   - "NORM" or "NORMAL" - Normal mode (first point from each sample interval)
#   - "SAMPLE" - Basic sample mode
#   - "PEAK" or "PEAKDETECT" - Peak detect mode (finds max/min in each interval)
#   - "HI_RES" or "HIRES" - High resolution mode (averages samples)
#   - "ENVELOPE" - Envelope mode (builds envelope over multiple acquisitions)
#   - "ET" or "RANDOM_ET" - Equivalent time mode (for repetitive signals)
device.write("WAV:MODE NORM")  # Set waveform to Normal

# WAV:FORM - Waveform Format (data encoding/format for waveform transfer)
# Possible values:
#   - "WORD" - Two bytes per point (16-bit), binary format
#   - "BYTE" - One byte per point (8-bit), binary format
#   - "ASC" or "ASCII" - ASCII formatted numeric text
#   - "REAL" or "FLOAT" - Floating-point values (if supported)
#   - "BIN" or "BINARY" - Raw binary data
device.write("WAV:FORM WORD")  # Data transmission type: binary

# TIM:MODE - Timebase Mode (how the horizontal axis/timebase operates)
# Possible values:
#   - "ROLL" - Rolling mode (for slow sweep rates, displays continuously without trigger)
#   - "MAIN" - Main timebase mode (triggers as usual, stable waveform)
#   - "NORM" or "NORMAL" - Normal mode (similar to MAIN, governed by triggers)
#   - "AUTO" - Automatically choose mode
#   - "SINGLE" - Capture single waveform on trigger then stop
device.write("TIM:MODE ROLL")  # Set horizontal scale to rolling

sample_rate = float(device.query("ACQ:SRAT?"))
print("Sample Rate:", sample_rate)

device.write("SYST:BEEP ON")
device.write("SYST:BEEP OFF")


def values():
    y = device.query_binary_values("WAV:DATA?", container=np.array, datatype="i")
    x = np.arange(0, len(y))
    return np.array([x, y])


root = tk.Tk()
StreamingPlot(root)
root.mainloop()
