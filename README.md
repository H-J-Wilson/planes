# Planes

Local web interface for an ADS-B receiver using readsb/tar1090.

Planes reads the aircraft JSON feed and provides a live dashboard, aircraft details, statistics and settings. It does not control the RTL-SDR.

## How it works

```text
RTL-SDR → readsb → tar1090/readsb JSON → Planes → Browser
```

Default feed:

```text
http://127.0.0.1:8504/data/aircraft.json
```

## Requirements

- Raspberry Pi/Linux/macOS
- Python 3.10+
- Working readsb/tar1090 aircraft JSON feed

## Install

```bash
git clone https://github.com/H-J-Wilson/planes.git
cd planes
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Open:

```text
http://<PI-IP>:8000
```

Example:

```text
http://192.168.0.33:8000
```

Before troubleshooting Planes, check the receiver feed:

```bash
curl http://127.0.0.1:8504/data/aircraft.json
```

The response should be JSON containing an `aircraft` list.

## Update

Stop Planes first.

Check for local changes:

```bash
cd ~/planes
git status
```

For the normal development branch:

```bash
git checkout main
git pull
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Do not run `git pull` when `git status` shows work you need to keep.

## Testing the current fixes

The current reliability fixes are on:

```text
v0.0.5-audit-fixes
```

On the Pi:

```bash
cd ~/planes
git fetch origin
git checkout v0.0.5-audit-fixes
git pull
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

This branch is a test candidate, not a released version.

When testing is finished:

```bash
git checkout main
git pull
```

## Raspberry Pi dependency note

The project requirements force pip to use PyPI directly:

```text
--index-url https://pypi.org/simple
```

This avoids a piwheels package-metadata problem that can cause pip to reject some Jinja2 and typing-extensions wheels.

## Dashboard

The Dashboard provides:

- live aircraft count
- feed status
- receiver data age
- search by callsign, type, description, registration and HEX
- sorting by flight, type, speed, altitude and distance
- moving, climbing, descending and valid-position filters
- favourites
- minimum altitude and speed filters
- manual refresh
- automatic refresh
- aircraft detail links

Aircraft fields depend on what readsb supplies. Missing values are normal.

## Aircraft details

Details can include:

- ICAO HEX
- callsign
- registration
- aircraft type/description
- squawk
- altitude
- ground speed
- vertical rate
- heading
- latitude/longitude
- distance and bearing
- scheduled route information from ASBDB when available

## Statistics

The Statistics page currently includes:

- aircraft visible
- aircraft with valid positions
- moving
- climbing
- descending
- average altitude
- average speed
- highest altitude
- fastest speed
- feed state
- feed response time
- aircraft type counts

Statistics use the current receiver data only. There is no historical database yet.

## Settings

Settings controls:

- **Aircraft data URL** — JSON feed used by Planes
- **Refresh interval** — browser refresh rate
- **ASBDB** — optional scheduled route lookup
- **Theme** — system, dark or light

Use **Test feed** before saving a new URL. It checks the URL currently typed into the box.

## Favourites

Favourites are stored in the browser's local storage. They are not sent to a server.

## Troubleshooting

### No aircraft

```bash
curl http://127.0.0.1:8504/data/aircraft.json
systemctl status readsb
```

### Planes will not load

```bash
ss -ltnp | grep :8000
curl -I http://127.0.0.1:8000/
```

### Aircraft type says Unknown

Planes displays the `t` or `desc` information supplied by the receiver. If both are missing, there is no type available from the feed.

### Route information is missing

ASBDB is optional and may not have a route for every callsign.

### Dependency installation fails

Activate the virtual environment and retry:

```bash
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Port 8000 is already in use

```bash
ss -ltnp | grep :8000
```

Stop the existing Planes process before starting another one.

## Project structure

```text
planes/
├── main.py
├── webpage.py
├── settings.json
├── requirements.txt
├── static/
├── tests/
└── README.md
```

`main.py` starts Uvicorn.

`webpage.py` contains the FastAPI application, routes, feed handling, HTML generation and Dashboard JavaScript.

`settings.json` stores local application settings.

`requirements.txt` defines Python dependencies.

`tests/` contains backend reliability tests.

## Testing checklist

### Dashboard

- page loads
- aircraft appear
- aircraft count updates
- data age updates
- automatic refresh works
- manual refresh works
- callsign search works
- HEX search works
- type/description search works
- registration search works
- clearing search works
- all/moving/climbing/descending filters work
- valid-position filter works
- favourites filter works
- minimum altitude works
- minimum speed works
- sorting works
- favourite star works
- aircraft details open

### Feed failure

Temporarily stop readsb:

```bash
sudo systemctl stop readsb
```

Confirm:

- Planes stays open
- existing aircraft remain visible
- feed status changes to stale/unavailable
- the UI does not say the feed is healthy

Restart readsb:

```bash
sudo systemctl start readsb
```

Confirm live updates resume.

### Settings

- test the current URL
- test a bad URL
- test an unsaved new URL
- save a valid URL
- change refresh interval
- toggle ASBDB
- change theme

### Other pages

- Statistics
- Aircraft Details
- Documentation
- About
- Contact

### Mobile

Check a narrow browser window and make sure controls and tables still fit.

## Automated tests

Run locally with:

```bash
source venv/bin/activate
python -m py_compile main.py webpage.py
python -m unittest discover -s tests -v
```

GitHub Actions also compiles and tests the project on Python 3.10–3.13.

## Current release state

Latest released version: **v0.0.5**

The branch `v0.0.5-audit-fixes` contains reliability and polish fixes found during post-release testing.

Do not treat the audit branch as a release until the Pi checklist passes.

## Data sources

### readsb / tar1090

Live aircraft JSON.

### ASBDB

Optional scheduled flight/route/airline information. It is not the source of live aircraft position data.

## Roadmap

Planned ideas include:

- military aircraft detection
- New Tracks mode
- richer aircraft cards
- airport codes
- more receiver/aircraft statistics
- historical records
- alerts
- track history
