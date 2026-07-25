import networkx as nx
from typing import Dict, List, Optional

from ..utils.logger import setup_logger

logger = setup_logger(__name__)


class Pathfinder:
    def __init__(self, graph: nx.Graph):
        self.graph = graph

        self.exits = [
            node for node, data in graph.nodes(data=True)
            if data.get('is_exit', False)
        ]
        if not self.exits:
            raise ValueError("Building graph has no exit nodes, Check YAML")
            
        self.last_path_available = True
        logger.info(f"Pathfinder ready Exits: {self.exits}")

    def find_path(self, start_zone: str, hazard_scores: Dict[str, float]) -> Dict:
        if start_zone not in self.graph:
            logger.error(f"Start zone '{start_zone}' not in graph")
            return self._empty_result("Start zone invalid")
        
        def edge_weight(u: str, v: str, edge_attrs: Dict) -> float:
            base_cost = edge_attrs.get('weight', 1.0)

            h_u = hazard_scores.get(u, 0.0)
            h_v = hazard_scores.get(v, 0.0)
            effective_hazard = max(h_u, h_v)

            if effective_hazard >= float('inf'):
                return float('inf')

            return base_cost * (1.0 + effective_hazard)

        best_exit = None
        best_path = None
        best_cost = float('inf')

        for exit_node in self.exits:
            try:
                path_length, path = nx.single_source_dijkstra(
                    self.graph,
                    source=start_zone,
                    target=exit_node,
                    weight=edge_weight
                )
                if path_length < best_cost:
                    best_cost = path_length
                    best_path = path
                    best_exit = exit_node
            except nx.NetworkXNoPath:
                continue

        if best_path is None:
            if self.last_path_available:
                logger.warning(f"No reachable exit from {start_zone} with given hazards")
                self.last_path_available = False
            return self._empty_result("All exits blocked or unreachable")

        if not self.last_path_available:
            logger.info(f"PATH RESTORED: {start_zone} -> {best_exit} (cost {best_cost:.1f})")
            self.last_path_available = True

        return {
            'path': best_path,
            'total_cost': best_cost,
            'exit_node': best_exit,
            'message': f"Evacuate via {best_exit} (cost {best_cost:.1f})"
        }

    def _empty_result(self, message: str) -> Dict:
        return {
            'path': [],
            'total_cost': float('inf'),
            'exit_node': None,
            'message': message
        }


if __name__ == "__main__":
    from ..loaders.config_loader import load_building_config

    try:
        building_name, graph = load_building_config("config/building_layout.yaml")
        print(f"Loaded '{building_name}' – {graph.number_of_nodes()} zones, {graph.number_of_edges()} corridors")
        pf = Pathfinder(graph)

        print("\nTest 1: No hazards (from 'office_c')")
        result = pf.find_path("office_c", {})
        print(f"   Path: {' -> '.join(result['path'])}")
        print(f"   Exit: {result['exit_node']} | Cost: {result['total_cost']:.2f}")
        print(f"   Message: {result['message']}")

        print("\nTest 2: Block 'fire_exit' (from 'office_c')")
        hazard_block = {"fire_exit": float('inf')}
        result = pf.find_path("office_c", hazard_block)
        print(f"   Path: {' -> '.join(result['path'])}")
        print(f"   Exit: {result['exit_node']} | Cost: {result['total_cost']:.2f}")
        print(f"   Message: {result['message']}")

        print("\nTest 3: Block 'stairwell' (from 'office_c')")
        hazard_block = {"stairwell": float('inf')}
        result = pf.find_path("office_c", hazard_block)
        print(f"   Path: {' -> '.join(result['path'])}")
        print(f"   Exit: {result['exit_node']} | Cost: {result['total_cost']:.2f}")
        print(f"   Message: {result['message']}")

    except Exception as e:
        print(f"Error during test: {e}")