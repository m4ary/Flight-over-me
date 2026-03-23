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

| Variable | Description | Default |
|----------|-------------|---------|
| `SHOUTRRR_URL` | Notification URL ([supported services](https://containrrr.dev/shoutrrr/services/overview/)) | _(required)_ |
| `LATITUDE` | Your latitude | `24.8539174` |
| `LONGITUDE` | Your longitude | `46.7484485` |
| `RADIUS_KM` | Search radius in kilometers | `10` |
| `QUERY_DELAY` | Seconds between flight checks | `30` |

## Finding Your Coordinates

Right-click any location on [Google Maps](https://maps.google.com) and copy the latitude/longitude.

## Shoutrrr URL Examples

| Service  | URL Format                                    |
|----------|-----------------------------------------------|
| Telegram | `telegram://token@telegram?chats=chat-id`     |
| Discord  | `discord://token@webhookid`                   |
| Slack    | `slack://token-a/token-b/token-c`             |
| Gotify   | `gotify://hostname/token`                     |
| Email    | `smtp://user:pass@host:port/?to=recipient`    |

## How It Works

The app queries FlightRadar24's public endpoints every `QUERY_DELAY` seconds for flights within your bounding box. When a new flight is detected, it sends a notification with:

- Flight number and airline
- Route (origin -> destination)
- Aircraft type

Duplicate notifications are suppressed -- you only get notified once per flight.

## Contributing

Found a bug or have an idea? [Open an issue](https://github.com/m4ary/Flight-over-me/issues) or submit a pull request.

## Note

This uses unofficial FlightRadar24 endpoints -- it may break if they change their API.

## License

[MIT](LICENSE)
