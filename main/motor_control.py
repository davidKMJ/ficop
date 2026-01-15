#
# MotorController class for managing multiple SCServo motors
#

from scservo_sdk import *

# Control table addresses
ADDR_SCS_TORQUE_ENABLE = 40
ADDR_STS_GOAL_ACC = 41
ADDR_STS_GOAL_POSITION = 42
ADDR_STS_GOAL_SPEED = 46
ADDR_STS_PRESENT_POSITION = 56


class MotorController:
    """
    A class to control multiple SCServo motors using sync read/write operations.
    """

    def __init__(
        self,
        device_name,
        servo_ids,
        baudrate=1000000,
        protocol_end=0,
    ):
        """
        Initialize the MotorController.

        Args:
            device_name (str): Serial port name (e.g., 'COM4' on Windows, '/dev/ttyUSB0' on Linux)
            servo_ids (list): List of servo IDs (e.g., [30, 31, 80, 81])
            baudrate (int): Communication baudrate (default: 1000000)
            protocol_end (int): Protocol end bit (0 for STS/SMS, 1 for SCS)
        """
        if not isinstance(servo_ids, list) or len(servo_ids) == 0:
            raise ValueError("servo_ids must be a non-empty list")
        
        self.device_name = device_name
        self.baudrate = baudrate
        self.servo_ids = servo_ids
        self.num_servos = len(servo_ids)
        self.protocol_end = protocol_end

        # Initialize handlers
        self.portHandler = None
        self.packetHandler = None
        self.groupSyncWrite = None
        self.groupSyncRead = None

        self.is_connected = False

    def connect(self):
        """
        Open the serial port and initialize communication.

        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            # Initialize PortHandler
            self.portHandler = PortHandler(self.device_name)

            # Initialize PacketHandler
            self.packetHandler = PacketHandler(self.protocol_end)

            # Initialize GroupSyncWrite for goal position
            self.groupSyncWrite = GroupSyncWrite(
                self.portHandler, self.packetHandler, ADDR_STS_GOAL_POSITION, 2
            )

            # Initialize GroupSyncRead for present position
            self.groupSyncRead = GroupSyncRead(
                self.portHandler, self.packetHandler, ADDR_STS_PRESENT_POSITION, 4
            )

            # Open port
            if not self.portHandler.openPort():
                print("Failed to open the port")
                return False
            print("Succeeded to open the port")

            # Set baudrate
            if not self.portHandler.setBaudRate(self.baudrate):
                print("Failed to change the baudrate")
                self.portHandler.closePort()
                return False
            print("Succeeded to change the baudrate")

            # Add servos to sync read group
            for servo_id in self.servo_ids:
                if not self.groupSyncRead.addParam(servo_id):
                    print(f"[ID:{servo_id:03d}] groupSyncRead addparam failed")
                    self.portHandler.closePort()
                    return False

            self.is_connected = True
            return True

        except Exception as e:
            print(f"Error connecting: {e}")
            if self.portHandler:
                try:
                    self.portHandler.closePort()
                except:
                    pass
            return False

    def disconnect(self):
        """
        Close the serial port connection.
        """
        if self.portHandler and self.is_connected:
            try:
                # Disable torque on all servos
                for servo_id in self.servo_ids:
                    try:
                        self.set_torque_enable(servo_id, False)
                    except:
                        pass  # Ignore errors when disconnecting

                # Clear sync read parameters
                if self.groupSyncRead:
                    self.groupSyncRead.clearParam()

                # Close port
                self.portHandler.closePort()
                self.is_connected = False
                print("Disconnected from port")
            except Exception as e:
                print(f"Error disconnecting: {e}")

    def set_acceleration(self, servo_id, acc_value):
        """
        Set acceleration for a servo.

        Args:
            servo_id (int): Servo ID
            acc_value (int): Acceleration value
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        scs_comm_result, scs_error = self.packetHandler.write1ByteTxRx(
            self.portHandler, servo_id, ADDR_STS_GOAL_ACC, acc_value
        )
        if scs_comm_result != COMM_SUCCESS:
            raise RuntimeError(
                f"[ID:{servo_id:03d}] Failed to set acceleration: {self.packetHandler.getTxRxResult(scs_comm_result)}"
            )
        elif scs_error != 0:
            error_msg = self.packetHandler.getRxPacketError(scs_error)
            if "Input voltage error" in error_msg:
                raise RuntimeError(
                    f"[ID:{servo_id:03d}] Hardware error - Input voltage error! "
                    f"Check power supply voltage and current capacity. "
                    f"Ensure the servo is receiving adequate power (typically 6-8.4V for most servos)."
                )
            raise RuntimeError(f"[ID:{servo_id:03d}] Servo error: {error_msg}")

    def set_speed(self, servo_id, speed_value):
        """
        Set speed for a servo.

        Args:
            servo_id (int): Servo ID
            speed_value (int): Speed value
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        scs_comm_result, scs_error = self.packetHandler.write2ByteTxRx(
            self.portHandler, servo_id, ADDR_STS_GOAL_SPEED, speed_value
        )
        if scs_comm_result != COMM_SUCCESS:
            raise RuntimeError(
                f"[ID:{servo_id:03d}] Failed to set speed: {self.packetHandler.getTxRxResult(scs_comm_result)}"
            )
        elif scs_error != 0:
            error_msg = self.packetHandler.getRxPacketError(scs_error)
            if "Input voltage error" in error_msg:
                raise RuntimeError(
                    f"[ID:{servo_id:03d}] Hardware error - Input voltage error! "
                    f"Check power supply voltage and current capacity. "
                    f"Ensure the servo is receiving adequate power (typically 6-8.4V for most servos)."
                )
            raise RuntimeError(f"[ID:{servo_id:03d}] Servo error: {error_msg}")

    def set_torque_enable(self, servo_id, enable):
        """
        Enable or disable torque for a servo.

        Args:
            servo_id (int): Servo ID
            enable (bool): True to enable torque, False to disable
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        value = 1 if enable else 0
        scs_comm_result, scs_error = self.packetHandler.write1ByteTxRx(
            self.portHandler, servo_id, ADDR_SCS_TORQUE_ENABLE, value
        )
        if scs_comm_result != COMM_SUCCESS:
            raise RuntimeError(
                f"[ID:{servo_id:03d}] Failed to set torque: {self.packetHandler.getTxRxResult(scs_comm_result)}"
            )
        elif scs_error != 0:
            error_msg = self.packetHandler.getRxPacketError(scs_error)
            if "Input voltage error" in error_msg:
                raise RuntimeError(
                    f"[ID:{servo_id:03d}] Hardware error - Input voltage error! "
                    f"Check power supply voltage and current capacity. "
                    f"Ensure the servo is receiving adequate power (typically 6-8.4V for most servos)."
                )
            raise RuntimeError(f"[ID:{servo_id:03d}] Servo error: {error_msg}")

    def configure_servos(self, acc=0, speed=0):
        """
        Configure all servos with acceleration and speed.

        Args:
            acc (int): Acceleration value (default: 0)
            speed (int): Speed value (default: 0)
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        # Configure all servos
        for servo_id in self.servo_ids:
            self.set_acceleration(servo_id, acc)
            self.set_speed(servo_id, speed)

    def set_goal_positions(self, positions):
        """
        Set goal positions for all servos simultaneously.

        Args:
            positions (list): List of goal positions for each servo (must match length of servo_ids)
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if len(positions) != self.num_servos:
            raise ValueError(
                f"Number of positions ({len(positions)}) must match number of servos ({self.num_servos})"
            )

        # Clear previous parameters
        self.groupSyncWrite.clearParam()

        # Add positions for all servos
        for servo_id, position in zip(self.servo_ids, positions):
            param_goal_position = [SCS_LOBYTE(position), SCS_HIBYTE(position)]
            if not self.groupSyncWrite.addParam(servo_id, param_goal_position):
                raise RuntimeError(
                    f"[ID:{servo_id:03d}] groupSyncWrite addparam failed"
                )

        # Send sync write packet
        scs_comm_result = self.groupSyncWrite.txPacket()
        if scs_comm_result != COMM_SUCCESS:
            raise RuntimeError(
                f"Sync write failed: {self.packetHandler.getTxRxResult(scs_comm_result)}"
            )

        # Clear parameters after sending
        self.groupSyncWrite.clearParam()

    def read_positions(self):
        """
        Read present positions and speeds from all servos.

        Returns:
            dict: Dictionary with keys 'servo1', 'servo2', etc., each containing:
                - 'position' (int): Present position
                - 'speed' (int): Present speed
            Also returns a 'positions' list for convenience: [pos1, pos2, ...]
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        # Send sync read request
        scs_comm_result = self.groupSyncRead.txRxPacket()
        if scs_comm_result != COMM_SUCCESS:
            raise RuntimeError(
                f"Sync read failed: {self.packetHandler.getTxRxResult(scs_comm_result)}"
            )

        result = {}
        positions_list = []

        # Read data for all servos
        for idx, servo_id in enumerate(self.servo_ids):
            if self.groupSyncRead.isAvailable(servo_id, ADDR_STS_PRESENT_POSITION, 4):
                scs_data = self.groupSyncRead.getData(
                    servo_id, ADDR_STS_PRESENT_POSITION, 4
                )
                position = SCS_LOWORD(scs_data)
                speed = SCS_TOHOST(SCS_HIWORD(scs_data), 15)
                result[f"servo{idx+1}"] = {"position": position, "speed": speed}
                positions_list.append(position)
            else:
                raise RuntimeError(
                    f"[ID:{servo_id:03d}] groupSyncRead getdata failed"
                )

        result["positions"] = positions_list
        return result

    def wait_for_positions(
        self,
        goal_positions,
        threshold=20,
        timeout=None,
    ):
        """
        Wait until all servos reach their goal positions.

        Args:
            goal_positions (list): List of goal positions for each servo (must match length of servo_ids)
            threshold (int): Position threshold to consider reached (default: 20)
            timeout (float): Maximum time to wait in seconds (None for no timeout)

        Returns:
            bool: True if positions reached, False if timeout
        """
        import time

        if len(goal_positions) != self.num_servos:
            raise ValueError(
                f"Number of goal positions ({len(goal_positions)}) must match number of servos ({self.num_servos})"
            )

        start_time = time.time()

        while True:
            positions = self.read_positions()

            # Check if all servos are within threshold
            all_reached = True
            for idx, goal_pos in enumerate(goal_positions):
                current_pos = positions[f"servo{idx+1}"]["position"]
                pos_diff = abs(goal_pos - current_pos)
                if pos_diff > threshold:
                    all_reached = False
                    break

            if all_reached:
                return True

            if timeout is not None and (time.time() - start_time) > timeout:
                return False

            time.sleep(0.01)  # Small delay to avoid excessive CPU usage

    def __enter__(self):
        """Context manager entry."""
        if not self.connect():
            raise RuntimeError("Failed to connect")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False
