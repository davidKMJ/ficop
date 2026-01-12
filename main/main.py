import numpy as np
from skopt import Optimizer
from skopt.space import Real
from sklearn.model_selection import ParameterGrid
from oscilloscope_reader import OscilloscopeReader
from motor_control import MotorController
import time
import csv
import pandas as pd

# Configuration
# Motor
MOTOR_DEVICE = "COM3"
MOTOR_BAUDRATE = 1000000
SERVO1_ID = 30
SERVO2_ID = 31
SERVO3_ID = 80
SERVO4_ID = 81
MIN_POSITION = 500
MAX_POSITION = 3500

# Oscilloscope
OSCILLOSCOPE_CHANNEL = None
OSCILLOSCOPE_SCALING_OFFSET = 8000000
OSCILLOSCOPE_SCALING_FACTOR = 10000000

# Global instances (initialized in main)
oscilloscope = None
motor_controller = None


def blackbox(pos1, pos2, pos3, pos4, position_threshold, wait_for_oscilloscope_settle):
    """
    Black-box function that:
    1. Sets motor positions
    2. Waits for motors to settle
    3. Reads most recent oscilloscope data
    4. Calculates signal quality metric (peak-to-peak amplitude)

    Args:
        pos1 (float): Motor 1 position (will be converted to int)
        pos2 (float): Motor 2 position (will be converted to int)
        pos3 (float): Motor 3 position (will be converted to int)
        pos4 (float): Motor 4 position (will be converted to int)
        position_threshold: Position threshold for the motor controller
        wait_for_oscilloscope_settle: Time to wait for the oscilloscope to settle

    Returns:
        float: Signal quality metric (peak-to-peak amplitude) to maximize
    """
    set_motor_positions(pos1, pos2, pos3, pos4, position_threshold)
    mean = get_mean_oscilloscope_value(
        OSCILLOSCOPE_CHANNEL, wait_for_oscilloscope_settle
    )

    return (mean - OSCILLOSCOPE_SCALING_OFFSET) / OSCILLOSCOPE_SCALING_FACTOR


def set_motor_positions(pos1, pos2, pos3, pos4, threshold):
    """
    Set and wait for motor positions.
    Args:
        motor_controller: MotorController instance
        pos1: Motor 1 position
        pos2: Motor 2 position
        pos3: Motor 3 position
        pos4: Motor 4 position
        threshold: Position threshold for the motor controller
    """
    if (
        pos1 < MIN_POSITION
        or pos1 > MAX_POSITION
        or pos2 < MIN_POSITION
        or pos2 > MAX_POSITION
        or pos3 < MIN_POSITION
        or pos3 > MAX_POSITION
        or pos4 < MIN_POSITION
        or pos4 > MAX_POSITION
    ):
        return
    pos1 = int(np.clip(pos1, MIN_POSITION, MAX_POSITION))
    pos2 = int(np.clip(pos2, MIN_POSITION, MAX_POSITION))
    pos3 = int(np.clip(pos3, MIN_POSITION, MAX_POSITION))
    pos4 = int(np.clip(pos4, MIN_POSITION, MAX_POSITION))

    motor_controller.set_goal_positions(pos1, pos2, pos3, pos4)
    motor_controller.wait_for_positions(
        pos1, pos2, pos3, pos4, threshold=threshold, timeout=5.0
    )


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
        if len(data[1]) >= 3:
            y_values = data[1][-3:]
            mean = np.mean(y_values)
            return mean
        time.sleep(0.01)


def optimization(
    position_threshold,
    wait_for_oscilloscope_settle,
    manual_search_iterations,
    optimization_iterations,
    optimization_initial_points,
    verbose=True,
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
    # Record time
    start_time = time.time()
    # Manual search
    manual_best_pos, manual_best_y = None, -np.inf

    if verbose:
        print("Starting manual search...")
        print("=" * 60)
    try:
        for i in range(manual_search_iterations):
            positions = motor_controller.read_positions()
            manual_best_pos = [
                positions["servo1"]["position"],
                positions["servo2"]["position"],
                positions["servo3"]["position"],
                positions["servo4"]["position"],
            ]
            low_position_1 = manual_best_pos[0] - int(500 / (1.8**i))
            high_position_1 = manual_best_pos[0] + int(500 / (1.8**i))
            low_position_2 = manual_best_pos[1] - int(500 / (1.8**i))
            high_position_2 = manual_best_pos[1] + int(500 / (1.8**i))
            low_position_3 = manual_best_pos[2] - int(500 / (1.8**i))
            high_position_3 = manual_best_pos[2] + int(500 / (1.8**i))
            low_position_4 = manual_best_pos[3] - int(500 / (1.8**i))
            high_position_4 = manual_best_pos[3] + int(500 / (1.8**i))
            if verbose:
                print(
                    f"iter {i+1:02d} | pos1={manual_best_pos[0]:4d}, pos2={manual_best_pos[1]:4d}, pos3={manual_best_pos[2]:4d}, pos4={manual_best_pos[3]:4d}"
                )

            for pos1 in range(low_position_1, high_position_1, max(1, 10//(i+1))):
                set_motor_positions(
                    pos1,
                    manual_best_pos[1],
                    manual_best_pos[2],
                    manual_best_pos[3],
                    position_threshold,
                )
                mean = get_mean_oscilloscope_value(
                    OSCILLOSCOPE_CHANNEL, wait_for_oscilloscope_settle
                )
                if mean > manual_best_y:
                    manual_best_y = mean
                    manual_best_pos[0] = pos1

            for pos2 in range(low_position_2, high_position_2, max(1, 10//(i+1))):
                set_motor_positions(
                    manual_best_pos[0],
                    pos2,
                    manual_best_pos[2],
                    manual_best_pos[3],
                    position_threshold,
                )
                mean = get_mean_oscilloscope_value(
                    OSCILLOSCOPE_CHANNEL, wait_for_oscilloscope_settle
                )
                if mean > manual_best_y:
                    manual_best_y = mean
                    manual_best_pos[1] = pos2

            for pos3 in range(low_position_3, high_position_3, max(1, 10//(i+1))):
                set_motor_positions(
                    manual_best_pos[0],
                    manual_best_pos[1],
                    pos3,
                    manual_best_pos[3],
                    position_threshold,
                )
                mean = get_mean_oscilloscope_value(
                    OSCILLOSCOPE_CHANNEL, wait_for_oscilloscope_settle
                )
                if mean > manual_best_y:
                    manual_best_y = mean
                    manual_best_pos[2] = pos3

            for pos4 in range(low_position_4, high_position_4, max(1, 10//(i+1))):
                set_motor_positions(
                    manual_best_pos[0],
                    manual_best_pos[1],
                    manual_best_pos[2],
                    pos4,
                    position_threshold,
                )
                mean = get_mean_oscilloscope_value(
                    OSCILLOSCOPE_CHANNEL, wait_for_oscilloscope_settle
                )
                if mean > manual_best_y:
                    manual_best_y = mean
                    manual_best_pos[3] = pos4

            set_motor_positions(
                manual_best_pos[0],
                manual_best_pos[1],
                manual_best_pos[2],
                manual_best_pos[3],
                position_threshold,
            )

    except KeyboardInterrupt:
        if verbose:
            print("\n\nManual search interrupted by user")
        else:
            print("\n\nInterrupted by user")

    except Exception as e:
        if verbose:
            print(f"\n\nError during manual search: {e}")
        else:
            print(f"\n\nError: {e}")
        import traceback

        traceback.print_exc()

    # Optimization
    positions = motor_controller.read_positions()
    low_position_1 = positions["servo1"]["position"] - 5
    high_position_1 = positions["servo1"]["position"] + 5
    low_position_2 = positions["servo2"]["position"] - 5
    high_position_2 = positions["servo2"]["position"] + 5
    low_position_3 = positions["servo3"]["position"] - 5
    high_position_3 = positions["servo3"]["position"] + 5
    low_position_4 = positions["servo4"]["position"] - 5
    high_position_4 = positions["servo4"]["position"] + 5

    space = [
        Real(low_position_1, high_position_1, name="motor_pos1"),
        Real(low_position_2, high_position_2, name="motor_pos2"),
        Real(low_position_3, high_position_3, name="motor_pos3"),
        Real(low_position_4, high_position_4, name="motor_pos4"),
    ]

    opt = Optimizer(
        dimensions=space,
        base_estimator="GP",
        acq_func="PI",
        n_initial_points=optimization_initial_points,
        random_state=0,
    )

    best_pos, best_y = None, -np.inf

    if verbose:
        print("\nStarting optimization...")
        print("=" * 60)

    try:
        for t in range(optimization_iterations):
            x = opt.ask()
            y = blackbox(
                x[0], x[1], x[2], x[3], 1, wait_for_oscilloscope_settle
            )
            opt.tell(x, -y)

            if y > best_y:
                best_pos, best_y = x, y

            if verbose:
                print(
                    f"iter {t+1:02d} | pos1={int(x[0]):4d}, pos2={int(x[1]):4d}, pos3={int(x[2]):4d}, pos4={int(x[3]):4d} | "
                    f"metric={y:.6f} | best={best_y:.6f}"
                )

        if verbose:
            print("\n" + "=" * 60)
            print("Optimization complete!")
            print("\nBest found:")
            print(f"Motor Position 1: {int(best_pos[0])}")
            print(f"Motor Position 2: {int(best_pos[1])}")
            print(f"Motor Position 3: {int(best_pos[2])}")
            print(f"Motor Position 4: {int(best_pos[3])}")
            print(f"Best Metric (Mean): {best_y:.6f}")

        # Move motor to best position
        set_motor_positions(
            best_pos[0], best_pos[1], best_pos[2], best_pos[3], 1
        )
        end_time = time.time()
        return best_y, end_time - start_time

    except KeyboardInterrupt:
        if verbose:
            print("\n\nOptimization interrupted by user")
        else:
            print("\n\nInterrupted by user")

    except Exception as e:
        if verbose:
            print(f"\n\nError during optimization: {e}")
        else:
            print(f"\n\nError: {e}")
        import traceback

        traceback.print_exc()


def main():
    global oscilloscope, motor_controller
    # position_threshold_space = list(np.arange(1, 10, 3))
    # wait_for_oscilloscope_settle_space = list(np.arange(0.01, 0.15, 0.05))
    # manual_search_iterations_space = list(np.arange(3, 6, 2))
    # optimization_iterations_space = list(np.arange(40, 100, 20))
    # optimization_initial_points_space = list(np.arange(5, 20, 5))
    position_threshold_space = [2]
    wait_for_oscilloscope_settle_space = [0.05]
    manual_search_iterations_space = [5]
    optimization_iterations_space = [100]
    optimization_initial_points_space = [20]
    parameter_grid = ParameterGrid(
        {
            "position_threshold": position_threshold_space,
            "wait_for_oscilloscope_settle": wait_for_oscilloscope_settle_space,
            "manual_search_iterations": manual_search_iterations_space,
            "optimization_iterations": optimization_iterations_space,
            "optimization_initial_points": optimization_initial_points_space,
        }
    )

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
        servo3_id=SERVO3_ID,
        servo4_id=SERVO4_ID,
    )
    if not motor_controller.connect():
        print("Failed to connect to motor controller")
        oscilloscope.disconnect()
        return

    # Configure servos
    motor_controller.configure_servos(acc=0, speed=0)
    print("Motor controller connected and configured")

    for params in parameter_grid:
        set_motor_positions(1500, 2800, 2000, 1800, params["position_threshold"])
        best_y, duration = optimization(
            params["position_threshold"],
            params["wait_for_oscilloscope_settle"],
            params["manual_search_iterations"],
            params["optimization_iterations"],
            params["optimization_initial_points"],
        )

    print(f"Duration: {duration:.2f} seconds")

    # Disconnect devices
    print("\nDisconnecting devices...")
    motor_controller.disconnect()
    oscilloscope.disconnect()
    print("Done")


if __name__ == "__main__":
    main()
