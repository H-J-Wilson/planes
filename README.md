# Planes

A small, mobile-first local web interface for an ADS-B receiver running readsb/tar1090.

## Features in v0.0.3

- Live aircraft count and feed status
- Configurable aircraft JSON URL
- Search and sorting
- Device-local favourites
- Configurable refresh interval
- Aircraft detail pages with optional ASBDB callsign/route information
- Statistics page
- Dark cyan, light and system themes
- Responsive mobile layout
- Keyboard-friendly navigation, skip link, visible focus, semantic headings and table headers
- Reduced-motion support and status announcements for dynamic updates

## Run

Python 3.10+ is required.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Then open:

```text
http://<your-pi-ip>:8000
```

The default aircraft feed is:

```text
http://127.0.0.1:8504/data/aircraft.json
```

This is designed for the existing readsb/tar1090 setup, so the web app reads the feed rather than trying to take control of the RTL-SDR itself.

## Settings

Use **Settings** in the web interface to change the aircraft feed URL, refresh interval and ASBDB route lookups. Theme selection is saved in the current browser.

## Accessibility testing

The project is designed to be checked with the WAVE browser extension at the rendered-page level. Test at least:

- Dashboard
- Statistics
- Settings
- Aircraft details
- Mobile-width viewport
- Keyboard-only navigation
- 200% zoom/reflow
- Light and dark themes

WAVE is an automated aid, not a complete accessibility certification; manual keyboard and visual checks are still required.
