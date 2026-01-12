#
# MotorController class for managing two SCServo motors
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
    A class to control four SCServo motors using sync read/write operations.
    """

    def __init__(
        self,
        device_name,
        baudrate=1000000,
        servo1_id=30,
        servo2_id=31,
        servo3_id=80,
        servo4_id=81,
        protocol_end=0,
    ):
        """
        Initialize the MotorController.

        Args:
            device_name (str): Serial port name (e.g., 'COM4' on Windows, '/dev/ttyUSB0' on Linux)
            baudrate (int): Communication baudrate (default: 1000000)
            servo1_id (int): ID of the first servo (default: 30)
            servo2_id (int): ID of the second servo (default: 31)
            servo3_id (int): ID of the third servo (default: 80)
            servo4_id (int): ID of the fourth servo (default: 81)
            protocol_end (int): Protocol end bit (0 for STS/SMS, 1 for SCS)
        """
        self.device_name = device_name
        self.baudrate = baudrate
        self.servo1_id = servo1_id
        self.servo2_id = servo2_id
        self.servo3_id = servo3_id
        self.servo4_id = servo4_id
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
            if not self.groupSyncRead.addParam(self.servo1_id):
                print(f"[ID:{self.servo1_id:03d}] groupSyncRead addparam failed")
                self.portHandler.closePort()
                return False

            if not self.groupSyncRead.addParam(self.servo2_id):
                print(f"[ID:{self.servo2_id:03d}] groupSyncRead addparam failed")
                self.portHandler.closePort()
                return False

            if not self.groupSyncRead.addParam(self.servo3_id):
                print(f"[ID:{self.servo3_id:03d}] groupSyncRead addparam failed")
                self.portHandler.closePort()
                return False

            if not self.groupSyncRead.addParam(self.servo4_id):
                print(f"[ID:{self.servo4_id:03d}] groupSyncRead addparam failed")
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
                self.set_torque_enable(self.servo1_id, False)
                self.set_torque_enable(self.servo2_id, False)
                self.set_torque_enable(self.servo3_id, False)
                self.set_torque_enable(self.servo4_id, False)

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
        Configure all four servos with acceleration and speed.

        Args:
            acc (int): Acceleration value (default: 0)
            speed (int): Speed value (default: 0)
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        # Configure servo 1
        self.set_acceleration(self.servo1_id, acc)
        self.set_speed(self.servo1_id, speed)

        # Configure servo 2
        self.set_acceleration(self.servo2_id, acc)
        self.set_speed(self.servo2_id, speed)

        # Configure servo 3
        self.set_acceleration(self.servo3_id, acc)
        self.set_speed(self.servo3_id, speed)

        # Configure servo 4
        self.set_acceleration(self.servo4_id, acc)
        self.set_speed(self.servo4_id, speed)

    def set_goal_positions(self, position1, position2, position3, position4):
        """
        Set goal positions for all four servos simultaneously.

        Args:
            position1 (int): Goal position for servo 1
            position2 (int): Goal position for servo 2
            position3 (int): Goal position for servo 3
            position4 (int): Goal position for servo 4
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        # Clear previous parameters
        self.groupSyncWrite.clearParam()

        # Prepare position 1
        param_goal_position1 = [SCS_LOBYTE(position1), SCS_HIBYTE(position1)]
        if not self.groupSyncWrite.addParam(self.servo1_id, param_goal_position1):
            raise RuntimeError(
                f"[ID:{self.servo1_id:03d}] groupSyncWrite addparam failed"
            )

        # Prepare position 2
        param_goal_position2 = [SCS_LOBYTE(position2), SCS_HIBYTE(position2)]
        if not self.groupSyncWrite.addParam(self.servo2_id, param_goal_position2):
            raise RuntimeError(
                f"[ID:{self.servo2_id:03d}] groupSyncWrite addparam failed"
            )

        # Prepare position 3
        param_goal_position3 = [SCS_LOBYTE(position3), SCS_HIBYTE(position3)]
        if not self.groupSyncWrite.addParam(self.servo3_id, param_goal_position3):
            raise RuntimeError(
                f"[ID:{self.servo3_id:03d}] groupSyncWrite addparam failed"
            )

        # Prepare position 4
        param_goal_position4 = [SCS_LOBYTE(position4), SCS_HIBYTE(position4)]
        if not self.groupSyncWrite.addParam(self.servo4_id, param_goal_position4):
            raise RuntimeError(
                f"[ID:{self.servo4_id:03d}] groupSyncWrite addparam failed"
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
        Read present positions and speeds from all four servos.

        Returns:
            dict: Dictionary with keys 'servo1', 'servo2', 'servo3', and 'servo4', each containing:
                - 'position' (int): Present position
                - 'speed' (int): Present speed
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call connect() first.")

        # Send sync read request
        scs_comm_result = self.groupSyncRead.txRxPacket()
        if scs_comm_result != COMM_SUCCESS:
            raise RuntimeError(
                f"Sync read failed: {self.packetHandler.getTxRxResult(scs_comm_result)}"
            )

        result = {
            "servo1": {"position": 0, "speed": 0},
            "servo2": {"position": 0, "speed": 0},
            "servo3": {"position": 0, "speed": 0},
            "servo4": {"position": 0, "speed": 0},
        }

        # Read servo 1 data
        if self.groupSyncRead.isAvailable(self.servo1_id, ADDR_STS_PRESENT_POSITION, 4):
            scs1_data = self.groupSyncRead.getData(
                self.servo1_id, ADDR_STS_PRESENT_POSITION, 4
            )
            result["servo1"]["position"] = SCS_LOWORD(scs1_data)
            result["servo1"]["speed"] = SCS_TOHOST(SCS_HIWORD(scs1_data), 15)
        else:
            raise RuntimeError(
                f"[ID:{self.servo1_id:03d}] groupSyncRead getdata failed"
            )

        # Read servo 2 data
        if self.groupSyncRead.isAvailable(self.servo2_id, ADDR_STS_PRESENT_POSITION, 4):
            scs2_data = self.groupSyncRead.getData(
                self.servo2_id, ADDR_STS_PRESENT_POSITION, 4
            )
            result["servo2"]["position"] = SCS_LOWORD(scs2_data)
            result["servo2"]["speed"] = SCS_TOHOST(SCS_HIWORD(scs2_data), 15)
        else:
            raise RuntimeError(
                f"[ID:{self.servo2_id:03d}] groupSyncRead getdata failed"
            )

        # Read servo 3 data
        if self.groupSyncRead.isAvailable(self.servo3_id, ADDR_STS_PRESENT_POSITION, 4):
            scs3_data = self.groupSyncRead.getData(
                self.servo3_id, ADDR_STS_PRESENT_POSITION, 4
            )
            result["servo3"]["position"] = SCS_LOWORD(scs3_data)
            result["servo3"]["speed"] = SCS_TOHOST(SCS_HIWORD(scs3_data), 15)
        else:
            raise RuntimeError(
                f"[ID:{self.servo3_id:03d}] groupSyncRead getdata failed"
            )

        # Read servo 4 data
        if self.groupSyncRead.isAvailable(self.servo4_id, ADDR_STS_PRESENT_POSITION, 4):
            scs4_data = self.groupSyncRead.getData(
                self.servo4_id, ADDR_STS_PRESENT_POSITION, 4
            )
            result["servo4"]["position"] = SCS_LOWORD(scs4_data)
            result["servo4"]["speed"] = SCS_TOHOST(SCS_HIWORD(scs4_data), 15)
        else:
            raise RuntimeError(
                f"[ID:{self.servo4_id:03d}] groupSyncRead getdata failed"
            )

        return result

    def wait_for_positions(
        self,
        goal_position1,
        goal_position2,
        goal_position3,
        goal_position4,
        threshold=20,
        timeout=None,
    ):
        """
        Wait until all four servos reach their goal positions.

        Args:
            goal_position1 (int): Goal position for servo 1
            goal_position2 (int): Goal position for servo 2
            goal_position3 (int): Goal position for servo 3
            goal_position4 (int): Goal position for servo 4
            threshold (int): Position threshold to consider reached (default: 20)
            timeout (float): Maximum time to wait in seconds (None for no timeout)

        Returns:
            bool: True if positions reached, False if timeout
        """
        import time

        start_time = time.time()

        while True:
            positions = self.read_positions()

            pos1_diff = abs(goal_position1 - positions["servo1"]["position"])
            pos2_diff = abs(goal_position2 - positions["servo2"]["position"])
            pos3_diff = abs(goal_position3 - positions["servo3"]["position"])
            pos4_diff = abs(goal_position4 - positions["servo4"]["position"])

            if (
                pos1_diff <= threshold
                and pos2_diff <= threshold
                and pos3_diff <= threshold
                and pos4_diff <= threshold
            ):
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
