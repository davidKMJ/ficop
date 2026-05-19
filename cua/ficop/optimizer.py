from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Callable, Optional, Sequence

import numpy as np

from cua.logger import BaseLogger
from cua.scservo import ServoController

ValueFn = Callable[[BaseLogger], float]
LogFn = Callable[[str], None]


def default_value_fn(channel: int) -> ValueFn:
    """Build a ``value_fn`` that reads ``logger.get_current_value(channel)``."""

    def fn(logger: BaseLogger) -> float:
        val, _unit = logger.get_current_value(channel)
        return float(val)

    return fn


def oscilloscope_mean_value_fn(
    channel: Optional[int] = None,
    offset: float = 0.0,
    scaling_factor: float = 1.0,
) -> ValueFn:
    """
    Build a ``value_fn`` for an oscilloscope-style logger.

    Reads ``logger.read_values(channel=channel)``, takes the mean of the
    second row (the y-samples), then returns ``(mean - offset) / scaling_factor``.
    """

    def fn(logger: BaseLogger) -> float:
        xy = logger.read_values(channel)
        mean = float(np.mean(xy[1]))
        return (mean - offset) / scaling_factor

    return fn


class BaseOptimizer(ABC):
    """
    Abstract base for an alignment optimizer.

    The optimizer reads the current servo positions, drives them to a test
    position, then reads a merit value via ``value_fn(logger)``. Subclasses
    implement the search policy in :meth:`run`.
    """

    def __init__(
        self,
        logger: BaseLogger,
        servo_controller: ServoController,
        *,
        min_position: int = -15000,
        max_position: int = 15000,
        position_threshold: int = 5,
        position_timeout: float = 5.0,
        wait_for_value: float = 0.1,
        value_threshold: float = -float("inf"),
        value_fn: Optional[ValueFn] = None,
        verbose: bool = True,
        log_fn: LogFn = print,
    ) -> None:
        """
        Args:
            logger: Connected logger producing the merit value.
            servo_controller: Connected, configured servo controller.
            min_position: Hardware lower bound (encoder counts).
            max_position: Hardware upper bound (encoder counts).
            position_threshold: Encoder-count tolerance for ``wait_for_positions``.
            position_timeout: Seconds to wait for the servos to settle.
            wait_for_value: Settle time (s) between motion and reading.
            value_threshold: Below this the read is treated as "beam not detected".
            value_fn: ``callable(logger) -> float`` returning the merit value.
                Defaults to :func:`default_value_fn` on channel ``1``.
            verbose: When True, per-iteration progress lines are emitted.
            log_fn: Sink for log messages (defaults to :func:`print`).
        """
        self.logger = logger
        self.servo_controller = servo_controller
        self.min_position = int(min_position)
        self.max_position = int(max_position)
        self.position_threshold = int(position_threshold)
        self.position_timeout = float(position_timeout)
        self.wait_for_value = float(wait_for_value)
        self.value_threshold = float(value_threshold)
        self.value_fn = value_fn if value_fn is not None else default_value_fn(1)
        self.verbose = bool(verbose)
        self._log = log_fn

    @property
    def num_servos(self) -> int:
        return self.servo_controller.num_servos

    def read_positions(self) -> list[int]:
        """Return a fresh copy of the present servo positions."""
        return list(self.servo_controller.read_positions())

    def set_positions(self, positions: Sequence[int]) -> bool:
        """
        Send ``positions`` to the servos and block until they settle.

        Safety: if any requested position is outside
        ``[min_position, max_position]`` the move is skipped and the method
        returns ``False`` (preserving the conservative behaviour of the
        original ficop scripts). Otherwise positions are clipped, sent, and
        we wait up to ``position_timeout``.
        """
        positions = list(positions)
        if len(positions) != self.num_servos:
            raise ValueError(
                f"Number of positions ({len(positions)}) must match "
                f"number of servos ({self.num_servos})"
            )
        for pos in positions:
            if pos < self.min_position or pos > self.max_position:
                return False
        clipped = [
            int(np.clip(pos, self.min_position, self.max_position)) for pos in positions
        ]
        self.servo_controller.set_positions(clipped)
        self.servo_controller.wait_for_positions(
            clipped,
            threshold=self.position_threshold,
            timeout=self.position_timeout,
        )
        return True

    def get_value(self) -> float:
        """Sleep ``wait_for_value`` then read the merit value via ``value_fn``."""
        if self.wait_for_value > 0:
            time.sleep(self.wait_for_value)
        value = float(self.value_fn(self.logger))
        if value < self.value_threshold:
            raise RuntimeError(
                "Beam not detected (try again after checking if the beam is blocked)"
            )
        return value

    def blackbox(self, positions: Sequence[int]) -> float:
        """Drive ``positions`` and return the merit value once settled."""
        self.set_positions(positions)
        return self.get_value()

    def _vprint(self, msg: str) -> None:
        if self.verbose:
            self._log(msg)

    def _print(self, msg: str) -> None:
        self._log(msg)

    @abstractmethod
    def run(self) -> float:
        """Execute one optimizer phase. Returns the best merit value observed."""


class ManualOptimizer(BaseOptimizer):
    """
    Manual search for the motor positions.
    """

    def __init__(
        self,
        logger: BaseLogger,
        servo_controller: ServoController,
        *,
        iterations: int = 1,
        margin: int = 500,
        step: int = 10,
        servo_indices: Optional[Sequence[int]] = None,
        margin_decay: float = 1.0,
        no_update_count_early_stop: bool = True,
        no_update_count_threshold: int = 10,
        **base_kwargs,
    ) -> None:
        super().__init__(logger, servo_controller, **base_kwargs)
        self.iterations = int(iterations)
        self.margin = int(margin)
        self.step = int(step)
        self.servo_indices = (
            list(range(self.num_servos))
            if servo_indices is None
            else list(servo_indices)
        )
        self.margin_decay = float(margin_decay)
        self.no_update_count_early_stop = bool(no_update_count_early_stop)
        self.no_update_count_threshold = int(no_update_count_threshold)

    def _sweep_one_servo(self, servo_idx: int, margin: int) -> float:
        positions = self.read_positions()
        best_pos = positions.copy()
        best_value = self.blackbox(positions)
        low = positions[servo_idx] - margin
        high = positions[servo_idx] + margin
        no_update_count = 0
        for i, pos in enumerate(range(low, high, self.step)):
            test_positions = positions.copy()
            test_positions[servo_idx] = pos
            value = self.blackbox(test_positions)
            self._vprint(
                f"manual: {servo_idx} | iter: {i} | position: {pos} | "
                f"value: {value} | best value: {best_value}"
            )
            if value > best_value:
                best_value = value
                best_pos[servo_idx] = pos
                no_update_count = 0
            else:
                no_update_count += 1
            if (
                self.no_update_count_early_stop
                and no_update_count > self.no_update_count_threshold
            ):
                break
        return self.blackbox(best_pos)

    def run(self) -> float:
        max_value = -np.inf
        for i in range(self.iterations):
            current = self.blackbox(self.read_positions())
            iteration_max = current
            margin = (
                int(self.margin / (self.margin_decay**i))
                if self.margin_decay > 0
                else self.margin
            )
            for servo_idx in self.servo_indices:
                iteration_max = max(
                    iteration_max, self._sweep_one_servo(servo_idx, margin)
                )
            max_value = max(max_value, iteration_max)
        return max_value


class TwoKnobOptimizer(BaseOptimizer):
    """
    Walk pairs of servos along the local 2D merit gradient.
    """

    def __init__(
        self,
        logger: BaseLogger,
        servo_controller: ServoController,
        *,
        iterations: int = 1,
        step: int = 10,
        pairs: Optional[Sequence[Sequence[int]]] = None,
        direction_update_interval: Optional[int] = None,
        no_update_count_threshold: int = 10,
        **base_kwargs,
    ) -> None:
        super().__init__(logger, servo_controller, **base_kwargs)
        if pairs is None:
            raise ValueError("TwoKnobOptimizer requires at least one pair")
        self.pairs = [tuple(p) for p in pairs]
        if any(len(p) != 2 for p in self.pairs):
            raise ValueError("Each pair must be a 2-tuple of servo indices")
        self.iterations = int(iterations)
        self.step = int(step)
        self.direction_update_interval = (
            None
            if direction_update_interval is None
            else int(direction_update_interval)
        )
        self.no_update_count_threshold = int(no_update_count_threshold)

    def _get_direction(self, idx1: int, idx2: int) -> np.ndarray:
        positions = self.read_positions()
        current = positions.copy()
        current[idx1] += self.step
        df_dx = self.blackbox(current)
        current[idx1] -= 2 * self.step
        df_dx -= self.blackbox(current)
        df_dx /= 2 * self.step
        current[idx1] += self.step
        current[idx2] += self.step
        df_dy = self.blackbox(current)
        current[idx2] -= 2 * self.step
        df_dy -= self.blackbox(current)
        df_dy /= 2 * self.step
        grad = np.array([df_dx, df_dy], dtype=float)
        norm = np.linalg.norm(grad)
        if norm == 0:
            return np.zeros(2, dtype=float)
        return grad / norm

    def _walk_pair(self, idx1: int, idx2: int) -> float:
        best_pos = self.read_positions()
        best_value = self.blackbox(best_pos)
        direction = self._get_direction(idx1, idx2)
        no_update_count = 0
        iter_count = 0
        while no_update_count < self.no_update_count_threshold:
            current = self.read_positions()
            test = current.copy()
            test[idx1] += self.step * direction[0]
            test[idx2] += self.step * direction[1]
            value = self.blackbox(test)
            if value > best_value:
                best_value = value
                best_pos[idx1] = test[idx1]
                best_pos[idx2] = test[idx2]
                no_update_count = 0
            else:
                no_update_count += 1
            self._vprint(
                f"two-knob: {idx1}, {idx2} | iter: {iter_count} | "
                f"position: {test[idx1]}, {test[idx2]} | "
                f"value: {value} | best value: {best_value}"
            )
            iter_count += 1
            if (
                self.direction_update_interval
                and iter_count % self.direction_update_interval == 0
            ):
                direction = self._get_direction(idx1, idx2)
        return self.blackbox(best_pos)

    def run(self) -> float:
        max_value = -np.inf
        for _ in range(self.iterations):
            current = self.blackbox(self.read_positions())
            iteration_max = current
            for idx1, idx2 in self.pairs:
                iteration_max = max(iteration_max, self._walk_pair(idx1, idx2))
            max_value = max(max_value, iteration_max)
        return max_value


class Compose:
    """
    Run a sequence of optimizers that share already-connected devices.
    """

    def __init__(
        self,
        optimizers: Sequence[BaseOptimizer],
        *,
        log_fn: LogFn = print,
    ) -> None:
        self.optimizers: list[BaseOptimizer] = list(optimizers)
        self._log = log_fn

    def append(self, optimizer: BaseOptimizer) -> "Compose":
        self.optimizers.append(optimizer)
        return self

    def run(self) -> float:
        max_value = -float("inf")
        for opt in self.optimizers:
            name = type(opt).__name__
            self._log("=" * 60)
            self._log(f"Starting {name}...")
            self._log("=" * 60)
            value = opt.run()
            self._log(f"\n\n{name} done — best value: {value}")
            if value > max_value:
                max_value = value
        return max_value
