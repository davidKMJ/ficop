import time

import numpy as np

# Configuration (mirrors main.py — no hardware)
MOTOR_DEVICE = "COM4"
MOTOR_BAUDRATE = 1000000
SERVO_IDS = [30, 31, 80, 81]
MIN_POSITION = 500
MAX_POSITION = 3500
THRESHOLD = 2

OSCILLOSCOPE_CHANNEL = None
# For dummy mode: the logical scope channel index (0-based) that carries the beam
# response. All other channel indices return a flat line (merit = 0).
SIGNAL_CARRYING_CHANNEL = 0
WAIT_FOR_OSCILLOSCOPE = 0.1

_log = print


def set_log_handler(fn):
    """Replace dummy's logging (``print``) for GUI or quiet runs. Pass ``None`` to reset."""
    global _log
    _log = fn or print

VALUE_OFFSET = 8000000
VALUE_SCALING_FACTOR = 10000000
VALUE_THRESHOLD = 0.000

NO_UPDATE_COUNT_THRESHOLD = 5
REASONABLE_VALUE_THRESHOLD = 0.020
# Same pairs as optimization() two_knob_search
TWO_KNOB_PAIRS = [(0, 3), (1, 2)]
# Isotropic Gaussian merit in encoder space (same σ per axis, centered at mid-travel)
GAUSSIAN_SIGMA = 300.0
# Small fixed counts so dummy runs without input()
MANUAL_SEARCH_ITERATIONS = 1
ONE_KNOB_SEARCH_ITERATIONS = 0
TWO_KNOB_SEARCH_ITERATIONS = 10
FINE_MANUAL_SEARCH_ITERATIONS = 1

oscilloscope = None
motor_controller = None


def _synthetic_value_from_positions(positions):
    """
    Fake beam strength: common (isotropic) Gaussian in position space,
    merit = exp(-||p - c||^2 / (2 σ^2)) with c mid-travel. Floor on raw limits
    spurious "beam blocked" from oscilloscope noise.
    """
    p = np.array(positions, dtype=float)
    c = (MIN_POSITION + MAX_POSITION) / 2.0
    d = p - c
    s = GAUSSIAN_SIGMA
    quad = float(np.sum((d / s) ** 2))
    merit = float(np.exp(-0.5 * quad))
    noise = 0.002 * np.random.randn()
    raw = VALUE_THRESHOLD + 0.100 * merit + noise
    return float(max(raw, VALUE_THRESHOLD + 0.002))


class DummyOscilloscope:
    def __init__(self, motor):
        self._motor = motor
        self._connected = False

    def connect(self):
        self._connected = True
        return True

    def disconnect(self):
        self._connected = False

    def configure(self, **kwargs):
        pass

    def read_values(self, channel=None):
        if not self._connected:
            raise RuntimeError("dummy oscilloscope not connected")
        ch = 0 if channel is None else int(channel)
        n = 1200
        if ch != SIGNAL_CARRYING_CHANNEL:
            return (
                np.arange(n, dtype=float),
                np.full(n, VALUE_OFFSET, dtype=float),
            )
        raw = _synthetic_value_from_positions(self._motor._positions)
        mean_level = VALUE_OFFSET + VALUE_SCALING_FACTOR * raw
        samples = mean_level + 15.0 * np.random.randn(n)
        return (np.arange(n, dtype=float), samples)


class DummyMotorController:
    def __init__(self, device_name, servo_ids, baudrate):
        self.device_name = device_name
        self.servo_ids = servo_ids
        self.baudrate = baudrate
        self._positions = [1450] * len(
            servo_ids
        )
        self._connected = False

    def connect(self):
        self._connected = True
        return True

    def disconnect(self):
        self._connected = False

    def configure_servos(self, acc, speed):
        pass

    def read_positions(self):
        return {"positions": self._positions.copy()}

    def set_goal_positions(self, positions):
        self._positions = [int(p) for p in positions]

    def wait_for_positions(self, positions, threshold, timeout=5.0):
        pass


def setup_oscilloscope():
    global oscilloscope

    _log("=" * 60)
    _log("Initializing oscilloscope... (dummy — no hardware)")
    _log("=" * 60)
    oscilloscope = DummyOscilloscope(motor_controller)
    if not oscilloscope.connect():
        if motor_controller:
            motor_controller.disconnect()
        raise RuntimeError("Failed to connect to oscilloscope")

    oscilloscope.configure(
        memory_depth=12000,
        waveform_mode="NORM",
        waveform_format="WORD",
        time_mode="YT",
        start_acquisition=True,
    )
    _log("\n\nOscilloscope connected and configured (dummy)")


def setup_motor_controller():
    global motor_controller

    _log("=" * 60)
    _log("Initializing motor controller... (dummy — no hardware)")
    _log("=" * 60)
    motor_controller = DummyMotorController(
        device_name=MOTOR_DEVICE,
        servo_ids=SERVO_IDS,
        baudrate=MOTOR_BAUDRATE,
    )
    if not motor_controller.connect():
        if oscilloscope:
            oscilloscope.disconnect()
        raise RuntimeError("Failed to connect to motor controller")

    motor_controller.configure_servos(acc=0, speed=0)
    _log("\n\nMotor controller connected and configured (dummy)")


def disconnect_devices():
    _log("=" * 60)
    _log("Disconnecting devices...")
    _log("=" * 60)
    if oscilloscope:
        oscilloscope.disconnect()
    if motor_controller:
        motor_controller.disconnect()
    _log("\n\nDisconnected from oscilloscope and motor controller (dummy)")


def set_motor_positions(positions):
    if len(positions) != len(SERVO_IDS):
        raise ValueError(
            f"Number of positions ({len(positions)}) must match number of servos ({len(SERVO_IDS)})"
        )

    for i, pos in enumerate(positions):
        if pos < MIN_POSITION or pos > MAX_POSITION:
            return
        positions[i] = int(np.clip(pos, MIN_POSITION, MAX_POSITION))

    motor_controller.set_goal_positions(positions)
    motor_controller.wait_for_positions(positions, THRESHOLD, timeout=5.0)


def get_value():
    time.sleep(WAIT_FOR_OSCILLOSCOPE)
    mean = np.mean(oscilloscope.read_values(channel=OSCILLOSCOPE_CHANNEL)[1])
    value = (mean - VALUE_OFFSET) / VALUE_SCALING_FACTOR

    if value < VALUE_THRESHOLD:
        raise Exception("Beam not detected (try again after checking if the beam is blocked)")
    return value


def blackbox(positions):
    set_motor_positions(positions)
    value = get_value()
    return value


def manual_search(servo_idx, margin, step, is_fine_search=False, verbose=True):
    positions = motor_controller.read_positions()
    manual_best_pos = positions["positions"].copy()
    manual_best_value = -np.inf
    low_position = positions["positions"][servo_idx] - margin
    high_position = positions["positions"][servo_idx] + margin
    no_update_count = 0
    for i, pos in enumerate(range(low_position, high_position, step)):
        test_positions = positions["positions"].copy()
        test_positions[servo_idx] = pos
        set_motor_positions(test_positions)
        value = blackbox(test_positions)
        if verbose:
            _log(
                f"{'fine-' if is_fine_search else ''}manual: {servo_idx} | iter: {i} | position: {pos} | value: {value} | best value: {manual_best_value}"
            )
        if value > manual_best_value:
            manual_best_value = value
            manual_best_pos[servo_idx] = pos
            no_update_count = 0
        else:
            no_update_count += 1
        if not is_fine_search and no_update_count > NO_UPDATE_COUNT_THRESHOLD and manual_best_value > REASONABLE_VALUE_THRESHOLD:
            break
    return blackbox(manual_best_pos)


def one_knob_search(servo_idx, step, verbose=True):
    def get_direction():
        positions = motor_controller.read_positions()
        current_position = positions["positions"].copy()
        current_position[servo_idx] += step
        df_dx = blackbox(current_position)
        current_position[servo_idx] -= 2 * step
        df_dx -= blackbox(current_position)
        df_dx /= 2 * step
        return df_dx / np.linalg.norm(df_dx)

    positions = motor_controller.read_positions()
    one_knob_best_pos = positions["positions"].copy()
    one_knob_best_value = -np.inf
    direction = get_direction()
    no_update_count = 0
    iter = 0
    _log(direction)
    while no_update_count < NO_UPDATE_COUNT_THRESHOLD:
        positions = motor_controller.read_positions()
        test_positions = positions["positions"].copy()
        test_positions[servo_idx] += step * direction
        value = blackbox(test_positions)
        if value > one_knob_best_value:
            one_knob_best_value = value
            one_knob_best_pos[servo_idx] = test_positions[servo_idx]
            no_update_count = 0
        else:
            no_update_count += 1
        if verbose:
            _log(
                f"one-knob: {servo_idx} | iter: {iter} | position: {test_positions[servo_idx]} | value: {value} | best value: {one_knob_best_value}"
            )
        iter += 1
    return blackbox(one_knob_best_pos)


def two_knob_search(
    servo_idx1, servo_idx2, step, direction_update_interval=None, verbose=True
):
    def get_direction():
        beginning_positions = motor_controller.read_positions()
        current_position = beginning_positions["positions"].copy()
        current_position[servo_idx1] += step
        df_dx = blackbox(current_position)
        current_position[servo_idx1] -= 2 * step
        df_dx -= blackbox(current_position)
        df_dx /= 2 * step
        current_position[servo_idx1] += step
        current_position[servo_idx2] += step
        df_dy = blackbox(current_position)
        current_position[servo_idx2] -= 2 * step
        df_dy -= blackbox(current_position)
        df_dy /= 2 * step
        return np.array([df_dx, df_dy]) / np.linalg.norm(np.array([df_dx, df_dy]))

    positions = motor_controller.read_positions()
    two_knob_best_pos = positions["positions"].copy()
    two_knob_best_value = -np.inf
    direction = get_direction()
    no_update_count = 0
    iter = 0
    while no_update_count < NO_UPDATE_COUNT_THRESHOLD:
        positions = motor_controller.read_positions()
        test_positions = positions["positions"].copy()
        test_positions[servo_idx1] += step * direction[0]
        test_positions[servo_idx2] += step * direction[1]
        set_motor_positions(test_positions)
        value = blackbox(test_positions)
        if value > two_knob_best_value:
            two_knob_best_value = value
            two_knob_best_pos[servo_idx1] = test_positions[servo_idx1]
            two_knob_best_pos[servo_idx2] = test_positions[servo_idx2]
            no_update_count = 0
        else:
            no_update_count += 1
        if verbose:
            _log(
                f"two-knob: {servo_idx1}, {servo_idx2} | iter: {iter} | position: {test_positions[servo_idx1]}, {test_positions[servo_idx2]} | value: {value} | best value: {two_knob_best_value}"
            )
        iter += 1
        if direction_update_interval and iter % direction_update_interval == 0:
            direction = get_direction()
    return blackbox(two_knob_best_pos)


def optimization(
    verbose=True,
    *,
    two_knob_step=10,
    two_knob_direction_update_interval=5,
):
    """
    Full optimization pipeline: optional manual sweep, one-knob, two-knob pairs, fine manual.

    ``two_knob_step`` and ``two_knob_direction_update_interval`` apply to the two-knob phase
    (see ``TWO_KNOB_PAIRS`` and ``TWO_KNOB_SEARCH_ITERATIONS``). Other phases use the fixed
    margins and steps in this function (same as ``main.py``).
    """
    tdui = two_knob_direction_update_interval or None
    start_time = time.time()

    if MANUAL_SEARCH_ITERATIONS > 0:
        _log("=" * 60)
        _log("Starting manual search...")
        _log("=" * 60)

        for i in range(MANUAL_SEARCH_ITERATIONS):
            blackbox(motor_controller.read_positions()["positions"])
            for servo_idx in range(len(SERVO_IDS)):
                manual_search(servo_idx, int(500 / (2**i)), 10, verbose=verbose)
        _log("\n\nManual search done")

    if ONE_KNOB_SEARCH_ITERATIONS > 0:
        _log("=" * 60)
        _log("Starting one-knob search...")
        _log("=" * 60)
        for i in range(ONE_KNOB_SEARCH_ITERATIONS):
            for servo_idx in range(len(SERVO_IDS)):
                one_knob_search(servo_idx, 10, verbose=verbose)
        _log("\n\nOne-knob search done")

    if TWO_KNOB_SEARCH_ITERATIONS > 0:
        _log("=" * 60)
        _log("Starting two-knob search...")
        _log("=" * 60)
        for i in range(TWO_KNOB_SEARCH_ITERATIONS):
            current_value = blackbox(motor_controller.read_positions()["positions"])
            max_value = current_value
            for pair in TWO_KNOB_PAIRS:
                max_value = max(
                    max_value,
                    two_knob_search(
                        pair[0],
                        pair[1],
                        two_knob_step,
                        direction_update_interval=tdui,
                        verbose=verbose,
                    ),
                )
            if max_value < current_value * 1.03:
                _log("\n\nEarly stopping condition met")
                break
        _log("\n\nTwo-knob search done")

    if FINE_MANUAL_SEARCH_ITERATIONS > 0:
        _log("=" * 60)
        _log("Starting fine-manual search...")
        _log("=" * 60)
        for i in range(FINE_MANUAL_SEARCH_ITERATIONS):
            current_value = blackbox(motor_controller.read_positions()["positions"])
            max_value = current_value
            for servo_idx in range(len(SERVO_IDS)):
                max_value = max(
                    max_value,
                    manual_search(
                        servo_idx, 40, 2, is_fine_search=True, verbose=verbose
                    ),
                )
            if max_value < current_value * 1.01:
                _log("\n\nEarly stopping condition met")
                break
        _log("\n\nFine-manual search done")

    duration = time.time() - start_time
    final = float("nan")
    if motor_controller is not None and oscilloscope is not None:
        try:
            pos = motor_controller.read_positions()["positions"]
            final = blackbox(pos)
        except Exception:
            pass
    return duration, final


def main():
    global oscilloscope, motor_controller

    # Motor must exist before oscilloscope dummy reads positions from it
    setup_motor_controller()
    setup_oscilloscope()

    duration, final_merit = optimization(verbose=True)

    _merit_s = f"{final_merit:.6f}" if final_merit == final_merit else "n/a"
    _log(f"\n\nDuration: {duration:.2f} s | final merit: {_merit_s}")

    disconnect_devices()

    _log("=" * 60)
    _log("Done (dummy)")
    _log("=" * 60)


if __name__ == "__main__":
    main()
