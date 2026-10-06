import json
import os
import time

import paho.mqtt.publish as publish

from senml import build_senml

MQTT_HOST = "mqtt3.thingspeak.com"
MQTT_PORT = 1883
MIN_INTERVAL_S = 15

FIELD_MAP = {
    "max30100:hr": "field1",
    "max30100:spo2": "field2",
    "mlx90614:temp": "field3",
    "resp_rate": "field4",
    "sbp_news2_points": "field5",
    "news2_total": "field6",
}

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "thingspeak_config.json")


def load_config(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg["channel_id"], cfg["write_api_key"]


def senml_to_thingspeak_payload(records):
    parts = []
    for rec in records:
        name = rec.get("n")
        if name in FIELD_MAP:
            parts.append(f"{FIELD_MAP[name]}={rec['v']}")
    return "&".join(parts)


class ThingSpeakPublisher:
    def __init__(self, channel_id, write_api_key):
        self.topic = f"channels/{channel_id}/publish/{write_api_key}"
        self._last_sent = 0.0

    def can_send(self):
        return time.time() - self._last_sent >= MIN_INTERVAL_S

    def publish(self, readings, timestamp=None):
        if not self.can_send():
            return False
        records = build_senml(readings, timestamp=timestamp)
        payload = senml_to_thingspeak_payload(records)
        if not payload:
            return False
        publish.single(self.topic, payload, hostname=MQTT_HOST, port=MQTT_PORT)
        self._last_sent = time.time()
        return True
