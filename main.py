import math
import os
import re
import time
import subprocess
import logging
import threading

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
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")  # Telegram bot token for commands (falls back to SHOUTRRR_URL token)
BOT_ADMIN_ID = os.environ.get("BOT_ADMIN_ID", "")  # Telegram user ID to restrict bot commands

# Airport runway monitoring (optional) — just set AIRPORT_CODE, rest is auto-detected
AIRPORT_CODE = os.environ.get("AIRPORT_CODE", "")   # IATA code, e.g. RUH
AIRPORT_ICAO = ""
RUNWAY_HEADINGS_RAW = ""
RUNWAY_HEADINGS = []  # parsed list of ints

# Reusable HTTP session (keeps TCP connections alive)
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:106.0) Gecko/20100101 Firefox/106.0",
    "Accept": "application/json",
})


def _lookup_airport(iata_code):
    """Look up ICAO code and runway headings automatically."""
    global AIRPORT_ICAO, RUNWAY_HEADINGS_RAW, RUNWAY_HEADINGS
    if not iata_code:
        return
    try:
        # Step 1: Get ICAO code from FR24
        resp = SESSION.get(
            f"https://api.flightradar24.com/common/v1/search.json?query={iata_code}&limit=1",
            timeout=10,
        )
        resp.raise_for_status()
        airports = resp.json().get("result", {}).get("response", {}).get("airport", {}).get("data", [])
        if not airports:
            log.warning("Airport %s not found on FR24", iata_code)
            return
        AIRPORT_ICAO = airports[0].get("code", {}).get("icao", "")
        if not AIRPORT_ICAO:
            log.warning("No ICAO code found for %s", iata_code)
            return

        # Step 2: Get runway headings from aviationweather.gov
        resp = SESSION.get(
            f"https://aviationweather.gov/api/data/airport?ids={AIRPORT_ICAO}&format=json",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            runways = data[0].get("runways", [])
            if runways:
                headings = set()
                for rwy in runways:
                    alignment = rwy.get("alignment", 0)
                    headings.add(alignment)
                    headings.add((alignment + 180) % 360)
                RUNWAY_HEADINGS = sorted(headings)
                RUNWAY_HEADINGS_RAW = ",".join(str(h) for h in RUNWAY_HEADINGS)

        log.info("Airport lookup: %s → ICAO=%s, runways=%s",
                 iata_code, AIRPORT_ICAO, RUNWAY_HEADINGS_RAW)
    except Exception as e:
        log.error("Airport lookup failed: %s", e)


def _bounds_box(lat, lng, radius_km):
    """Convert center point + radius to FR24 bounding box string."""
    lat_offset = radius_km / 111.0
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


def get_flights():
    """Search for flights in the configured bounding box. Returns a flight ID or None."""
    try:
        resp = SESSION.get(FLIGHT_SEARCH_URL, timeout=15)
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
        resp = SESSION.get(FLIGHT_DETAILS_URL + flight_id, timeout=15)
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
        aircraft = data.get("aircraft", {}) or {}
        aircraft_code = (aircraft.get("model", {}) or {}).get("code", "") or ""
        aircraft_model = (aircraft.get("model", {}) or {}).get("text", "") or ""
        aircraft_registration = aircraft.get("registration", "") or ""

        origin = data.get("airport", {}).get("origin", {}) or {}
        dest = data.get("airport", {}).get("destination", {}) or {}

        origin_code = (origin.get("code", {}) or {}).get("iata", "") or ""
        origin_city = (origin.get("position", {}) or {}).get("region", {}).get("city", "") or ""
        origin_country_code = (origin.get("position", {}) or {}).get("country", {}).get("code", "") or ""
        dest_code = (dest.get("code", {}) or {}).get("iata", "") or ""
        dest_city = (dest.get("position", {}) or {}).get("region", {}).get("city", "") or ""
        dest_country_code = (dest.get("position", {}) or {}).get("country", {}).get("code", "") or ""

        return {
            "flight_number": flight_number or callsign,
            "airline": airline,
            "origin_code": origin_code,
            "origin_city": origin_city,
            "origin_country_code": origin_country_code,
            "dest_code": dest_code,
            "dest_city": dest_city,
            "dest_country_code": dest_country_code,
            "aircraft_code": aircraft_code,
            "aircraft_model": aircraft_model,
            "aircraft_registration": aircraft_registration,
        }
    except (KeyError, TypeError) as e:
        log.error("Failed to parse flight details: %s", e)
        return None


# ISO 3166-1 alpha-3 to alpha-2 mapping
_ALPHA3_TO_ALPHA2 = {
    "AFG": "AF", "ALB": "AL", "DZA": "DZ", "AND": "AD", "AGO": "AO",
    "ATG": "AG", "ARG": "AR", "ARM": "AM", "AUS": "AU", "AUT": "AT",
    "AZE": "AZ", "BHS": "BS", "BHR": "BH", "BGD": "BD", "BRB": "BB",
    "BLR": "BY", "BEL": "BE", "BLZ": "BZ", "BEN": "BJ", "BTN": "BT",
    "BOL": "BO", "BIH": "BA", "BWA": "BW", "BRA": "BR", "BRN": "BN",
    "BGR": "BG", "BFA": "BF", "BDI": "BI", "KHM": "KH", "CMR": "CM",
    "CAN": "CA", "CPV": "CV", "CAF": "CF", "TCD": "TD", "CHL": "CL",
    "CHN": "CN", "COL": "CO", "COM": "KM", "COG": "CG", "COD": "CD",
    "CRI": "CR", "CIV": "CI", "HRV": "HR", "CUB": "CU", "CYP": "CY",
    "CZE": "CZ", "DNK": "DK", "DJI": "DJ", "DMA": "DM", "DOM": "DO",
    "ECU": "EC", "EGY": "EG", "SLV": "SV", "GNQ": "GQ", "ERI": "ER",
    "EST": "EE", "ETH": "ET", "FJI": "FJ", "FIN": "FI", "FRA": "FR",
    "GAB": "GA", "GMB": "GM", "GEO": "GE", "DEU": "DE", "GHA": "GH",
    "GRC": "GR", "GRD": "GD", "GTM": "GT", "GIN": "GN", "GNB": "GW",
    "GUY": "GY", "HTI": "HT", "HND": "HN", "HUN": "HU", "ISL": "IS",
    "IND": "IN", "IDN": "ID", "IRN": "IR", "IRQ": "IQ", "IRL": "IE",
    "ISR": "IL", "ITA": "IT", "JAM": "JM", "JPN": "JP", "JOR": "JO",
    "KAZ": "KZ", "KEN": "KE", "KIR": "KI", "PRK": "KP", "KOR": "KR",
    "KWT": "KW", "KGZ": "KG", "LAO": "LA", "LVA": "LV", "LBN": "LB",
    "LSO": "LS", "LBR": "LR", "LBY": "LY", "LIE": "LI", "LTU": "LT",
    "LUX": "LU", "MKD": "MK", "MDG": "MG", "MWI": "MW", "MYS": "MY",
    "MDV": "MV", "MLI": "ML", "MLT": "MT", "MHL": "MH", "MRT": "MR",
    "MUS": "MU", "MEX": "MX", "FSM": "FM", "MDA": "MD", "MCO": "MC",
    "MNG": "MN", "MNE": "ME", "MAR": "MA", "MOZ": "MZ", "MMR": "MM",
    "NAM": "NA", "NRU": "NR", "NPL": "NP", "NLD": "NL", "NZL": "NZ",
    "NIC": "NI", "NER": "NE", "NGA": "NG", "NOR": "NO", "OMN": "OM",
    "PAK": "PK", "PLW": "PW", "PAN": "PA", "PNG": "PG", "PRY": "PY",
    "PER": "PE", "PHL": "PH", "POL": "PL", "PRT": "PT", "QAT": "QA",
    "ROU": "RO", "RUS": "RU", "RWA": "RW", "KNA": "KN", "LCA": "LC",
    "VCT": "VC", "WSM": "WS", "SMR": "SM", "STP": "ST", "SAU": "SA",
    "SEN": "SN", "SRB": "RS", "SYC": "SC", "SLE": "SL", "SGP": "SG",
    "SVK": "SK", "SVN": "SI", "SLB": "SB", "SOM": "SO", "ZAF": "ZA",
    "ESP": "ES", "LKA": "LK", "SDN": "SD", "SUR": "SR", "SWZ": "SZ",
    "SWE": "SE", "CHE": "CH", "SYR": "SY", "TWN": "TW", "TJK": "TJ",
    "TZA": "TZ", "THA": "TH", "TLS": "TL", "TGO": "TG", "TON": "TO",
    "TTO": "TT", "TUN": "TN", "TUR": "TR", "TKM": "TM", "TUV": "TV",
    "UGA": "UG", "UKR": "UA", "ARE": "AE", "GBR": "GB", "USA": "US",
    "URY": "UY", "UZB": "UZ", "VUT": "VU", "VEN": "VE", "VNM": "VN",
    "YEM": "YE", "ZMB": "ZM", "ZWE": "ZW", "PSE": "PS", "HKG": "HK",
    "MAC": "MO", "XKX": "XK", "CUW": "CW", "SSD": "SS",
}


def _country_flag(country_code):
    """Convert a country code (2 or 3 letter) to a flag emoji."""
    if not country_code:
        return ""
    code = country_code.upper()
    if len(code) == 3:
        code = _ALPHA3_TO_ALPHA2.get(code, "")
    if len(code) != 2:
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code)


def _wind_direction_name(degrees):
    """Convert wind degrees to compass direction."""
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = round(degrees / 22.5) % 16
    return dirs[idx]


def _approach_direction(runway_heading):
    """Planes approach from the opposite direction of the runway heading."""
    approach = (runway_heading + 180) % 360
    return _wind_direction_name(approach)


def get_metar():
    """Fetch current METAR from aviationweather.gov (free, no key)."""
    if not AIRPORT_ICAO:
        return None
    try:
        resp = SESSION.get(
            f"https://aviationweather.gov/api/data/metar?ids={AIRPORT_ICAO}&format=json",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None
        metar = data[0]
        return {
            "direction": int(metar.get("wdir", 0) or 0),
            "speed_kt": int(metar.get("wspd", 0) or 0),
            "gust_kt": int(metar.get("wgst", 0) or 0),
            "raw": metar.get("rawOb", ""),
        }
    except Exception as e:
        log.error("METAR fetch failed: %s", e)
        return None


def get_active_runway(wind_direction):
    """Determine active runway based on wind direction. Planes land into the wind,
    so the active runway heading should be closest to the wind direction."""
    if not RUNWAY_HEADINGS:
        return None
    best = None
    best_diff = 360
    for h in RUNWAY_HEADINGS:
        # Angular difference between runway heading and wind direction
        diff = abs(((wind_direction - h) + 180) % 360 - 180)
        if diff < best_diff:
            best_diff = diff
            best = h
    return best


def get_taf():
    """Fetch TAF forecast from aviationweather.gov (free, no key)."""
    if not AIRPORT_ICAO:
        return None
    try:
        resp = SESSION.get(
            f"https://aviationweather.gov/api/data/taf?ids={AIRPORT_ICAO}&format=json",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None
        return data[0].get("fcsts", [])
    except Exception as e:
        log.error("TAF fetch failed: %s", e)
        return None


def estimate_runway_duration(current_heading):
    """Estimate how long the current runway stays active based on TAF forecast."""
    fcsts = get_taf()
    if not fcsts:
        return None
    now = int(time.time())
    for fcst in fcsts:
        wdir = fcst.get("wdir")
        if wdir is None or wdir == "VRB":
            continue
        wdir = int(wdir)
        time_from = fcst.get("timeFrom", 0)
        time_bec = fcst.get("timeBec")
        # Only look at future forecast periods
        change_time = time_bec or time_from
        if change_time <= now:
            continue
        predicted_runway = get_active_runway(wdir)
        if predicted_runway and predicted_runway != current_heading:
            hours = max(1, round((change_time - now) / 3600))
            return hours
    return None


def format_runway_change(old_heading, new_heading, metar):
    """Format a runway change notification."""
    old_name = f"{round(old_heading / 10):02d}"
    new_name = f"{round(new_heading / 10):02d}"
    approach_from = _approach_direction(new_heading)
    wind_dir = _wind_direction_name(metar["direction"])
    wind_kt = metar["speed_kt"]
    gust_kt = metar["gust_kt"]

    duration = estimate_runway_duration(new_heading)
    if duration:
        duration_str = f"~{duration}h" if duration > 1 else "~1h"
        until_time = time.strftime("%d/%m %I:%M %p", time.localtime(time.time() + duration * 3600))
        duration_str += f" (until {until_time})"
    else:
        duration_str = "24h+"

    lines = [
        f"🛣 {AIRPORT_CODE} Runway Changed: {old_name} → {new_name}",
        "",
        f"🌬 Wind: {wind_dir} {wind_kt}kt" + (f" (gusts {gust_kt}kt)" if gust_kt else ""),
        f"🧭 Landing from: {approach_from}",
        f"⏱ Estimated: {duration_str}",
    ]
    return "\n".join(lines)


def _or_unknown(value):
    return value if value else "Unknown"


def format_message(flight):
    """Format a notification message from flight info."""
    origin_flag = _country_flag(flight["origin_country_code"])
    dest_flag = _country_flag(flight["dest_country_code"])

    aircraft = _or_unknown(flight["aircraft_code"])
    if flight["aircraft_model"]:
        aircraft = f"{flight['aircraft_model']} ({flight['aircraft_code']})"

    origin_code = flight["origin_code"] or "???"
    dest_code = flight["dest_code"] or "???"

    origin_city = _or_unknown(flight["origin_city"])
    dest_city = _or_unknown(flight["dest_city"])

    flight_num = _or_unknown(flight['flight_number'])
    lines = [
        f"✈ {flight_num} - {_or_unknown(flight['airline'])}",
        f"🛫 {origin_city} ({origin_code}) {origin_flag}",
        f"🛬 {dest_city} ({dest_code}) {dest_flag}",
        f"🛩 {aircraft}",
    ]
    if flight["aircraft_registration"]:
        lines.append(f"🔖 {flight['aircraft_registration']}")
    if flight_num != "Unknown":
        lines.append(f"🔗 flightradar24.com/{flight_num}")

    return "\n".join(lines)


def format_wind_status():
    """Format current wind/runway status for /wind command."""
    if not AIRPORT_ICAO or not RUNWAY_HEADINGS:
        return "Airport not configured."
    metar = get_metar()
    if not metar:
        return "Could not fetch METAR data."
    runway_heading = get_active_runway(metar["direction"])
    if not runway_heading:
        return "Could not determine active runway."

    runway_name = f"{round(runway_heading / 10):02d}"
    approach_from = _approach_direction(runway_heading)
    wind_dir = _wind_direction_name(metar["direction"])
    wind_kt = metar["speed_kt"]
    gust_kt = metar["gust_kt"]

    duration = estimate_runway_duration(runway_heading)
    if duration:
        duration_str = f"~{duration}h" if duration > 1 else "~1h"
        until_time = time.strftime("%d/%m %I:%M %p", time.localtime(time.time() + duration * 3600))
        duration_str += f" (until {until_time})"
    else:
        duration_str = "24h+"

    lines = [
        f"🛣 {AIRPORT_CODE} Active Runway: {runway_name}",
        "",
        f"🌬 Wind: {wind_dir} {wind_kt}kt" + (f" (gusts {gust_kt}kt)" if gust_kt else ""),
        f"🧭 Landing from: {approach_from}",
        f"⏱ Estimated: {duration_str}",
        "",
        f"📡 METAR: {metar['raw']}",
    ]
    return "\n".join(lines)


def _parse_shoutrrr_url(url):
    """Parse a Shoutrrr-style URL into service type and params."""
    m = re.match(r"^telegram://([^@]+)@telegram\?chats?=(.+)$", url)
    if m:
        return "telegram", {"token": m.group(1), "chat_id": m.group(2)}
    return "shoutrrr", {}


def _send_telegram(token, chat_id, message, pin=False):
    """Send via Telegram Bot API directly (handles unicode properly). Returns message_id."""
    resp = SESSION.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "disable_notification": True},
        timeout=15,
    )
    if resp.status_code != 200:
        log.error("Telegram API error: %s %s", resp.status_code, resp.text)
        return None
    log.info("Notification sent via Telegram")
    msg_id = resp.json().get("result", {}).get("message_id")
    if pin and msg_id:
        SESSION.post(
            f"https://api.telegram.org/bot{token}/pinChatMessage",
            json={"chat_id": chat_id, "message_id": msg_id, "disable_notification": True},
            timeout=10,
        )
    return msg_id


def _send_shoutrrr(url, message):
    """Fallback: send via shoutrrr binary."""
    try:
        result = subprocess.run(
            ["shoutrrr", "send", "--url", url, "--message", message],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.error("Shoutrrr failed: %s", result.stderr.strip())
        else:
            log.info("Notification sent via Shoutrrr")
    except FileNotFoundError:
        log.error("shoutrrr binary not found")
    except Exception as e:
        log.error("Notification error: %s", e)


_NOTIFY_SERVICE, _NOTIFY_PARAMS = _parse_shoutrrr_url(SHOUTRRR_URL)

# Tracking state for bot commands
_start_time = time.time()
_flights_seen = 0
_last_flight_msg = None


def format_help():
    """Format /help response."""
    return "\n".join([
        "📖 FlightOverME Commands",
        "",
        "/track SV1164 — Check flight status & delays",
        "/runway — Active runway & wind info",
        "/status — Tracker uptime & flight count",
        "/last — Last flight seen",
        "/help — Show this message",
    ])


def format_status():
    """Format /status response."""
    uptime_s = int(time.time() - _start_time)
    hours, remainder = divmod(uptime_s, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours > 0:
        uptime_str = f"{hours}h {minutes}m"
    else:
        uptime_str = f"{minutes}m"

    lines = [
        "📊 FlightOverME Status",
        "",
        f"⏱ Uptime: {uptime_str}",
        f"✈ Flights seen: {_flights_seen}",
        f"📍 Location: {LATITUDE}, {LONGITUDE}",
        f"📡 Radius: {RADIUS_KM} km",
    ]
    if AIRPORT_CODE:
        lines.append(f"🛣 Airport: {AIRPORT_CODE} ({AIRPORT_ICAO})")
    return "\n".join(lines)


def format_last_flight():
    """Format /last response."""
    if not _last_flight_msg:
        return "No flights seen yet."
    return f"📋 Last Flight\n\n{_last_flight_msg}"


def _search_flight(flight_number):
    """Search FR24 for a flight by number and return its live tracking ID."""
    try:
        resp = SESSION.get(
            f"https://api.flightradar24.com/common/v1/search.json?query={flight_number}&limit=1",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        live = data.get("result", {}).get("response", {}).get("flight", {}).get("data", [])
        if live:
            return live[0].get("id")
    except Exception as e:
        log.error("Flight search failed: %s", e)
    return None


def format_track(flight_number):
    """Track a flight: find it on FR24, get details, show status."""
    flight_number = flight_number.upper().strip()
    if not flight_number:
        return "Usage: /track SV1164"

    flight_id = _search_flight(flight_number)
    if not flight_id:
        return f"Flight {flight_number} not found on FlightRadar24."

    details = get_flight_details(flight_id)
    if not details:
        return f"Could not fetch details for {flight_number}."

    try:
        ident = details.get("identification", {})
        airline_name = (details.get("airline", {}) or {}).get("name", "") or ""
        aircraft = details.get("aircraft", {}) or {}
        reg = aircraft.get("registration", "") or ""
        model_text = (aircraft.get("model", {}) or {}).get("text", "") or ""

        origin = (details.get("airport", {}) or {}).get("origin", {}) or {}
        dest = (details.get("airport", {}) or {}).get("destination", {}) or {}
        origin_code = (origin.get("code", {}) or {}).get("iata", "") or "???"
        origin_city = (origin.get("position", {}) or {}).get("region", {}).get("city", "") or ""
        dest_code = (dest.get("code", {}) or {}).get("iata", "") or "???"
        dest_city = (dest.get("position", {}) or {}).get("region", {}).get("city", "") or ""

        status = (details.get("status", {}) or {}).get("text", "") or "Unknown"

        # Time info
        time_info = details.get("time", {}) or {}
        scheduled_dep = (time_info.get("scheduled", {}) or {}).get("departure")
        actual_dep = (time_info.get("real", {}) or {}).get("departure")
        estimated_arr = (time_info.get("estimated", {}) or {}).get("arrival")

        lines = [
            f"🔍 {flight_number} - {airline_name}" if airline_name else f"🔍 {flight_number}",
            f"🛫 {origin_city} ({origin_code}) → 🛬 {dest_city} ({dest_code})",
            f"📍 Status: {status}",
        ]

        if model_text:
            lines.append(f"🛩 {model_text}" + (f" · 🔖 {reg}" if reg else ""))

        # Show delay info
        if scheduled_dep and actual_dep:
            delay_min = (actual_dep - scheduled_dep) // 60
            if delay_min > 5:
                lines.append(f"⚠ Departed {delay_min}min late")
            elif delay_min < -5:
                lines.append(f"✅ Departed {abs(delay_min)}min early")
            else:
                lines.append("✅ Departed on time")

        if estimated_arr:
            eta = time.strftime("%d/%m %I:%M %p", time.localtime(estimated_arr))
            lines.append(f"🕐 ETA: {eta}")

        lines.append(f"🔗 flightradar24.com/{flight_number}")
        return "\n".join(lines)

    except Exception as e:
        log.error("Failed to format track info: %s", e)
        return f"Error getting details for {flight_number}."


def send_notification(message, pin=False):
    """Send a notification. Uses Telegram API directly if URL is telegram://, otherwise shoutrrr."""
    if not SHOUTRRR_URL:
        log.warning("SHOUTRRR_URL not set, skipping notification")
        return

    if _NOTIFY_SERVICE == "telegram":
        _send_telegram(_NOTIFY_PARAMS["token"], _NOTIFY_PARAMS["chat_id"], message, pin=pin)
    else:
        _send_shoutrrr(SHOUTRRR_URL, message)


def telegram_bot_loop(token):
    """Poll Telegram for bot commands and reply."""
    commands = {
        "/runway": format_wind_status,
        "/wind": format_wind_status,  # backward compat
        "/status": format_status,
        "/last": format_last_flight,
        "/help": format_help,
    }
    offset = None
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if offset:
                params["offset"] = offset
            resp = SESSION.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params=params,
                timeout=35,
            )
            if resp.status_code != 200:
                log.error("Telegram getUpdates error: %s", resp.status_code)
                time.sleep(5)
                continue
            updates = resp.json().get("result", [])
            for update in updates:
                offset = int(update["update_id"]) + 1
                msg = update.get("message", {})
                text = (msg.get("text", "") or "").strip().split("@")[0]  # strip @botname
                chat_id = msg.get("chat", {}).get("id")
                user_id = str(msg.get("from", {}).get("id", ""))
                if not chat_id:
                    continue
                if BOT_ADMIN_ID and user_id != BOT_ADMIN_ID:
                    continue
                # Handle /track with argument
                if text.startswith("/track"):
                    parts = text.split(None, 1)
                    arg = parts[1] if len(parts) > 1 else ""
                    reply = format_track(arg)
                    _send_telegram(token, str(chat_id), reply)
                    continue
                handler = commands.get(text)
                if handler:
                    reply = handler()
                    _send_telegram(token, str(chat_id), reply)
        except Exception as e:
            log.error("Telegram bot error: %s", e)
            time.sleep(5)


def main():
    global _flights_seen, _last_flight_msg

    if AIRPORT_CODE:
        _lookup_airport(AIRPORT_CODE)

    if not SHOUTRRR_URL:
        log.warning("SHOUTRRR_URL not configured — notifications will be skipped")

    log.info("Starting flight tracker (center=%.4f,%.4f radius=%gkm delay=%ds)",
             LATITUDE, LONGITUDE, RADIUS_KM, QUERY_DELAY)

    # Start Telegram bot listener for commands
    bot_token = BOT_TOKEN or (_NOTIFY_PARAMS.get("token") if _NOTIFY_SERVICE == "telegram" else "")
    if bot_token:
        bot_thread = threading.Thread(
            target=telegram_bot_loop,
            args=(bot_token,),
            daemon=True,
        )
        bot_thread.start()
        log.info("Telegram bot started (listening for commands)")

    # Initialize active runway for change detection
    active_runway = None
    if AIRPORT_ICAO and RUNWAY_HEADINGS:
        metar = get_metar()
        if metar:
            active_runway = get_active_runway(metar["direction"])
            if active_runway:
                log.info("Initial active runway: %s (%s)",
                         f"{round(active_runway / 10):02d}", AIRPORT_CODE)

    last_flight = None

    loop_count = 0

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
                    _last_flight_msg = msg
                    _flights_seen += 1
                else:
                    log.warning("Could not parse flight details")
            else:
                log.warning("Could not fetch flight details")
            last_flight = flight_id
        elif flight_id:
            log.debug("Same flight %s still overhead", flight_id)
        else:
            last_flight = None

        # Check for runway change every ~5 minutes (10 loops at 30s)
        loop_count += 1
        if AIRPORT_ICAO and RUNWAY_HEADINGS and loop_count % 10 == 0:
            metar = get_metar()
            if metar:
                new_runway = get_active_runway(metar["direction"])
                if new_runway and active_runway and new_runway != active_runway:
                    msg = format_runway_change(active_runway, new_runway, metar)
                    log.info("Runway change detected:\n%s", msg)
                    send_notification(msg, pin=True)
                    active_runway = new_runway
                elif new_runway:
                    active_runway = new_runway

        time.sleep(QUERY_DELAY)


if __name__ == "__main__":
    main()
