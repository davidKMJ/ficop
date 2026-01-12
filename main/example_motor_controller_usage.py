#
# Example usage of MotorController class
#

from motor_control import MotorController

# Configuration
DEVICENAME = "COM4"  # Change to your port
BAUDRATE = 1000000
SERVO1_ID = 30
SERVO2_ID = 31
SERVO3_ID = 80
SERVO4_ID = 81

# Position limits
MIN_POSITION = 100
MAX_POSITION = 4000


def main():
    # Create motor controller instance
    controller = MotorController(
        device_name=DEVICENAME,
        baudrate=BAUDRATE,
        servo1_id=SERVO1_ID,
        servo2_id=SERVO2_ID,
        servo3_id=SERVO3_ID,
        servo4_id=SERVO4_ID,
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
        controller.set_goal_positions(MAX_POSITION, MIN_POSITION, MAX_POSITION, MIN_POSITION)

        # Read positions
        positions = controller.read_positions()
        print(
            f"Servo 1 - Position: {positions['servo1']['position']}, Speed: {positions['servo1']['speed']}"
        )
        print(
            f"Servo 2 - Position: {positions['servo2']['position']}, Speed: {positions['servo2']['speed']}"
        )
        print(
            f"Servo 3 - Position: {positions['servo3']['position']}, Speed: {positions['servo3']['speed']}"
        )
        print(
            f"Servo 4 - Position: {positions['servo4']['position']}, Speed: {positions['servo4']['speed']}"
        )

        # Example 2: Wait for servos to reach goal positions
        print("\n--- Example 2: Waiting for servos to reach goal ---")
        controller.set_goal_positions(MAX_POSITION, MIN_POSITION, MAX_POSITION, MIN_POSITION)
        if controller.wait_for_positions(MAX_POSITION, MIN_POSITION, MAX_POSITION, MIN_POSITION, threshold=20):
            print("All servos reached their goal positions!")
        else:
            print("Timeout waiting for servos to reach goal positions")

        # Example 3: Read positions multiple times
        print("\n--- Example 3: Reading positions multiple times ---")
        for i in range(5):
            positions = controller.read_positions()
            print(
                f"Read {i+1}: Servo1={positions['servo1']['position']}, Servo2={positions['servo2']['position']}, "
                f"Servo3={positions['servo3']['position']}, Servo4={positions['servo4']['position']}"
            )

        # Example 4: Individual servo control
        print("\n--- Example 4: Individual servo configuration ---")
        controller.set_acceleration(SERVO1_ID, 0)
        controller.set_speed(SERVO1_ID, 0)
        controller.set_acceleration(SERVO2_ID, 0)
        controller.set_speed(SERVO2_ID, 0)
        controller.set_acceleration(SERVO3_ID, 0)
        controller.set_speed(SERVO3_ID, 0)
        controller.set_acceleration(SERVO4_ID, 0)
        controller.set_speed(SERVO4_ID, 0)

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
        with MotorController(DEVICENAME, BAUDRATE, SERVO1_ID, SERVO2_ID, SERVO3_ID, SERVO4_ID) as controller:
            # Configure servos
            controller.configure_servos(acc=0, speed=0)

            # Set and wait for positions
            controller.set_goal_positions(MIN_POSITION, MIN_POSITION, MIN_POSITION, MIN_POSITION)
            controller.wait_for_positions(MIN_POSITION, MIN_POSITION, MIN_POSITION, MIN_POSITION)

            # Read final positions
            positions = controller.read_positions()
            print(
                f"Final positions - Servo1: {positions['servo1']['position']}, Servo2: {positions['servo2']['position']}, "
                f"Servo3: {positions['servo3']['position']}, Servo4: {positions['servo4']['position']}"
            )

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    # Run main example
    main()

    # Uncomment to run context manager example
    # example_with_context_manager()
