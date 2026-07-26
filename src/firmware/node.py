import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

from ..models.schemas import SensorPayload
from ..hazard.hazard_engine import HazardEngine
from ..routing.pathfinder import Pathfinder
from ..utils.logger import setup_logger

logger = setup_logger(__name__)


class LEDState(Enum):
    SAFE = "green"
    HAZARD = "yellow"
    DANGER = "pulsing_red"
    OFF = "off"


@dataclass
class ZoneActuatorState:
    """State of LED and buzzer for a single zone."""
    led_color: LEDState = LEDState.OFF
    led_direction: Optional[str] = None   
    buzzer_active: bool = False
    last_update: float = field(default_factory=time.time)


class FirmwareNode:
    def __init__(self, node_id: str, graph, zone_ids: List[str], zone_capacities: Dict[str, int]):
        self.node_id = node_id
        self.graph = graph
        self.zone_ids = zone_ids
        self.hazard_engine = HazardEngine(zone_ids, zone_capacities)
        self.pathfinder = Pathfinder(graph)
        self.actuators: Dict[str, ZoneActuatorState] = {
            zid: ZoneActuatorState() for zid in zone_ids
        }
        self.source_zone = "office_c"   
        self.last_path = []
        self.last_exit = None
        self.current_hazard_scores = {}

    def process_sensor_data(self, payloads: List[SensorPayload]) -> Dict:
        self.current_hazard_scores = self.hazard_engine.update(payloads)

        path_result = self.pathfinder.find_path(self.source_zone, self.current_hazard_scores)
        path = path_result.get('path', [])
        exit_node = path_result.get('exit_node')

        self._update_actuators(path, exit_node)

        return {
            'hazard_scores': self.current_hazard_scores,
            'path': path,
            'exit_node': exit_node,
            'actuators': self.get_actuator_state()
        }

    def _update_actuators(self, path: List[str], exit_node: Optional[str]) -> None:
        path_changed = (path != self.last_path)
        self.last_path = path
        self.last_exit = exit_node

        for zone_id in self.zone_ids:
            state = self.actuators[zone_id]
            score = self.current_hazard_scores.get(zone_id, 0.0)

            if score == float('inf') or score > 100.0:
                state.led_color = LEDState.DANGER
                state.buzzer_active = True
            elif score > 2.0:
                state.led_color = LEDState.DANGER
                state.buzzer_active = False
            elif score > 0.5:
                state.led_color = LEDState.HAZARD
                state.buzzer_active = False
            else:
                state.led_color = LEDState.SAFE
                state.buzzer_active = False

            if zone_id in path and len(path) > 1:
                idx = path.index(zone_id)
                if idx < len(path) - 1:
                    next_zone = path[idx + 1]
                    state.led_direction = f"→ {next_zone}"
                else:
                    state.led_direction = f"→ EXIT ({exit_node})"
            else:
                if state.led_color == LEDState.DANGER:
                    state.led_direction = "STAY AWAY"
                else:
                    state.led_direction = "↺"

            if path_changed and zone_id in path:
                logger.debug(f"[LED] {zone_id} direction: {state.led_direction}")

        if not path:
            for state in self.actuators.values():
                state.buzzer_active = True
            logger.critical("[FIRMWARE] NO PATH Buzzer active on all zones")

        if path_changed:
            if path:
                logger.info(f"[FIRMWARE] Path set: {' -> '.join(path)} | Exit: {exit_node}")
            else:
                logger.critical("[FIRMWARE] NO PATH Buzzer active on all zones")

    def get_actuator_state(self) -> Dict[str, Dict]:
        return {
            zid: {
                'led': state.led_color.value,
                'direction': state.led_direction,
                'buzzer': state.buzzer_active
            } for zid, state in self.actuators.items()
        }

    def set_source(self, zone_id: str) -> None:
        if zone_id in self.zone_ids:
            self.source_zone = zone_id
            logger.info(f"Source zone changed to {zone_id}")

    def merge_remote_hazard(self, zone_id: str, score: float) -> None:
        self.hazard_engine.update_remote_hazard(zone_id, score)