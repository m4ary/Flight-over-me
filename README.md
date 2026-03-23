<p align="center">
  <img src="logo.svg" width="150" alt="FlightOverME logo"/>
</p>

<h1 align="center">FlightOverME</h1>

<p align="center">
  Detect flights overhead and get instant notifications via Telegram, Discord, Slack, and more.
</p>

<p align="center">
  <a href="https://hub.docker.com/r/m4ary/flightoverme"><img src="https://img.shields.io/docker/v/m4ary/flightoverme?label=Docker%20Hub&logo=docker" alt="Docker Hub"/></a>
  <img src="https://img.shields.io/docker/image-size/m4ary/flightoverme/latest?label=Size" alt="Image Size"/>
  <img src="https://img.shields.io/badge/arch-amd64%20%7C%20arm64-blue" alt="Architectures"/>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"/></a>
</p>

---

## Features

- **Flight notifications** -- get alerted when a plane flies over your area with flight number, airline, route, aircraft type, tail number, and country flags
- **Runway monitoring** -- get notified when the active runway changes direction, with estimated duration from TAF forecast
- **Telegram bot** -- send `/wind` to get current wind, active runway, and METAR data on demand
- **Multi-arch** -- runs on amd64 and arm64 (Raspberry Pi, etc.)

## Quick Start

```bash
docker run -d --restart unless-stopped \
  -e SHOUTRRR_URL="telegram://token@telegram?chats=chat-id" \
  -e LATITUDE=24.8539 \
  -e LONGITUDE=46.7484 \
  -e RADIUS_KM=10 \
  m4ary/flightoverme
```

Or with Docker Compose:

```bash
cp .env.example .env   # edit with your settings
docker compose up -d
```

## Configuration

### Flight Tracking

| Variable | Description | Default |
|----------|-------------|---------|
| `SHOUTRRR_URL` | Notification URL ([supported services](https://containrrr.dev/shoutrrr/services/overview/)) | _(required)_ |
| `LATITUDE` | Your latitude | `24.8539174` |
| `LONGITUDE` | Your longitude | `46.7484485` |
| `RADIUS_KM` | Search radius in kilometers | `10` |
| `QUERY_DELAY` | Seconds between flight checks | `30` |

### Runway Monitoring (optional)

| Variable | Description | Example |
|----------|-------------|---------|
| `AIRPORT_ICAO` | ICAO code for METAR/TAF data | `OERK` |
| `AIRPORT_CODE` | IATA code for display | `RUH` |
| `RUNWAY_HEADINGS` | Comma-separated runway headings | `330,150` |

## Finding Your Coordinates

Right-click any location on [Google Maps](https://maps.google.com) and copy the latitude/longitude.

## Telegram Bot Commands

When using Telegram as your notification service, the bot listens for commands:

| Command | Description |
|---------|-------------|
| `/wind` | Current wind, active runway, estimated duration, and raw METAR |

## Notification Examples

**Flight overhead:**
```
✈  SV775 - Saudia

🛫 From:
Cochin International (COK)
Kochi, India 🇮🇳

🛬 To:
Riyadh King Khalid International (RUH)
Riyadh, Saudi Arabia 🇸🇦

🛩 Aircraft: Airbus A330-343 (A333)
🔖 Tail: HZ-AQ23
📅 Age: 8 years
```

**Runway change:**
```
🛣 RUH Runway Changed: 15 → 33

🌬 Wind: NNE 5kt
🧭 Landing from: SSE
⏱ Estimated duration: ~6h
```

## Shoutrrr URL Examples

| Service  | URL Format                                    |
|----------|-----------------------------------------------|
| Telegram | `telegram://token@telegram?chats=chat-id`     |
| Discord  | `discord://token@webhookid`                   |
| Slack    | `slack://token-a/token-b/token-c`             |
| Gotify   | `gotify://hostname/token`                     |
| Email    | `smtp://user:pass@host:port/?to=recipient`    |

## Data Sources

- **FlightRadar24** -- flight tracking (unofficial public endpoints)
- **aviationweather.gov** -- METAR and TAF data (free, no API key)

## Contributing

Found a bug or have an idea? [Open an issue](https://github.com/m4ary/Flight-over-me/issues) or submit a pull request.

## License

[MIT](LICENSE)
