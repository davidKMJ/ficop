from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pyvisa as visa

from ..logger import BaseLogger, Number


class Oscilloscope(BaseLogger):
    """
    PyVISA oscilloscope: connect to an oscilloscope and read values from it.
    """

    def __init__(
        self,
        device_name: Optional[str] = None,
        timeout: int = 30000,
        auto_configure: bool = True,
    ) -> None:
        """
        Initialize the Oscilloscope.

        Args:
            device_name: The name of the oscilloscope device to connect to.
            timeout: The VISA timeout in milliseconds. The first ``*IDN?`` after
                opening a USB-serial scope (e.g. Rigol via CH340/FTDI) can take
                several seconds, and ``pyvisa-py`` blocks for the full timeout
                when no byte arrives, so the default mirrors the 30 s used in
                the original standalone script.
            auto_configure: Whether to automatically configure the oscilloscope.
        """
        super().__init__(device_name)
        self.timeout = timeout
        self.rm = None
        self.device = None
        self.sample_rate: Optional[float] = None
        self._auto_configure = auto_configure

    def connect(self, verbose: bool = False) -> None:
        if self._connected:
            return
        try:
            self.rm = visa.ResourceManager()
            devices = self.rm.list_resources()
            if verbose:
                print(f"Available VISA devices: {devices}")

            if self.device_name is None:
                if len(devices) == 0:
                    raise RuntimeError("No VISA devices found")
                if len(devices) > 1:
                    print(
                        f"Warning: Multiple VISA devices found. Using first device: {devices[0]}"
                    )
                self.device_name = devices[0]
            elif self.device_name not in devices:
                raise RuntimeError(
                    f"Device '{self.device_name}' not found in available VISA devices: {devices}"
                )

            self.device = self.rm.open_resource(self.device_name)
            self.device.timeout = self.timeout

            idn = self.device.query("*IDN?")
            if verbose:
                print(f"Device Identification Number: {idn}")

            self.device.write("*CLS")

            self._connected = True
            if self._auto_configure:
                self.configure()

            print("Oscilloscope connected")

        except Exception as e:
            if self.device:
                try:
                    self.device.close()
                except Exception:
                    pass
            self.device = None
            self._connected = False
            raise RuntimeError(f"Oscilloscope failed to connect: {e}") from e

    def disconnect(self) -> None:
        if not (self.device and self._connected):
            self._connected = False
            return
        try:
            self.device.close()
            print("Oscilloscope disconnected")
        except Exception as e:
            raise RuntimeError(f"Oscilloscope failed to disconnect: {e}") from e
        finally:
            self._connected = False

    def configure(
        self,
        memory_depth: int = 12000,
        waveform_mode: str = "NORM",
        waveform_format: str = "WORD",
        time_mode: str = "ROLL",
        start_acquisition: bool = True,
        time_scale: float = 0.001,
    ) -> None:
        if not self._connected:
            raise RuntimeError("Oscilloscope not connected")

        if start_acquisition:
            self.device.write("RUN")

        self.device.write(f"ACQ:MDEP {memory_depth}")
        self.device.write(f"WAV:MODE {waveform_mode}")
        self.device.write(f"WAV:FORM {waveform_format}")
        self.device.write(f"TIM:MODE {time_mode}")
        self.device.write(f"TIM:MAIN:SCAL {time_scale}")

        self.sample_rate = float(self.device.query("ACQ:SRAT?"))

    def get_sample_rate(self) -> float:
        if not self._connected:
            raise RuntimeError("Oscilloscope not connected")

        self.sample_rate = float(self.device.query("ACQ:SRAT?"))
        return self.sample_rate

    def start_acquisition(self) -> None:
        if not self._connected:
            raise RuntimeError("Oscilloscope not connected")

        self.device.write("RUN")

    def stop_acquisition(self) -> None:
        if not self._connected:
            raise RuntimeError("Oscilloscope not connected")

        self.device.write("STOP")

    def beep(self) -> None:
        if not self._connected:
            raise RuntimeError("Oscilloscope not connected")

        self.device.write("SYST:BEEP ON")
        self.device.write("SYST:BEEP OFF")

    def read_values(self, channel: int) -> np.ndarray:
        if not self._connected:
            raise RuntimeError("Oscilloscope not connected")

        self.device.write(f"WAV:SOUR CHAN{channel}")

        y = self.device.query_binary_values(
            "WAV:DATA?", container=np.array, datatype="i"
        )

        x = np.arange(0, len(y))
        return np.array([x, y])

    def read_values_with_time(self, channel: int) -> np.ndarray:
        if not self._connected:
            raise RuntimeError("Oscilloscope not connected")

        if self.sample_rate is None:
            self.sample_rate = self.get_sample_rate()

        x, y = self.read_values(channel)
        time_values = x / self.sample_rate
        return np.array([time_values, y])

    def query(self, command: str) -> str:
        if not self._connected:
            raise RuntimeError("Oscilloscope not connected")

        return self.device.query(command)

    def write(self, command: str) -> None:
        if not self._connected:
            raise RuntimeError("Oscilloscope not connected")

        self.device.write(command)

    def get_current_value(self, channel: int) -> Tuple[Number, Optional[str]]:
        if not self._connected:
            raise RuntimeError("Oscilloscope not connected")
        xy = self.read_values(channel)
        y = xy[1]
        if len(y) == 0:
            raise RuntimeError("Oscilloscope returned an empty waveform")
        return float(y[-1]), None
