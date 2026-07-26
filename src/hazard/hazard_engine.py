from typing import Dict, List, Optional
from ..models.schemas import SensorPayload, HazardIndex
from ..utils.logger import setup_logger

logger = setup_logger(__name__)


class HazardEngine:
    def __init__(self, zone_ids: List[str], zone_capacities: Optional[Dict[str, int]] = None):
        self.zone_ids = set(zone_ids)
        self.zone_capacities = zone_capacities or {zid: 20 for zid in zone_ids}
        self.last_hazard_scores: Dict[str, float] = {zid: 0.0 for zid in zone_ids}
        self.last_blocked_state: Dict[str, bool] = {zid: False for zid in zone_ids}
        self.remote_hazard_scores: Dict[str, float] = {}
        logger.info(f"HazardEngine initialized for {len(zone_ids)} zones")

    def update(self, sensor_data: List[SensorPayload]) -> Dict[str, float]:
        new_scores = self.last_hazard_scores.copy()

        for payload in sensor_data:
            zone_id = payload.node_id
            if zone_id not in self.zone_ids:
                logger.warning(f"Sensor '{zone_id}' not in building, ignoring.")
                continue

            try:
                hazard = HazardIndex(
                    zone_id=zone_id,
                    raw_temp=payload.temperature_c,
                    raw_smoke=payload.smoke_ppm,
                    raw_flame=payload.flame_presence,
                    raw_occupancy=payload.occupant_count
                ).compute()
                new_scores[zone_id] = hazard.combined_score
                is_blocked = hazard.is_blocked
            except Exception as e:
                logger.warning(f"Failed to compute hazard for {zone_id}: {e}. Using last known score")
                continue

            was_blocked = self.last_blocked_state.get(zone_id, False)
            if is_blocked and not was_blocked:
                logger.critical(f"ZONE BLOCKED: {zone_id} | Temp={payload.temperature_c:.1f}°C, Flame={payload.flame_presence:.2f}")
            elif not is_blocked and was_blocked:
                logger.info(f"ZONE RECOVERED: {zone_id}")
            self.last_blocked_state[zone_id] = is_blocked

        for zid, remote_score in self.remote_hazard_scores.items():
            if zid in new_scores and remote_score > new_scores[zid]:
                new_scores[zid] = remote_score
                if remote_score >= float('inf'):
                    self.last_blocked_state[zid] = True

        self.last_hazard_scores = new_scores
        return new_scores

    def get_current_scores(self) -> Dict[str, float]:
        merged = self.last_hazard_scores.copy()
        for zid, remote_score in self.remote_hazard_scores.items():
            if zid in merged and remote_score > merged[zid]:
                merged[zid] = remote_score
        return merged

    def update_remote_hazard(self, zone_id: str, score: float) -> None:
        if zone_id not in self.zone_ids:
            logger.warning(f"Remote hazard for unknown zone {zone_id}")
            return
        self.remote_hazard_scores[zone_id] = max(
            self.remote_hazard_scores.get(zone_id, 0.0),
            score
        )