import time
import math
import yaml
from typing import Dict, List, Optional, Callable, Tuple
from datetime import datetime
from pathlib import Path

from ..models.schemas import SensorPayload
from ..hazard.hazard_engine import HazardEngine
from ..routing.pathfinder import Pathfinder
from ..utils.logger import setup_logger

logger = setup_logger(__name__)


class ZoneFireProfile:
    def __init__(self, data: dict):
        self.zone_id = data['id']
        self.fire_type = data.get('fire_type', 'smoldering')  
        self.start_time = data.get('start_time', 0.0)
        self.peak_temp = data.get('peak_temp', 200.0)
        self.peak_smoke = data.get('peak_smoke', 1000.0)
        self.flame_probability = data.get('flame_probability', 0.0)
        self.occupant_factor = data.get('occupant_factor', 1.0)  

        self.growth_rate = data.get('growth_rate', 0.08)  

    def get_readings(self, elapsed_time: float) -> Tuple[float, float, float]:
        if elapsed_time < self.start_time:
            return 22.0, 10.0, 0.0

        t = elapsed_time - self.start_time

        if self.fire_type == 'flashover':
            factor = 1.0 - math.exp(-0.6 * t)  
            temp = 22.0 + (self.peak_temp - 22.0) * min(1.0, factor)
            smoke = 10.0 + (self.peak_smoke - 10.0) * min(1.0, factor)
            flame = min(1.0, self.flame_probability * (1.0 - math.exp(-0.8 * t)))

            if t > 5.0 and self.flame_probability > 0.5:
                flame = 1.0

        else:
            growth = self.growth_rate
            midpoint = 30.0 

            logistic = 1.0 / (1.0 + math.exp(-growth * (t - midpoint)))

            temp = 22.0 + (self.peak_temp - 22.0) * logistic
            smoke = 10.0 + (self.peak_smoke - 10.0) * logistic
            flame = min(1.0, self.flame_probability * logistic)

        temp = max(22.0, min(600.0, temp))
        smoke = max(0.0, min(3000.0, smoke))
        flame = max(0.0, min(1.0, flame))

        return temp, smoke, flame


class DigitalTwin:
    def __init__(self, hazard_engine: HazardEngine, pathfinder: Pathfinder, zone_capacities: Optional[Dict[str, int]] = None):
        self.hazard_engine = hazard_engine
        self.pathfinder = pathfinder
        self.zone_ids = list(hazard_engine.zone_ids)
        self.zone_capacities = zone_capacities or {zid: 20 for zid in self.zone_ids}   
        self.fire_profiles: Dict[str, ZoneFireProfile] = {}
        self.current_time = 0.0
        self.is_running = False
        self.callback_on_update: Optional[Callable] = None
        self.last_path_result = None
        self.source_zone = 'office_c'

    def load_scenario(self, scenario_path: str | Path) -> None:
        scenario_path = Path(scenario_path)
        if not scenario_path.exists():
            raise FileNotFoundError(f"Scenario not found: {scenario_path}")

        with open(scenario_path, 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f)

        self.fire_profiles.clear()

        for zone_data in raw.get('zones', []):
            profile = ZoneFireProfile(zone_data)
            if profile.zone_id not in self.zone_ids:
                logger.warning(f"Scenario references unknown zone '{profile.zone_id}'")
                continue
            self.fire_profiles[profile.zone_id] = profile

        logger.info(f"Loaded scenario '{scenario_path.name}' with {len(self.fire_profiles)} active fire zones")
        if not self.fire_profiles:
            logger.warning("Scenario has no fire zones, Simulation will run with safe readings only")

    def step(self, dt: float = 0.2) -> Dict:
        self.current_time += dt

        sensor_batch = []
        for zone_id in self.zone_ids:
            capacity = self.zone_capacities.get(zone_id, 20)

            if zone_id in self.fire_profiles:
                profile = self.fire_profiles[zone_id]
                temp, smoke, flame = profile.get_readings(self.current_time)
                base_occ = int(capacity * 0.8 * max(0, (1 - self.current_time / 60.0)))
                occ = int(base_occ * getattr(profile, 'occupant_factor', 1.0))
            else:
                temp = 22.0 + 0.5 * math.sin(self.current_time * 0.01)  
                smoke = 10.0 + 2.0 * math.sin(self.current_time * 0.02)
                flame = 0.0
                occ = max(0, int(capacity * 0.3))  

            try:
                payload = SensorPayload(
                    node_id=zone_id,
                    temperature_c=temp,
                    smoke_ppm=smoke,
                    flame_presence=flame,
                    occupant_count=occ
                )
                sensor_batch.append(payload)
            except Exception as e:
                logger.warning(f"Corrupted sensor data for {zone_id}: {e}. Skipping this reading.")
                continue

        hazard_scores = self.hazard_engine.update(sensor_batch)

        source_zone = self.source_zone
        if source_zone not in self.zone_ids:
            source_zone = list(self.zone_ids)[0]  

        path_result = self.pathfinder.find_path(source_zone, hazard_scores)

        if self.last_path_result is None or path_result['path'] != self.last_path_result['path']:
            if path_result['path']:
                logger.info(f"PATH CHANGED at t={self.current_time:.1f}s")
                logger.info(f"New path: {' -> '.join(path_result['path'])}")
                logger.info(f"Via exit: {path_result['exit_node']} (cost {path_result['total_cost']:.1f})")
            else:
                logger.critical(f"NO PATH AVAILABLE at t={self.current_time:.1f}s - {path_result['message']}")

        self.last_path_result = path_result

        if self.callback_on_update:
            self.callback_on_update({
                'timestamp': datetime.now().isoformat(),
                'time': self.current_time,
                'hazard_scores': hazard_scores,
                'path_result': path_result,
                'sensor_batch': sensor_batch
            })

        return {
            'hazard_scores': hazard_scores,
            'path_result': path_result,
            'time': self.current_time
        }

    def run(self, scenario_path: str, speed_multiplier: float = 1.0,
            step_interval: float = 0.2, max_duration: float = None,
            callback: Optional[Callable] = None) -> None:
        self.load_scenario(scenario_path)
        self.callback_on_update = callback
        self.is_running = True
        self.current_time = 0.0
        self.last_path_result = None

        logger.info(f"Simulation started. Speed: {speed_multiplier}x, Step: {step_interval}s")
        real_sleep = step_interval / speed_multiplier

        try:
            while self.is_running:
                start_step = time.perf_counter()
                self.step(step_interval)
                if max_duration and self.current_time >= max_duration:
                    logger.info(f"Simulation reached max duration ({max_duration}s) so Stopping")
                    break

                elapsed = time.perf_counter() - start_step
                if elapsed < real_sleep:
                    time.sleep(real_sleep - elapsed)

        except KeyboardInterrupt:
            logger.info("Simulation stopped by user")
        finally:
            self.is_running = False
            logger.info("Simulation ended")

    def trigger_flashover(self, zone_id: str) -> None:
        if zone_id not in self.zone_ids:
            logger.error(f"Cannot trigger flashover: '{zone_id}' is not a valid zone")
            return
        temp_profile = ZoneFireProfile({
            'id': zone_id,
            'fire_type': 'flashover',
            'start_time': 0.0,  
            'peak_temp': 400.0,
            'peak_smoke': 2000.0,
            'flame_probability': 1.0,
            'growth_rate': 0.8  
        })

        self.fire_profiles[zone_id] = temp_profile
        logger.critical(f"MANUAL TRIGGER for zone: {zone_id}")
        sensor_batch = []
        for zid in self.zone_ids:
            if zid == zone_id:
                sensor_batch.append(SensorPayload(
                    node_id=zid,
                    temperature_c=400.0,
                    smoke_ppm=2000.0,
                    flame_presence=1.0,
                    occupant_count=10
                ))
            else:
                sensor_batch.append(SensorPayload(
                    node_id=zid,
                    temperature_c=22.0,
                    smoke_ppm=10.0,
                    flame_presence=0.0,
                    occupant_count=5
                ))
        self.hazard_engine.update(sensor_batch)

        source_zone = self.source_zone
        if source_zone not in self.zone_ids:
            source_zone = list(self.zone_ids)[0]

        hazard_scores = self.hazard_engine.get_current_scores()
        path_result = self.pathfinder.find_path(source_zone, hazard_scores)
        self.last_path_result = path_result
        logger.info(f"Post flashover path: {' -> '.join(path_result['path'])}")

if __name__ == "__main__":
    from ..loaders.config_loader import load_building_config
    _, graph = load_building_config("config/building_layout.yaml")
    zone_ids = list(graph.nodes())

    zone_capacities = {node: graph.nodes[node]['capacity'] for node in graph.nodes}

    hazard_engine = HazardEngine(zone_ids, zone_capacities)  
    pathfinder = Pathfinder(graph)
    twin = DigitalTwin(hazard_engine, pathfinder, zone_capacities) 
    twin.source_zone = 'office_c' 

    def print_update(data):
        path = data['path_result']['path']
        if path:
            print(f"[t={data['time']:.1f}s] Path: {' -> '.join(path)}")

    print("\nRunning manual step test")
    twin.load_scenario("config/scenarios/flashover_stairwell.yaml")
    result = twin.step(0.2)
    print(f"Manual step result: {result['path_result']['message']}")
    print("Digital twin loaded and stepped successfully.")