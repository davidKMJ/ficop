from __future__ import annotations

import time

from cua.ficop import Compose, ManualOptimizer, TwoKnobOptimizer
from cua.ficop.dummy import DummyController, DummyLogger

SERVO_IDS = [30, 31, 80, 81]
INITIAL_POSITIONS = [400, -300, 250, -350]

CENTER = [200, -150, 100, -50]
SIGMA = 100.0
NOISE = 0.001

MIN_POSITION = -15000
MAX_POSITION = 15000


def build_pipeline(logger: DummyLogger, servos: DummyController) -> Compose:
    base = dict(
        logger=logger,
        servo_controller=servos,
        min_position=MIN_POSITION,
        max_position=MAX_POSITION,
        wait_for_value=0.0,
        verbose=True,
    )

    coarse_manual = ManualOptimizer(
        **base,
        iterations=5,
        margin=500,
        step=10,
        margin_decay=1.5,
        no_update_count_early_stop=False,
    )

    two_knob = TwoKnobOptimizer(
        **base,
        iterations=10,
        step=5,
        pairs=[(0, 3), (1, 2)],
        direction_update_interval=5,
        no_update_count_threshold=10,
    )

    fine_manual = ManualOptimizer(
        **base,
        iterations=5,
        margin=50,
        step=4,
        margin_decay=1.0,
        no_update_count_early_stop=True,
        no_update_count_threshold=5,
    )

    return Compose([coarse_manual, two_knob, fine_manual])


def main() -> None:
    print("=" * 60)
    print("ficop dummy optimization")
    print("=" * 60)

    servos = DummyController(
        servo_ids=SERVO_IDS,
        initial_positions=INITIAL_POSITIONS,
    )
    logger = DummyLogger(servos, center=CENTER, sigma=SIGMA, noise=NOISE)

    servos.connect(verbose=True)
    servos.configure_servos(acc=0, speed=0)
    logger.connect()

    try:
        print(f"Initial positions: {servos.read_positions()}")
        print(f"Initial merit:     {logger.get_current_value(1)[0]:.6f}")

        pipeline = build_pipeline(logger, servos)

        t0 = time.perf_counter()
        best = pipeline.run()
        duration = time.perf_counter() - t0

        print()
        print("=" * 60)
        print(f"Best merit reported by Compose: {best:.6f}")
        print(f"Final positions:                {servos.read_positions()}")
        print(f"Final merit (re-read):          {logger.get_current_value(1)[0]:.6f}")
        print(f"Wall-clock duration:            {duration:.2f} s")
        print("=" * 60)
    finally:
        logger.disconnect()
        servos.disconnect()


if __name__ == "__main__":
    main()
