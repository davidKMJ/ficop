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
        self.line, = self.ax.plot([], [])

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

device.write("*CLS")  # Clear Event Register

device.write("RUN")  # Start reading
device.write("ACQ:MDEP 12000")  # Memory depth for the sample
device.write("WAV:MODE NORM")  # Set waveform to Normal
device.write("WAV:FORM WORD")  # Data transmission type: binary
device.write("TIM:MODE ROLL")  # Set horizontal scale to rolling

sample_rate = float(device.query("ACQ:SRAT?"))
print("Sample Rate:", sample_rate)

device.write("SYST:BEEP ON")
device.write("SYST:BEEP OFF")

def values():
    y = device.query_binary_values("WAV:DATA?", container=np.array, datatype='i')
    x = np.arange(0, len(y))
    return np.array([x, y])


root = tk.Tk()
StreamingPlot(root)
root.mainloop()