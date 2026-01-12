import numpy as np
from skopt import Optimizer
from skopt.space import Real
from oscilloscope_reader import OscilloscopeReader
from motor_control import MotorController
import time

# Configuration
# Motor
MOTOR_DEVICE = "COM3"
MOTOR_BAUDRATE = 1000000
SERVO1_ID = 30
SERVO2_ID = 31
MIN_POSITION = 500
MAX_POSITION = 3500
POSITION_THRESHOLD = 20

# Oscilloscope
OSCILLOSCOPE_CHANNEL = None
WAIT_FOR_OSCILLOSCOPE_SETTLE = 0.1  # Seconds
OSCILLOSCOPE_SCALING_OFFSET = 8000000
OSCILLOSCOPE_SCALING_FACTOR = 10000000

# Optimization
MANUAL_SEARCH_ITERATIONS = 3
OPTIMIZATION_ITERATIONS = 60
OPTIMIZATION_INITIAL_POINTS = 10

# Global instances (initialized in main)
oscilloscope = None
motor_controller = None


def blackbox(pos1, pos2):
    """
    Black-box function that:
    1. Sets motor positions
    2. Waits for motors to settle
    3. Reads most recent oscilloscope data
    4. Calculates signal quality metric (peak-to-peak amplitude)

    Args:
        pos1 (float): Motor 1 position (will be converted to int)
        pos2 (float): Motor 2 position (will be converted to int)

    Returns:
        float: Signal quality metric (peak-to-peak amplitude) to maximize
    """
    set_motor_positions(pos1, pos2)
    mean = get_mean_oscilloscope_value(OSCILLOSCOPE_CHANNEL)

    return (mean - OSCILLOSCOPE_SCALING_OFFSET) / OSCILLOSCOPE_SCALING_FACTOR


def set_motor_positions(pos1, pos2, threshold):
    """
    Set and wait for motor positions.
    Args:
        motor_controller: MotorController instance
        pos1: Motor 1 position
        pos2: Motor 2 position
        threshold: Position threshold for the motor controller
    """
    if (
        pos1 < MIN_POSITION
        or pos1 > MAX_POSITION
        or pos2 < MIN_POSITION
        or pos2 > MAX_POSITION
    ):
        return
    pos1 = int(np.clip(pos1, MIN_POSITION, MAX_POSITION))
    pos2 = int(np.clip(pos2, MIN_POSITION, MAX_POSITION))

    motor_controller.set_goal_positions(pos1, pos2)
    motor_controller.wait_for_positions(pos1, pos2, threshold=threshold, timeout=5.0)


def get_mean_oscilloscope_value(channel, wait_for_oscilloscope_settle):
    """
    Get the mean of the last 10 oscilloscope values.
    Args:
        channel: Oscilloscope channel
    Returns:
        float: Mean of the last 10 oscilloscope values
    """
    time.sleep(wait_for_oscilloscope_settle)
    while True:
        data = oscilloscope.read_values(channel=channel)
        if len(data[1]) >= 10:
            y_values = data[1][-10:]
            mean = np.mean(y_values)
            return mean
        time.sleep(0.01)


def optimization(
    position_threshold,
    wait_for_oscilloscope_settle,
    manual_search_iterations,
    optimization_iterations,
    optimization_initial_points,
):
    """
    Optimize the motor positions using a manual search and an optimization algorithm.
    Args:
        oscilloscope: OscilloscopeReader instance
        motor_controller: MotorController instance
        wait_for_oscilloscope_settle: Time to wait for the oscilloscope to settle
        manual_search_iterations: Number of iterations for the manual search
        optimization_iterations: Number of iterations for the optimization
        optimization_initial_points: Number of initial points for the optimization
        position_threshold: Position threshold for the motor controller
    """
    # Manual search
    manual_best_pos, manual_best_y = None, -np.inf

    print("Starting manual search...")
    print("=" * 60)
    try:
        for i in range(manual_search_iterations):
            positions = motor_controller.read_positions()
            manual_best_pos = [
                positions["servo1"]["position"],
                positions["servo2"]["position"],
            ]
            low_position_1 = manual_best_pos[0] - 500 // (i + 1)
            high_position_1 = manual_best_pos[0] + 500 // (i + 1)
            low_position_2 = manual_best_pos[1] - 500 // (i + 1)
            high_position_2 = manual_best_pos[1] + 500 // (i + 1)
            print(
                f"iter {i+1:02d} | pos1={manual_best_pos[0]:4d}, pos2={manual_best_pos[1]:4d}"
            )

            for pos1 in range(low_position_1, high_position_1, 10):
                set_motor_positions(pos1, manual_best_pos[1], position_threshold)
                mean = get_mean_oscilloscope_value(
                    OSCILLOSCOPE_CHANNEL, wait_for_oscilloscope_settle
                )
                if mean > manual_best_y:
                    manual_best_y = mean
                    manual_best_pos[0] = pos1

            for pos2 in range(low_position_2, high_position_2, 10):
                set_motor_positions(manual_best_pos[0], pos2, position_threshold)
                mean = get_mean_oscilloscope_value(
                    OSCILLOSCOPE_CHANNEL, wait_for_oscilloscope_settle
                )
                if mean > manual_best_y:
                    manual_best_y = mean
                    manual_best_pos[1] = pos2

            set_motor_positions(
                manual_best_pos[0], manual_best_pos[1], position_threshold
            )

    except KeyboardInterrupt:
        print("\n\nManual search interrupted by user")

    except Exception as e:
        print(f"\n\nError during manual search: {e}")
        import traceback

        traceback.print_exc()

    # Optimization
    positions = motor_controller.read_positions()
    low_position_1 = positions["servo1"]["position"] - 50
    high_position_1 = positions["servo1"]["position"] + 50
    low_position_2 = positions["servo2"]["position"] - 50
    high_position_2 = positions["servo2"]["position"] + 50

    space = [
        Real(low_position_1, high_position_1, name="motor_pos1"),
        Real(low_position_2, high_position_2, name="motor_pos2"),
    ]

    opt = Optimizer(
        dimensions=space,
        base_estimator="GP",
        acq_func="EI",
        n_initial_points=optimization_initial_points,
        random_state=0,
    )

    best_pos, best_y = None, -np.inf

    print("\nStarting optimization...")
    print("=" * 60)

    try:
        for t in range(optimization_iterations):
            x = opt.ask()
            y = blackbox(x[0], x[1])
            opt.tell(x, -y)

            if y > best_y:
                best_pos, best_y = x, y

            print(
                f"iter {t+1:02d} | pos1={int(x[0]):4d}, pos2={int(x[1]):4d} | "
                f"metric={y:.6f} | best={best_y:.6f}"
            )

        print("\n" + "=" * 60)
        print("Optimization complete!")
        print("\nBest found:")
        print(f"Motor Position 1: {int(best_pos[0])}")
        print(f"Motor Position 2: {int(best_pos[1])}")
        print(f"Best Metric (Mean): {best_y:.6f}")

        # Move motor to best position
        set_motor_positions(best_pos[0], best_pos[1])

    except KeyboardInterrupt:
        print("\n\nOptimization interrupted by user")

    except Exception as e:
        print(f"\n\nError during optimization: {e}")
        import traceback

        traceback.print_exc()


def main():
    global oscilloscope, motor_controller
    # Initialize oscilloscope
    print("Initializing oscilloscope...")
    oscilloscope = OscilloscopeReader()
    if not oscilloscope.connect():
        print("Failed to connect to oscilloscope")
        return

    # Configure oscilloscope
    oscilloscope.configure(
        memory_depth=12000,
        waveform_mode="NORM",
        waveform_format="WORD",
        time_mode="ROLL",
        start_acquisition=True,
    )
    print("Oscilloscope connected and configured")

    # Initialize motor controller
    print("Initializing motor controller...")
    motor_controller = MotorController(
        device_name=MOTOR_DEVICE,
        baudrate=MOTOR_BAUDRATE,
        servo1_id=SERVO1_ID,
        servo2_id=SERVO2_ID,
    )
    if not motor_controller.connect():
        print("Failed to connect to motor controller")
        oscilloscope.disconnect()
        return

    # Configure servos
    motor_controller.configure_servos(acc=0, speed=0)
    print("Motor controller connected and configured")

    optimization(
        POSITION_THRESHOLD,
        WAIT_FOR_OSCILLOSCOPE_SETTLE,
        MANUAL_SEARCH_ITERATIONS,
        OPTIMIZATION_ITERATIONS,
        OPTIMIZATION_INITIAL_POINTS,
    )

    # Disconnect devices
    print("\nDisconnecting devices...")
    motor_controller.disconnect()
    oscilloscope.disconnect()
    print("Done")


if __name__ == "__main__":
    main()
