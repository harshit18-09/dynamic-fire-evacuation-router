import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import time
import sys
import threading
import queue
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.loaders.config_loader import load_building_config
from src.hazard.hazard_engine import HazardEngine
from src.routing.pathfinder import Pathfinder
from src.simulation.digital_twin import DigitalTwin
from src.firmware.node import FirmwareNode
from src.comms.message_bus import MessageBus, NodeComms
from src.models.schemas import SensorPayload

st.set_page_config(
    page_title="Fire Evacuation Router",
    page_icon="🚒",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    .stButton>button { width: 100%; background-color: #ff4b4b; color: white; font-weight: bold; }
    .stButton>button:hover { background-color: #ff6b6b; }
    .stSelectbox>div>div { background-color: #1e2229; }
    .stDataFrame { background-color: #1e2229; }
    .event-log { background-color: #1e2229; padding: 10px; border-radius: 5px; font-family: monospace; }
    .metric-card { background-color: #1e2229; padding: 15px; border-radius: 10px; text-align: center; }
    .led-indicator { display: inline-block; width: 16px; height: 16px; border-radius: 50%; margin-right: 6px; }
    </style>
""", unsafe_allow_html=True)

if "twin" not in st.session_state:
    building_name, graph = load_building_config("config/building_layout.yaml")
    zone_ids = list(graph.nodes)

    zone_capacities = {node: graph.nodes[node]['capacity'] for node in graph.nodes}

    hazard_engine = HazardEngine(zone_ids, zone_capacities)
    pathfinder = Pathfinder(graph)
    twin = DigitalTwin(hazard_engine, pathfinder, zone_capacities)
    twin.source_zone = "office_c"
    firmware_node = FirmwareNode("node_1", graph, zone_ids, zone_capacities)
    firmware_node.set_source("office_c")

    st.session_state.twin = twin
    st.session_state.firmware_node = firmware_node
    st.session_state.graph = graph
    st.session_state.zone_ids = zone_ids
    st.session_state.building_name = building_name
    st.session_state.zone_capacities = zone_capacities
    st.session_state.last_data = None
    st.session_state.event_log = []
    st.session_state.sim_thread = None
    st.session_state.running = False
    st.session_state.scenario = "config/scenarios/sequential_fire.yaml"
    st.session_state.source_zone = "office_c"
    st.session_state.data_queue = queue.Queue()

    st.session_state.last_logged_path = None
    st.session_state.last_blocked_zones = set()


def get_node_positions(graph):
    pos = {
        "main_exit": (3, 0),
        "lobby": (5, 0),
        "ground_hallway": (5, 2),
        "office_a": (2, 2),
        "office_b": (8, 2),
        "stairwell": (5, 4),
        "upper_hallway": (5, 6),
        "office_c": (2, 6),
        "office_d": (8, 6),
        "fire_exit": (3, 8),
    }
    for node in graph.nodes:
        if node not in pos:
            pos[node] = (5, 5)
    return pos


def create_figure(graph, hazard_scores, path, pos):
    edge_colors = []
    edge_widths = []
    for u, v in graph.edges:
        if path and u in path and v in path and abs(path.index(u) - path.index(v)) == 1:
            edge_colors.append("#00aaff")
            edge_widths.append(4)
        else:
            edge_colors.append("#444444")
            edge_widths.append(1)

    node_colors = []
    node_texts = []
    for node in graph.nodes:
        score = hazard_scores.get(node, 0.0)
        is_exit = graph.nodes[node].get('is_exit', False)
        if score == float('inf') or score > 100.0:
            node_colors.append("#ff4b4b")
            label = "BLOCKED"
        elif score > 2.0:
            node_colors.append("#ff8c00")
            label = f"{score:.1f}"
        elif score > 0.5:
            node_colors.append("#ffcc00")
            label = f"{score:.2f}"
        else:
            node_colors.append("#00cc66")
            label = "Safe"
        if is_exit:
            label += " (Exit)"
        node_texts.append(f"<b>{node}</b><br>{label}")

    fig = go.Figure()
    for (u, v), color, width in zip(graph.edges, edge_colors, edge_widths):
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        fig.add_trace(go.Scatter(
            x=[x0, x1],
            y=[y0, y1],
            mode='lines',
            line=dict(color=color, width=width),
            hoverinfo='none',
            showlegend=False
        ))
    fig.add_trace(go.Scatter(
        x=[pos[node][0] for node in graph.nodes],
        y=[pos[node][1] for node in graph.nodes],
        mode='markers+text',
        marker=dict(
            size=40,
            color=node_colors,
            line=dict(width=2, color='white'),
            symbol='circle'
        ),
        text=[node for node in graph.nodes],
        textposition='middle center',
        textfont=dict(color='white', size=12),
        hovertext=node_texts,
        hoverinfo='text',
        showlegend=False
    ))

    fig.update_layout(
        plot_bgcolor='#0e1117',
        paper_bgcolor='#0e1117',
        height=550,
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        margin=dict(l=20, r=20, t=40, b=20),
        font=dict(color='white')
    )
    return fig


def add_event(message):
    timestamp = time.strftime("%H:%M:%S")
    st.session_state.event_log.append(f"[{timestamp}] {message}")
    if len(st.session_state.event_log) > 100:
        st.session_state.event_log = st.session_state.event_log[-100:]


def sync_firmware_from_flashover(flashover_zone: str):
    payloads = []
    for zid in st.session_state.zone_ids:
        if zid == flashover_zone:
            payloads.append(SensorPayload(
                node_id=zid, temperature_c=400.0, smoke_ppm=2000.0,
                flame_presence=1.0, occupant_count=10
            ))
        else:
            payloads.append(SensorPayload(
                node_id=zid, temperature_c=22.0, smoke_ppm=10.0,
                flame_presence=0.0, occupant_count=5
            ))
    st.session_state.firmware_node.set_source(st.session_state.source_zone)
    fw_result = st.session_state.firmware_node.process_sensor_data(payloads)

    twin = st.session_state.twin
    st.session_state.last_data = {
        'time': twin.current_time,
        'hazard_scores': twin.hazard_engine.get_current_scores(),
        'path_result': twin.last_path_result or {'path': fw_result['path'], 'exit_node': fw_result['exit_node']},
        'actuators': fw_result['actuators'],
    }


with st.sidebar:
    st.image("https://img.icons8.com/color/96/000000/fire-alarm.png", width=80)
    st.title("Controls")

    scenario_options = {
        "Sequential Fire (2 reroutes)": "config/scenarios/sequential_fire.yaml",
        "Stairwell Flashover": "config/scenarios/flashover_stairwell.yaml",
    }
    selected_scenario_label = st.selectbox(
        "Scenario",
        list(scenario_options.keys()),
        index=0
    )
    st.session_state.scenario = scenario_options[selected_scenario_label]

    source_zone = st.selectbox(
        "Evacuation Source",
        st.session_state.zone_ids,
        index=st.session_state.zone_ids.index("office_c")
    )
    st.session_state.source_zone = source_zone
    st.session_state.firmware_node.set_source(source_zone)

    speed = st.slider("Speed", 0.5, 5.0, 2.0, 0.5)
    duration = st.number_input("Duration (s)", 10, 300, 60, 10)

    st.markdown("---")
    st.subheader("Manual Flashover")
    flashover_zone = st.selectbox("Select zone to ignite", st.session_state.zone_ids, key="flashover_zone")
    if st.button("Trigger Flashover", use_container_width=True):
        if st.session_state.running and st.session_state.twin:
            st.session_state.twin.trigger_flashover(flashover_zone)
            sync_firmware_from_flashover(flashover_zone)
            add_event(f"Manual flashover triggered on {flashover_zone}")
            st.success(f"Flashover triggered on {flashover_zone}")
        else:
            st.warning("Start the simulation first.")

    st.markdown("---")
    col_start, col_stop = st.columns(2)
    with col_start:
        if st.button("Start", use_container_width=True):
            if st.session_state.sim_thread is None or not st.session_state.sim_thread.is_alive():
                st.session_state.running = True
                st.session_state.event_log = []
                st.session_state.last_logged_path = None
                st.session_state.last_blocked_zones = set()

                twin = st.session_state.twin
                twin.source_zone = st.session_state.source_zone
                q = st.session_state.data_queue
                st.session_state.firmware_node = FirmwareNode(
                    "node_1", st.session_state.graph, st.session_state.zone_ids,
                    st.session_state.zone_capacities
                )
                st.session_state.firmware_node.set_source(st.session_state.source_zone)

                def sim_callback(data):
                    q.put(data)

                def run_sim(twin, scenario, speed, duration, callback):
                    twin.run(
                        scenario_path=scenario,
                        speed_multiplier=speed,
                        step_interval=0.2,
                        max_duration=duration,
                        callback=callback
                    )
                    q.put(None)

                st.session_state.sim_thread = threading.Thread(
                    target=run_sim,
                    args=(twin, st.session_state.scenario, speed, duration, sim_callback),
                    daemon=True
                )
                st.session_state.sim_thread.start()
                add_event("Simulation started.")
                st.success("Started!")
            else:
                st.warning("Already running.")

    with col_stop:
        if st.button("Stop", use_container_width=True):
            if st.session_state.running:
                st.session_state.running = False
                st.session_state.twin.is_running = False
                if st.session_state.sim_thread:
                    st.session_state.sim_thread.join(timeout=1)
                add_event("Simulation stopped by user.")
                st.warning("Stopped.")
            else:
                st.info("Not running.")


q = st.session_state.data_queue
while not q.empty():
    data = q.get()
    if data is None:
        st.session_state.running = False
        add_event("Simulation ended.")
        continue

    if 'sensor_batch' in data:
        st.session_state.firmware_node.set_source(st.session_state.source_zone)
        fw_result = st.session_state.firmware_node.process_sensor_data(data['sensor_batch'])
        data['actuators'] = fw_result['actuators']

    st.session_state.last_data = data

    hazard_scores = data.get('hazard_scores', {})
    path = data.get('path_result', {}).get('path', [])
    current_blocked = {z for z, s in hazard_scores.items() if s == float('inf') or s > 100.0}

    if path and path != st.session_state.last_logged_path:
        add_event(f"PATH CHANGED: {' -> '.join(path)}")
        st.session_state.last_logged_path = path
    elif not path and st.session_state.last_logged_path is not None:
        add_event("NO PATH AVAILABLE All exits blocked or unreachable")
        st.session_state.last_logged_path = None

    new_blocked = current_blocked - st.session_state.last_blocked_zones
    for zone in new_blocked:
        add_event(f"ZONE BLOCKED: {zone}")

    recovered = st.session_state.last_blocked_zones - current_blocked
    for zone in recovered:
        add_event(f"ZONE RECOVERED: {zone}")

    st.session_state.last_blocked_zones = current_blocked


st.title("Dynamic Fire Evacuation Router")
st.caption(f"{st.session_state.building_name}  |  Live Dashboard")

col_metrics = st.columns(4)
with col_metrics[0]:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    time_val = st.session_state.last_data['time'] if st.session_state.last_data else 0.0
    st.metric("Time", f"{time_val:.1f}s")
    st.markdown('</div>', unsafe_allow_html=True)
with col_metrics[1]:
    scores = st.session_state.last_data.get('hazard_scores', {}) if st.session_state.last_data else {}
    safe_count = sum(1 for s in scores.values() if s <= 0.5)
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.metric("Safe Zones", safe_count)
    st.markdown('</div>', unsafe_allow_html=True)
with col_metrics[2]:
    hazard_count = sum(1 for s in scores.values() if 0.5 < s <= 100.0)
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.metric("Hazard Zones", hazard_count)
    st.markdown('</div>', unsafe_allow_html=True)
with col_metrics[3]:
    blocked_count = sum(1 for s in scores.values() if s == float('inf') or s > 100.0)
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.metric("Blocked Zones", blocked_count)
    st.markdown('</div>', unsafe_allow_html=True)

col1, col2 = st.columns([2, 1])

with col1:
    graph_placeholder = st.empty()
    status_placeholder = st.empty()

with col2:
    st.subheader("Zone Status")
    table_placeholder = st.empty()

    st.subheader("LED & Buzzer Status")
    led_placeholder = st.empty()

    st.subheader("Event Log")
    log_placeholder = st.empty()


data = st.session_state.last_data
graph = st.session_state.graph
pos = get_node_positions(graph)

if data:
    hazard_scores = data.get('hazard_scores', {})
    path = data.get('path_result', {}).get('path', [])
    time_elapsed = data.get('time', 0.0)

    fig = create_figure(graph, hazard_scores, path, pos)
    graph_placeholder.plotly_chart(fig, use_container_width=True)

    if path:
        path_str = " -> ".join(path)
        status_placeholder.success(f"Evacuation Path: {path_str}  (t={time_elapsed:.1f}s)")
    else:
        status_placeholder.error(f"NO PATH AVAILABLE  (t={time_elapsed:.1f}s)")

    df_data = []
    for zone in graph.nodes:
        score = hazard_scores.get(zone, 0.0)
        if score == float('inf') or score > 100.0:
            status = "Blocked"
        elif score > 0.5:
            status = "Hazard"
        else:
            status = "Safe"
        df_data.append({
            "Zone": zone,
            "Score": f"{score:.2f}" if score != float('inf') and score <= 100.0 else "∞",
            "Status": status
        })
    df = pd.DataFrame(df_data)
    table_placeholder.dataframe(df, use_container_width=True, height=250)

    if 'actuators' in data:
        actuators = data['actuators']
        led_html = ""
        for zone_id, state in actuators.items():
            color = state['led']
            direction = state['direction'] or "—"
            buzzer = "🔊" if state['buzzer'] else "🔇"
            emoji = "🟢" if color == "green" else ("🟡" if color == "yellow" else "🔴")
            led_html += f"<div><span style='display:inline-block; width:80px;'>{zone_id}</span> {emoji} {direction} {buzzer}</div>"
        led_placeholder.markdown(led_html, unsafe_allow_html=True)
    else:
        led_placeholder.info("Actuator data not available – run with FirmwareNode to see LED/buzzer status.")

else:
    graph_placeholder.info("Waiting for simulation data...")
    status_placeholder.info("Start the simulation to see live updates.")
    led_placeholder.info("LED matrix will appear once the simulation starts.")

if st.session_state.event_log:
    log_text = "\n".join(st.session_state.event_log[-20:])
    log_placeholder.code(log_text, language="text", height=200)
else:
    log_placeholder.info("No events yet.")

if st.session_state.running:
    time.sleep(2)
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()