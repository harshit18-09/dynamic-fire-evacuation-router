import yaml
import networkx as nx
from pydantic import BaseModel, field_validator, ValidationError
from typing import List, Optional, Tuple
from pathlib import Path

class NeighborModel(BaseModel):
    target: str
    cost: float

    @field_validator('cost')
    @classmethod
    def cost_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"Edge cost must be > 0, got {v}")
        return v

class ZoneModel(BaseModel):
    id: str
    type: str
    capacity: int
    is_exit: bool
    sensor_id: str
    neighbors: List[NeighborModel]

    @field_validator('capacity')
    @classmethod
    def capacity_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"Capacity cannot be negative, got {v}")
        return v

class BuildingConfig(BaseModel):
    building_name: str
    zones: List[ZoneModel]

def load_building_config(yaml_path: str | Path) -> Tuple[str, nx.Graph]:
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"Building config not found: {yaml_path}")
    
    with open(yaml_path, 'r', encoding='utf-8') as f:
        raw_data = yaml.safe_load(f)
    
    try:
        config = BuildingConfig(**raw_data)
    except ValidationError as e:
        raise ValueError(f"YAML validation failed in {yaml_path}:\n{e}")
    G = nx.Graph()
    
    zone_ids = {zone.id for zone in config.zones}
    
    for zone in config.zones:
        G.add_node(
            zone.id,
            type=zone.type,
            capacity=zone.capacity,
            is_exit=zone.is_exit,
            sensor_id=zone.sensor_id
        )

    for zone in config.zones:
        for neighbor in zone.neighbors:
            if neighbor.target not in zone_ids:
                raise ValueError(
                    f"Zone '{zone.id}' points to neighbor '{neighbor.target}', "
                    f"but '{neighbor.target}' does not exist in the zone list."
                )
            G.add_edge(zone.id, neighbor.target, weight=neighbor.cost)

    if not nx.is_connected(G):
        components = list(nx.connected_components(G))
        raise ValueError(
            f"Building graph is not fully connected! Found {len(components)} components. "
            f"Check your neighbor links. Components: {components}"
        )
    
    return config.building_name, G


if __name__ == "__main__":
    try:
        name, graph = load_building_config("config/building_layout.yaml")
        print(f"Loaded building: {name}")
        print(f"   Nodes: {graph.number_of_nodes()}")
        print(f"   Edges: {graph.number_of_edges()}")
        print(f"   Exits: {[n for n, d in graph.nodes(data=True) if d['is_exit']]}")
        
        print("\n   Sample edges (first 5):")
        for i, (u, v, data) in enumerate(list(graph.edges(data=True))[:5]):
            print(f"      {u} <-> {v} (cost: {data['weight']})")
        
    except Exception as e:
        print(f"Error: {e}")