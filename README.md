# Planes

A small, mobile-first local web interface for an ADS-B receiver running readsb/tar1090.

Planes is designed to sit alongside an existing ADS-B setup: it reads the aircraft JSON feed produced by readsb/tar1090 and turns it into a simple dashboard, statistics view and aircraft information interface.

## Current version

**v0.0.4**

v0.0.4 adds a dedicated Documentation page and expands the in-app guidance.

## Current features

- Live aircraft count and feed status
- Configurable aircraft JSON URL
- Search by flight/callsign, aircraft type and ICAO HEX
- Sorting
- Device-local favourites
- Configurable refresh interval
- Aircraft detail pages
- ICAO/HEX, callsign, type, squawk, altitude, speed, position, distance and bearing information when supplied by the feed
- Optional ASBDB callsign/route information
- Statistics page
- Dark, light and system themes
- Responsive mobile layout
- Keyboard-friendly navigation, skip link, visible focus, semantic headings and table headers
- Reduced-motion support and status announcements for dynamic updates
- Built-in Documentation page
- Configurable settings saved locally by the application

## How Planes works

Planes does **not** control the RTL-SDR directly.

A typical setup is:

```text
RTL-SDR → readsb → tar1090/readsb JSON → Planes → Web browser
```

The default aircraft feed is:

```text
http://127.0.0.1:8504/data/aircraft.json
```

Using `127.0.0.1` means the feed is expected to be available on the same machine running Planes. If Planes and readsb are on different machines, use the appropriate reachable feed URL in **Settings**.

## First-time setup

### Requirements

- Python 3.10+
- A working readsb/tar1090 aircraft JSON feed
- Network access to the machine running Planes
- A modern web browser

### Install

From the Planes project directory:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

On Windows, activate the virtual environment with:

```text
venv\\Scripts\\activate
```

Then open:

```text
http://<your-pi-ip>:8000
```

For example, if your Raspberry Pi is on `192.168.0.33`:

```text
http://192.168.0.33:8000
```

### Check the aircraft feed first

Before troubleshooting Planes, verify that readsb is producing aircraft JSON.

On the receiver machine:

```bash
curl http://127.0.0.1:8504/data/aircraft.json
```

A working response should contain JSON with an `aircraft` list.

If this URL does not work, fix the readsb/tar1090 setup first. Planes cannot display aircraft that are not present in its configured feed.

## Starting Planes

Activate the virtual environment and run:

```bash
source venv/bin/activate
python main.py
```

The server listens on port **8000**.

Then visit:

```text
http://<your-pi-ip>:8000
```

Keep the terminal running while using Planes.

## Restarting Planes

If you stopped Planes with `Ctrl+C`, simply start it again:

```bash
cd ~/planes
source venv/bin/activate
python main.py
```

If you are not sure whether it is already running, check port 8000:

```bash
ss -ltnp | grep :8000
```

If another Planes process is already using port 8000, do not start a second copy. Stop the existing process or use the existing web page.

### Restarting after a Raspberry Pi reboot

If Planes is currently started manually with `python main.py`, it will stop when the Pi reboots.

To make Planes start automatically, create a systemd service. Example:

```ini
[Unit]
Description=Planes aircraft web interface
After=network-online.target
Wants=network-online.target

[Service]
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/planes
ExecStart=/home/YOUR_USER/planes/venv/bin/python /home/YOUR_USER/planes/main.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Save it as:

```text
/etc/systemd/system/planes.service
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now planes
sudo systemctl status planes
```

Replace `YOUR_USER` with the Linux username that owns the Planes installation.

## User guide

### Dashboard

The Dashboard is the main live aircraft view.

Use it to:

- See the current number of aircraft
- Search for a callsign, aircraft type or HEX
- Sort the aircraft list
- Favourite an aircraft
- Open aircraft details
- Manually refresh the data
- Watch the automatic refresh status

### Aircraft details

Open an aircraft from the Dashboard to see the information currently available from the receiver.

Depending on the aircraft and feed, this can include:

- ICAO/HEX
- Callsign
- Aircraft type
- Squawk
- Altitude
- Ground speed
- Latitude/longitude
- Distance from the receiver
- Bearing
- Scheduled route information from ASBDB, when available

Not every aircraft transmits every field, so missing information is normal.

### Statistics

Statistics summarise the aircraft currently visible to the receiver.

The exact values depend on the data currently supplied by readsb. Missing or invalid measurements are excluded from calculations where appropriate.

### Settings

Settings lets you configure:

- **Aircraft data URL** — the JSON feed Planes reads
- **Refresh interval** — how often the live data is refreshed
- **ASBDB lookups** — whether optional scheduled route information is requested

Theme selection is handled in the interface and stored in the browser.

### Favourites

Use the star/favourite control to mark aircraft you want to find again.

Favourites are stored locally in the browser/device rather than being synchronised to a server.

## Common problems and fixes

### No aircraft are showing

Check the configured feed URL.

On the Pi:

```bash
curl http://127.0.0.1:8504/data/aircraft.json
```

If it fails, check that readsb is running:

```bash
systemctl status readsb
```

Also check that the URL in **Settings** matches the machine running the feed.

### The Planes page will not load

Check that Planes is running:

```bash
ss -ltnp | grep :8000
```

Then try the page from the Pi itself:

```bash
curl -I http://127.0.0.1:8000/
```

If that works on the Pi but not from another device, check the Pi's IP address, network connection and firewall configuration.

### Aircraft type says Unknown

The receiver has not supplied usable aircraft type/description information for that aircraft.

This does not necessarily mean the aircraft itself is unknown. Planes currently displays the information available from the feed rather than inventing a type.

### Route information is missing

ASBDB is optional and may not have route information for every callsign.

Check that ASBDB lookups are enabled in Settings and that the aircraft has a usable callsign.

### The feed works with curl but Planes shows an error

Check that the URL in **Settings** is exactly the URL that works with curl.

Also make sure the response is valid JSON and contains the expected aircraft data.

### Changes in Settings do not seem to apply

Save the settings and refresh the page.

If a browser has cached an old version of the interface, perform a normal hard refresh.

### Port 8000 is already in use

Find the process using the port:

```bash
ss -ltnp | grep :8000
```

Do not run another Planes instance on the same port. Stop the old process first if necessary.

### `ModuleNotFoundError`

Make sure the virtual environment is activated:

```bash
source venv/bin/activate
```

Then reinstall the requirements:

```bash
pip install -r requirements.txt
```

You can check the Python interpreter with:

```bash
which python
python --version
```

### `pip` or dependency installation fails

First check your Python version:

```bash
python3 --version
```

Then update pip inside the virtual environment:

```bash
python -m pip install --upgrade pip
```

Run the installation again:

```bash
pip install -r requirements.txt
```

If installation still fails, keep the complete error message when reporting the problem. The final lines alone often do not contain the real cause.

## Updating Planes from GitHub

Before updating, stop the currently running Planes process.

Then:

```bash
cd ~/planes
git status
git pull
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

If you have local changes, do **not** blindly run `git pull`. Check `git status` first so local work is not overwritten or put into a difficult merge.

## Development

Clone the repository:

```bash
git clone https://github.com/H-J-Wilson/planes.git
cd planes
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

The application is currently a small Python web application with the main server entry point in `main.py` and the web interface/routes in `webpage.py`.

## Accessibility

The project is designed to be checked with the WAVE browser extension at the rendered-page level.

Test at least:

- Dashboard
- Statistics
- Settings
- Aircraft details
- Documentation
- Mobile-width viewport
- Keyboard-only navigation
- 200% zoom/reflow
- Light and dark themes
- Reduced-motion behaviour

WAVE is an automated aid, not a complete accessibility certification; manual keyboard and visual checks are still required.

## Future roadmap

The following are planned ideas and are **not all implemented in v0.0.4**.

### Aircraft and tracking

- Military aircraft detection with clear MIL badges
- New Tracks mode for recently appeared aircraft
- Interesting-aircraft detection
- First-seen and last-seen times
- Track duration
- Remember aircraft seen during the day/week
- Aircraft history and previous observations

### Better aircraft cards

Potential additional fields include:

- Callsign
- Registration
- Aircraft type and full description
- Operator
- Origin → destination airport codes such as `BHX → LHR`
- Altitude
- Ground speed
- IAS / TAS
- Mach
- Heading
- Vertical rate
- Roll
- Turn rate
- Distance from receiver
- Position age
- Messages received
- Time tracked
- Military/interesting status

Some fields depend on what the receiver actually supplies; Planes should not imply that a value is available when it is not.

### More statistics

Possible future normal statistics:

- Aircraft currently visible
- New tracks
- Military aircraft
- Unique aircraft today
- Average altitude
- Average speed
- Average distance
- Aircraft with valid positions
- Aircraft currently climbing/descending

Possible niche statistics:

- Highest altitude
- Fastest ground speed
- Fastest TAS
- Highest Mach
- Fastest climb
- Fastest descent
- Sharpest turn
- Largest roll
- Furthest aircraft
- Closest aircraft
- Most messages received
- Strongest signal
- Longest tracked aircraft
- Most new tracks
- Most military tracks
- Most common operator
- Most common aircraft type
- Most common origin
- Most common destination

### Records

A future Records section could maintain:

- Highest aircraft ever seen
- Fastest aircraft
- Fastest climb/descent
- Sharpest turn
- Highest Mach
- Furthest aircraft
- Closest aircraft
- Longest tracked aircraft
- Most messages

with **Today / 7 Days / All Time** views.

### Alerts

Optional future alerts could include:

- Military aircraft detected
- New aircraft detected
- Aircraft very close to the receiver
- Very high altitude
- Very high speed
- Emergency squawks
- Interesting aircraft
- Specific callsigns or registrations

### Receiver statistics

Future receiver monitoring could include:

- Aircraft count
- Messages/sec
- Position updates/sec
- Maximum range
- Feed latency
- CPU usage
- Memory usage
- Uptime
- Receiver performance over time

### "What changed?" summary

A future dashboard summary could show changes since the previous update, for example:

```text
Since last update

+7 new aircraft
-4 disappeared
+1 military
+2 interesting
Highest altitude ↑ 3,200 ft
Fastest aircraft ↑ 41 kt
```

### Historical data

Eventually, Planes could keep a local database containing:

- Every aircraft observed
- First/last seen
- Number of sightings
- Total tracking time
- Maximum altitude
- Maximum speed
- Historical statistics
- Daily/weekly/monthly summaries

The long-term goal is to develop Planes from a live aircraft viewer into a **personal ADS-B tracking and statistics system**, while keeping the interface focused and without requiring a map.

## Data sources

### readsb / tar1090

Provides the live aircraft data from the local ADS-B receiver.

### ASBDB

Provides optional scheduled flight/route information when a callsign can be matched.

ASBDB is supplementary information and is not the source of the live aircraft position.

## Project structure

Important files include:

```text
planes/
├── main.py
├── webpage.py
├── requirements.txt
├── README.md
└── static/
```

The exact repository contents can change between versions.

## Version history

### v0.0.4

- Added the Documentation page
- Added Documentation to the main navigation
- Expanded user guidance and troubleshooting
- Updated application version references

### v0.0.3

- Live aircraft dashboard improvements
- Aircraft detail information
- Statistics
- Settings
- Favourites
- Responsive interface
- Accessibility and theme improvements

## Licence

See the `LICENSE` file in the repository.

## Links

- Repository: https://github.com/H-J-Wilson/planes
- Releases: https://github.com/H-J-Wilson/planes/releases
