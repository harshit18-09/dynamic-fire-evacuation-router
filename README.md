# 🚒 Dynamic Fire Evacuation Router

## Real‑Time Hazard‑Aware Evacuation Pathfinding

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.28%2B-FF4B4B)](https://streamlit.io/)
[![NetworkX](https://img.shields.io/badge/NetworkX-3.0-4CAF50)](https://networkx.org/)

---

## Overview

**Dynamic Fire Evacuation Router** is a complete simulation and visualisation platform for intelligent emergency evacuation. It ingests multi‑sensor data (temperature, smoke, flame, occupancy), fuses them into a dynamic hazard score, and continuously computes the safest evacuation path using Dijkstra’s algorithm with exponentially weighted edge costs. The system is designed for decentralised node networks (ESP32/STM32/Pico W) and includes a full‑featured dashboard for live monitoring, scenario injection, and actuator visualisation (LED matrix & buzzer).

---

## Key Features

- **Multi‑Sensor Fusion** – Combines thermal, particulate, optical, and occupancy data into a single **Hazard Index** using an exponential formula:  
  `H.I. = e^(α·T_norm + β·S_norm + γ·F + δ·O_norm) - 1`
- **Dynamic Pathfinding** – Edge costs are recalculated every simulation step (200 ms, well under the 300 ms requirement) using Dijkstra’s algorithm.
- **Real‑Time Rerouting** – As hazards evolve, the path is instantly recomputed; the dashboard highlights the new route and updates LED/buzzer status.
- **Digital Twin Simulator** – Injects realistic fire timelines (flashover, smoldering) via YAML scenarios, with configurable speed multiplier.
- **Multi‑Node Communication** – A built‑in in‑memory message bus (MQTT‑like) demonstrates how distributed nodes share hazard vectors.
- **Fire Commander Dashboard** – Streamlit‑based UI with a 2D floor grid, live hazard heatmap, path overlay, zone status table, event log, and manual flashover trigger.
- **Fail‑Safe Operation** – Graceful handling of corrupted sensor data, stale readings, and unreachable exits (falls back to last known safe state).
- **LED & Buzzer Simulation** – Emulates actuator states per zone (green/yellow/pulsing‑red) and audible alerts when no path exists.

---

##  Architecture

<img width="892" height="890" alt="image" src="https://github.com/user-attachments/assets/aff9bcab-a72e-4ded-98dc-2ce499bebcb0" />


All components are decoupled, allowing easy replacement of the simulation layer with real hardware (ESP32/Pico W running MicroPython).

---

## Project Structure
```
dynamic-fire-evacuation-router/
├── config/
│ ├── building_layout.yaml # Static building map (zones, exits, capacities, edges)
│ └── scenarios/
│ ├── flashover_stairwell.yaml # Fire scenario: stairwell flashover at t=10s
│ └── sequential_fire.yaml # Fire scenario: fire_exit blocks @5s, stairwell @15s
├── src/
│ ├── init.py
│ ├── models/
│ │ └── schemas.py # SensorPayload, HazardIndex (exponential fusion)
│ ├── utils/
│ │ └── logger.py # Coloured console logger with timestamps
│ ├── loaders/
│ │ └── config_loader.py # Loads YAML, builds NetworkX graph
│ ├── hazard/
│ │ └── hazard_engine.py # Fuses sensors, edge‑triggered logging, remote hazard merge
│ ├── routing/
│ │ └── pathfinder.py # Dijkstra with dynamic weights
│ ├── simulation/
│ │ └── digital_twin.py # Fire dynamics, scenario runner, path change detection
│ ├── firmware/
│ │ ├── init.py
│ │ └── node.py # Simulated MCU node (LED/buzzer states)
│ ├── comms/
│ │ ├── init.py
│ │ └── message_bus.py # In‑memory MQTT‑like pub/sub
│ └── main.py # CLI orchestrator (--source, --speed, --duration, etc.)
├── dashboard.py # Streamlit Fire Commander Dashboard
├── demo_multi_node.py # Multi‑node communication demo
├── requirements.txt
└── README.md
```


---

## Getting Started

### Prerequisites

- Python 3.10 or higher
- pip (or conda)

### 1. Clone the repository

```bash
git clone [https://github.com/yourusername/dynamic-fire-evacuation-router.git
cd dynamic-fire-evacuation-router](https://github.com/harshit18-09/dynamic-fire-evacuation-router.git)
```
### 2. Install dependencies

```bash
pip install -r requirements.txt
```
### 3. Run the CLI simulation (headless)

```bash
python -m src.main --source office_c --scenario config/scenarios/sequential_fire.yaml --speed 2.0
```
### 4. Launch the Dashboard

```bash
streamlit run dashboard.py
```

## Dashboard Controls

| Control | Description |
| :--- | :--- |
| **Scenario** | Choose between `Sequential Fire (2 reroutes)` or `Stairwell Flashover`. |
| **Evacuation Source** | Set the starting zone (e.g., `office_c`, `lobby`). |
| **Speed** | Multiplier for simulation speed (0.5× – 5×). |
| **Duration** | Max simulated time (seconds). |
| **Manual Flashover** | Select a zone and click “Trigger Flashover” to instantly block it and force rerouting. |
| **Start / Stop** | Begin or pause the simulation. |

The dashboard displays:
- **Live Hazard Map** – coloured nodes (green = safe, yellow = hazard, red = blocked).
- **Current Evacuation Path** – highlighted in blue.
- **Metrics** – Safe, Hazard, and Blocked zone counts.
- **Zone Status Table** – detailed scores per zone.
- **LED & Buzzer Status** – simulated LED colours and buzzer states for each zone.
- **Event Log** – timestamped events (path changes, zone blocks, manual triggers).

##  Screenshots
<img width="1867" height="810" alt="image" src="https://github.com/user-attachments/assets/a85f3c55-96d5-494c-83d9-6ccf14aee043" />
<img width="1867" height="827" alt="image" src="https://github.com/user-attachments/assets/62d5c4f0-2280-4ad2-82cd-6fa128ab01db" />
<img width="1060" height="335" alt="image" src="https://github.com/user-attachments/assets/ab22e288-cc2b-41be-89f5-678854f69492" />
<img width="552" height="611" alt="image" src="https://github.com/user-attachments/assets/80c09ee1-c39a-4b99-880b-2b6eaedea082" />
<img width="172" height="602" alt="image" src="https://github.com/user-attachments/assets/1a5d668f-301a-44da-9e38-55cc8bf83eda" />

##  Demo Walkthrough

1. Launch the dashboard.
2. Select `Sequential Fire (2 reroutes)` scenario.
3. Click `Start`.
4. Watch the path change twice:
   - **t=5s:** `fire_exit` blocks → path reroutes through `stairwell`
   - **t=15s:** `stairwell` blocks → `NO PATH AVAILABLE` (fail‑safe)
5. Trigger a manual flashover on any zone to see instant rerouting.


