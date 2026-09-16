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

The default assumes readsb/tar1090 and Planes run on the same machine.

## Requirements

- Python 3.10+
- Working readsb/tar1090 aircraft JSON feed
- Network access to the machine running Planes

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

## First check: the aircraft feed

Before debugging Planes, make sure the receiver is producing aircraft data:

```bash
curl http://127.0.0.1:8504/data/aircraft.json
```

The response should be JSON containing an `aircraft` list.

If this fails, fix readsb/tar1090 first.

## Updating Planes

Stop the running Planes process first.

Check for local changes:

```bash
cd ~/planes
git status
```

For the normal `main` branch:

```bash
git pull
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Do not run `git pull` when `git status` shows changes you need to keep. Back them up first.

### Testing the current audit-fix branch

The reliability fixes are currently on:

```text
v0.0.5-audit-fixes
```

On the Pi:

```bash
cd ~/planes
git status
git fetch origin
git checkout v0.0.5-audit-fixes
git pull
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

When testing is finished, return to `main` with:

```bash
git checkout main
git pull
```

Do not delete the branch until testing is complete.

## Dashboard

The Dashboard provides:

- Live aircraft count
- Feed status
- Data age when supplied by the feed
- Search by callsign, aircraft type, description, registration or ICAO HEX
- Sorting by flight, type, speed, altitude or distance
- Moving/climbing/descending filters
- Valid-position filter
- Favourite filter
- Minimum altitude and speed filters
- Local favourites
- Aircraft detail links

Aircraft fields depend on what readsb supplies. Missing values are normal.

## Aircraft details

Details can include:

- ICAO HEX
- Callsign
- Aircraft type/description
- Squawk
- Altitude
- Ground speed
- Latitude/longitude
- Distance and bearing
- ASBDB route information when available

## Statistics

The Statistics page summarises the aircraft currently visible to the receiver.

Values depend on the data currently supplied by readsb. Missing or invalid measurements are excluded where appropriate.

## Settings

Settings controls:

- **Aircraft data URL** — JSON feed used by Planes
- **Refresh interval** — browser refresh interval
- **ASBDB** — optional route lookups
- **Theme** — system, dark or light

Use **Test feed** before saving a new feed URL. On the audit-fix branch, the test checks the URL currently typed into the box rather than only the saved URL.

## Favourites

Favourites are stored in the browser's local storage. They are not sent to a server.

## Troubleshooting

### No aircraft

```bash
curl http://127.0.0.1:8504/data/aircraft.json
systemctl status readsb
```

Check that the URL in Settings matches the working feed URL.

### Planes will not load

```bash
ss -ltnp | grep :8000
curl -I http://127.0.0.1:8000/
```

If it works on the Pi but not another device, check the Pi IP/network/firewall.

### Aircraft type says Unknown

Planes displays the type information supplied by the receiver. If `t` and `desc` are missing, the UI cannot display a type from the feed alone.

### Route is missing

ASBDB is optional and does not have matching information for every callsign.

### Settings or dependency errors

```bash
source venv/bin/activate
python --version
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Port 8000 already in use

```bash
ss -ltnp | grep :8000
```

Stop the existing Planes process before starting another one.

## Development

Main files:

```text
planes/
├── main.py
├── webpage.py
├── runtime_fixes.py        # audit branch reliability layer
├── requirements.txt
├── settings.json
└── static/
```

`main.py` starts Uvicorn. `webpage.py` contains the FastAPI app, routes, HTML and browser JavaScript. `runtime_fixes.py` contains the temporary audit-branch reliability fixes that will be folded into the main application after testing.

For a detailed code walkthrough, use the **Documentation** page inside Planes.

## Testing checklist

Before merging a release candidate, test:

### Dashboard

- Page loads
- Aircraft appear
- Aircraft count changes with feed data
- Data age is shown
- Automatic refresh changes the list
- Manual Refresh works
- Search works for callsign
- Search works for HEX
- Search works for type/description
- Search works for registration
- Clearing search restores the list
- Sorting works
- Moving filter works
- Climbing filter works
- Descending filter works
- Valid position filter works
- Favourite filter works
- Minimum altitude works
- Minimum speed works
- Clearing filters restores the list
- Favourite star can be added and removed
- Aircraft details open

### Failure behaviour

Temporarily make the configured feed unavailable and confirm:

- The page does not crash
- Previously loaded aircraft remain visible
- Feed status changes to a stale/unavailable state
- The UI does not falsely report the feed as healthy
- Restoring the feed returns to normal updates

### Settings

- Save a valid feed URL
- Test a valid feed URL
- Enter an invalid feed URL and confirm an error is shown
- Test a URL before saving it
- Change refresh interval
- Toggle ASBDB
- Change theme

### Other pages

- Statistics loads
- Aircraft details load
- Documentation loads
- About loads
- Contact loads

### Mobile/accessibility

- Test a narrow mobile viewport
- Keyboard navigation works
- Focus is visible
- Light and dark themes work
- Reduced-motion behaviour does not break the UI

## Current version

The latest released version is **v0.0.5**. The `v0.0.5-audit-fixes` branch contains reliability fixes found during post-release testing and is not a release yet.

## Data sources

### readsb / tar1090

Provides the live aircraft JSON used by Planes.

### ASBDB

Provides optional scheduled route/airline information for callsigns when available. It is not the source of live aircraft position data.

## Roadmap

Planned ideas include:

- Military aircraft detection
- New Tracks mode
- Better aircraft cards with registration/operator/airport codes
- More receiver and aircraft statistics
- Records and historical data
- Alerts
- Track history

These are ideas, not promises of a particular release.