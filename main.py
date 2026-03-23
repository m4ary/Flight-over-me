import os
import re
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
        aircraft = data.get("aircraft", {}) or {}
        aircraft_code = (aircraft.get("model", {}) or {}).get("code", "") or ""
        aircraft_model = (aircraft.get("model", {}) or {}).get("text", "") or ""
        aircraft_age = aircraft.get("age", "") or ""
        aircraft_registration = aircraft.get("registration", "") or ""

        origin = data.get("airport", {}).get("origin", {}) or {}
        dest = data.get("airport", {}).get("destination", {}) or {}

        origin_code = (origin.get("code", {}) or {}).get("iata", "") or ""
        origin_name = (origin.get("name", "") or "").replace(" Airport", "")
        origin_city = (origin.get("position", {}) or {}).get("region", {}).get("city", "") or ""
        origin_country = (origin.get("position", {}) or {}).get("country", {}).get("name", "") or ""
        origin_country_code = (origin.get("position", {}) or {}).get("country", {}).get("code", "") or ""
        dest_code = (dest.get("code", {}) or {}).get("iata", "") or ""
        dest_name = (dest.get("name", "") or "").replace(" Airport", "")
        dest_city = (dest.get("position", {}) or {}).get("region", {}).get("city", "") or ""
        dest_country = (dest.get("position", {}) or {}).get("country", {}).get("name", "") or ""
        dest_country_code = (dest.get("position", {}) or {}).get("country", {}).get("code", "") or ""

        return {
            "flight_number": flight_number or callsign,
            "airline": airline,
            "origin_code": origin_code,
            "origin_name": origin_name,
            "origin_city": origin_city,
            "origin_country": origin_country,
            "origin_country_code": origin_country_code,
            "dest_code": dest_code,
            "dest_name": dest_name,
            "dest_city": dest_city,
            "dest_country": dest_country,
            "dest_country_code": dest_country_code,
            "aircraft_code": aircraft_code,
            "aircraft_model": aircraft_model,
            "aircraft_age": aircraft_age,
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


def format_message(flight):
    """Format a notification message from flight info."""
    origin_flag = _country_flag(flight["origin_country_code"])
    dest_flag = _country_flag(flight["dest_country_code"])

    aircraft = flight["aircraft_code"]
    if flight["aircraft_model"]:
        aircraft = f"{flight['aircraft_model']} ({aircraft})"

    lines = [
        f"✈  {flight['flight_number']} - {flight['airline']}",
        "",
        f"🛫 From:",
        f"{flight['origin_name']} ({flight['origin_code']})",
        f"{flight['origin_city']}, {flight['origin_country']} {origin_flag}",
        "",
        f"🛬 To:",
        f"{flight['dest_name']} ({flight['dest_code']})",
        f"{flight['dest_city']}, {flight['dest_country']} {dest_flag}",
        "",
        f"🛩 Aircraft: {aircraft}",
        f"🔖 Tail: {flight['aircraft_registration']}" if flight["aircraft_registration"] else "",
        f"📅 Age: {flight['aircraft_age']} years" if flight["aircraft_age"] else "",
    ]

    return "\n".join(lines)


def _parse_shoutrrr_url(url):
    """Parse a Shoutrrr-style URL into service type and params."""
    m = re.match(r"^telegram://([^@]+)@telegram\?chats?=(.+)$", url)
    if m:
        return "telegram", {"token": m.group(1), "chat_id": m.group(2)}
    return "shoutrrr", {}


def _send_telegram(token, chat_id, message):
    """Send via Telegram Bot API directly (handles unicode properly)."""
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message},
        timeout=15,
    )
    if resp.status_code != 200:
        log.error("Telegram API error: %s %s", resp.status_code, resp.text)
    else:
        log.info("Notification sent via Telegram")


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


def send_notification(message):
    """Send a notification. Uses Telegram API directly if URL is telegram://, otherwise shoutrrr."""
    if not SHOUTRRR_URL:
        log.warning("SHOUTRRR_URL not set, skipping notification")
        return

    service, params = _parse_shoutrrr_url(SHOUTRRR_URL)
    if service == "telegram":
        _send_telegram(params["token"], params["chat_id"], message)
    else:
        _send_shoutrrr(SHOUTRRR_URL, message)


def main():
    if not SHOUTRRR_URL:
        log.warning("SHOUTRRR_URL not configured — notifications will be skipped")

    log.info("Starting flight tracker (center=%.4f,%.4f radius=%gkm delay=%ds)",
             LATITUDE, LONGITUDE, RADIUS_KM, QUERY_DELAY)

    send_notification("✅ FlightOverME started\n"
                      f"📍 Location: {LATITUDE}, {LONGITUDE}\n"
                      f"📡 Radius: {RADIUS_KM} km\n"
                      f"⏱ Interval: {QUERY_DELAY}s")

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
