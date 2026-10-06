import json
import time

NODE_ID = "urn:dev:pi3-001:"
SENML_VERSION = 5

UNITS = {
    "max30100:hr": "1/min",
    "max30100:spo2": "%",
    "mlx90614:temp": "Cel",
    "resp_rate": "1/min",
    "sbp_news2_points": None,
    "news2_total": None,
    "news2_level": None,
}


def build_senml(readings, timestamp=None):
    ts = int(time.time()) if timestamp is None else int(timestamp)
    records = []
    first = True
    for name, value in readings.items():
        if value is None or name not in UNITS:
            continue
        rec = {}
        if first:
            rec["bn"] = NODE_ID
            rec["bt"] = ts
            rec["bver"] = SENML_VERSION
            first = False
        rec["n"] = name
        unit = UNITS[name]
        if unit:
            rec["u"] = unit
        rec["v"] = value
        records.append(rec)
    return records


def senml_to_json(records):
    return json.dumps(records, ensure_ascii=False)
