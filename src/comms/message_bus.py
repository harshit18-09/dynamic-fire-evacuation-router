import time
import threading
from typing import Dict, List, Callable, Any
from collections import defaultdict

from ..utils.logger import setup_logger

logger = setup_logger(__name__)


class MessageBus:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._subscribers = defaultdict(list)
                cls._instance._messages = []
                cls._instance._running = True
                logger.info("MessageBus singleton initialized")
            return cls._instance

    def publish(self, topic: str, payload: Any) -> None:
        if not self._running:
            logger.warning("Bus stopped, message dropped")
            return

        timestamp = time.time()
        self._messages.append((timestamp, topic, payload))
        if len(self._messages) > 1000:
            self._messages = self._messages[-1000:]

        delivered = 0
        for pattern, callbacks in self._subscribers.items():
            if self._topic_matches(pattern, topic):
                for cb in callbacks:
                    try:
                        cb(topic, payload)
                        delivered += 1
                    except Exception as e:
                        logger.error(f"Callback error for {topic}: {e}")

        if delivered == 0:
            logger.debug(f"No subscribers for '{topic}'")

    def subscribe(self, pattern: str, callback: Callable[[str, Any], None]) -> None:
        self._subscribers[pattern].append(callback)
        logger.info(f"Subscribed to '{pattern}'")

    def unsubscribe(self, pattern: str, callback: Callable) -> None:
        if pattern in self._subscribers:
            self._subscribers[pattern] = [cb for cb in self._subscribers[pattern] if cb != callback]
            if not self._subscribers[pattern]:
                del self._subscribers[pattern]
            logger.info(f"Unsubscribed from '{pattern}'")

    def get_messages(self, topic: str = None, limit: int = 50) -> List:
        if topic:
            return [(t, msg) for t, msg in self._messages[-limit:] if t == topic]
        return self._messages[-limit:]

    def stop(self):
        self._running = False
        logger.info("MessageBus stopped")

    def _topic_matches(self, pattern: str, topic: str) -> bool:
        if pattern == "#":
            return True
        pat_parts = pattern.split('.')
        top_parts = topic.split('.')
        if len(pat_parts) != len(top_parts):
            return False
        for p, t in zip(pat_parts, top_parts):
            if p != '*' and p != t:
                return False
        return True

class NodeComms:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.bus = MessageBus()
        self._subscriptions = []

    def publish_hazard(self, zone_id: str, hazard_score: float) -> None:
        topic = f"hazard.{zone_id}"
        self.bus.publish(topic, {
            'node_id': self.node_id,
            'zone_id': zone_id,
            'hazard_score': hazard_score,
            'timestamp': time.time()
        })

    def publish_path(self, path: List[str], exit_node: str) -> None:
        topic = f"path.{self.node_id}"
        self.bus.publish(topic, {
            'node_id': self.node_id,
            'path': path,
            'exit_node': exit_node,
            'timestamp': time.time()
        })

    def subscribe_to_hazards(self, callback: Callable) -> None:
        def wrapper(topic, payload):
            if payload.get('node_id') != self.node_id: 
                callback(payload)
        self.bus.subscribe("hazard.*", wrapper)
        self._subscriptions.append(("hazard.*", wrapper))

    def subscribe_to_paths(self, callback: Callable) -> None:
        def wrapper(topic, payload):
            if payload.get('node_id') != self.node_id:
                callback(payload)
        self.bus.subscribe("path.*", wrapper)
        self._subscriptions.append(("path.*", wrapper))

    def stop(self):
        for pattern, cb in self._subscriptions:
            self.bus.unsubscribe(pattern, cb)