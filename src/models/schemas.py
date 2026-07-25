from pydantic import BaseModel, Field, field_validator
from typing import Tuple
from datetime import datetime
import math

class SensorPayload(BaseModel):
    node_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    temperature_c: float
    smoke_ppm: float
    flame_presence: float  #0.0 = no flame, 1.0 = flame detected
    occupant_count: int

    @field_validator('temperature_c')
    @classmethod
    def validate_temp(cls, v: float) -> float:
        if v < -10 or v > 600:
            raise ValueError(f"Temperature out of realistic range [-10, 600]: {v}")
        return v

    @field_validator('smoke_ppm')
    @classmethod
    def validate_smoke(cls, v: float) -> float:
        return max(0.0, min(3000.0, v)) 

    @field_validator('flame_presence')
    @classmethod
    def validate_flame(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @field_validator('occupant_count')
    @classmethod
    def validate_occupancy(cls, v: int) -> int:
        return max(0, v)


class HazardIndex(BaseModel):
    zone_id: str
    raw_temp: float
    raw_smoke: float
    raw_flame: float
    raw_occupancy: int
    normalized_temp: float = 0.0
    normalized_smoke: float = 0.0
    normalized_flame: float = 0.0
    normalized_occ: float = 0.0
    combined_score: float = 0.0
    is_blocked: bool = False

    def compute(self, alpha: float = 0.4, beta: float = 0.3,
                gamma: float = 0.2, delta: float = 0.1) -> 'HazardIndex':
        self.normalized_temp = 1 / (1 + math.exp(-0.02 * (self.raw_temp - 60)))
        self.normalized_smoke = 1 / (1 + math.exp(-0.005 * (self.raw_smoke - 400)))
        self.normalized_flame = min(1.0, self.raw_flame * 1.25)
        self.normalized_occ = min(1.0, self.raw_occupancy / 50.0)
        
        raw_sum = (alpha * self.normalized_temp +
                   beta * self.normalized_smoke +
                   gamma * self.normalized_flame +
                   delta * self.normalized_occ)
        
        self.combined_score = math.exp(raw_sum) - 1.0
        
        if self.raw_flame > 0.9 or self.raw_temp > 250.0:
            self.is_blocked = True
            self.combined_score = float('inf')
        
        return self