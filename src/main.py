import argparse
import signal
import sys
from pathlib import Path

from .loaders.config_loader import load_building_config
from .hazard.hazard_engine import HazardEngine
from .routing.pathfinder import Pathfinder
from .simulation.digital_twin import DigitalTwin
from .utils.logger import setup_logger

logger = setup_logger(__name__)


def create_default_scenario(scenario_path: str) -> None:
    path = Path(scenario_path)
    if path.exists():
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    default_scenario = """# Default scenario: Flashover in the stairwell
# This file is auto-generated for demo purposes.

zones:
  - id: "stairwell"
    fire_type: "flashover"
    start_time: 10.0
    peak_temp: 350
    peak_smoke: 1800
    flame_probability: 0.95
    growth_rate: 0.6

  - id: "office_a"
    fire_type: "smoldering"
    start_time: 25.0
    peak_temp: 120
    peak_smoke: 400
    flame_probability: 0.2
    growth_rate: 0.05

  - id: "office_d"
    fire_type: "smoldering"
    start_time: 30.0
    peak_temp: 100
    peak_smoke: 350
    flame_probability: 0.1
    growth_rate: 0.04
"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(default_scenario)

    logger.info(f"Created default scenario file: {path}")


class EvacuationSystem:
    def __init__(self, building_yaml: str, scenario_yaml: str,
                 source_zone: str, speed: float = 1.0,
                 step_interval: float = 0.2, max_duration: float = 120.0):
        self.building_yaml = building_yaml
        self.scenario_yaml = scenario_yaml
        self.source_zone = source_zone
        self.speed = speed
        self.step_interval = step_interval
        self.max_duration = max_duration

        self.hazard_engine = None
        self.pathfinder = None
        self.twin = None
        self.graph = None
        self.zone_capacities = None   

        self.is_running = False

    def setup(self):
        logger.info("=" * 60)
        logger.info("Dynamic Fire Evacuation Router Started")
        logger.info("=" * 60)

        create_default_scenario(self.scenario_yaml)
        building_name, self.graph = load_building_config(self.building_yaml)
        zone_ids = list(self.graph.nodes)
        logger.info(f"Building: {building_name} ({len(zone_ids)} zones)")

        if self.source_zone not in zone_ids:
            logger.error(f"Source zone '{self.source_zone}' not found in building!")
            logger.info(f"Available zones: {zone_ids}")
            sys.exit(1)

        logger.info(f"Evacuation source: {self.source_zone}")

        self.zone_capacities = {
            node: self.graph.nodes[node]['capacity'] for node in self.graph.nodes
        }
        self.hazard_engine = HazardEngine(zone_ids, self.zone_capacities)
        self.pathfinder = Pathfinder(self.graph)

        self.twin = DigitalTwin(
            self.hazard_engine,
            self.pathfinder,
            self.zone_capacities
        )
        self.twin.source_zone = self.source_zone

        logger.info("System ready. Starting simulation...")

    def run(self):
        if not self.twin:
            self.setup()

        self.is_running = True

        def signal_handler(sig, frame):
            logger.info("Shutdown signal received. Stopping...")
            self.is_running = False
            self.twin.is_running = False
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            last_logged_path = None

            def console_callback(data):
                nonlocal last_logged_path
                path = data['path_result']['path']
                time_now = data['time']
                exit_node = data['path_result'].get('exit_node')
                cost = data['path_result'].get('total_cost', 0.0)

                if path and path != last_logged_path:
                    logger.info(f"[t={time_now:.1f}s] PATH CHANGED")
                    if last_logged_path is not None:
                        logger.info(f"Old: {' -> '.join(last_logged_path)}")
                    logger.info(f"New: {' -> '.join(path)}")
                    if exit_node:
                        logger.info(f"Via exit: {exit_node} (cost {cost:.1f})")
                    last_logged_path = path
                elif not path and last_logged_path is not None:
                    logger.critical(f"[t={time_now:.1f}s] NO PATH AVAILABLE")
                    if last_logged_path is not None:
                        logger.info(f"   Last path: {' -> '.join(last_logged_path)}")
                    logger.info(f"   Message: {data['path_result']['message']}")
                    last_logged_path = None

            self.twin.run(
                scenario_path=self.scenario_yaml,
                speed_multiplier=self.speed,
                step_interval=self.step_interval,
                max_duration=self.max_duration,
                callback=console_callback
            )
        except KeyboardInterrupt:
            logger.info("Simulation interrupted by user")
        finally:
            self.is_running = False
            logger.info("System shutdown complete")


def main():
    parser = argparse.ArgumentParser(
        description="Dynamic Fire Evacuation Router",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main --source office_c --speed 2.0
  python -m src.main --source lobby --scenario custom_scenario.yaml
  python -m src.main --source office_a --duration 60 --speed 3.0
        """
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default="config/scenarios/flashover_stairwell.yaml",
        help="Path to the fire scenario YAML file"
    )
    parser.add_argument(
        "--building",
        type=str,
        default="config/building_layout.yaml",
        help="Path to the building layout YAML file."
    )
    parser.add_argument(
        "--source",
        type=str,
        default="office_c",
        help="Zone ID where evacuees are located which is the starting point"
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speed multiplier"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=120.0,
        help="Max simulation duration in seconds (simulated time)."
    )
    parser.add_argument(
        "--step",
        type=float,
        default=0.2,
        help="Simulation step interval in seconds (default 200ms)."
    )

    args = parser.parse_args()
    if not Path(args.building).exists():
        print(f"Building file not found: {args.building}")
        print("Create one or adjust the path.")
        sys.exit(1)

    system = EvacuationSystem(
        building_yaml=args.building,
        scenario_yaml=args.scenario,
        source_zone=args.source,
        speed=args.speed,
        step_interval=args.step,
        max_duration=args.duration
    )
    system.setup()
    system.run()


if __name__ == "__main__":
    main()