from __future__ import annotations

import time
from typing import Callable, Optional, Tuple, Union

from . import sdk

# Control table addresses
ADDR_SCS_TORQUE_ENABLE = 40
ADDR_STS_GOAL_ACC = 41
ADDR_STS_GOAL_POSITION = 42
ADDR_STS_GOAL_SPEED = 46
ADDR_STS_PRESENT_POSITION = 56


def check_scservo_port(
    device_name: str,
    servo_ids: Union[int, list[int], tuple[int, ...]],
    baudrate: int = 1_000_000,
    protocol_end: int = 0,
) -> Tuple[bool, str]:
    """
    Open the port briefly and ping each servo ID.

    Args:
        device_name: Serial device path.
        servo_ids: One or more servo IDs to ping.
        baudrate: Bus baud rate.
        protocol_end: ``0`` for STS/SMS, ``1`` for SCS.

    Returns:
        (ok, message): ``ok`` is True if every ping succeeded; ``message`` is a
        short error description when ``ok`` is False, or an empty string otherwise.
    """
    if not device_name or not isinstance(device_name, str):
        return False, "invalid device_name"
    if isinstance(servo_ids, int):
        ids: list[int] = [servo_ids]
    elif isinstance(servo_ids, (list, tuple)) and len(servo_ids) > 0:
        ids = list(servo_ids)
    else:
        return False, "servo_ids must be a non-empty int or list of int"

    port = sdk.PortHandler(device_name.strip())
    handler = sdk.PacketHandler(protocol_end)
    try:
        if not port.openPort():
            return False, "failed to open serial port"
        if not port.setBaudRate(baudrate):
            return False, "failed to set baudrate"
        for sid in ids:
            _model, result, _err = handler.ping(port, sid)
            if result != sdk.COMM_SUCCESS:
                label = handler.getTxRxResult(result)
                return False, f"ping failed for id {sid}: {label}"
        return True, ""
    except OSError as e:
        return False, f"os error: {e}"
    except Exception as e:
        return False, str(e)
    finally:
        if getattr(port, "is_open", False):
            try:
                port.closePort()
            except Exception:
                pass


def scan_scservo_ids(
    device_name: str,
    baudrate: int = 1_000_000,
    protocol_end: int = 0,
    id_min: int = 1,
    id_max: int = 252,
    on_progress: Optional[Callable[[int, int, int], None]] = None,
) -> list[dict[str, int]]:
    """
    Ping each servo ID in ``[id_min, id_max]`` on ``device_name`` and collect responses.

    Args:
        device_name: Serial device path.
        baudrate: Bus baud rate.
        protocol_end: ``0`` for STS/SMS, ``1`` for SCS.
        id_min: Inclusive lower bound of the ID range (valid IDs are typically ``1`` … ``252``).
        id_max: Inclusive upper bound of the ID range.
        on_progress: Optional ``callable(servo_id, step_index, total_steps)`` for UI feedback
            (``step_index`` is 1-based within the scan).

    Returns:
        Each entry ``{"id": ..., "model": ...}`` for IDs that answered ping with
        ``COMM_SUCCESS`` (model from the control table when the read succeeds).
    """
    if not device_name or not isinstance(device_name, str):
        raise ValueError("device_name must be a non-empty string")
    id_min = int(id_min)
    id_max = int(id_max)
    if id_min < 1 or id_max > 252 or id_min > id_max:
        raise ValueError("id_min and id_max must satisfy 1 <= id_min <= id_max <= 252")

    port = sdk.PortHandler(device_name.strip())
    handler = sdk.PacketHandler(protocol_end)
    found: list[dict[str, int]] = []
    span = id_max - id_min + 1
    try:
        if not port.openPort():
            raise OSError("failed to open serial port")
        if not port.setBaudRate(baudrate):
            raise OSError("failed to set baudrate")

        for idx, sid in enumerate(range(id_min, id_max + 1)):
            if on_progress is not None:
                on_progress(sid, idx + 1, span)
            model, result, _err = handler.ping(port, sid)
            if result == sdk.COMM_SUCCESS:
                found.append({"id": sid, "model": int(model)})

    finally:
        if getattr(port, "is_open", False):
            try:
                port.closePort()
            except Exception:
                pass

    return found


class ServoController:
    """
    ServoController: control multiple SCServo motors using sync read/write operations.
    """

    def __init__(
        self,
        device_name: str,
        servo_ids: list[int],
        baudrate: int = 1_000_000,
        protocol_end: int = 0,
    ) -> None:
        """
        Initialize the ServoController.

        Args:
            device_name: Serial port name (e.g. ``"COM4"`` on Windows, ``"/dev/ttyUSB0"`` on Linux).
            servo_ids: Servo IDs (e.g. ``[30, 31, 80, 81]``).
            baudrate: Communication baudrate.
            protocol_end: Protocol end bit (``0`` for STS/SMS, ``1`` for SCS).
        """
        if not isinstance(servo_ids, list) or len(servo_ids) == 0:
            raise ValueError("servo_ids must be a non-empty list")

        self.device_name = device_name
        self.baudrate = baudrate
        self.servo_ids = servo_ids
        self.num_servos = len(servo_ids)
        self.protocol_end = protocol_end

        self.portHandler: Optional[sdk.PortHandler] = None
        self.packetHandler = None
        self.groupSyncWrite: Optional[sdk.GroupSyncWrite] = None
        self.groupSyncRead: Optional[sdk.GroupSyncRead] = None

        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, verbose: bool = False) -> None:
        """Open the serial port and initialize communication."""
        if self._connected:
            return
        try:
            self.portHandler = sdk.PortHandler(self.device_name)

            self.packetHandler = sdk.PacketHandler(self.protocol_end)

            self.groupSyncWrite = sdk.GroupSyncWrite(
                self.portHandler, self.packetHandler, ADDR_STS_GOAL_POSITION, 2
            )

            self.groupSyncRead = sdk.GroupSyncRead(
                self.portHandler, self.packetHandler, ADDR_STS_PRESENT_POSITION, 4
            )

            if not self.portHandler.openPort():
                raise RuntimeError("ServoController failed to open the port")
            if verbose:
                print("ServoController succeeded to open the port")

            if not self.portHandler.setBaudRate(self.baudrate):
                self.portHandler.closePort()
                raise RuntimeError("ServoController failed to change the baudrate")
            if verbose:
                print("ServoController succeeded to change the baudrate")

            for servo_id in self.servo_ids:
                if not self.groupSyncRead.addParam(servo_id):
                    self.portHandler.closePort()
                    raise RuntimeError(
                        f"[ID:{servo_id:03d}] Servo groupSyncRead addparam failed"
                    )

            self._connected = True

        except Exception as e:
            if self.portHandler:
                try:
                    self.portHandler.closePort()
                except:
                    pass
            self._connected = False
            raise RuntimeError(f"ServoController failed to connect: {e}") from e

    def disconnect(self, hold_torque: bool = False) -> None:
        """Close the serial port connection."""
        if self.portHandler and self._connected:
            try:
                for servo_id in self.servo_ids:
                    try:
                        self.set_torque_enable(servo_id, hold_torque)
                    except:
                        pass

                if self.groupSyncRead:
                    self.groupSyncRead.clearParam()

                self.portHandler.closePort()
                self._connected = False
                print("ServoController disconnected from port")
            except Exception as e:
                self._connected = False
                raise RuntimeError(f"ServoController failed to disconnect: {e}") from e

    def set_acceleration(self, servo_id: int, acc_value: int) -> None:
        """
        Set acceleration for a servo.

        Args:
            servo_id: Servo ID.
            acc_value: Acceleration value.
        """
        if not self._connected:
            raise RuntimeError("ServoController not connected")

        scs_comm_result, scs_error = self.packetHandler.write1ByteTxRx(
            self.portHandler, servo_id, ADDR_STS_GOAL_ACC, acc_value
        )
        if scs_comm_result != sdk.COMM_SUCCESS:
            raise RuntimeError(
                f"[ID:{servo_id:03d}] Servo failed to set acceleration: {self.packetHandler.getTxRxResult(scs_comm_result)}"
            )
        elif scs_error != sdk.COMM_SUCCESS:
            error_msg = self.packetHandler.getRxPacketError(scs_error)
            if "Input voltage error" in error_msg:
                raise RuntimeError(
                    f"[ID:{servo_id:03d}] Servo hardware error - Input voltage error! "
                    f"Check power supply voltage and current capacity. "
                    f"Ensure the servo is receiving adequate power (typically 6-8.4V for most servos)."
                )
            raise RuntimeError(f"[ID:{servo_id:03d}] Servo error: {error_msg}")

    def set_speed(self, servo_id: int, speed_value: int) -> None:
        """
        Set speed for a servo.

        Args:
            servo_id: Servo ID.
            speed_value: Speed value.
        """
        if not self._connected:
            raise RuntimeError("ServoController not connected")

        scs_comm_result, scs_error = self.packetHandler.write2ByteTxRx(
            self.portHandler, servo_id, ADDR_STS_GOAL_SPEED, speed_value
        )
        if scs_comm_result != sdk.COMM_SUCCESS:
            raise RuntimeError(
                f"[ID:{servo_id:03d}] Servo failed to set speed: {self.packetHandler.getTxRxResult(scs_comm_result)}"
            )
        elif scs_error != 0:
            error_msg = self.packetHandler.getRxPacketError(scs_error)
            if "Input voltage error" in error_msg:
                raise RuntimeError(
                    f"[ID:{servo_id:03d}] Servo hardware error - Input voltage error! "
                    f"Check power supply voltage and current capacity. "
                    f"Ensure the servo is receiving adequate power (typically 6-8.4V for most servos)."
                )
            raise RuntimeError(f"[ID:{servo_id:03d}] Servo error: {error_msg}")

    def set_position(self, servo_id: int, position: int) -> None:
        """
        Set goal position for a single servo.

        Args:
            servo_id: Servo ID.
            position: Goal position.
        """
        if not self._connected:
            raise RuntimeError("ServoController not connected")

        scs_comm_result, scs_error = self.packetHandler.write2ByteTxRx(
            self.portHandler, servo_id, ADDR_STS_GOAL_POSITION, position
        )
        if scs_comm_result != sdk.COMM_SUCCESS:
            raise RuntimeError(
                f"[ID:{servo_id:03d}] Servo failed to set position: {self.packetHandler.getTxRxResult(scs_comm_result)}"
            )
        elif scs_error != 0:
            error_msg = self.packetHandler.getRxPacketError(scs_error)
            if "Input voltage error" in error_msg:
                raise RuntimeError(
                    f"[ID:{servo_id:03d}] Servo hardware error - Input voltage error! "
                    f"Check power supply voltage and current capacity. "
                    f"Ensure the servo is receiving adequate power (typically 6-8.4V for most servos)."
                )
            raise RuntimeError(f"[ID:{servo_id:03d}] Servo error: {error_msg}")

    def set_torque_enable(self, servo_id: int, enable: bool) -> None:
        """
        Enable or disable torque for a servo.

        Args:
            servo_id: Servo ID.
            enable: True to enable torque, False to disable.
        """
        if not self._connected:
            raise RuntimeError("ServoController not connected")

        value = 1 if enable else 0
        scs_comm_result, scs_error = self.packetHandler.write1ByteTxRx(
            self.portHandler, servo_id, ADDR_SCS_TORQUE_ENABLE, value
        )
        if scs_comm_result != sdk.COMM_SUCCESS:
            raise RuntimeError(
                f"[ID:{servo_id:03d}] Servo failed to set torque: {self.packetHandler.getTxRxResult(scs_comm_result)}"
            )
        elif scs_error != 0:
            error_msg = self.packetHandler.getRxPacketError(scs_error)
            if "Input voltage error" in error_msg:
                raise RuntimeError(
                    f"[ID:{servo_id:03d}] Servo hardware error - Input voltage error! "
                    f"Check power supply voltage and current capacity. "
                    f"Ensure the servo is receiving adequate power (typically 6-8.4V for most servos)."
                )
            raise RuntimeError(f"[ID:{servo_id:03d}] Servo error: {error_msg}")

    def configure_servos(self, acc: int = 0, speed: int = 0) -> None:
        """
        Configure all servos with acceleration and speed.

        Args:
            acc: Acceleration value.
            speed: Speed value.
        """
        if not self._connected:
            raise RuntimeError("ServoController not connected")

        for servo_id in self.servo_ids:
            self.set_acceleration(servo_id, acc)
            self.set_speed(servo_id, speed)

    def set_positions(self, positions: list[int]) -> None:
        """
        Set goal positions for all servos.

        Args:
            positions: Goal positions, one per servo (must match length of ``servo_ids``).
        """
        if not self._connected:
            raise RuntimeError("ServoController not connected")

        if len(positions) != self.num_servos:
            raise ValueError(
                f"Number of positions ({len(positions)}) must match number of servos ({self.num_servos})"
            )

        for servo_id, position in zip(self.servo_ids, positions):
            self.set_position(servo_id, position)

    def read_speed(self, servo_id: int) -> int:
        """
        Read present speed from a single servo.

        Args:
            servo_id: Servo ID.

        Returns:
            Present speed.
        """
        if not self._connected:
            raise RuntimeError("ServoController not connected")

        scs_data, scs_comm_result, scs_error = self.packetHandler.read4ByteTxRx(
            self.portHandler, servo_id, ADDR_STS_PRESENT_POSITION
        )
        if scs_comm_result != sdk.COMM_SUCCESS:
            raise RuntimeError(
                f"[ID:{servo_id:03d}] Servo failed to read speed: {self.packetHandler.getTxRxResult(scs_comm_result)}"
            )
        elif scs_error != 0:
            error_msg = self.packetHandler.getRxPacketError(scs_error)
            raise RuntimeError(f"[ID:{servo_id:03d}] Servo error: {error_msg}")

        speed = sdk.SCS_TOHOST(sdk.SCS_HIWORD(scs_data), 15)
        return speed

    def read_position(self, servo_id: int) -> int:
        """
        Read present position from a single servo.

        Args:
            servo_id: Servo ID.

        Returns:
            Present position.
        """
        if not self._connected:
            raise RuntimeError("ServoController not connected")

        scs_data, scs_comm_result, scs_error = self.packetHandler.read4ByteTxRx(
            self.portHandler, servo_id, ADDR_STS_PRESENT_POSITION
        )
        if scs_comm_result != sdk.COMM_SUCCESS:
            raise RuntimeError(
                f"[ID:{servo_id:03d}] Servo failed to read position: {self.packetHandler.getTxRxResult(scs_comm_result)}"
            )
        elif scs_error != 0:
            error_msg = self.packetHandler.getRxPacketError(scs_error)
            raise RuntimeError(f"[ID:{servo_id:03d}] Servo error: {error_msg}")

        position = sdk.SCS_LOWORD(scs_data)
        return position

    def read_speeds(self) -> list[int]:
        """
        Read present speeds from all servos.

        Returns:
            Present speeds, one per servo (same order as ``servo_ids``).
        """
        if not self._connected:
            raise RuntimeError("ServoController not connected")

        speeds: list[int] = []

        for servo_id in self.servo_ids:
            speed = self.read_speed(servo_id)
            speeds.append(speed)

        return speeds

    def read_positions(self) -> list[int]:
        """
        Read present positions from all servos.

        Returns:
            Present positions, one per servo (same order as ``servo_ids``).
        """
        if not self._connected:
            raise RuntimeError("ServoController not connected")

        positions: list[int] = []

        for servo_id in self.servo_ids:
            position = self.read_position(servo_id)
            positions.append(position)

        return positions

    def wait_for_positions(
        self,
        goal_positions: list[int],
        threshold: int = 20,
        timeout: Optional[float] = None,
    ) -> bool:
        """
        Wait until all servos reach their goal positions.

        Args:
            goal_positions: Goal positions, one per servo (must match length of ``servo_ids``).
            threshold: Position threshold to consider reached.
            timeout: Maximum time to wait in seconds (``None`` for no timeout).

        Returns:
            True if all positions were reached, False if the timeout elapsed first.
        """
        if not self._connected:
            raise RuntimeError("ServoController not connected")

        if len(goal_positions) != self.num_servos:
            raise ValueError(
                f"ServoController number of goal positions ({len(goal_positions)}) must match number of servos ({self.num_servos})"
            )

        start_time = time.time()

        while True:
            positions = self.read_positions()

            all_reached = True
            for idx, goal_pos in enumerate(goal_positions):
                current_pos = positions[idx]
                pos_diff = abs(goal_pos - current_pos)
                if pos_diff > threshold:
                    all_reached = False
                    break

            if all_reached:
                return True

            if timeout is not None and (time.time() - start_time) > timeout:
                return False

            time.sleep(0.01)

    def __enter__(self) -> ServoController:
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.disconnect()
        return False
