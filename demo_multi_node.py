import time
import threading
import math

from src.loaders.config_loader import load_building_config
from src.firmware.node import FirmwareNode
from src.comms.message_bus import NodeComms
from src.models.schemas import SensorPayload
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def run_node(node_id: str, source_zone: str, hazard_data: dict):
    _, graph = load_building_config("config/building_layout.yaml")
    zone_ids = list(graph.nodes)
    zone_capacities = {node: graph.nodes[node]['capacity'] for node in zone_ids}

    node = FirmwareNode(node_id, graph, zone_ids, zone_capacities)
    node.set_source(source_zone)

    comms = NodeComms(node_id)

    def on_remote_hazard(payload):
        if payload['node_id'] != node_id:
            node.merge_remote_hazard(payload['zone_id'], payload['hazard_score'])
            logger.info(f"[{node_id}] Remote hazard: {payload['zone_id']} = {payload['hazard_score']:.2f} from {payload['node_id']}")

    comms.subscribe_to_hazards(on_remote_hazard)

    for step in range(15):
        payloads = []
        for zid in zone_ids:
            if zid in hazard_data and step >= hazard_data[zid]['start']:
                t = step - hazard_data[zid]['start']
                factor = 1 - math.exp(-0.6 * t) if hazard_data[zid].get('type', 'flashover') == 'flashover' else min(1, t/10)
                temp = 22 + (hazard_data[zid]['peak'] - 22) * factor
                smoke = 10 + (hazard_data[zid]['smoke'] - 10) * factor
                flame = min(1, hazard_data[zid]['flame'] * factor * 2)
            else:
                temp, smoke, flame = 22.0, 10.0, 0.0

            occ = int(zone_capacities[zid] * 0.8 * max(0, (1 - step / 30)))
            payloads.append(SensorPayload(
                node_id=zid,
                temperature_c=temp,
                smoke_ppm=smoke,
                flame_presence=flame,
                occupant_count=occ
            ))

        result = node.process_sensor_data(payloads)
        logger.info(f"[{node_id}] Path: {' → '.join(result['path'])}")

        for zid, score in result['hazard_scores'].items():
            if score > 0.5:
                comms.publish_hazard(zid, score)

        time.sleep(2)

    logger.info(f"[{node_id}] Finished.")


if __name__ == "__main__":
    hazards = [
        {'stairwell': {'start': 2, 'peak': 350, 'smoke': 1800, 'flame': 0.95, 'type': 'flashover'}},
        {'main_exit': {'start': 4, 'peak': 400, 'smoke': 2000, 'flame': 1.0, 'type': 'flashover'}},
        {'office_a': {'start': 6, 'peak': 250, 'smoke': 800, 'flame': 0.7, 'type': 'smoldering'}}
    ]

    nodes = [
        ("node_1", "office_c", hazards[0]),
        ("node_2", "lobby", hazards[1]),
        ("node_3", "office_a", hazards[2]),
    ]

    threads = []
    for node_id, source, hazard in nodes:
        t = threading.Thread(target=run_node, args=(node_id, source, hazard), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.5)  

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        logger.info("Stopping...")