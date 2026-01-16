import numpy as np
from oscilloscope_reader import OscilloscopeReader
from motor_control import MotorController
import time

# Configuration
# Motor
MOTOR_DEVICE = "COM4"
MOTOR_BAUDRATE = 1000000
SERVO_IDS = [30, 31, 80, 81]
MIN_POSITION = 500
MAX_POSITION = 3500
THRESHOLD = 2  # Threshold for the motor controller

# Oscilloscope
OSCILLOSCOPE_CHANNEL = None
WAIT_FOR_OSCILLOSCOPE = 0.1  # Seconds

# Value scaling
VALUE_OFFSET = 8000000
VALUE_SCALING_FACTOR = 10000000
VALUE_THRESHOLD = 0.032

# Optimization
NO_UPDATE_COUNT_THRESHOLD = 3
REASONABLE_VALUE_THRESHOLD = 0.035
MANUAL_SEARCH_ITERATIONS = int(input("MANUAL_SEARCH_ITERATIONS: "))
ONE_KNOB_SEARCH_ITERATIONS = 0
TWO_KNOB_SEARCH_ITERATIONS = int(input("TWO_KNOB_SEARCH_ITERATIONS: "))
FINE_MANUAL_SEARCH_ITERATIONS = int(input("FINE_MANUAL_SEARCH_ITERATIONS: "))

# Global instances (initialized in main)
oscilloscope = None
motor_controller = None


def setup_oscilloscope():
    """
    Initialize the oscilloscope.
    """
    global oscilloscope

    print("=" * 60)
    print("Initializing oscilloscope...")
    print("=" * 60)
    oscilloscope = OscilloscopeReader()
    if not oscilloscope.connect():
        if motor_controller:
            motor_controller.disconnect()
        raise RuntimeError("Failed to connect to oscilloscope")

    # Configure oscilloscope
    oscilloscope.configure(
        memory_depth=12000,
        waveform_mode="NORM",
        waveform_format="WORD",
        time_mode="YT",
        start_acquisition=True,
    )
    print("\n\nOscilloscope connected and configured")


def setup_motor_controller():
    """
    Initialize the motor controller.
    """
    global motor_controller

    print("=" * 60)
    print("Initializing motor controller...")
    print("=" * 60)
    motor_controller = MotorController(
        device_name=MOTOR_DEVICE,
        servo_ids=SERVO_IDS,
        baudrate=MOTOR_BAUDRATE,
    )
    if not motor_controller.connect():
        if oscilloscope:
            oscilloscope.disconnect()
        raise RuntimeError("Failed to connect to motor controller")

    # Configure servos
    motor_controller.configure_servos(acc=0, speed=0)
    print("\n\nMotor controller connected and configured")


def disconnect_devices():
    """
    Disconnect the oscilloscope and motor controller.
    """
    print("=" * 60)
    print("Disconnecting devices...")
    print("=" * 60)
    if oscilloscope:
        oscilloscope.disconnect()
    if motor_controller:
        motor_controller.disconnect()
    print("\n\nDisconnected from oscilloscope and motor controller")


def set_motor_positions(positions):
    """
    Set and wait for motor positions.
    Args:
        positions: List of motor positions
        threshold: Position threshold for the motor controller
    """
    if len(positions) != len(SERVO_IDS):
        raise ValueError(
            f"Number of positions ({len(positions)}) must match number of servos ({len(SERVO_IDS)})"
        )

    # Check and clip positions
    for i, pos in enumerate(positions):
        if pos < MIN_POSITION or pos > MAX_POSITION:
            return
        positions[i] = int(np.clip(pos, MIN_POSITION, MAX_POSITION))

    motor_controller.set_goal_positions(positions)
    motor_controller.wait_for_positions(positions, THRESHOLD, timeout=5.0)


def get_value():
    """
    Get the scaled value of the mean of the oscilloscope values.
    Returns:
        float: Value
    """
    time.sleep(WAIT_FOR_OSCILLOSCOPE)
    mean = np.mean(oscilloscope.read_values(channel=OSCILLOSCOPE_CHANNEL)[1])
    value = (mean - VALUE_OFFSET) / VALUE_SCALING_FACTOR

    if value < VALUE_THRESHOLD:
        raise Exception("Beam not detected (try again after checking if the beam is blocked)")
    return value

def blackbox(positions):
    """
    Black-box function that:
    1. Sets motor positions
    2. Gets the value

    Args:
        positions (list): List of motor positions (will be converted to int)

    Returns:
        float: Value to maximize
    """
    set_motor_positions(positions)
    value = get_value()

    return value


def manual_search(servo_idx, margin, step, is_fine_search=False, verbose=True):
    """
    Manual search for the motor positions.
    Args:
        servo_idx: Index of the servo to search
        margin: Margin for the search
        step: Step size for the search
        verbose: Whether to print verbose output
    """
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
            print(
                f"{'fine-' if is_fine_search else ''}manual: {servo_idx} | iter: {i} | position: {pos} | value: {value} | best value: {manual_best_value}"
            )
        if value > manual_best_value:
            manual_best_value = value
            manual_best_pos[servo_idx] = pos
        else:
            no_update_count += 1
        if not is_fine_search and no_update_count > NO_UPDATE_COUNT_THRESHOLD and manual_best_value > REASONABLE_VALUE_THRESHOLD:
            break
    return blackbox(manual_best_pos)


def one_knob_search(servo_idx, step, verbose=True):
    """
    One-knob search for the motor positions.
    Args:
        servo_idx: Index of the servo to search
        step: Step size for the search
        verbose: Whether to print verbose output
    """

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
    print(direction)
    while no_update_count < NO_UPDATE_COUNT_THRESHOLD:
        positions = motor_controller.read_positions()
        test_positions = positions["positions"].copy()
        test_positions[servo_idx] += step * direction
        value = blackbox(test_positions)
        if value > one_knob_best_value:
            one_knob_best_value = value
            one_knob_best_pos[servo_idx] = test_positions[servo_idx]
        else:
            no_update_count += 1
        if verbose:
            print(
                f"one-knob: {servo_idx} | iter: {iter} | position: {test_positions[servo_idx]} | value: {value} | best value: {one_knob_best_value}"
            )
        iter += 1
    return blackbox(one_knob_best_pos)


def two_knob_search(
    servo_idx1, servo_idx2, step, direction_update_interval=None, verbose=True
):
    """
    Two-knob search for the motor positions.
    Args:
        servo_idx1: Index of the first servo to search
        servo_idx2: Index of the second servo to search
        step: Step size for the search
        verbose: Whether to print verbose output
    """

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
        else:
            no_update_count += 1
        if verbose:
            print(
                f"two-knob: {servo_idx1}, {servo_idx2} | iter: {iter} | position: {test_positions[servo_idx1]}, {test_positions[servo_idx2]} | value: {value} | best value: {two_knob_best_value}"
            )
        iter += 1
        if direction_update_interval and iter % direction_update_interval == 0:
            direction = get_direction()
    return blackbox(two_knob_best_pos)


def optimization(verbose=True):
    """
    Optimize the motor positions.
    Args:
        verbose: Whether to print verbose output
    """
    start_time = time.time()

    # Manual search
    if MANUAL_SEARCH_ITERATIONS > 0:
        print("=" * 60)
        print("Starting manual search...")
        print("=" * 60)

        for i in range(MANUAL_SEARCH_ITERATIONS):
            blackbox(motor_controller.read_positions()["positions"])
            for servo_idx in range(len(SERVO_IDS)):
                manual_search(servo_idx, int(500 / (2**i)), 10, verbose=verbose)
        print("\n\nManual search done")

    # One-knob search
    if ONE_KNOB_SEARCH_ITERATIONS > 0:
        print("=" * 60)
        print("Starting one-knob search...")
        print("=" * 60)
        for i in range(ONE_KNOB_SEARCH_ITERATIONS):
            for servo_idx in range(len(SERVO_IDS)):
                one_knob_search(servo_idx, 10, verbose=verbose)
        print("\n\nOne-knob search done")

    # Two-knob search
    if TWO_KNOB_SEARCH_ITERATIONS > 0:
        print("=" * 60)
        print("Starting two-knob search...")
        print("=" * 60)
        two_knob_pairs = [(0, 3), (1, 2)]
        for i in range(TWO_KNOB_SEARCH_ITERATIONS):
            current_value = blackbox(motor_controller.read_positions()["positions"])
            max_value = current_value
            for pair in two_knob_pairs:
                max_value = max(
                    max_value,
                    two_knob_search(
                        pair[0],
                        pair[1],
                        10,
                        direction_update_interval=5,
                        verbose=verbose,
                    ),
                )
            if max_value < current_value * 1.03:
                print("\n\nEarly stopping condition met")
                break
        print("\n\nTwo-knob search done")

    # Fine-Manual search
    if FINE_MANUAL_SEARCH_ITERATIONS > 0:
        print("=" * 60)
        print("Starting fine-manual search...")
        print("=" * 60)
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
                print("\n\nEarly stopping condition met")
                break
        print("\n\nFine-manual search done")

        duration = time.time() - start_time
        return duration


def main():
    global oscilloscope, motor_controller

    setup_oscilloscope()
    setup_motor_controller()

    duration = optimization(verbose=True)

    print(f"\n\nDuration: {duration:.2f} seconds")

    # Disconnect devices
    disconnect_devices()

    print("=" * 60)
    print("Done")
    print("=" * 60)


if __name__ == "__main__":
    main()
