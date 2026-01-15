#
# Example usage of MotorController class
#

from motor_control import MotorController

# Configuration
DEVICENAME = "COM4"  # Change to your port
BAUDRATE = 1000000
SERVO_IDS = [30, 31, 80, 81]  # List of servo IDs: [servo1, servo2, servo3, servo4]

# Position limits
MIN_POSITION = 100
MAX_POSITION = 4000


def main():
    # Create motor controller instance
    controller = MotorController(
        device_name=DEVICENAME,
        servo_ids=SERVO_IDS,
        baudrate=BAUDRATE,
    )

    try:
        # Connect to the motors
        if not controller.connect():
            print("Failed to connect to motors")
            return

        # Configure servos (acceleration and speed)
        print("Configuring servos...")
        controller.configure_servos(acc=0, speed=0)

        # Example 1: Set goal positions and read current positions
        print("\n--- Example 1: Setting goal positions ---")
        goal_positions = [MAX_POSITION, MIN_POSITION, MAX_POSITION, MIN_POSITION]
        controller.set_goal_positions(goal_positions)

        # Read positions
        positions = controller.read_positions()
        for idx, servo_id in enumerate(SERVO_IDS):
            servo_key = f"servo{idx+1}"
            print(
                f"Servo {idx+1} (ID:{servo_id:03d}) - Position: {positions[servo_key]['position']}, Speed: {positions[servo_key]['speed']}"
            )

        # Example 2: Wait for servos to reach goal positions
        print("\n--- Example 2: Waiting for servos to reach goal ---")
        controller.set_goal_positions(goal_positions)
        if controller.wait_for_positions(goal_positions, threshold=20):
            print("All servos reached their goal positions!")
        else:
            print("Timeout waiting for servos to reach goal positions")

        # Example 3: Read positions multiple times
        print("\n--- Example 3: Reading positions multiple times ---")
        for i in range(5):
            positions = controller.read_positions()
            pos_list = positions["positions"]
            pos_str = ", ".join([f"Servo{j+1}={pos_list[j]}" for j in range(len(pos_list))])
            print(f"Read {i+1}: {pos_str}")

        # Example 4: Individual servo control
        print("\n--- Example 4: Individual servo configuration ---")
        for servo_id in SERVO_IDS:
            controller.set_acceleration(servo_id, 0)
            controller.set_speed(servo_id, 0)

    except Exception as e:
        print(f"Error: {e}")

    finally:
        # Disconnect (this will also disable torque)
        controller.disconnect()


def example_with_context_manager():
    """
    Example using the context manager (with statement).
    This automatically handles connection and disconnection.
    """
    print("\n--- Example with context manager ---")

    try:
        with MotorController(DEVICENAME, SERVO_IDS, BAUDRATE) as controller:
            # Configure servos
            controller.configure_servos(acc=0, speed=0)

            # Set and wait for positions
            goal_positions = [MIN_POSITION] * len(SERVO_IDS)
            controller.set_goal_positions(goal_positions)
            controller.wait_for_positions(goal_positions)

            # Read final positions
            positions = controller.read_positions()
            pos_list = positions["positions"]
            pos_str = ", ".join([f"Servo{j+1}: {pos_list[j]}" for j in range(len(pos_list))])
            print(f"Final positions - {pos_str}")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    # Run main example
    main()

    # Uncomment to run context manager example
    # example_with_context_manager()
