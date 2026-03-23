import os
import time
import json
import subprocess
import logging

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("flightportal")

# Config from environment
SHOUTRRR_URL = os.environ.get("SHOUTRRR_URL", "")
LATITUDE = float(os.environ.get("LATITUDE", "24.8539174"))
LONGITUDE = float(os.environ.get("LONGITUDE", "46.7484485"))
RADIUS_KM = float(os.environ.get("RADIUS_KM", "10"))
QUERY_DELAY = int(os.environ.get("QUERY_DELAY", "30"))


def _bounds_box(lat, lng, radius_km):
    """Convert center point + radius to FR24 bounding box string."""
    # 1 degree latitude ~ 111 km
    lat_offset = radius_km / 111.0
    # 1 degree longitude ~ 111 km * cos(latitude)
    import math
    lng_offset = radius_km / (111.0 * math.cos(math.radians(lat)))
    return f"{lat + lat_offset},{lat - lat_offset},{lng - lng_offset},{lng + lng_offset}"


BOUNDS_BOX = _bounds_box(LATITUDE, LONGITUDE, RADIUS_KM)

# FlightRadar24 endpoints
FLIGHT_SEARCH_URL = (
    f"https://data-cloud.flightradar24.com/zones/fcgi/feed.js?bounds={BOUNDS_BOX}"
    "&faa=1&satellite=1&mlat=1&flarm=1&adsb=1&gnd=0&air=1"
    "&vehicles=0&estimated=0&maxage=14400&gliders=0&stats=0&ems=1&limit=1"
)
FLIGHT_DETAILS_URL = "https://data-live.flightradar24.com/clickhandler/?flight="

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:106.0) Gecko/20100101 Firefox/106.0",
    "Accept": "application/json",
}


def get_flights():
    """Search for flights in the configured bounding box. Returns a flight ID or None."""
    try:
        resp = requests.get(FLIGHT_SEARCH_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.error("Flight search failed: %s", e)
        return None

    # Response has "version", "full_count", and optionally one flight entry
    if len(data) == 3:
        for key, value in data.items():
            if key not in ("version", "full_count") and isinstance(value, list) and len(value) > 13:
                return key
    return None


def get_flight_details(flight_id):
    """Fetch detailed info for a flight. Returns a dict or None."""
    try:
        resp = requests.get(FLIGHT_DETAILS_URL + flight_id, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error("Flight details fetch failed: %s", e)
        return None


def parse_flight(data):
    """Extract basic flight info from FR24 detail JSON. Returns a dict or None."""
    try:
        flight_number = data["identification"]["number"]["default"] or ""
        callsign = data["identification"]["callsign"] or ""
        airline = data.get("airline", {}).get("name", "") or ""
        aircraft_code = data.get("aircraft", {}).get("model", {}).get("code", "") or ""
        aircraft_model = data.get("aircraft", {}).get("model", {}).get("text", "") or ""

        origin = data.get("airport", {}).get("origin", {}) or {}
        dest = data.get("airport", {}).get("destination", {}) or {}

        origin_code = (origin.get("code", {}) or {}).get("iata", "") or ""
        origin_name = (origin.get("name", "") or "").replace(" Airport", "")
        dest_code = (dest.get("code", {}) or {}).get("iata", "") or ""
        dest_name = (dest.get("name", "") or "").replace(" Airport", "")

        return {
            "flight_number": flight_number or callsign,
            "airline": airline,
            "origin_code": origin_code,
            "origin_name": origin_name,
            "dest_code": dest_code,
            "dest_name": dest_name,
            "aircraft_code": aircraft_code,
            "aircraft_model": aircraft_model,
        }
    except (KeyError, TypeError) as e:
        log.error("Failed to parse flight details: %s", e)
        return None


def format_message(flight):
    """Format a notification message from flight info."""
    route = f"{flight['origin_code']}-{flight['dest_code']}"
    if flight["origin_name"] and flight["dest_name"]:
        route += f" ({flight['origin_name']} → {flight['dest_name']})"

    aircraft = flight["aircraft_code"]
    if flight["aircraft_model"]:
        aircraft += f" ({flight['aircraft_model']})"

    lines = [
        f"✈ {flight['flight_number']}",
        f"Airline: {flight['airline']}",
        f"Route: {route}",
        f"Aircraft: {aircraft}",
    ]
    return "\n".join(line for line in lines if line)


def send_notification(message):
    """Send a notification via Shoutrrr."""
    if not SHOUTRRR_URL:
        log.warning("SHOUTRRR_URL not set, skipping notification")
        return

    try:
        result = subprocess.run(
            ["shoutrrr", "send", "--url", SHOUTRRR_URL, "--message", message],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.error("Shoutrrr failed: %s", result.stderr.strip())
        else:
            log.info("Notification sent")
    except FileNotFoundError:
        log.error("shoutrrr binary not found")
    except Exception as e:
        log.error("Notification error: %s", e)


def main():
    if not SHOUTRRR_URL:
        log.warning("SHOUTRRR_URL not configured — notifications will be skipped")

    log.info("Starting flight tracker (center=%.4f,%.4f radius=%gkm delay=%ds)",
             LATITUDE, LONGITUDE, RADIUS_KM, QUERY_DELAY)

    last_flight = None

    while True:
        flight_id = get_flights()

        if flight_id and flight_id != last_flight:
            log.info("New flight detected: %s", flight_id)
            details = get_flight_details(flight_id)
            if details:
                flight = parse_flight(details)
                if flight:
                    msg = format_message(flight)
                    log.info("\n%s", msg)
                    send_notification(msg)
                else:
                    log.warning("Could not parse flight details")
            else:
                log.warning("Could not fetch flight details")
            last_flight = flight_id
        elif flight_id:
            log.debug("Same flight %s still overhead", flight_id)
        else:
            last_flight = None

        time.sleep(QUERY_DELAY)


if __name__ == "__main__":
    main()
