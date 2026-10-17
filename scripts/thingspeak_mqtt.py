import json
import os
import time

import certifi
import paho.mqtt.publish as publish

from senml import build_senml

MQTT_HOST = "mqtt3.thingspeak.com"
MQTT_PORT = 8883
MIN_INTERVAL_S = 15

TLS_CONFIG = {"ca_certs": certifi.where()}

FIELD_MAP = {
    "max30100:hr": "field1",
    "max30100:spo2": "field2",
    "mlx90614:temp": "field3",
    "resp_rate": "field4",
    "sbp_news2_points": "field5",
    "news2_total": "field6",
    "node_id": "field7",
}

FIELD_ORDER = list(FIELD_MAP.keys())

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "thingspeak_config.json")


def load_config(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg["channel_id"], cfg["mqtt_client_id"], cfg["mqtt_username"], cfg["mqtt_password"]


def build_field_message(channel_id, name, value):
    field = FIELD_MAP[name]
    topic = f"channels/{channel_id}/publish/fields/{field}"
    return topic, str(value)


class ThingSpeakPublisher:
    def __init__(self, channel_id, mqtt_client_id, mqtt_username, mqtt_password):
        self.channel_id = channel_id
        self.client_id = mqtt_client_id
        self.auth = {"username": mqtt_username, "password": mqtt_password}
        self._last_sent = 0.0
        self._next_idx = 0
        self._mensajes_enviados = 0

    def can_send(self):
        return time.time() - self._last_sent >= MIN_INTERVAL_S

    def publish(self, readings, timestamp=None):
        if not self.can_send():
            return False

        records = build_senml(readings, timestamp=timestamp)
        values = {rec["n"]: rec["v"] for rec in records if rec.get("n") in FIELD_MAP}
        if not values:
            return False

        for _ in range(len(FIELD_ORDER)):
            name = FIELD_ORDER[self._next_idx]
            self._next_idx = (self._next_idx + 1) % len(FIELD_ORDER)
            if name in values:
                topic, payload = build_field_message(self.channel_id, name, values[name])
                publish.single(
                    topic, payload,
                    hostname=MQTT_HOST, port=MQTT_PORT,
                    client_id=self.client_id, auth=self.auth, tls=TLS_CONFIG,
                )
                self._last_sent = time.time()
                self._mensajes_enviados += 1
                print(f"[ThingSpeak] Mensaje #{self._mensajes_enviados} enviado -> {name}={payload}")
                return True
        return False
