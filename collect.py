#!/usr/bin/env python3
import json
import sqlite3
import time
import urllib.request
from pathlib import Path
import sys

from location import ensure_location, handle_location_command

HOME = Path.home()
DATA_DIR = HOME / ".local/share/kanslor-weather"
DATABASE_PATH = DATA_DIR / "history.sqlite3"


def initialize_database(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            alert_id TEXT PRIMARY KEY,
            event TEXT,
            severity TEXT,
            urgency TEXT,
            certainty TEXT,
            status TEXT,
            message_type TEXT,
            sent TEXT,
            effective TEXT,
            onset TEXT,
            expires TEXT,
            ends TEXT,
            area TEXT,
            headline TEXT,
            description TEXT,
            instruction TEXT,
            web TEXT,
            geometry_json TEXT,
            active INTEGER NOT NULL,
            first_seen INTEGER NOT NULL,
            last_seen INTEGER NOT NULL
        )
    """)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(alerts)")}
    if "geometry_json" not in columns:
        connection.execute("ALTER TABLE alerts ADD COLUMN geometry_json TEXT")
    connection.execute("CREATE INDEX IF NOT EXISTS alerts_active_expires ON alerts(active, expires)")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS conditions (
            observed_at TEXT PRIMARY KEY,
            station_id TEXT,
            station_name TEXT,
            description TEXT,
            temperature_f REAL,
            humidity REAL,
            wind_mph REAL,
            wind_direction REAL,
            wind_gust_mph REAL,
            heat_index_f REAL,
            visibility_miles REAL,
            collected_at INTEGER NOT NULL
        )
    """)


def fetch_json(url, user_agent):
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/geo+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fahrenheit(value):
    return round((value * 9 / 5) + 32, 1) if value is not None else None


def wind_mph(value):
    return round(value * 0.621371, 1) if value is not None else None


def miles(value):
    return round(value / 1609.344, 1) if value is not None else None


def main():
    if handle_location_command(sys.argv[1:]):
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    config = ensure_location(interactive=sys.stdin.isatty())
    user_agent = "kanslor-weather-watch/1.0"
    point_url = f"https://api.weather.gov/points/{config['latitude']},{config['longitude']}"
    point = fetch_json(point_url, user_agent)["properties"]
    features = fetch_json(f"https://api.weather.gov/alerts/active?point={config['latitude']},{config['longitude']}", user_agent).get("features", [])
    stations = fetch_json(point["observationStations"], user_agent).get("features", [])
    observation = {}
    if stations:
        station_id = stations[0]["properties"]["stationIdentifier"]
        observation = fetch_json(f"https://api.weather.gov/stations/{station_id}/observations/latest", user_agent).get("properties", {})

    now = int(time.time())
    alert_ids = []
    with sqlite3.connect(DATABASE_PATH) as connection:
        initialize_database(connection)
        for feature in features:
            properties = feature.get("properties", {})
            alert_id = properties.get("id") or feature.get("id")
            if not alert_id:
                continue
            alert_ids.append(alert_id)
            connection.execute("""
                INSERT INTO alerts (
                    alert_id, event, severity, urgency, certainty, status, message_type,
                    sent, effective, onset, expires, ends, area, headline, description,
                    instruction, web, geometry_json, active, first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(alert_id) DO UPDATE SET
                    event = excluded.event, severity = excluded.severity, urgency = excluded.urgency,
                    certainty = excluded.certainty, status = excluded.status, message_type = excluded.message_type,
                    sent = excluded.sent, effective = excluded.effective, onset = excluded.onset,
                    expires = excluded.expires, ends = excluded.ends, area = excluded.area,
                    headline = excluded.headline, description = excluded.description,
                    instruction = excluded.instruction, web = excluded.web, geometry_json = excluded.geometry_json, active = 1,
                    last_seen = excluded.last_seen
            """, (
                alert_id, properties.get("event"), properties.get("severity"), properties.get("urgency"),
                properties.get("certainty"), properties.get("status"), properties.get("messageType"),
                properties.get("sent"), properties.get("effective"), properties.get("onset"),
                properties.get("expires"), properties.get("ends"), properties.get("areaDesc"),
                properties.get("headline"), properties.get("description"), properties.get("instruction"),
                properties.get("web"), json.dumps(feature.get("geometry")), now, now,
            ))
        if alert_ids:
            placeholders = ",".join("?" for _ in alert_ids)
            connection.execute(f"UPDATE alerts SET active = 0 WHERE active = 1 AND alert_id NOT IN ({placeholders})", alert_ids)
        else:
            connection.execute("UPDATE alerts SET active = 0 WHERE active = 1")
        if observation:
            connection.execute("""
                INSERT INTO conditions (
                    observed_at, station_id, station_name, description, temperature_f, humidity,
                    wind_mph, wind_direction, wind_gust_mph, heat_index_f, visibility_miles, collected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(observed_at) DO UPDATE SET collected_at = excluded.collected_at
            """, (
                observation.get("timestamp"), observation.get("stationId"), observation.get("stationName"),
                observation.get("textDescription"), fahrenheit(observation.get("temperature", {}).get("value")),
                observation.get("relativeHumidity", {}).get("value"),
                wind_mph(observation.get("windSpeed", {}).get("value")), observation.get("windDirection", {}).get("value"),
                wind_mph(observation.get("windGust", {}).get("value")), fahrenheit(observation.get("heatIndex", {}).get("value")),
                miles(observation.get("visibility", {}).get("value")), now,
            ))
    (DATA_DIR / "last_success").write_text(str(now), encoding="utf-8")


if __name__ == "__main__":
    main()
