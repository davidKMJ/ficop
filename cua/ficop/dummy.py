from __future__ import annotations

import time
from typing import Optional, Sequence, Tuple, Union

import numpy as np

from cua.logger import BaseLogger


class DummyController:
    """
    Software stand-in for :class:`cua.scservo.ServoController`.
    """

    def __init__(
        self,
        servo_ids: Sequence[int],
        *,
        device_name: str = "<dummy>",
        baudrate: int = 1_000_000,
        initial_positions: Optional[Sequence[int]] = None,
        move_delay: float = 0.0,
    ) -> None:
        if not isinstance(servo_ids, (list, tuple)) or len(servo_ids) == 0:
            raise ValueError("servo_ids must be a non-empty sequence")

        self.device_name = device_name
        self.baudrate = baudrate
        self.servo_ids: list[int] = list(servo_ids)
        self.num_servos = len(self.servo_ids)
        self.move_delay = float(move_delay)

        if initial_positions is None:
            self._positions: list[int] = [0] * self.num_servos
        else:
            initial_positions = list(initial_positions)
            if len(initial_positions) != self.num_servos:
                raise ValueError(
                    f"Number of initial positions ({len(initial_positions)}) "
                    f"must match number of servos ({self.num_servos})"
                )
            self._positions = [int(p) for p in initial_positions]

        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, verbose: bool = False) -> None:
        self._connected = True
        if verbose:
            print(f"DummyController connected ({self.num_servos} servos)")

    def disconnect(self, hold_torque: bool = False) -> None:
        self._connected = False
        print("DummyController disconnected")

    def configure_servos(self, acc: int = 0, speed: int = 0) -> None:
        if not self._connected:
            raise RuntimeError("DummyController not connected")

    def read_positions(self) -> list[int]:
        if not self._connected:
            raise RuntimeError("DummyController not connected")
        return list(self._positions)

    def set_positions(self, positions: Sequence[int]) -> None:
        if not self._connected:
            raise RuntimeError("DummyController not connected")
        positions = list(positions)
        if len(positions) != self.num_servos:
            raise ValueError(
                f"Number of positions ({len(positions)}) must match "
                f"number of servos ({self.num_servos})"
            )
        self._positions = [int(p) for p in positions]
        if self.move_delay > 0:
            time.sleep(self.move_delay)

    def wait_for_positions(
        self,
        goal_positions: Sequence[int],
        threshold: int = 20,
        timeout: Optional[float] = None,
    ) -> bool:
        if not self._connected:
            raise RuntimeError("DummyController not connected")
        return True

    def __enter__(self) -> "DummyController":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.disconnect()
        return False


class DummyLogger(BaseLogger):
    """
    Synthetic :class:`BaseLogger` whose merit is a Gaussian over the controller's
    positions
    """

    def __init__(
        self,
        controller: DummyController,
        *,
        center: Union[float, Sequence[float]] = 0.0,
        sigma: Union[float, Sequence[float]] = 100.0,
        noise: float = 0.0,
        unit: Optional[str] = None,
    ) -> None:
        super().__init__(device_name="<dummy>")
        self.controller = controller
        self.center = self._broadcast(center, controller.num_servos, "center")
        self.sigma = self._broadcast(sigma, controller.num_servos, "sigma")
        if np.any(self.sigma <= 0):
            raise ValueError("sigma values must be positive")
        self.noise = float(noise)
        self._unit = unit

    @staticmethod
    def _broadcast(value, n: int, name: str) -> np.ndarray:
        arr = np.atleast_1d(np.asarray(value, dtype=float))
        if arr.size == 1:
            return np.full(n, float(arr.item()))
        if arr.size != n:
            raise ValueError(
                f"{name} must be a scalar or have length {n} (got {arr.size})"
            )
        return arr

    def connect(self) -> None:
        self._connected = True
        print(
            f"DummyLogger connected (center={self.center.tolist()}, "
            f"sigma={self.sigma.tolist()})"
        )

    def disconnect(self) -> None:
        self._connected = False
        print("DummyLogger disconnected")

    def _merit(self) -> float:
        positions = np.asarray(self.controller.read_positions(), dtype=float)
        if positions.shape[0] != self.center.shape[0]:
            raise RuntimeError(
                f"DummyController has {positions.shape[0]} servos but DummyLogger "
                f"was configured for {self.center.shape[0]}"
            )
        d = (positions - self.center) / self.sigma
        merit = float(np.exp(-0.5 * float(np.sum(d * d))))
        if self.noise > 0:
            merit += float(self.noise * np.random.randn())
        return merit

    def get_current_value(self, channel: int = 1) -> Tuple[float, Optional[str]]:
        if not self._connected:
            raise RuntimeError("DummyLogger not connected")
        return self._merit(), self._unit
