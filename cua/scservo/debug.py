from __future__ import annotations

from typing import Optional

from serial.tools import list_ports

from .servo import (
    ServoController,
    check_scservo_port,
    scan_scservo_ids,
)


def get_available_serial_ports() -> list[dict[str, str]]:
    """
    Return serial ports reported by the OS with basic metadata.

    Returns:
        Each dict has ``device``, ``description``, and ``manufacturer`` (all strings).
    """
    out: list[dict[str, str]] = []
    for p in list_ports.comports():
        out.append(
            {
                "device": p.device,
                "description": (p.description or "").strip(),
                "manufacturer": (p.manufacturer or "").strip(),
            }
        )
    return out


def print_available_serial_ports() -> None:
    """Print enumerated serial ports (same source as :func:`get_available_serial_ports`)."""
    rows = get_available_serial_ports()
    if not rows:
        print("No serial ports found.")
        return
    print("Available serial ports:")
    for r in rows:
        extra = r["description"] or "(no description)"
        mfg = r["manufacturer"]
        if mfg:
            extra = f"{extra} [{mfg}]"
        print(f"  {r['device']}")
        print(f"      {extra}")


def _parse_int_list(s: str) -> list[int]:
    parts = [p.strip() for p in s.replace(",", " ").split() if p.strip()]
    return [int(p) for p in parts]


def _cmd_help() -> None:
    print(
        """
Commands:
  help              Show this text
  ports             List OS serial ports (:func:`print_available_serial_ports`)
  connect           Prompt for port, baud, protocol_end; optional ID scan; then connect
  scan <dev> ...    Ping IDs in a range on a port (see usage)
  ping              Optional probe: ping specific IDs before/without staying connected
  read              Read present positions (must be connected)
  goal <n> [n...]   Set goal positions (one value per servo, same order as IDs)
  torque on|off     Enable/disable torque on all servos
  acc <n>           Set acceleration on all servos
  speed <n>         Set speed on all servos
  disconnect        Close serial / disable torque
  quit | exit       Leave the program
"""
    )


def run_interactive_console() -> None:
    ctrl: Optional[ServoController] = None

    print("SCServo interactive debug. Type 'help' for commands.")

    while True:
        try:
            line = input("scservo> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        if cmd in ("quit", "exit", "q"):
            break
        if cmd == "help":
            _cmd_help()
            continue
        if cmd == "ports":
            print_available_serial_ports()
            continue

        if cmd == "ping":
            if len(parts) < 2:
                print("Usage: ping <device> <id> [id ...] [baud=1000000] [end=0]")
                continue
            dev = parts[1]
            rest = parts[2:]
            baud = 1_000_000
            end = 0
            ids_raw: list[str] = []
            for p in rest:
                if p.lower().startswith("baud="):
                    baud = int(p.split("=", 1)[1])
                elif p.lower().startswith("end="):
                    end = int(p.split("=", 1)[1])
                else:
                    ids_raw.append(p)
            if not ids_raw:
                print("Provide at least one servo ID after the device name.")
                continue
            ids = [int(x) for x in ids_raw]
            ok, msg = check_scservo_port(dev, ids, baudrate=baud, protocol_end=end)
            print("OK" if ok else f"FAIL: {msg}")
            continue

        if cmd == "scan":
            if len(parts) < 2:
                print("Usage: scan <device> [baud=1000000] [end=0] [min=1] [max=252]")
                continue
            dev = parts[1]
            baud = 1_000_000
            end = 0
            id_min, id_max = 1, 252
            for p in parts[2:]:
                pl = p.lower()
                if pl.startswith("baud="):
                    baud = int(p.split("=", 1)[1])
                elif pl.startswith("end="):
                    end = int(p.split("=", 1)[1])
                elif pl.startswith("min="):
                    id_min = int(p.split("=", 1)[1])
                elif pl.startswith("max="):
                    id_max = int(p.split("=", 1)[1])
            try:

                def _prog(sid: int, step: int, total: int) -> None:
                    print(f"\rScanning id {sid} ({step}/{total})", end="", flush=True)

                found = scan_scservo_ids(
                    dev,
                    baudrate=baud,
                    protocol_end=end,
                    id_min=id_min,
                    id_max=id_max,
                    on_progress=_prog,
                )
                print()
            except (ValueError, OSError) as e:
                print(f"\nScan failed: {e}")
                continue
            if not found:
                print("No servos responded in that range.")
            else:
                print("Found:")
                for row in found:
                    print(f"  ID {row['id']:3d}  model {row['model']}")
            continue

        if cmd == "connect":
            if ctrl and ctrl.connected:
                print("Already connected. Use 'disconnect' first.")
                continue
            try:
                ports = [p["device"] for p in get_available_serial_ports()]
                if ports:
                    print(f"Detected ports: {', '.join(ports)}")
                dev = input("Serial device: ").strip()
                if not dev:
                    if not ports:
                        print("No ports available.")
                        continue
                    dev = ports[0]
                    print(f"Using first port {dev!r}")
                baud_s = input("Baudrate [1000000]: ").strip()
                baud = int(baud_s) if baud_s else 1_000_000
                end_s = input("protocol_end 0=STS/SMS 1=SCS [0]: ").strip()
                end = int(end_s) if end_s else 0

                scan_ans = (
                    input("Scan bus for servo IDs in a range (ping 1…252)? [y/N]: ")
                    .strip()
                    .lower()
                )
                if scan_ans in ("y", "yes"):
                    r1 = input("Start ID [1]: ").strip() or "1"
                    r2 = input("End ID [252]: ").strip() or "252"
                    id_min, id_max = int(r1), int(r2)

                    def _prog(sid: int, step: int, total: int) -> None:
                        print(
                            f"\rScanning id {sid} ({step}/{total})", end="", flush=True
                        )

                    try:
                        found = scan_scservo_ids(
                            dev,
                            baudrate=baud,
                            protocol_end=end,
                            id_min=id_min,
                            id_max=id_max,
                            on_progress=_prog,
                        )
                    except (ValueError, OSError) as e:
                        print(f"\nScan failed: {e}")
                        continue
                    print()
                    if found:
                        print("Found:")
                        for row in found:
                            print(f"  ID {row['id']:3d}  model {row['model']}")
                    else:
                        print("No servos responded in that range.")
                    default_ids = " ".join(str(x["id"]) for x in found)
                    ids_s = input(f"Servo IDs to use [{default_ids}]: ").strip()
                    if not ids_s:
                        if not found:
                            print("No IDs to connect with. Aborting connect.")
                            continue
                        ids = [x["id"] for x in found]
                    else:
                        ids = _parse_int_list(ids_s)
                else:
                    ids_s = input(
                        "Servo IDs (comma or space separated, e.g. 30 31): "
                    ).strip()
                    ids = _parse_int_list(ids_s)
            except ValueError as e:
                print(f"Invalid number: {e}")
                continue

            probe = input("Ping servos before connect? [y/N]: ").strip().lower()
            if probe in ("y", "yes"):
                ok, msg = check_scservo_port(dev, ids, baudrate=baud, protocol_end=end)
                if not ok:
                    print(f"Ping check failed: {msg}")
                    cont = input("Connect anyway? [y/N]: ").strip().lower()
                    if cont not in ("y", "yes"):
                        continue

            ctrl = ServoController(dev, ids, baudrate=baud, protocol_end=end)
            try:
                ctrl.connect()
            except Exception as e:
                print(f"connect failed: {e}")
                ctrl = None
            else:
                print(
                    f"Connected to {dev!r}, IDs={ids}, baud={baud}, protocol_end={end}"
                )
            continue

        if cmd == "disconnect":
            if ctrl and ctrl.connected:
                ctrl.disconnect()
                print("Disconnected.")
            else:
                print("Not connected.")
            ctrl = None
            continue

        if ctrl is None or not ctrl.connected:
            print("Not connected. Use 'connect' first.")
            continue

        if cmd == "read" or cmd == "r":
            try:
                data = ctrl.read_positions()
                for i, sid in enumerate(ctrl.servo_ids):
                    print(f"  ID {sid}: position={data[i]}")
            except Exception as e:
                print(f"read failed: {e}")
            continue

        if cmd == "goal" or cmd == "g":
            if len(parts) < 2:
                print(
                    f"Usage: goal <pos1> [pos2 ...] ({ctrl.num_servos} values required)"
                )
                continue
            try:
                positions = [int(x) for x in parts[1:]]
            except ValueError:
                print("Positions must be integers.")
                continue
            if len(positions) != ctrl.num_servos:
                print(
                    f"Need exactly {ctrl.num_servos} goal values, got {len(positions)}."
                )
                continue
            try:
                ctrl.set_positions(positions)
                print("Goal positions sent.")
            except Exception as e:
                print(f"goal failed: {e}")
            continue

        if cmd == "torque":
            if len(parts) < 2 or parts[1].lower() not in ("on", "off", "1", "0"):
                print("Usage: torque on|off")
                continue
            on = parts[1].lower() in ("on", "1")
            try:
                for sid in ctrl.servo_ids:
                    ctrl.set_torque_enable(sid, on)
                print(f"Torque {'enabled' if on else 'disabled'} for all IDs.")
            except Exception as e:
                print(f"torque failed: {e}")
            continue

        if cmd == "acc":
            if len(parts) < 2:
                print("Usage: acc <value>")
                continue
            try:
                v = int(parts[1])
                for sid in ctrl.servo_ids:
                    ctrl.set_acceleration(sid, v)
                print("Acceleration set for all IDs.")
            except Exception as e:
                print(f"acc failed: {e}")
            continue

        if cmd == "speed":
            if len(parts) < 2:
                print("Usage: speed <value>")
                continue
            try:
                v = int(parts[1])
                for sid in ctrl.servo_ids:
                    ctrl.set_speed(sid, v)
                print("Speed set for all IDs.")
            except Exception as e:
                print(f"speed failed: {e}")
            continue

        print(f"Unknown command {cmd!r}. Type 'help'.")

    if ctrl and ctrl.connected:
        ctrl.disconnect()


def main() -> None:
    run_interactive_console()


if __name__ == "__main__":
    main()
