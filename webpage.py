import datetime as dt
import html
import ipaddress
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import fastapi
import requests
from fastapi import Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = fastapi.FastAPI(title="Planes Flight Tracker")
app.mount("/static", StaticFiles(directory="static"), name="static")

SETTINGS_FILE = Path("settings.json")
DEFAULT_SETTINGS = {
    "aircraft_data_url": "http://127.0.0.1:8504/data/aircraft.json",
    "refresh_seconds": 5,
    "asbdb_enabled": True,
    "asbdb_cache_seconds": 30,
}
ASBDB_BASE = "https://api.adsbdb.com/v0/callsign/"
APP_VERSION = "0.0.5-test"
FIRST_RUN_FILE = Path(".planes_setup_complete")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s planes: %(message)s")
logger = logging.getLogger("planes")


def load_settings() -> dict[str, Any]:
    settings = DEFAULT_SETTINGS.copy()
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            settings.update(raw)
    except (OSError, json.JSONDecodeError, TypeError):
        logger.warning("Unable to read settings.json cleanly; using defaults.")

    try:
        settings["aircraft_data_url"] = validate_data_url(
            str(settings.get("aircraft_data_url", DEFAULT_SETTINGS["aircraft_data_url"]))
        )
    except (ValueError, TypeError):
        settings["aircraft_data_url"] = DEFAULT_SETTINGS["aircraft_data_url"]

    try:
        refresh = int(settings.get("refresh_seconds", DEFAULT_SETTINGS["refresh_seconds"]))
    except (TypeError, ValueError):
        refresh = DEFAULT_SETTINGS["refresh_seconds"]
    settings["refresh_seconds"] = max(2, min(60, refresh))

    settings["asbdb_enabled"] = bool(settings.get("asbdb_enabled", DEFAULT_SETTINGS["asbdb_enabled"]))
    try:
        cache_seconds = int(settings.get("asbdb_cache_seconds", DEFAULT_SETTINGS["asbdb_cache_seconds"]))
    except (TypeError, ValueError):
        cache_seconds = DEFAULT_SETTINGS["asbdb_cache_seconds"]
    settings["asbdb_cache_seconds"] = max(5, min(3600, cache_seconds))
    return settings

def setup_complete() -> bool:
    return FIRST_RUN_FILE.exists()


def mark_setup_complete() -> None:
    FIRST_RUN_FILE.write_text("Planes setup completed.\\n", encoding="utf-8")


def setup_content() -> str:
    settings = load_settings()
    feed_url = clean(settings.get("aircraft_data_url", DEFAULT_SETTINGS["aircraft_data_url"]))
    refresh = settings["refresh_seconds"]
    asbdb_checked = "checked" if settings.get("asbdb_enabled", True) else ""
    return f'''<section class="panel setup-hero">
      <p class="eyebrow">FIRST-RUN SETUP</p>
      <h2>Welcome to Planes</h2>
      <p>Set the few options Planes needs before opening the live aircraft dashboard. You can change all of these later in Settings.</p>
    </section>

    <form id="setup-form" class="panel settings-form">
      <div>
        <label for="setup-feed-url">Aircraft data URL</label>
        <input id="setup-feed-url" type="url" value="{feed_url}" required>
        <p class="field-help">Default for readsb/tar1090 on the same Pi: <code>http://127.0.0.1:8504/data/aircraft.json</code></p>
      </div>

      <div>
        <label for="setup-refresh">Refresh interval</label>
        <select id="setup-refresh">
          {''.join(f'<option value="{n}" {"selected" if refresh == n else ""}>{n} seconds</option>' for n in [2,3,5,10,15,30,60])}
        </select>
      </div>

      <div>
        <label for="setup-theme">Base theme</label>
        <select id="setup-theme">
          <option value="system">Use system setting</option>
          <option value="dark">Dark</option>
          <option value="light">Light</option>
        </select>
        <p class="field-help">You can change this later without changing receiver settings.</p>
      </div>

      <label class="checkbox">
        <input id="setup-asbdb" type="checkbox" {asbdb_checked}>
        Enable optional ASBDB route information
      </label>

      <div class="form-actions">
        <button id="setup-test" class="button secondary" type="button">Test feed</button>
        <button class="button" type="submit">Save and open Planes</button>
        <span id="setup-status" role="status" aria-live="polite"></span>
      </div>
    </form>

    <section class="panel">
      <h2>What happens next?</h2>
      <ul class="clean-list">
        <li>Planes saves the receiver URL and refresh interval.</li>
        <li>Your theme is saved only in this browser.</li>
        <li>The Dashboard opens and starts live refreshes.</li>
        <li>You can change these settings at any time.</li>
      </ul>
    </section>

    <script>
      (() => {{
        const form = document.getElementById('setup-form');
        const url = document.getElementById('setup-feed-url');
        const refresh = document.getElementById('setup-refresh');
        const theme = document.getElementById('setup-theme');
        const asbdb = document.getElementById('setup-asbdb');
        const test = document.getElementById('setup-test');
        const status = document.getElementById('setup-status');

        theme.value = localStorage.getItem('planes-theme') || 'system';
        document.documentElement.dataset.theme = theme.value;
        theme.addEventListener('change', () => {{
          localStorage.setItem('planes-theme', theme.value);
          document.documentElement.dataset.theme = theme.value;
        }});

        test.addEventListener('click', async () => {{
          status.textContent = 'Testing feed…';
          try {{
            const response = await fetch('/api/test-feed-url?url=' + encodeURIComponent(url.value.trim()), {{cache:'no-store'}});
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || 'Feed test failed');
            status.textContent = 'Feed OK · ' + result.aircraft_count + ' aircraft · ' + result.response_ms + ' ms';
          }} catch (error) {{
            status.textContent = error.message || 'Feed test failed';
          }}
        }});

        form.addEventListener('submit', async event => {{
          event.preventDefault();
          status.textContent = 'Saving…';
          try {{
            const response = await fetch('/api/setup', {{
              method: 'POST',
              headers: {{'Content-Type': 'application/json'}},
              body: JSON.stringify({{
                aircraft_data_url: url.value.trim(),
                refresh_seconds: Number(refresh.value),
                asbdb_enabled: asbdb.checked
              }})
            }});
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || 'Setup could not be saved');
            localStorage.setItem('planes-theme', theme.value);
            document.documentElement.dataset.theme = theme.value;
            status.textContent = 'Setup complete. Opening Dashboard…';
            window.location.href = '/';
          }} catch (error) {{
            status.textContent = error.message || 'Setup could not be saved';
          }}
        }});
      }})();
    </script>'''


AIRCRAFT_LOOKUP_BASE = "https://api.adsbdb.com/v0/aircraft/"


def valid_aircraft_identifier(value: Any) -> bool:
    return bool(re.fullmatch(r"~?[0-9a-f]{6}", str(value or "").strip().lower()))


# Lightweight in-memory session metrics. These reset when Planes restarts.
PLANES_SESSION_STARTED = time.time()
PLANES_SESSION_LAST_SNAPSHOT: Any = None
PLANES_SESSION_SAMPLES = 0
PLANES_SESSION_AIRCRAFT_TOTAL = 0
PLANES_SESSION_PEAK_AIRCRAFT = 0
PLANES_SESSION_UNIQUE_HEX: set[str] = set()
PLANES_SESSION_HIGHEST_ALTITUDE: float | None = None
PLANES_SESSION_FASTEST_SPEED: float | None = None
PLANES_SESSION_FEED_UP = False
PLANES_SESSION_FEED_INTERRUPTS = 0


def record_feed_success(data: dict[str, Any]) -> None:
    global PLANES_SESSION_LAST_SNAPSHOT, PLANES_SESSION_SAMPLES
    global PLANES_SESSION_AIRCRAFT_TOTAL, PLANES_SESSION_PEAK_AIRCRAFT
    global PLANES_SESSION_HIGHEST_ALTITUDE, PLANES_SESSION_FASTEST_SPEED
    global PLANES_SESSION_FEED_UP
    PLANES_SESSION_FEED_UP = True
    snapshot_key = data.get("now")
    if snapshot_key == PLANES_SESSION_LAST_SNAPSHOT:
        return
    PLANES_SESSION_LAST_SNAPSHOT = snapshot_key
    aircraft = [a for a in data.get("aircraft", []) if isinstance(a, dict)]
    count = len(aircraft)
    PLANES_SESSION_SAMPLES += 1
    PLANES_SESSION_AIRCRAFT_TOTAL += count
    PLANES_SESSION_PEAK_AIRCRAFT = max(PLANES_SESSION_PEAK_AIRCRAFT, count)
    for plane in aircraft:
        hex_code = str(plane.get("hex") or "").strip().lower()
        if hex_code:
            PLANES_SESSION_UNIQUE_HEX.add(hex_code)
        altitude = plane.get("alt_baro")
        if isinstance(altitude, (int, float)):
            PLANES_SESSION_HIGHEST_ALTITUDE = max(PLANES_SESSION_HIGHEST_ALTITUDE or altitude, altitude)
        speed = plane.get("gs")
        if isinstance(speed, (int, float)):
            PLANES_SESSION_FASTEST_SPEED = max(PLANES_SESSION_FASTEST_SPEED or speed, speed)


def record_feed_failure() -> None:
    global PLANES_SESSION_FEED_UP, PLANES_SESSION_FEED_INTERRUPTS
    if PLANES_SESSION_FEED_UP:
        PLANES_SESSION_FEED_INTERRUPTS += 1
    PLANES_SESSION_FEED_UP = False


def format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_number(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return clean(value)


def readsb_stats_url() -> str:
    return urljoin(load_settings()["aircraft_data_url"], "stats.json")


def get_readsb_stats() -> dict[str, Any] | None:
    try:
        response = requests.get(readsb_stats_url(), timeout=2)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else None
    except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.info("readsb stats request failed: %s", exc)
        return None


_aircraft_metadata_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def aircraft_metadata_lookup(hex_code: str, callsign: str = "") -> dict[str, Any] | None:
    hex_code = str(hex_code or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{6}", hex_code):
        return None
    now = time.time()
    clean_callsign = callsign.strip().upper()
    cache_key = hex_code + "|" + clean_callsign
    cached = _aircraft_metadata_cache.get(cache_key)
    if cached and now - cached[0] < 86400:
        return cached[1]
    url = AIRCRAFT_LOOKUP_BASE + quote(hex_code, safe="")
    if clean_callsign:
        url += "?callsign=" + quote(clean_callsign, safe="")
    try:
        response = requests.get(url, timeout=3)
        if response.status_code == 404:
            _aircraft_metadata_cache[cache_key] = (now, None)
            return None
        response.raise_for_status()
        payload = response.json()
        root = payload.get("response", {}) if isinstance(payload, dict) else {}
        aircraft = root.get("aircraft") if isinstance(root, dict) else None
        route = root.get("flightroute") if isinstance(root, dict) else None
        result: dict[str, Any] = {}
        if isinstance(aircraft, dict):
            result["aircraft"] = aircraft
        if isinstance(route, dict):
            result["flightroute"] = route
        _aircraft_metadata_cache[cache_key] = (now, result or None)
        return result or None
    except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
        logger.info("Aircraft metadata lookup failed for %s: %s", hex_code, exc)
        return None


def metadata_for_aircraft(hex_code: str, callsign: str = "") -> dict[str, Any]:
    result = aircraft_metadata_lookup(hex_code, callsign) or {}
    aircraft = result.get("aircraft") if isinstance(result.get("aircraft"), dict) else {}
    route = result.get("flightroute") if isinstance(result.get("flightroute"), dict) else {}
    return {
        "ok": bool(result),
        "aircraft": aircraft,
        "flightroute": route,
    }


def save_settings(settings: dict[str, Any]) -> None:
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def validate_data_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Aircraft data URL must be an HTTP or HTTPS URL.")
    if parsed.username or parsed.password:
        raise ValueError("Usernames and passwords are not allowed in the aircraft data URL.")
    return value


LAST_GOOD_DATA: dict[str, Any] = {"aircraft": []}
LAST_GOOD_AVAILABLE = False


def get_aircraft_data() -> tuple[dict[str, Any], float | None]:
    global LAST_GOOD_DATA, LAST_GOOD_AVAILABLE
    settings = load_settings()
    try:
        url = validate_data_url(str(settings["aircraft_data_url"]))
        started = time.monotonic()
        response = requests.get(url, timeout=2)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("aircraft"), list):
            raise ValueError("Aircraft feed did not return the expected JSON structure.")
        LAST_GOOD_DATA = data
        LAST_GOOD_AVAILABLE = True
        record_feed_success(data)
        return data, time.monotonic() - started
    except requests.RequestException as exc:
        logger.warning("Aircraft feed request failed: %s", exc)
        record_feed_failure()
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("Aircraft feed returned invalid data: %s", exc)
        record_feed_failure()

    if LAST_GOOD_AVAILABLE:
        return LAST_GOOD_DATA, None
    return {"aircraft": []}, None

def clean(value: Any, fallback: str = "—") -> str:
    if value is None or value == "":
        return fallback
    return html.escape(str(value))


def aircraft_rows(aircraft: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for plane in aircraft:
        if not isinstance(plane, dict):
            continue
        hex_code = str(plane.get("hex", "")).strip().lower()
        valid_id = valid_aircraft_identifier(hex_code)
        flight = str(plane.get("flight") or plane.get("callsign") or plane.get("fn") or "").strip() or (f"ICAO {hex_code.replace('~','').upper()}" if valid_id else "Unknown")
        aircraft_type = str(plane.get("t") or plane.get("desc") or "").strip() or "Type unavailable"
        registration = str(plane.get("r") or plane.get("registration") or "").strip()
        speed = plane.get("gs", "—")
        altitude = plane.get("alt_baro", "—")
        fav_key = clean(hex_code) if valid_id else ""
        details = f"/aircraft/{quote(hex_code, safe='')}" if valid_id else "#"
        registration_html = f'<small class="unit">{clean(registration)}</small>' if registration else ""
        favourite_html = (
            f'<button type="button" class="favourite-button" data-favourite="{fav_key}" aria-label="Add {clean(flight)} to favourites" aria-pressed="false">☆</button>'
            if valid_id else ""
        )
        details_html = f'<a class="text-link" href="{details}">View details</a>' if valid_id else ""
        rows.append(
            f'''<tr data-aircraft-row data-flight="{clean(flight).lower()}" data-type="{clean(aircraft_type).lower()}" data-hex="{fav_key}">
                <td><span class="mobile-label">Flight</span><strong>{clean(flight)}</strong>{registration_html}</td>
                <td><span class="mobile-label">Aircraft</span>{clean(aircraft_type)}</td>
                <td><span class="mobile-label">Speed</span>{clean(speed)} <span class="unit">kt</span></td>
                <td><span class="mobile-label">Altitude</span>{clean(altitude)} <span class="unit">ft</span></td>
                <td class="actions">{favourite_html} {details_html}</td>
            </tr>'''
        )
    if not rows:
        return '<tr><td colspan="5" class="empty-cell">No aircraft data is currently available.</td></tr>'
    return "\n".join(rows)

def page(title: str, content: str, active: str = "") -> str:
    settings = load_settings()
    refresh = max(2, min(60, int(settings.get("refresh_seconds", 5))))
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nav = f'''<header class="site-header">
      <a class="brand" href="/" aria-label="Planes home">
        <img src="/static/images/airplane-svgrepo-com.svg" alt="" width="30" height="30">
        <span>Planes</span>
      </a>
      <nav aria-label="Main navigation">
        <a class="nav-link {"active" if active == "dashboard" else ""}" href="/">Dashboard</a>
        <a class="nav-link {"active" if active == "statistics" else ""}" href="/statistics">Statistics</a>
        <a class="nav-link {"active" if active == "settings" else ""}" href="/settings">Settings</a>
        <a class="nav-link {"active" if active == "documentation" else ""}" href="/documentation">Documentation</a>
        <a class="nav-link {"active" if active == "about" else ""}" href="/about">About</a>
      </nav>
    </header>'''
    return f'''<!doctype html>
<html lang="en" data-theme="system">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="A local live aircraft tracker powered by readsb and tar1090.">
  <title>{clean(title)} · Planes</title>
  <link rel="icon" href="/static/images/airplane-svgrepo-com.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/static/output.css?v={APP_VERSION}">
  <script>
    (() => {{
      const saved = localStorage.getItem('planes-theme') || 'system';
      document.documentElement.dataset.theme = saved;
    }})();
  </script>
</head>
<body>
  <a class="skip-link" href="#main-content">Skip to main content</a>
  <div class="app-shell">
    {nav}
    <main id="main-content" class="main-content">
      <div class="page-heading">
        <div><p class="eyebrow">LIVE AIRCRAFT TRACKING</p><h1>{clean(title)}</h1></div>
        <div class="live-pill" aria-label="Live data status"><span class="live-dot" aria-hidden="true"></span>LIVE</div>
      </div>
      {content}
    </main>
    <footer class="site-footer">
      <div><strong>Planes</strong><p>Local aircraft tracking interface for your ADS-B receiver.</p></div>
      <div class="footer-links">
        <a href="https://github.com/H-J-Wilson/planes" rel="noopener noreferrer">GitHub</a>
        <a href="https://github.com/wiedehopf/tar1090" rel="noopener noreferrer">tar1090</a>
        <a href="/contact">Contact</a>
      </div>
      <div class="footer-meta"><span>v{APP_VERSION}</span><span>Updated {now}</span><span>Refresh {refresh}s</span></div>
    </footer>
  </div>
  <script>
    const REFRESH_SECONDS = {refresh};
    const themeSelect = document.getElementById('theme-select');
    function applyTheme(value) {{
      document.documentElement.dataset.theme = value;
      localStorage.setItem('planes-theme', value);
      if (themeSelect) themeSelect.value = value;
    }}
    if (themeSelect) {{
      themeSelect.value = localStorage.getItem('planes-theme') || 'system';
      themeSelect.addEventListener('change', e => applyTheme(e.target.value));
    }}
    const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
    systemTheme.addEventListener?.('change', () => {{
      if ((localStorage.getItem('planes-theme') || 'system') === 'system') document.documentElement.dataset.theme = 'system';
    }});
  </script>
</body>
</html>'''


def dashboard_content() -> str:
    settings = load_settings()
    refresh = settings["refresh_seconds"]
    data, elapsed = get_aircraft_data()
    aircraft = data.get("aircraft", [])
    count = len(aircraft)
    stale = elapsed is None and LAST_GOOD_AVAILABLE
    status = "Feed responding" if elapsed is not None else ("Using last good data" if stale else "Feed unavailable")
    status_class = "status-ok" if elapsed is not None else ("status-warning" if stale else "status-error")
    rows = aircraft_rows(aircraft)
    initial_json = json.dumps(aircraft, separators=(",", ":"), ensure_ascii=True).replace("</", "<\\/")

    return f'''<section class="toolbar" aria-label="Aircraft table controls">
      <div class="search-wrap"><label for="aircraft-search">Search aircraft</label><input id="aircraft-search" type="search" placeholder="Flight, type, registration or HEX…" autocomplete="off"></div>
      <div><label for="sort-select">Sort by</label><select id="sort-select"><option value="flight">Flight</option><option value="type">Aircraft</option><option value="speed">Speed</option><option value="altitude">Altitude</option><option value="distance">Distance</option></select></div>
      <button id="refresh-now" class="button secondary" type="button">Refresh now</button>
    </section>
    <section class="filter-bar" aria-label="Aircraft filters">
      <div><label for="aircraft-filter">Show</label><select id="aircraft-filter"><option value="all">All aircraft</option><option value="moving">Moving</option><option value="climbing">Climbing</option><option value="descending">Descending</option><option value="position">Valid position</option><option value="favourite">Favourites</option></select></div>
      <div><label for="min-altitude">Minimum altitude (ft)</label><input id="min-altitude" type="number" min="0" step="100" placeholder="Any" inputmode="numeric"></div>
      <div><label for="min-speed">Minimum speed (kt)</label><input id="min-speed" type="number" min="0" step="5" placeholder="Any" inputmode="numeric"></div>
      <button id="clear-filters" class="button secondary" type="button">Clear filters</button>
    </section>
    <section class="stats-strip" aria-label="Live receiver status">
      <div class="metric"><span>Aircraft</span><strong id="aircraft-count">{count}</strong></div>
      <div class="metric"><span>Feed</span><strong id="feed-status" class="{status_class}">{status}</strong></div>
      <div class="metric"><span>Last check</span><strong id="last-check">Just now</strong></div>
      <div class="metric"><span>Data age</span><strong id="data-age">—</strong></div>
    </section>
    <div id="table-status" class="sr-status" role="status" aria-live="polite"></div>
    <div class="table-card">
      <table id="aircraft-table">
        <caption>Aircraft currently visible to the receiver</caption>
        <thead><tr><th scope="col">Flight</th><th scope="col">Aircraft</th><th scope="col">Speed</th><th scope="col">Altitude</th><th scope="col">More info</th></tr></thead>
        <tbody id="flight-rows">{rows}</tbody>
      </table>
    </div>
    <p id="search-status" class="help-text">Updates automatically every {refresh} seconds. Search and favourites stay on this device. Press Escape in the search box to clear it.</p>
    <script>
      (() => {{
        const tbody = document.getElementById('flight-rows');
        const count = document.getElementById('aircraft-count');
        const status = document.getElementById('feed-status');
        const last = document.getElementById('last-check');
        const dataAge = document.getElementById('data-age');
        const search = document.getElementById('aircraft-search');
        const sort = document.getElementById('sort-select');
        const filter = document.getElementById('aircraft-filter');
        const minAltitude = document.getElementById('min-altitude');
        const minSpeed = document.getElementById('min-speed');
        const clearFilters = document.getElementById('clear-filters');
        const tableStatus = document.getElementById('table-status');
        const searchStatus = document.getElementById('search-status');
        const refreshButton = document.getElementById('refresh-now');
        const REFRESH_SECONDS = {refresh};
        let aircraftData = {initial_json};
        let refreshInFlight = false;
        const metadataCache = new Map();
        const metadataRequested = new Set();

        function esc(value) {{
          return String(value ?? '').replace(/[&<>'"]/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}}[ch]));
        }}
        function favouriteState() {{
          try {{
            const value = JSON.parse(localStorage.getItem('planes-favourites') || '[]');
            return Array.isArray(value) ? value.map(v => String(v).trim().toLowerCase()) : [];
          }} catch {{ return []; }}
        }}
        function toggleFavourite(key) {{
          if (!key) return;
          const favs = new Set(favouriteState());
          if (favs.has(key)) favs.delete(key); else favs.add(key);
          try {{
            localStorage.setItem('planes-favourites', JSON.stringify([...favs]));
          }} catch {{
            tableStatus.textContent = 'Favourites could not be saved in this browser.';
          }}
          renderRows();
        }}
        function renderRows() {{
          const q = search.value.trim().toLowerCase();
          const searchTerms = [q, q.replace(/^icao\s+/, '')].filter(Boolean);
          const key = sort.value;
          const hasMinAlt = minAltitude.value.trim() !== '';
          const hasMinSpd = minSpeed.value.trim() !== '';
          const minAlt = Number(minAltitude.value);
          const minSpd = Number(minSpeed.value);
          const favs = new Set(favouriteState());

          const list = [...aircraftData].filter(a => {{
            if (!a || typeof a !== 'object') return false;
            const meta = metadataCache.get(String(a.hex || '').toLowerCase()) || {{}};
            const text = [a.flight || a.callsign || a.fn || '', a.t || '', a.desc || '', a.hex || '', a.r || a.registration || '', a.manufacturer || '', a.type || '', meta.type || '', meta.icao_type || '', meta.manufacturer || '', meta.registration || ''].join(' ').toLowerCase();
            const vr = Number(a.baro_rate ?? a.geom_rate);
            const gs = Number(a.gs);
            const alt = Number(a.alt_baro);
            const hasPosition = Number.isFinite(Number(a.lat)) && Number.isFinite(Number(a.lon));
            const matchesFilter =
              filter.value === 'all' ||
              (filter.value === 'moving' && Number.isFinite(gs) && gs > 1) ||
              (filter.value === 'climbing' && Number.isFinite(vr) && vr > 100) ||
              (filter.value === 'descending' && Number.isFinite(vr) && vr < -100) ||
              (filter.value === 'position' && hasPosition) ||
              (filter.value === 'favourite' && favs.has(String(a.hex || '').trim().toLowerCase()));
            const altitudeMatches = !hasMinAlt || (Number.isFinite(alt) && alt >= minAlt);
            const speedMatches = !hasMinSpd || (Number.isFinite(gs) && gs >= minSpd);
            const textMatches = !searchTerms.length || searchTerms.some(term => text.includes(term));
            return textMatches && altitudeMatches && speedMatches && matchesFilter;
          }});

          list.sort((a,b) => {{
            if (key === 'speed') return Number(b.gs ?? -1) - Number(a.gs ?? -1);
            if (key === 'altitude') return Number(b.alt_baro ?? -1) - Number(a.alt_baro ?? -1);
            if (key === 'type') {
              const am = metadataCache.get(String(a.hex || '').toLowerCase()) || {};
              const bm = metadataCache.get(String(b.hex || '').toLowerCase()) || {};
              return String(a.t || a.desc || am.type || am.icao_type || '').localeCompare(String(b.t || b.desc || bm.type || bm.icao_type || ''));
            }
            if (key === 'distance') return Number(b.r_dst ?? -1) - Number(a.r_dst ?? -1);
            return String(a.flight || a.callsign || a.fn || '').localeCompare(String(b.flight || b.callsign || b.fn || ''));
          }});

          tbody.innerHTML = list.length ? list.map(a => {{
            const safeAircraft = (a && typeof a === 'object') ? a : {{}};
            const flight = String(safeAircraft.flight || safeAircraft.callsign || safeAircraft.fn || (safeAircraft.hex ? 'ICAO ' + String(safeAircraft.hex).toUpperCase() : 'Unknown')).trim();
            const meta = metadataCache.get(String(safeAircraft.hex || '').toLowerCase()) || {};
            const type = safeAircraft.t || safeAircraft.desc || meta.type || meta.icao_type || 'Looking up…';
            const hex = String(safeAircraft.hex || '').toLowerCase();
            const registration = String(safeAircraft.r || safeAircraft.registration || meta.registration || '').trim();
            const manufacturer = String(meta.manufacturer || '').trim();
            const typeExtra = manufacturer ? '<small class="unit">'+esc(manufacturer)+'</small>' : '';
            const favOn = favs.has(hex);
            const validHex = /^~?[0-9a-f]{{6}}$/i.test(hex);
            const details = validHex ? '/aircraft/' + encodeURIComponent(hex) : '#';
            const registrationHtml = registration ? '<small class="unit">'+esc(registration)+'</small>' : '';
            const favouriteHtml = validHex ? '<button type="button" class="favourite-button" data-favourite="'+esc(hex)+'" aria-label="'+(favOn ? 'Remove ' : 'Add ')+'favourite" aria-pressed="'+favOn+'">'+(favOn ? '★' : '☆')+'</button>' : '';
            const detailsHtml = validHex ? '<a class="text-link" href="'+details+'">View details</a>' : '';
            return '<tr data-aircraft-row><td><span class="mobile-label">Flight</span><strong>'+esc(flight)+'</strong>'+registrationHtml+'</td><td><span class="mobile-label">Aircraft</span><strong>'+esc(type)+'</strong>'+typeExtra+'</td><td><span class="mobile-label">Speed</span>'+esc(a.gs ?? '—')+' <span class="unit">kt</span></td><td><span class="mobile-label">Altitude</span>'+esc(a.alt_baro ?? '—')+' <span class="unit">ft</span></td><td class="actions">'+favouriteHtml+' '+detailsHtml+'</td></tr>';
          }}).join('') : '<tr><td colspan="5" class="empty-cell">'+(aircraftData.length ? 'No aircraft match the current filters.' : 'No aircraft data is currently available.')+'</td></tr>';
        }}

        async function enrichVisibleAircraft() {{
          const candidates = aircraftData
            .filter(a => a && typeof a === 'object')
            .filter(a => /^~?[0-9a-f]{6}$/i.test(String(a.hex || '')))
            .filter(a => !a.t && !a.desc && !metadataCache.has(String(a.hex).toLowerCase()) && !metadataRequested.has(String(a.hex).toLowerCase()))
            .slice(0, 20);
          if (!candidates.length) return;
          candidates.forEach(a => metadataRequested.add(String(a.hex).toLowerCase()));
          for (const aircraft of candidates) {{
            const hex = String(aircraft.hex).toLowerCase();
            try {{
              const response = await fetch('/api/aircraft-metadata/' + encodeURIComponent(hex), {{cache:'no-store'}});
              if (!response.ok) continue;
              const payload = await response.json();
              if (payload && payload.aircraft) metadataCache.set(hex, payload.aircraft);
            }} catch (error) {{
              // Metadata is supplementary; keep live readsb data working when lookup fails.
            }}
            renderRows();
          }}
        }}

        async function refresh() {{
          if (refreshInFlight) return;
          refreshInFlight = true;
          refreshButton.disabled = true;
          try {{
            const res = await fetch('/api/dashboard-data', {{cache:'no-store'}});
            if (!res.ok) throw new Error('HTTP '+res.status);
            const payload = await res.json();
            if (!payload || !Array.isArray(payload.aircraft)) throw new Error('Invalid aircraft data');
            const feedOk = payload.feed_ok !== false;
            aircraftData = payload.aircraft;
            count.textContent = aircraftData.length;
            status.textContent = feedOk ? 'Feed responding' : (aircraftData.length ? 'Using last good data' : 'Feed unavailable');
            status.className = feedOk ? 'status-ok' : (aircraftData.length ? 'status-warning' : 'status-error');
            last.textContent = new Date().toLocaleTimeString();
            if (typeof payload.now === 'number') {{
              const age = Math.max(0, Date.now()/1000 - payload.now);
              dataAge.textContent = age < 2 ? '<2s' : Math.round(age) + 's';
            }} else {{
              dataAge.textContent = '—';
            }}
            renderRows();
            enrichVisibleAircraft();
            tableStatus.textContent = feedOk ? 'Aircraft list updated.' : 'Feed unavailable; showing the last successful aircraft data.';
          }} catch (error) {{
            status.textContent = aircraftData.length ? 'Using last good data' : 'Feed unavailable';
            status.className = aircraftData.length ? 'status-warning' : 'status-error';
            last.textContent = 'Refresh failed';
            tableStatus.textContent = aircraftData.length ? 'Refresh failed; keeping the last successful aircraft data.' : 'Unable to load aircraft data.';
          }} finally {{
            refreshButton.disabled = false;
            refreshInFlight = false;
          }}
        }}

        tbody.addEventListener('click', event => {{
          const button = event.target.closest('[data-favourite]');
          if (button) toggleFavourite(button.dataset.favourite);
        }});
        search.addEventListener('input', () => {{ renderRows(); enrichVisibleAircraft(); }});
        search.addEventListener('keydown', event => {{
          if (event.key === 'Escape' && search.value) {{
            search.value = '';
            renderRows();
          }}
        }});
        sort.addEventListener('change', renderRows);
        filter.addEventListener('change', renderRows);
        minAltitude.addEventListener('input', renderRows);
        minSpeed.addEventListener('input', renderRows);
        clearFilters.addEventListener('click', () => {{
          search.value = '';
          filter.value = 'all';
          minAltitude.value = '';
          minSpeed.value = '';
          sort.value = 'flight';
          renderRows();
          search.focus();
        }});
        refreshButton.addEventListener('click', refresh);
        renderRows();
        enrichVisibleAircraft();
        refresh();
        setInterval(refresh, REFRESH_SECONDS * 1000);
      }})();
    </script>'''

@app.get("/", response_class=HTMLResponse)
def read_root():
    if not setup_complete():
        return page("Welcome to Planes", setup_content())
    return page("Aircraft Dashboard", dashboard_content(), "dashboard")


@app.get("/api/dashboard-data")
def dashboard_data(response: Response):
    response.headers["Cache-Control"] = "no-store"
    data, elapsed = get_aircraft_data()
    aircraft = data.get("aircraft", [])
    return JSONResponse({
        "aircraft": aircraft,
        "feed_ok": elapsed is not None,
        "stale": elapsed is None and LAST_GOOD_AVAILABLE,
        "now": data.get("now"),
        "response_ms": round(elapsed * 1000) if elapsed is not None else None,
    })

@app.get("/api/dashboard-table", response_class=HTMLResponse)
def get_dashboard_table(response: Response):
    response.headers["Cache-Control"] = "no-store"
    data, _ = get_aircraft_data()
    return HTMLResponse(aircraft_rows(data.get("aircraft", [])))


@app.get("/statistics", response_class=HTMLResponse)
def read_statistics():
    data, elapsed = get_aircraft_data()
    aircraft = [a for a in data.get("aircraft", []) if isinstance(a, dict)]
    altitudes = [a.get("alt_baro") for a in aircraft if isinstance(a.get("alt_baro"), (int, float))]
    speeds = [a.get("gs") for a in aircraft if isinstance(a.get("gs"), (int, float))]
    positions = [a for a in aircraft if isinstance(a.get("lat"), (int, float)) and isinstance(a.get("lon"), (int, float))]
    moving = [a for a in aircraft if isinstance(a.get("gs"), (int, float)) and a.get("gs") > 1]
    climbing = [a for a in aircraft if isinstance(a.get("baro_rate"), (int, float)) and a.get("baro_rate") > 100]
    descending = [a for a in aircraft if isinstance(a.get("baro_rate"), (int, float)) and a.get("baro_rate") < -100]

    types: dict[str, int] = {}
    for a in aircraft:
        key = str(a.get("t") or a.get("desc") or "Type unavailable").strip() or "Type unavailable"
        types[key] = types.get(key, 0) + 1
    top_types = sorted(types.items(), key=lambda x: x[1], reverse=True)[:10]
    type_rows = "".join(f"<tr><td>{clean(k)}</td><td>{v}</td></tr>" for k,v in top_types) or '<tr><td colspan="2">No aircraft type data available.</td></tr>'

    readsb = get_readsb_stats()
    total = readsb.get("total", {}) if isinstance(readsb, dict) else {}
    last15 = readsb.get("last15min", {}) if isinstance(readsb, dict) else {}
    local = total.get("local", {}) if isinstance(total, dict) else {}
    cpr = total.get("cpr", {}) if isinstance(total, dict) else {}
    tracks = total.get("tracks", {}) if isinstance(total, dict) else {}
    readsb_start = total.get("start") if isinstance(total, dict) else None
    readsb_end = total.get("end") if isinstance(total, dict) else None
    readsb_runtime = (readsb_end - readsb_start) if isinstance(readsb_start, (int, float)) and isinstance(readsb_end, (int, float)) else None

    settings = load_settings()
    feed_status = "Live" if elapsed is not None else ("Stale — last good data" if LAST_GOOD_AVAILABLE else "Unavailable")
    average_aircraft = PLANES_SESSION_AIRCRAFT_TOTAL / PLANES_SESSION_SAMPLES if PLANES_SESSION_SAMPLES else 0
    session_runtime = time.time() - PLANES_SESSION_STARTED

    live_cards = [
        ("Aircraft visible", format_number(len(aircraft)), "Current entries in the live feed."),
        ("With position", format_number(len(positions)), "Aircraft with numeric latitude and longitude."),
        ("Moving", format_number(len(moving)), "Ground speed above 1 kt."),
        ("Climbing", format_number(len(climbing)), "Vertical rate above 100 ft/min."),
        ("Descending", format_number(len(descending)), "Vertical rate below −100 ft/min."),
        ("Average altitude", f"{format_number(sum(altitudes)/len(altitudes))} ft" if altitudes else "—", "Current numeric barometric altitude average."),
        ("Average speed", f"{format_number(sum(speeds)/len(speeds))} kt" if speeds else "—", "Current numeric ground speed average."),
        ("Highest altitude", f"{format_number(max(altitudes))} ft" if altitudes else "—", "Highest altitude in the current snapshot."),
        ("Fastest speed", f"{format_number(max(speeds))} kt" if speeds else "—", "Fastest ground speed in the current snapshot."),
    ]
    period_cards = [
        ("Planes running", format_duration(session_runtime), "Since this Planes process started."),
        ("Unique aircraft seen", format_number(len(PLANES_SESSION_UNIQUE_HEX)), "Distinct aircraft identifiers seen this session."),
        ("Peak aircraft", format_number(PLANES_SESSION_PEAK_AIRCRAFT), "Most aircraft in one successful snapshot."),
        ("Average aircraft", format_number(round(average_aircraft, 1)), "Average aircraft count across recorded snapshots."),
        ("Highest altitude", f"{format_number(PLANES_SESSION_HIGHEST_ALTITUDE)} ft" if PLANES_SESSION_HIGHEST_ALTITUDE is not None else "—", "Highest numeric altitude seen this session."),
        ("Fastest speed", f"{format_number(PLANES_SESSION_FASTEST_SPEED)} kt" if PLANES_SESSION_FASTEST_SPEED is not None else "—", "Fastest numeric ground speed seen this session."),
        ("Snapshots recorded", format_number(PLANES_SESSION_SAMPLES), "Distinct feed timestamps recorded by Planes."),
        ("Feed interruptions", format_number(PLANES_SESSION_FEED_INTERRUPTS), "Times a live feed recovered after an interruption."),
    ]

    receiver_cards = []
    if readsb:
        receiver_cards.extend([
            ("readsb running", format_duration(readsb_runtime), "Total period reported by readsb."),
            ("Messages accepted", format_number(total.get("messages")), "Messages accepted across the readsb total period."),
            ("Tracks created", format_number(tracks.get("all")), "Aircraft tracks created during the readsb period."),
            ("Global positions", format_number(cpr.get("global_ok")), "Successfully decoded global CPR positions."),
            ("Blocks processed", format_number(local.get("blocks_processed")), "Local SDR sample blocks processed."),
            ("Blocks dropped", format_number(local.get("blocks_dropped")), "Local SDR sample blocks dropped before processing."),
            ("Mean signal", f"{format_number(local.get('signal'))} dBFS" if local.get("signal") is not None else "—", "Mean signal power for successful messages."),
            ("15 min messages", format_number(last15.get("messages")), "Messages accepted during readsb's rolling 15-minute window."),
            ("Readsb period start", dt.datetime.fromtimestamp(readsb_start).strftime("%Y-%m-%d %H:%M") if isinstance(readsb_start, (int, float)) else "—", "Start time of the readsb total period."),
        ])
    else:
        receiver_cards.append(("readsb stats", "Unavailable", "stats.json could not be read from the configured feed host."))

    def cards_html(items: list[tuple[str, str, str]]) -> str:
        return "".join(
            f'<article class="panel stat-card"><span>{clean(label)}</span><strong>{clean(value)}</strong><p>{clean(description)}</p></article>'
            for label, value, description in items
        )

    receiver_rows = "".join(
        f'<div><dt>{clean(label)}</dt><dd>{clean(value)}</dd></div>'
        for label, value, _description in receiver_cards
    )

    content = f'''<section class="stats-section">
      <div class="section-heading"><div><p class="eyebrow">RIGHT NOW</p><h2>Live snapshot</h2></div><span class="section-note">{clean(feed_status)}</span></div>
      <div class="stats-grid live-stats">{cards_html(live_cards)}</div>
    </section>
    <details class="stats-section stats-collapsible" open>
      <summary><span><p class="eyebrow">PLANES SESSION</p><h2>Since Planes started</h2></span><span class="section-note">{clean(dt.datetime.fromtimestamp(PLANES_SESSION_STARTED).strftime("%H:%M:%S"))}</span></summary>
      <div class="stats-grid session-stats">{cards_html(period_cards)}</div>
    </details>
    <details class="stats-section stats-collapsible">
      <summary><span><p class="eyebrow">RECEIVER PERIOD</p><h2>Since readsb started</h2></span><span class="section-note">readsb stats.json</span></summary>
      <div class="period-list"><dl class="details-list">{receiver_rows}</dl></div>
    </details>
    <section class="stats-columns">
      <section class="panel"><h2>Aircraft types right now</h2><table><caption>Aircraft types currently visible</caption><thead><tr><th scope="col">Type</th><th scope="col">Count</th></tr></thead><tbody>{type_rows}</tbody></table></section>
      <section class="panel"><h2>Receiver connection</h2><dl class="details-list"><div><dt>Aircraft feed</dt><dd>{clean(settings.get("aircraft_data_url"))}</dd></div><div><dt>Refresh interval</dt><dd>{settings["refresh_seconds"]} seconds</dd></div><div><dt>ASBDB lookups</dt><dd>{"Enabled" if settings.get("asbdb_enabled") else "Disabled"}</dd></div><div><dt>Feed status</dt><dd>{clean(feed_status)}</dd></div><div><dt>Feed response</dt><dd>{round(elapsed*1000) if elapsed is not None else "—"} ms</dd></div></dl></section>
    </section>'''
    return page("Statistics", content, "statistics")

_asbdb_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def asbdb_lookup(callsign: str) -> dict[str, Any] | None:
    settings = load_settings()
    if not settings.get("asbdb_enabled", True) or not callsign:
        return None
    callsign = callsign.strip().upper()
    now = time.time()
    cached = _asbdb_cache.get(callsign)
    if cached and now - cached[0] < settings["asbdb_cache_seconds"]:
        return cached[1]

    try:
        res = requests.get(ASBDB_BASE + quote(callsign, safe=""), timeout=3)
        if res.status_code == 404:
            _asbdb_cache[callsign] = (now, None)
            return None
        res.raise_for_status()
        payload = res.json()
        route = payload.get("response", {}).get("flightroute")
        if isinstance(route, dict):
            _asbdb_cache[callsign] = (now, route)
            return route
    except requests.RequestException as exc:
        logger.info("ASBDB request failed for %s: %s", callsign, exc)
    except (ValueError, TypeError, AttributeError) as exc:
        logger.info("ASBDB returned invalid data for %s: %s", callsign, exc)

    return None

def detail_fragment(hex_code: str) -> str:
    hex_code = str(hex_code or "").strip().lower()
    if not valid_aircraft_identifier(hex_code):
        return '<div class="notice error"><strong>Invalid aircraft identifier.</strong><p>Aircraft identifiers must be six hexadecimal characters, optionally prefixed with ~ for non-ICAO targets.</p></div>'

    data, _ = get_aircraft_data()
    target = next((a for a in data.get("aircraft", []) if str(a.get("hex", "")).strip().lower() == hex_code), None)
    if not target:
        return '<div class="notice error"><strong>Aircraft not currently visible.</strong><p>It may have left receiver range or stopped transmitting.</p></div>'

    flight = str(target.get("flight") or target.get("callsign") or target.get("fn") or "").strip()
    metadata = metadata_for_aircraft(hex_code, flight)
    db_aircraft = metadata.get("aircraft", {})
    route = metadata.get("flightroute", {})

    registration = target.get("r") or target.get("registration") or db_aircraft.get("registration")
    aircraft_type = target.get("t") or target.get("desc") or db_aircraft.get("type")
    icao_type = db_aircraft.get("icao_type")
    manufacturer = db_aircraft.get("manufacturer")
    operator = db_aircraft.get("registered_owner_operator_flag_code") or db_aircraft.get("registered_owner")
    owner_country = db_aircraft.get("registered_owner_country_name")

    route_callsign = str(route.get("callsign_icao") or "").strip()
    route_iata = str(route.get("callsign_iata") or "").strip()
    display_flight = flight or route_callsign or f"ICAO {hex_code.replace('~','').upper()}"

    def field(label: str, value: Any) -> str:
        return f'<div class="detail-card"><span>{clean(label)}</span><strong>{clean(value, "Not available")}</strong></div>'

    identity = "".join([
        field("Flight / callsign", flight or route_callsign),
        field("ICAO callsign", route_callsign),
        field("IATA callsign", route_iata),
        field("Registration", registration),
        field("Aircraft type", aircraft_type),
        field("ICAO type", icao_type),
        field("Manufacturer", manufacturer),
        field("Operator / owner", operator),
        field("Owner country", owner_country),
        field("HEX / Mode-S", hex_code.upper()),
        field("Message source", target.get("type")),
    ])

    flight_data = "".join([
        field("Barometric altitude", f"{target.get('alt_baro')} ft" if target.get("alt_baro") is not None else None),
        field("Geometric altitude", f"{target.get('alt_geom')} ft" if target.get("alt_geom") is not None else None),
        field("Ground speed", f"{target.get('gs')} kt" if target.get("gs") is not None else None),
        field("Indicated airspeed", f"{target.get('ias')} kt" if target.get("ias") is not None else None),
        field("True airspeed", f"{target.get('tas')} kt" if target.get("tas") is not None else None),
        field("Mach", target.get("mach")),
        field("Track", f"{target.get('track')}°" if target.get("track") is not None else None),
        field("Magnetic heading", f"{target.get('mag_heading')}°" if target.get("mag_heading") is not None else None),
        field("True heading", f"{target.get('true_heading')}°" if target.get("true_heading") is not None else None),
        field("Barometric rate", f"{target.get('baro_rate')} ft/min" if target.get("baro_rate") is not None else None),
        field("Geometric rate", f"{target.get('geom_rate')} ft/min" if target.get("geom_rate") is not None else None),
        field("Roll", f"{target.get('roll')}°" if target.get("roll") is not None else None),
        field("Outside air temp", f"{target.get('oat')} °C" if target.get("oat") is not None else None),
    ])

    navigation = "".join([
        field("Latitude", target.get("lat")),
        field("Longitude", target.get("lon")),
        field("Distance", f"{target.get('r_dst')} nm" if target.get('r_dst') is not None else None),
        field("Bearing", f"{target.get('r_dir')}°" if target.get('r_dir') is not None else None),
        field("Squawk", target.get("squawk")),
        field("Emergency", target.get("emergency")),
        field("Emitter category", target.get("category")),
        field("Selected altitude", f"{target.get('nav_altitude_mcp')} ft" if target.get("nav_altitude_mcp") is not None else None),
        field("QNH", f"{target.get('nav_qnh')} hPa" if target.get("nav_qnh") is not None else None),
        field("NIC", target.get("nic")),
        field("NAC-P", target.get("nac_p")),
        field("NAC-V", target.get("nac_v")),
        field("SIL", target.get("sil")),
        field("GVA", target.get("gva")),
        field("SDA", target.get("sda")),
    ])

    signal = "".join([
        field("Messages from aircraft", target.get("messages")),
        field("Last seen", f"{target.get('seen')} s ago" if target.get("seen") is not None else None),
        field("Position last seen", f"{target.get('seen_pos')} s ago" if target.get("seen_pos") is not None else None),
        field("RSSI", f"{target.get('rssi')} dBFS" if target.get("rssi") is not None else None),
        field("Readsb data source", target.get("type")),
        field("MLAT fields", ", ".join(target.get("mlat", [])) if isinstance(target.get("mlat"), list) and target.get("mlat") else None),
        field("TIS-B fields", ", ".join(target.get("tisb", [])) if isinstance(target.get("tisb"), list) and target.get("tisb") else None),
    ])

    route_html = '<p class="muted">No scheduled route data was returned for this aircraft.</p>'
    if isinstance(route, dict) and route:
        origin = route.get("origin") if isinstance(route.get("origin"), dict) else {}
        destination = route.get("destination") if isinstance(route.get("destination"), dict) else {}
        airline = route.get("airline") if isinstance(route.get("airline"), dict) else {}
        origin_code = origin.get("iata_code") or origin.get("icao_code")
        destination_code = destination.get("iata_code") or destination.get("icao_code")
        origin_label = f"{clean(origin_code)} · {clean(origin.get('name'))}" if origin_code else clean(origin.get("name"))
        destination_label = f"{clean(destination_code)} · {clean(destination.get('name'))}" if destination_code else clean(destination.get("name"))
        airline_label = clean(airline.get("name")) if airline.get("name") else "Unknown airline"
        route_html = f'<div class="route"><div><span>Origin</span><strong>{origin_label}</strong></div><div class="route-arrow" aria-hidden="true">→</div><div><span>Destination</span><strong>{destination_label}</strong></div><p>{airline_label} · ASBDB scheduled route</p></div>'

    photo_html = ""
    photo_url = db_aircraft.get("url_photo_thumbnail") or db_aircraft.get("url_photo")
    if isinstance(photo_url, str) and urlparse(photo_url).scheme in {"http", "https"}:
        photo_html = f'<img class="aircraft-photo" src="{html.escape(photo_url, quote=True)}" alt="Aircraft photo from ADSBDB" loading="lazy">'

    source_note = "Live telemetry: readsb"
    if metadata.get("ok"):
        source_note += " · identity: ADSBDB"

    return f'''<div class="detail-title"><div><p class="eyebrow">AIRCRAFT DETAILS</p><h2>{clean(display_flight)}</h2><p class="detail-subtitle">HEX {clean(hex_code.replace("~","").upper())} · {clean(registration, "Registration unavailable")}</p></div><span class="live-pill">LIVE</span></div>
    {photo_html}
    <p class="detail-source-note">{source_note}</p>
    <section class="detail-section"><div class="section-heading"><div><p class="eyebrow">IDENTITY</p><h3>Aircraft identity</h3></div></div><div class="detail-grid">{identity}</div></section>
    <section class="detail-section"><div class="section-heading"><div><p class="eyebrow">FLIGHT DATA</p><h3>Live flight data</h3></div></div><div class="detail-grid">{flight_data}</div></section>
    <section class="detail-section"><div class="section-heading"><div><p class="eyebrow">NAVIGATION</p><h3>Navigation and transponder</h3></div></div><div class="detail-grid">{navigation}</div></section>
    <section class="detail-section"><div class="section-heading"><div><p class="eyebrow">SIGNAL</p><h3>Receiver / signal data</h3></div></div><div class="detail-grid">{signal}</div></section>
    <section class="route-panel"><div class="section-heading"><div><p class="eyebrow">ROUTE</p><h3>Scheduled route</h3></div></div>{route_html}</section>'''

@app.get("/aircraft/{hex_code}", response_class=HTMLResponse)
def read_aircraft_details(hex_code: str):
    safe_hex = str(hex_code or "").strip().lower()
    if not valid_aircraft_identifier(safe_hex):
        return page("Aircraft Details", '<section class="panel"><div class="notice error"><strong>Invalid aircraft identifier.</strong></div><a class="back-link" href="/">← Back to dashboard</a></section>')
    content = f'''<section class="panel detail-panel"><div id="live-details" role="region" aria-live="polite" aria-label="Live aircraft details"><p class="loading">Loading live aircraft data…</p></div><a class="back-link" href="/">← Back to dashboard</a></section>
    <script>
      async function refreshAircraft() {{
        try {{
          const res = await fetch('/api/aircraft/'+encodeURIComponent({json.dumps(safe_hex)}), {{cache:'no-store'}});
          const body = await res.text();
          if (!res.ok) throw new Error(body || 'Aircraft is no longer available');
          document.getElementById('live-details').innerHTML = body;
        }} catch (error) {{
          document.getElementById('live-details').innerHTML = '<div class="notice error">'+escDetail(error.message)+'</div>';
        }}
      }}
      function escDetail(value) {{
        const d = document.createElement('div');
        d.textContent = String(value);
        return d.innerHTML;
      }}
      refreshAircraft();
      setInterval(refreshAircraft, REFRESH_SECONDS * 1000);
    </script>'''
    return page("Aircraft Details", content)

@app.get("/api/aircraft-metadata/{hex_code}")
def get_aircraft_metadata(hex_code: str):
    safe_hex = str(hex_code or "").strip().lower()
    if not valid_aircraft_identifier(safe_hex):
        return JSONResponse({"ok": False, "detail": "Invalid aircraft identifier."}, status_code=400)
    data, _ = get_aircraft_data()
    target = next((a for a in data.get("aircraft", []) if str(a.get("hex", "")).strip().lower() == safe_hex), None)
    callsign = str(target.get("flight") or target.get("callsign") or target.get("fn") or "").strip() if isinstance(target, dict) else ""
    result = metadata_for_aircraft(safe_hex, callsign)
    response = {"ok": result["ok"], "aircraft": result["aircraft"], "flightroute": result["flightroute"]}
    return JSONResponse(response, headers={"Cache-Control": "public, max-age=300"})


@app.get("/api/aircraft/{hex_code}", response_class=HTMLResponse)
def get_aircraft_details_fragment(hex_code: str, response: Response):
    response.headers["Cache-Control"] = "no-store"
    safe_hex = str(hex_code or "").strip().lower()
    if not valid_aircraft_identifier(safe_hex):
        return HTMLResponse(
            '<div class="notice error"><strong>Invalid aircraft identifier.</strong><p>Aircraft identifiers must be six hexadecimal characters, optionally prefixed with ~ for non-ICAO targets.</p></div>',
            status_code=400,
        )
    return HTMLResponse(detail_fragment(safe_hex))


@app.get("/settings", response_class=HTMLResponse)
def read_settings():
    settings = load_settings()
    content = f'''<form id="settings-form" class="panel settings-form">
      <div><label for="aircraft-data-url">Aircraft data URL</label><input id="aircraft-data-url" name="aircraft_data_url" type="url" value="{clean(settings.get('aircraft_data_url'))}" required><p class="field-help">Usually the local readsb/tar1090 JSON endpoint.</p></div>
      <div><label for="refresh-seconds">Refresh interval</label><select id="refresh-seconds" name="refresh_seconds">{''.join(f'<option value="{n}" {"selected" if settings["refresh_seconds"] == n else ""}>{n} seconds</option>' for n in [2,3,5,10,15,30,60])}</select></div>
      <label class="checkbox"><input id="asbdb-enabled" name="asbdb_enabled" type="checkbox" {"checked" if settings.get("asbdb_enabled",True) else ""}> Use ASBDB route lookups on aircraft detail pages</label>
      <fieldset><legend>Appearance</legend><label for="theme-select">Theme</label><select id="theme-select"><option value="system">Use system setting</option><option value="dark">Dark cyan</option><option value="light">Light</option></select><p class="field-help">This preference is saved only in this browser.</p></fieldset>
      <div class="form-actions"><button class="button" type="submit">Save settings</button><button id="test-feed" class="button secondary" type="button">Test feed</button><span id="save-status" role="status" aria-live="polite"></span></div>
    </form>
    <section class="panel"><h2>Settings explained</h2><ul class="clean-list"><li><strong>Aircraft data URL</strong> is the live JSON endpoint Planes reads.</li><li><strong>Refresh interval</strong> controls how often the Dashboard asks the server for fresh data.</li><li><strong>ASBDB</strong> adds optional scheduled route/airline information to detail pages.</li><li><strong>Theme</strong> is saved in this browser and does not change the receiver.</li></ul></section>
    <script>
      const settingsStatus = document.getElementById('save-status');
      document.getElementById('test-feed').addEventListener('click', async () => {{
        settingsStatus.textContent = 'Testing feed…';
        try {{
          const url = document.getElementById('aircraft-data-url').value.trim();
          const r = await fetch('/api/test-feed-url?url=' + encodeURIComponent(url), {{cache:'no-store'}});
          const j = await r.json();
          if (!r.ok) throw new Error(j.detail || 'Feed test failed');
          settingsStatus.textContent = 'Feed OK · ' + j.aircraft_count + ' aircraft · ' + j.response_ms + ' ms';
        }} catch (err) {{
          settingsStatus.textContent = err.message || 'Feed test failed';
        }}
      }});
      document.getElementById('settings-form').addEventListener('submit', async e => {{
        e.preventDefault();
        settingsStatus.textContent = 'Saving…';
        const body = {{
          aircraft_data_url: document.getElementById('aircraft-data-url').value.trim(),
          refresh_seconds: Number(document.getElementById('refresh-seconds').value),
          asbdb_enabled: document.getElementById('asbdb-enabled').checked
        }};
        try {{
          const r = await fetch('/api/settings', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify(body)}});
          const j = await r.json();
          if (!r.ok) throw new Error(j.detail || 'Save failed');
          settingsStatus.textContent = 'Saved. Reloading…';
          setTimeout(() => location.reload(), 500);
        }} catch (err) {{
          settingsStatus.textContent = err.message || 'Save failed';
        }}
      }});
    </script>'''
    return page("Settings", content, "settings")

@app.get("/setup", response_class=HTMLResponse)
def read_setup():
    if setup_complete():
        return page("Setup complete", '<section class="panel"><h2>Setup already completed</h2><p>Use Settings to change the receiver URL, refresh interval, ASBDB or theme.</p><a class="button" href="/settings">Open Settings</a></section>')
    return page("Welcome to Planes", setup_content())


@app.get("/api/settings")
def get_settings():
    return load_settings()


@app.get("/api/test-feed")
def test_feed():
    data, elapsed = get_aircraft_data()
    if elapsed is None:
        return JSONResponse({"detail": "Aircraft feed is unavailable or returned invalid JSON."}, status_code=502)
    return {"ok": True, "aircraft_count": len(data.get("aircraft", [])), "response_ms": round(elapsed * 1000)}


@app.get("/api/test-feed-url")
def test_feed_url(url: str):
    try:
        clean_url = validate_data_url(url)
        started = time.monotonic()
        response = requests.get(clean_url, timeout=2)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("aircraft"), list):
            raise ValueError("Aircraft feed did not return the expected JSON structure.")
        return {
            "ok": True,
            "aircraft_count": len(data["aircraft"]),
            "response_ms": round((time.monotonic() - started) * 1000),
        }
    except (ValueError, TypeError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except requests.RequestException as exc:
        logger.warning("Feed test failed for %s: %s", url, exc)
        return JSONResponse({"detail": f"Feed request failed: {exc}"}, status_code=502)


@app.post("/api/setup")
def finish_setup(payload: dict[str, Any]):
    try:
        url = validate_data_url(str(payload.get("aircraft_data_url", "")))
        refresh = int(payload.get("refresh_seconds", 5))
        if refresh not in {2,3,5,10,15,30,60}:
            raise ValueError("Choose a refresh interval from the list.")
        settings = load_settings()
        settings.update({
            "aircraft_data_url": url,
            "refresh_seconds": refresh,
            "asbdb_enabled": bool(payload.get("asbdb_enabled", True)),
        })
        save_settings(settings)
        mark_setup_complete()
        return {"ok": True, "settings": settings}
    except (ValueError, TypeError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except OSError as exc:
        logger.error("Unable to mark first-run setup complete: %s", exc)
        return JSONResponse({"detail": "Setup could not be saved on this installation."}, status_code=500)


@app.post("/api/settings")
def update_settings(payload: dict[str, Any]):
    try:
        url = validate_data_url(str(payload.get("aircraft_data_url", "")))
        refresh = int(payload.get("refresh_seconds", 5))
        if refresh not in {2,3,5,10,15,30,60}:
            raise ValueError("Choose a refresh interval from the list.")
        settings = load_settings()
        settings.update({"aircraft_data_url": url, "refresh_seconds": refresh, "asbdb_enabled": bool(payload.get("asbdb_enabled", True))})
        save_settings(settings)
        return {"ok": True, "settings": settings}
    except (ValueError, TypeError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


@app.get("/documentation", response_class=HTMLResponse)
def read_documentation():
    content = '''<section class="panel prose">
      <p class="eyebrow">PLANES CODE DOCUMENTATION</p>
      <h2>Architecture</h2>
      <pre><code>RTL-SDR → readsb → tar1090/readsb JSON → FastAPI → Browser</code></pre>
      <p>Planes does not control the RTL-SDR. readsb produces aircraft JSON; the FastAPI server reads that JSON and serves the Dashboard and API endpoints.</p>

      <h2>1. main.py</h2>
      <p><code>main.py</code> is the server entry point. It imports <code>webpage.app</code> and starts Uvicorn on port 8000.</p>
      <pre><code>import uvicorn
import webpage

uvicorn.run(webpage.app, host="0.0.0.0", port=8000)</code></pre>

      <h2>2. webpage.py</h2>
      <p><code>webpage.py</code> contains the FastAPI app, configuration handling, feed access, HTML generation, browser JavaScript, statistics and routes.</p>
      <ul class="clean-list">
        <li><code>app</code> creates the FastAPI application.</li>
        <li><code>SETTINGS_FILE</code> points to <code>settings.json</code>.</li>
        <li><code>DEFAULT_SETTINGS</code> provides fallback values.</li>
        <li><code>ASBDB_BASE</code> is the optional route lookup API.</li>
        <li><code>APP_VERSION</code> is displayed in the UI and used for CSS cache busting.</li>
        <li><code>logger</code> records feed and lookup failures.</li>
      </ul>

      <h2>3. settings.json</h2>
      <ul class="clean-list">
        <li><code>aircraft_data_url</code> — live aircraft JSON URL.</li>
        <li><code>refresh_seconds</code> — Dashboard polling interval.</li>
        <li><code>asbdb_enabled</code> — enable scheduled route lookups.</li>
        <li><code>asbdb_cache_seconds</code> — route-result cache duration.</li>
      </ul>

      <h2>4. Settings functions</h2>
      <p><code>load_settings()</code> merges the JSON file over safe defaults and validates the URL, refresh interval and ASBDB cache time. Bad JSON or invalid types no longer make page rendering crash.</p>
      <p><code>save_settings()</code> writes the resulting dictionary as formatted JSON.</p>
      <p><code>validate_data_url()</code> requires HTTP/HTTPS and rejects embedded usernames/passwords.</p>

      <h2>5. Aircraft feed</h2>
      <pre><code>settings
↓
validate_data_url()
↓
requests.get(timeout=2)
↓
HTTP status check
↓
response.json()
↓
check aircraft is a list
↓
return data + request time</code></pre>
      <p><code>get_aircraft_data()</code> stores the last successful response. A later timeout, HTTP error or invalid JSON returns that previous response with <code>feed_ok</code> represented as false by the API.</p>
      <p>A successful empty aircraft list is still remembered. This prevents an error after an empty period from being confused with a successful empty feed.</p>

      <h2>6. Dashboard server rendering</h2>
      <p><code>dashboard_content()</code> performs one initial feed read, creates the first table and embeds the aircraft list into browser JavaScript.</p>
      <p><code>aircraft_rows()</code> escapes displayed values, validates readsb identifiers (including <code>~</code>-prefixed non-ICAO identifiers), and adds registration beneath the callsign when available. The feed's <code>type</code> field is treated as a message-source field, not an aircraft model.</p>

      <h2>7. Dashboard JavaScript</h2>
      <p>The browser keeps an <code>aircraftData</code> array and redraws the table when a control changes.</p>
      <ul class="clean-list">
        <li><strong>Search:</strong> callsign/flight, aircraft type/description, HEX, registration, manufacturer and other receiver fields.</li>
        <li><strong>Sort:</strong> flight, type, speed, altitude and distance.</li>
        <li><strong>Filters:</strong> moving, climbing, descending, valid position, favourites, minimum altitude and minimum speed.</li>
        <li><strong>Favourites:</strong> stored in browser <code>localStorage</code>.</li>
        <li><strong>Refresh:</strong> blocks overlapping manual/automatic requests.</li>
        <li><strong>Failure:</strong> preserves the last good aircraft list.</li>
        <li><strong>Escape:</strong> clears the search field.</li>
      </ul>
      <p>Minimum altitude/speed filters only apply when a value is actually entered. Missing altitude/speed therefore does not hide an aircraft in the default view.</p>

      <h2>8. Dashboard API</h2>
      <ul class="clean-list">
        <li><code>/api/dashboard-data</code> returns aircraft, feed health, stale state, receiver timestamp and request time.</li>
        <li><code>/api/dashboard-table</code> returns the server-rendered aircraft rows.</li>
      </ul>

      <h2>9. Aircraft details</h2>
      <p>The detail page validates the HEX identifier before starting its polling loop. The browser polls <code>/api/aircraft/&lt;hex&gt;</code> and now checks HTTP errors instead of displaying an error response as if it were valid detail data.</p>
      <p>The detail view first uses the live receiver object, then enriches it from ADSBDB by Mode-S HEX when the target has a normal ICAO address. It can show registration, aircraft type, ICAO type, manufacturer, operator/owner, flight number, ICAO/IATA callsign, squawk, altitude, speed, vertical rate, heading, position, distance, bearing and signal.</p>

      <h2>10. ASBDB</h2>
      <p><code>aircraft_metadata_lookup()</code> looks up a normal six-digit Mode-S HEX in ADSBDB and caches the result for 24 hours. When a receiver callsign is available, it also requests the combined aircraft/callsign response so the detail card can show the returned ICAO/IATA callsign and route.</p><p><code>asbdb_lookup()</code> remains the route fallback for callsigns and caches successful results and 404 misses.</p>
      <p>ASBDB is supplementary scheduled-route data. It is not the live aircraft position source.</p>

      <h2>11. Statistics</h2>
      <p>The Statistics page is split into three periods: the current live snapshot, the current Planes session, and the overall period reported by readsb's <code>stats.json</code>. Planes session metrics include unique aircraft seen, peak and average aircraft counts, highest altitude, fastest speed, recorded snapshots and feed interruptions. readsb-period metrics include running time, accepted messages, tracks, CPR positions, SDR blocks and signal information when supplied.</p>

      <h2>12. Settings feed test</h2>
      <p><code>/api/test-feed</code> tests the saved configuration. <code>/api/test-feed-url</code> tests the URL currently typed into the Settings box, so a new URL can be checked before saving it.</p>

      <h2>13. HTTP routes</h2>
      <ul class="clean-list">
        <li><code>/</code> — Dashboard.</li>
        <li><code>/statistics</code> — current statistics.</li>
        <li><code>/settings</code> — settings page.</li>
        <li><code>/documentation</code> — code documentation.</li>
        <li><code>/about</code> — project information.</li>
        <li><code>/contact</code> — project contact.</li>
        <li><code>/aircraft/&lt;hex&gt;</code> — aircraft detail page.</li>
        <li><code>/api/dashboard-data</code> — Dashboard refresh JSON.</li>
        <li><code>/api/dashboard-table</code> — aircraft table HTML.</li>
        <li><code>/api/aircraft/&lt;hex&gt;</code> — live detail HTML fragment.</li>
        <li><code>/api/aircraft-metadata/&lt;hex&gt;</code> — cached ADSBDB aircraft metadata.</li>
        <li><code>/api/settings</code> — settings read/write.</li>
        <li><code>/api/test-feed</code> — saved-feed test.</li>
        <li><code>/api/test-feed-url</code> — unsaved-feed test.</li>
        <li><code>/statistics</code> also reads <code>stats.json</code> from the configured readsb host when available.</li>
      </ul>

      <h2>14. Static files</h2>
      <p><code>static/</code> contains CSS, icons and browser assets and is mounted at <code>/static</code>.</p>

      <h2>15. Project structure</h2>
      <pre><code>main.py            server startup
webpage.py         FastAPI app, routes, rendering and browser JS
settings.json      application/feed settings
requirements.txt   Python dependencies
static/            CSS, icons and browser assets
tests/             automated tests
README.md          setup and testing guide</code></pre>

      <h2>16. First-run setup</h2>
      <p>A new installation opens a setup screen before the Dashboard. The setup screen asks for the aircraft JSON URL, refresh interval, base theme and optional ASBDB lookups.</p>
      <p><strong>Test feed</strong> checks the URL before saving it. <strong>Save and open Planes</strong> stores the server settings, records that setup is complete and opens the Dashboard.</p>
      <p>The completion marker is <code>.planes_setup_complete</code>. It is local to the installation and ignored by Git. Existing settings are prefilled, so an existing installation can normally keep its current receiver URL.</p>

      <h2>17. Raspberry Pi testing</h2>
      <p>The repository includes <code>scripts/pi_smoke_test.sh</code>. It is a safe, non-destructive smoke test for a running Raspberry Pi installation.</p>
      <pre><code>cd ~/planes
bash scripts/pi_smoke_test.sh</code></pre>
      <p>It checks Python imports and syntax, the readsb service, the live aircraft JSON feed, the Planes HTTP server, the main pages, the Dashboard API and both feed-test endpoints. It does not stop services or modify <code>settings.json</code>.</p>
      <p>A separate manual recovery test should stop readsb, wait for one or more Dashboard refreshes, confirm Planes keeps the last known-good aircraft data and reports a stale/unavailable feed, then restart readsb and confirm live updates resume.</p>
      <pre><code>sudo systemctl stop readsb
# wait for a Dashboard refresh
sudo systemctl start readsb</code></pre>

      <h2>16. First-run setup</h2>
      <p>On a new installation, Planes shows a setup screen before the Dashboard. It asks for the aircraft JSON URL, refresh interval, base theme and optional ASBDB lookups.</p>
      <p><strong>Test feed</strong> checks the URL before it is saved. <strong>Save and open Planes</strong> stores the server settings, records that setup is complete and opens the Dashboard.</p>
      <p>The completion marker is stored locally as <code>.planes_setup_complete</code> and is ignored by Git. Existing settings are prefilled so an existing installation can normally accept its current configuration and continue.</p>
      <h2>17. Raspberry Pi testing</h2>
      <p><strong>v0.0.5 audit fixes</strong>. This branch contains fixes found during manual post-release testing, including metadata enrichment, non-ICAO identifier support, dashboard search/favourite fixes and the reworked statistics periods. It should not be treated as the next release until the Pi test checklist passes.</p>
    </section>'''
    return page("Documentation", content, "documentation")

@app.get("/about", response_class=HTMLResponse)
def read_about():
    content = '''<section class="panel prose"><h2>About Planes</h2><p>Planes is a small local web interface for an ADS-B receiver. It reads aircraft JSON from a configurable feed and presents live aircraft, statistics and detail pages.</p><h2>Data sources</h2><p>Live aircraft data comes from the configured receiver feed. Optional route information on detail pages comes from ASBDB and should be treated as supplementary scheduled-route information rather than a live position source.</p></section>'''
    return page("About", content, "about")


@app.get("/contact", response_class=HTMLResponse)
def read_contact():
    content = '''<section class="panel prose"><h2>Contact</h2><p>For project issues, suggestions or code contributions, use the project repository.</p><p><a class="text-link" href="https://github.com/H-J-Wilson/planes" rel="noopener noreferrer">Open the Planes GitHub repository</a></p></section>'''
    return page("Contact", content)
