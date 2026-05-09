from __future__ import annotations

import time

from cua.scservo import (
    ServoController,
    check_scservo_port,
    scan_scservo_ids,
)
from cua.scservo.debug import print_available_serial_ports

DEVICE_NAME = "/dev/tty.usbserial-FT891TQT"
SERVO_IDS = [30, 31, 80, 81]
BAUDRATE = 1_000_000
PROTOCOL_END = 0

GOAL_LO = 1500
GOAL_HI = 2500
SETTLE_THRESHOLD = 20
SETTLE_TIMEOUT = 5.0


def example_list_and_ping() -> None:
    """Show OS-visible serial ports and ping the configured IDs once."""
    print("=" * 60)
    print("Example 1: list ports + ping configured IDs")
    print("=" * 60)
    print_available_serial_ports()
    ok, msg = check_scservo_port(
        DEVICE_NAME,
        SERVO_IDS,
        baudrate=BAUDRATE,
        protocol_end=PROTOCOL_END,
    )
    print(f"\nping result on {DEVICE_NAME}: {'OK' if ok else f'FAIL: {msg}'}")


def example_scan_bus() -> None:
    """Probe IDs 1..30 on the bus and print whichever respond."""
    print("=" * 60)
    print("Example 2: scan IDs 1..30")
    print("=" * 60)

    def _progress(sid: int, step: int, total: int) -> None:
        print(f"\r  scanning id {sid:3d} ({step}/{total})", end="", flush=True)

    found = scan_scservo_ids(
        DEVICE_NAME,
        baudrate=BAUDRATE,
        protocol_end=PROTOCOL_END,
        id_min=1,
        id_max=30,
        on_progress=_progress,
    )
    print()
    if not found:
        print("  no servos answered in this range")
        return
    print("  found:")
    for row in found:
        print(f"    ID {row['id']:3d}  model {row['model']}")


def example_move_servos() -> None:
    """Move the configured servos between two goal positions a few times."""
    print("=" * 60)
    print("Example 3: move servos between two goal positions")
    print("=" * 60)

    with ServoController(
        DEVICE_NAME,
        SERVO_IDS,
        baudrate=BAUDRATE,
        protocol_end=PROTOCOL_END,
    ) as ctrl:
        ctrl.configure_servos(acc=20, speed=1000)

        for sid in ctrl.servo_ids:
            ctrl.set_torque_enable(sid, True)

        try:
            for cycle in range(2):
                for goal in (GOAL_LO, GOAL_HI):
                    targets = [goal] * ctrl.num_servos
                    print(f"  cycle {cycle}: goal={targets}")
                    ctrl.set_positions(targets)

                    reached = ctrl.wait_for_positions(
                        targets,
                        threshold=SETTLE_THRESHOLD,
                        timeout=SETTLE_TIMEOUT,
                    )
                    positions = ctrl.read_positions()
                    print(f"    {'reached' if reached else 'TIMEOUT'} -> {positions}")
                    time.sleep(0.5)
        finally:
            for sid in ctrl.servo_ids:
                try:
                    ctrl.set_torque_enable(sid, False)
                except Exception:
                    pass


def main() -> None:
    example_list_and_ping()
    example_scan_bus()
    example_move_servos()


if __name__ == "__main__":
    main()
