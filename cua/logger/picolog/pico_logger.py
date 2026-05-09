from __future__ import annotations

import ctypes
from time import sleep
from typing import Optional, Tuple

import numpy as np
from numpy.typing import NDArray

from ..logger import BaseLogger, Number

INPUT_RANGE_MV_DEFAULT = 2500


class PicoLogger(BaseLogger):
    """
    PicoLog PL-1000 style logger: connect to a PicoLog and read values from it.
    """

    def __init__(
        self,
        device_name: Optional[str] = None,
        channel_key: str = "PL1000_CHANNEL_1",
        input_range_mv: int = INPUT_RANGE_MV_DEFAULT,
        stream_samples_per_channel: int = 1_000,
        stream_us_per_block: int = 1_000_000,
    ) -> None:
        """
        Initialize the PicoLogger.

        Args:
            device_name: The name of the PicoLog device to connect to.
            channel_key: The key of the channel to read from (e.g. ``"PL1000_CHANNEL_1"``).
            input_range_mv: The input range in millivolts.
            stream_samples_per_channel: The number of samples per channel to stream.
            stream_us_per_block: The time in microseconds per block to stream.
        """
        super().__init__(device_name)
        self._channel_key = channel_key
        self._input_range_mv = input_range_mv
        self._stream_n_samples = stream_samples_per_channel
        self._stream_us_per_block = stream_us_per_block
        self._chandle = ctypes.c_int16()
        self._max_adc = ctypes.c_uint16()
        self._pl = None
        self._streaming = False
        self._stream_values: Optional[ctypes.Array] = None
        self._stream_overflow = ctypes.c_uint16()
        self._stream_trigger_index = ctypes.c_uint32(0)

    def connect(self) -> None:
        if self._connected:
            return
        try:
            from picosdk.functions import assert_pico_ok
            from picosdk.pl1000 import pl1000 as pl

            status: dict[str, int] = {}
            status["openUnit"] = pl.pl1000OpenUnit(ctypes.byref(self._chandle))
            assert_pico_ok(status["openUnit"])
            status["maxValue"] = pl.pl1000MaxValue(
                self._chandle, ctypes.byref(self._max_adc)
            )
            assert_pico_ok(status["maxValue"])
            self._pl = pl
            self._streaming = False
            self._stream_values = None
            self._connected = True
            print("PicoLogger connected")
        except Exception as e:
            self._connected = False
            raise RuntimeError(f"PicoLogger failed to connect: {e}") from e

    def disconnect(self) -> None:
        if not self._connected:
            return
        try:
            from picosdk.functions import assert_pico_ok

            pl = self._pl
            if self._streaming:
                pl.pl1000Stop(self._chandle)
                self._streaming = False
            self._stream_values = None
            status: dict[str, int] = {}
            status["closeUnit"] = pl.pl1000CloseUnit(self._chandle)
            assert_pico_ok(status["closeUnit"])
            print("PicoLogger disconnected")
        except Exception as e:
            raise RuntimeError(f"PicoLogger failed to disconnect: {e}") from e
        finally:
            self._connected = False

    def stop_streaming(self) -> None:
        """End streaming mode so ``get_current_value`` can be used again."""
        if not self._connected:
            raise RuntimeError("PicoLogger not connected")
        if not self._streaming:
            return
        from picosdk.functions import assert_pico_ok

        assert_pico_ok(self._pl.pl1000Stop(self._chandle))
        self._streaming = False

    def _ensure_streaming(self) -> None:
        if not self._connected:
            raise RuntimeError("PicoLogger not connected")
        if self._streaming:
            return
        from picosdk.functions import assert_pico_ok

        pl = self._pl
        n_ch = 1
        n_ideal = ctypes.c_uint32(self._stream_n_samples)
        us_for_block = ctypes.c_uint32(self._stream_us_per_block)
        channels = (ctypes.c_int16 * n_ch)(pl.PL1000Inputs[self._channel_key])

        status: dict[str, int] = {}
        status["setInterval"] = pl.pl1000SetInterval(
            self._chandle,
            ctypes.byref(us_for_block),
            n_ideal,
            channels,
            n_ch,
        )
        assert_pico_ok(status["setInterval"])

        chunk = self._stream_n_samples
        self._stream_values = (ctypes.c_uint16 * chunk)()
        stream_buffer_samples = 10 * chunk
        mode = pl.PL1000_BLOCK_METHOD["BM_STREAM"]
        status["run"] = pl.pl1000Run(self._chandle, stream_buffer_samples, mode)
        assert_pico_ok(status["run"])

        ready = ctypes.c_int16(0)
        while ready.value == 0:
            assert_pico_ok(pl.pl1000Ready(self._chandle, ctypes.byref(ready)))
            sleep(0.001)

        self._streaming = True

    def get_values(self) -> NDArray[np.floating]:
        """
        Return one block of samples from the streaming buffer.

        Row 0 is time in **ms** relative to the start of this block; row 1 is **mV**.
        Shape ``(2, n)`` with ``n`` the number of samples returned (≤ configured block size).

        After calling this, use :meth:`stop_streaming` before :meth:`get_current_value`.
        """
        if not self._connected:
            raise RuntimeError("PicoLogger not connected")
        from picosdk.functions import adc2mVpl1000, assert_pico_ok

        self._ensure_streaming()
        pl = self._pl
        assert self._stream_values is not None
        chunk = self._stream_n_samples
        n_got = ctypes.c_uint32(chunk)

        assert_pico_ok(
            pl.pl1000GetValues(
                self._chandle,
                ctypes.byref(self._stream_values),
                ctypes.byref(n_got),
                ctypes.byref(self._stream_overflow),
                ctypes.byref(self._stream_trigger_index),
            )
        )

        n = int(n_got.value)
        mvs = np.asarray(
            adc2mVpl1000(self._stream_values[:n], self._input_range_mv, self._max_adc),
            dtype=np.float64,
        )

        dt_ms = self._stream_us_per_block / max(n, 1) / 1000.0
        time_ms = np.arange(n, dtype=np.float64) * dt_ms
        return np.stack([time_ms, mvs.astype(np.float64)])

    def get_current_value(self) -> Tuple[Number, Optional[str]]:
        if not self._connected:
            raise RuntimeError("PicoLogger not connected")
        if self._streaming:
            raise RuntimeError(
                "PicoLogger streaming is active; call stop_streaming() before get_current_value()"
            )
        from picosdk.functions import assert_pico_ok

        pl = self._pl
        raw = ctypes.c_uint16()
        st = pl.pl1000GetSingle(
            self._chandle,
            pl.PL1000Inputs[self._channel_key],
            ctypes.byref(raw),
        )
        assert_pico_ok(st)
        max_adc = self._max_adc.value or 1
        mv = (int(raw.value) * int(self._input_range_mv)) / max_adc
        return float(mv), "mV"
