import datetime as dt
import html
import ipaddress
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


def load_settings() -> dict[str, Any]:
    settings = DEFAULT_SETTINGS.copy()
    try:
        settings.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        pass
    return settings


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


def get_aircraft_data() -> tuple[dict[str, Any], float | None]:
    settings = load_settings()
    try:
        url = validate_data_url(str(settings["aircraft_data_url"]))
        started = time.monotonic()
        response = requests.get(url, timeout=2)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("aircraft"), list):
            raise ValueError("Aircraft feed did not return the expected JSON structure.")
        return data, time.monotonic() - started
    except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError):
        return {"aircraft": []}, None


def clean(value: Any, fallback: str = "—") -> str:
    if value is None or value == "":
        return fallback
    return html.escape(str(value))


def aircraft_rows(aircraft: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for plane in aircraft:
        hex_code = str(plane.get("hex", "")).strip().lower()
        flight = str(plane.get("flight", "")).strip() or "Unknown"
        aircraft_type = str(plane.get("t", "")).strip() or str(plane.get("desc", "")).strip() or "Unknown"
        speed = plane.get("gs", "—")
        altitude = plane.get("alt_baro", "—")
        fav_key = clean(hex_code)
        details = f"/aircraft/{fav_key}" if hex_code else "#"
        rows.append(
            f'''<tr data-aircraft-row data-flight="{clean(flight).lower()}" data-type="{clean(aircraft_type).lower()}" data-hex="{fav_key}">
                <td><span class="mobile-label">Flight</span><strong>{clean(flight)}</strong></td>
                <td><span class="mobile-label">Aircraft</span>{clean(aircraft_type)}</td>
                <td><span class="mobile-label">Speed</span>{clean(speed)} <span class="unit">kt</span></td>
                <td><span class="mobile-label">Altitude</span>{clean(altitude)} <span class="unit">ft</span></td>
                <td class="actions"><button type="button" class="favourite-button" data-favourite="{fav_key}" aria-label="Add {clean(flight)} to favourites" aria-pressed="false">☆</button>
                    <a class="text-link" href="{details}">View details</a></td>
            </tr>'''
        )
    if not rows:
        return '<tr><td colspan="5" class="empty-cell">No active aircraft are being tracked right now.</td></tr>'
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
  <link rel="stylesheet" href="/static/output.css?v=0.0.3">
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
      <div class="footer-meta"><span>v0.0.3</span><span>Updated {now}</span><span>Refresh {refresh}s</span></div>
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
    refresh = max(2, min(60, int(settings.get("refresh_seconds", 5))))
    data, elapsed = get_aircraft_data()
    aircraft = data.get("aircraft", [])
    count = len(aircraft)
    status = "Feed responding" if elapsed is not None else "Feed unavailable"
    status_class = "status-ok" if elapsed is not None else "status-error"
    rows = aircraft_rows(aircraft)
    return f'''<section class="toolbar" aria-label="Aircraft table controls">
      <div class="search-wrap"><label for="aircraft-search">Search aircraft</label><input id="aircraft-search" type="search" placeholder="Flight, type or hex…" autocomplete="off"></div>
      <div><label for="sort-select">Sort by</label><select id="sort-select"><option value="flight">Flight</option><option value="type">Aircraft</option><option value="speed">Speed</option><option value="altitude">Altitude</option></select></div>
      <button id="refresh-now" class="button secondary" type="button">Refresh now</button>
    </section>
    <section class="stats-strip" aria-label="Live receiver status">
      <div class="metric"><span>Aircraft</span><strong id="aircraft-count">{count}</strong></div>
      <div class="metric"><span>Feed</span><strong id="feed-status" class="{status_class}">{status}</strong></div>
      <div class="metric"><span>Last check</span><strong id="last-check">Just now</strong></div>
    </section>
    <div id="table-status" class="sr-status" role="status" aria-live="polite"></div>
    <div class="table-card">
      <table id="aircraft-table">
        <caption>Aircraft currently visible to the receiver</caption>
        <thead><tr><th scope="col">Flight</th><th scope="col">Aircraft</th><th scope="col">Speed</th><th scope="col">Altitude</th><th scope="col">More info</th></tr></thead>
        <tbody id="flight-rows">{rows}</tbody>
      </table>
    </div>
    <p class="help-text">Updates automatically every {refresh} seconds. Search and favourites stay on this device.</p>
    <script>
      (() => {{
        const tbody = document.getElementById('flight-rows');
        const count = document.getElementById('aircraft-count');
        const status = document.getElementById('feed-status');
        const last = document.getElementById('last-check');
        const search = document.getElementById('aircraft-search');
        const sort = document.getElementById('sort-select');
        const tableStatus = document.getElementById('table-status');
        let rows = [...tbody.querySelectorAll('tr[data-aircraft-row]')];
        let aircraftData = [];
        function favouriteState() {{ try {{ return JSON.parse(localStorage.getItem('planes-favourites') || '[]'); }} catch {{ return []; }} }}
        function setFavourite(key, button) {{
          if (!key) return;
          const favs = new Set(favouriteState());
          if (favs.has(key)) favs.delete(key); else favs.add(key);
          localStorage.setItem('planes-favourites', JSON.stringify([...favs]));
          updateFavouriteButtons();
        }}
        function updateFavouriteButtons() {{
          const favs = new Set(favouriteState());
          document.querySelectorAll('[data-favourite]').forEach(btn => {{ const on = favs.has(btn.dataset.favourite); btn.textContent = on ? '★' : '☆'; btn.setAttribute('aria-pressed', String(on)); btn.setAttribute('aria-label', (on ? 'Remove ' : 'Add ') + 'aircraft ' + btn.dataset.favourite + ' to favourites'); }});
        }}
        function bindButtons() {{ document.querySelectorAll('[data-favourite]').forEach(btn => btn.addEventListener('click', () => setFavourite(btn.dataset.favourite, btn))); updateFavouriteButtons(); }}
        function renderRows() {{
          const q = search.value.trim().toLowerCase();
          const key = sort.value;
          const list = [...aircraftData].filter(a => {{ const text = [a.flight || '', a.t || '', a.desc || '', a.hex || ''].join(' ').toLowerCase(); return text.includes(q); }});
          list.sort((a,b) => {{ if (key === 'speed') return Number(b.gs || -1) - Number(a.gs || -1); if (key === 'altitude') return Number(b.alt_baro || -1) - Number(a.alt_baro || -1); if (key === 'type') return String(a.t || a.desc || '').localeCompare(String(b.t || b.desc || '')); return String(a.flight || '').localeCompare(String(b.flight || '')); }});
          tbody.innerHTML = list.length ? list.map(a => {{ const flight = (a.flight || "Unknown").trim(); const type = a.t || a.desc || "Unknown"; const hex = (a.hex || "").toLowerCase(); return "<tr data-aircraft-row><td><span class=\"mobile-label\">Flight</span><strong>"+esc(flight)+"</strong></td><td><span class=\"mobile-label\">Aircraft</span>"+esc(type)+"</td><td><span class=\"mobile-label\">Speed</span>"+esc(a.gs ?? "—")+" <span class=\"unit\">kt</span></td><td><span class=\"mobile-label\">Altitude</span>"+esc(a.alt_baro ?? "—")+" <span class=\"unit\">ft</span></td><td class=\"actions\"><button type=\"button\" class=\"favourite-button\" data-favourite=\""+esc(hex)+"\" aria-pressed=\"false\">☆</button> <a class=\"text-link\" href=\"/aircraft/"+encodeURIComponent(hex)+"\">View details</a></td></tr>"; }}).join("") : "<tr><td colspan=\"5\" class=\"empty-cell\">No aircraft match your search.</td></tr>";
          bindButtons();
        }}
        function esc(v) {{ const d=document.createElement('div'); d.textContent=String(v); return d.innerHTML; }}
        async function refresh() {{
          try {{
            const res = await fetch('/api/dashboard-data', {{cache:'no-store'}}); if (!res.ok) throw new Error('HTTP '+res.status);
            const payload = await res.json(); aircraftData = payload.aircraft || []; count.textContent = aircraftData.length; status.textContent='Feed responding'; status.className='status-ok'; last.textContent=new Date().toLocaleTimeString(); renderRows(); tableStatus.textContent = 'Aircraft list updated.';
          }} catch (e) {{ status.textContent='Feed unavailable'; status.className='status-error'; last.textContent='Connection failed'; tableStatus.textContent='Unable to update aircraft data.'; }}
        }}
        search.addEventListener('input', renderRows); sort.addEventListener('change', renderRows); document.getElementById('refresh-now').addEventListener('click', refresh); bindButtons();
        refresh(); setInterval(refresh, REFRESH_SECONDS * 1000);
      }})();
    </script>'''


@app.get("/", response_class=HTMLResponse)
def read_root():
    return page("Aircraft Dashboard", dashboard_content(), "dashboard")


@app.get("/api/dashboard-data")
def dashboard_data(response: Response):
    response.headers["Cache-Control"] = "no-store"
    data, elapsed = get_aircraft_data()
    return JSONResponse({"aircraft": data.get("aircraft", []), "feed_ok": elapsed is not None})


@app.get("/api/dashboard-table", response_class=HTMLResponse)
def get_dashboard_table(response: Response):
    response.headers["Cache-Control"] = "no-store"
    data, _ = get_aircraft_data()
    return HTMLResponse(aircraft_rows(data.get("aircraft", [])))


@app.get("/statistics", response_class=HTMLResponse)
def read_statistics():
    data, elapsed = get_aircraft_data()
    aircraft = data.get("aircraft", [])
    altitudes = [a.get("alt_baro") for a in aircraft if isinstance(a.get("alt_baro"), (int, float))]
    speeds = [a.get("gs") for a in aircraft if isinstance(a.get("gs"), (int, float))]
    types = {}
    for a in aircraft:
        key = a.get("t") or a.get("desc") or "Unknown"
        types[key] = types.get(key, 0) + 1
    top_types = sorted(types.items(), key=lambda x: x[1], reverse=True)[:8]
    type_rows = "".join(f"<tr><td>{clean(k)}</td><td>{v}</td></tr>" for k,v in top_types) or '<tr><td colspan="2">No type data available.</td></tr>'
    settings = load_settings()
    content = f'''<section class="stats-grid">
      <article class="panel"><span>Aircraft visible</span><strong>{len(aircraft)}</strong><p>Current entries in the receiver feed.</p></article>
      <article class="panel"><span>Average altitude</span><strong>{round(sum(altitudes)/len(altitudes)) if altitudes else "—"} <small>ft</small></strong><p>Barometric altitude where available.</p></article>
      <article class="panel"><span>Average speed</span><strong>{round(sum(speeds)/len(speeds)) if speeds else "—"} <small>kt</small></strong><p>Ground speed where available.</p></article>
      <article class="panel"><span>Feed response</span><strong>{round(elapsed*1000) if elapsed is not None else "—"} <small>ms</small></strong><p>Approximate request time from the web server.</p></article>
    </section>
    <section class="panel table-card"><h2>Aircraft types</h2><table><caption>Aircraft types currently visible</caption><thead><tr><th scope="col">Type</th><th scope="col">Count</th></tr></thead><tbody>{type_rows}</tbody></table></section>
    <section class="panel"><h2>Receiver connection</h2><dl class="details-list"><div><dt>Aircraft feed</dt><dd>{clean(settings.get("aircraft_data_url"))}</dd></div><div><dt>Refresh interval</dt><dd>{int(settings.get("refresh_seconds",5))} seconds</dd></div><div><dt>ASBDB lookups</dt><dd>{"Enabled" if settings.get("asbdb_enabled") else "Disabled"}</dd></div></dl></section>'''
    return page("Statistics", content, "statistics")


_asbdb_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def asbdb_lookup(callsign: str) -> dict[str, Any] | None:
    settings = load_settings()
    if not settings.get("asbdb_enabled", True) or not callsign:
        return None
    callsign = callsign.strip().upper()
    now = time.time()
    cached = _asbdb_cache.get(callsign)
    if cached and now - cached[0] < int(settings.get("asbdb_cache_seconds", 30)):
        return cached[1]
    try:
        res = requests.get(ASBDB_BASE + callsign, timeout=3)
        if res.status_code == 404:
            return None
        res.raise_for_status()
        payload = res.json()
        route = payload.get("response", {}).get("flightroute")
        if isinstance(route, dict):
            _asbdb_cache[callsign] = (now, route)
            return route
    except (requests.RequestException, ValueError, TypeError):
        pass
    return None


def detail_fragment(hex_code: str) -> str:
    data, _ = get_aircraft_data()
    target = next((a for a in data.get("aircraft", []) if str(a.get("hex", "")).lower() == hex_code.lower()), None)
    if not target:
        return '<div class="notice error"><strong>Aircraft not currently visible.</strong><p>It may have left receiver range or stopped transmitting.</p></div>'
    flight = str(target.get("flight", "Unknown")).strip() or "Unknown"
    route = asbdb_lookup(flight)
    route_html = '<p class="muted">No route information available.</p>'
    if route:
        origin = route.get("origin", {}).get("name", route.get("origin", {}).get("iata", "Unknown")) if isinstance(route.get("origin"), dict) else "Unknown"
        destination = route.get("destination", {}).get("name", route.get("destination", {}).get("iata", "Unknown")) if isinstance(route.get("destination"), dict) else "Unknown"
        airline = route.get("airline", {}).get("name", "Unknown airline") if isinstance(route.get("airline"), dict) else "Unknown airline"
        route_html = f'<div class="route"><div><span>Origin</span><strong>{clean(origin)}</strong></div><div class="route-arrow" aria-hidden="true">→</div><div><span>Destination</span><strong>{clean(destination)}</strong></div><p>{clean(airline)} · ASBDB scheduled-route data</p></div>'
    fields = [
        ("Aircraft type", target.get("desc") or target.get("t")), ("Squawk", target.get("squawk")),
        ("Ground speed", f"{target.get('gs')} kt" if target.get("gs") is not None else None),
        ("Altitude", f"{target.get('alt_baro')} ft" if target.get("alt_baro") is not None else None),
        ("Latitude", target.get("lat")), ("Longitude", target.get("lon")),
        ("Distance", f"{target.get('r_dst')} nm" if target.get("r_dst") is not None else None),
        ("Bearing", f"{target.get('r_dir')}°" if target.get("r_dir") is not None else None),
    ]
    cards = "".join(f'<div><span>{clean(label)}</span><strong>{clean(value)}</strong></div>' for label,value in fields)
    return f'''<div class="detail-title"><div><p class="eyebrow">HEX {clean(hex_code.upper())}</p><h2>{clean(flight)}</h2></div><span class="live-pill">LIVE</span></div>
    <div class="detail-grid">{cards}</div><section class="route-panel"><h3>Route information</h3>{route_html}</section>'''


@app.get("/aircraft/{hex_code}", response_class=HTMLResponse)
def read_aircraft_details(hex_code: str):
    safe_hex = html.escape(hex_code)
    content = f'''<section class="panel detail-panel"><div id="live-details" role="region" aria-live="polite" aria-label="Live aircraft details"><p class="loading">Loading live aircraft data…</p></div><a class="back-link" href="/">← Back to dashboard</a></section>
    <script>
      async function refreshAircraft() {{ try {{ const res=await fetch('/api/aircraft/{safe_hex}',{{cache:'no-store'}}); document.getElementById('live-details').innerHTML=await res.text(); }} catch {{ document.getElementById('live-details').innerHTML='<div class="notice error">Unable to refresh aircraft data.</div>'; }} }}
      refreshAircraft(); setInterval(refreshAircraft, REFRESH_SECONDS*1000);
    </script>'''
    return page("Aircraft Details", content)


@app.get("/api/aircraft/{hex_code}", response_class=HTMLResponse)
def get_aircraft_details_fragment(hex_code: str, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return HTMLResponse(detail_fragment(hex_code))


@app.get("/settings", response_class=HTMLResponse)
def read_settings():
    settings = load_settings()
    content = f'''<form id="settings-form" class="panel settings-form">
      <div><label for="aircraft-data-url">Aircraft data URL</label><input id="aircraft-data-url" name="aircraft_data_url" type="url" value="{clean(settings.get('aircraft_data_url'))}" required><p class="field-help">Usually the local readsb/tar1090 JSON endpoint.</p></div>
      <div><label for="refresh-seconds">Refresh interval</label><select id="refresh-seconds" name="refresh_seconds">{''.join(f'<option value="{n}" {"selected" if int(settings.get("refresh_seconds",5)) == n else ""}>{n} seconds</option>' for n in [2,3,5,10,15,30,60])}</select></div>
      <label class="checkbox"><input id="asbdb-enabled" name="asbdb_enabled" type="checkbox" {"checked" if settings.get("asbdb_enabled",True) else ""}> Use ASBDB route lookups on aircraft detail pages</label>
      <fieldset><legend>Appearance</legend><label for="theme-select">Theme</label><select id="theme-select"><option value="system">Use system setting</option><option value="dark">Dark cyan</option><option value="light">Light</option></select><p class="field-help">This preference is saved only in this browser.</p></fieldset>
      <div class="form-actions"><button class="button" type="submit">Save settings</button><span id="save-status" role="status" aria-live="polite"></span></div>
    </form>
    <section class="panel"><h2>What these settings do</h2><ul class="clean-list"><li><strong>Aircraft data URL</strong> controls where this server reads aircraft JSON.</li><li><strong>Refresh interval</strong> controls how often the browser requests fresh data.</li><li><strong>ASBDB</strong> adds scheduled route/airline information when a callsign can be matched.</li><li><strong>Theme</strong> changes the interface without changing the receiver configuration.</li></ul></section>
    <script>
      document.getElementById('settings-form').addEventListener('submit', async e => {{ e.preventDefault(); const s=document.getElementById('save-status'); s.textContent='Saving…'; const body={{aircraft_data_url:document.getElementById('aircraft-data-url').value,refresh_seconds:Number(document.getElementById('refresh-seconds').value),asbdb_enabled:document.getElementById('asbdb-enabled').checked}}; try {{ const r=await fetch('/api/settings',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}}); const j=await r.json(); if(!r.ok) throw new Error(j.detail||'Save failed'); s.textContent='Saved. Reloading…'; setTimeout(()=>location.reload(),500); }} catch(err) {{ s.textContent=err.message; }} }});
    </script>'''
    return page("Settings", content, "settings")


@app.get("/api/settings")
def get_settings():
    return load_settings()


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


@app.get("/about", response_class=HTMLResponse)
def read_about():
    content = '''<section class="panel prose"><h2>About Planes</h2><p>Planes is a small local web interface for an ADS-B receiver. It reads aircraft JSON from a configurable feed and presents live aircraft, statistics and detail pages.</p><h2>Data sources</h2><p>Live aircraft data comes from the configured receiver feed. Optional route information on detail pages comes from ASBDB and should be treated as supplementary scheduled-route information rather than a live position source.</p></section>'''
    return page("About", content, "about")


@app.get("/contact", response_class=HTMLResponse)
def read_contact():
    content = '''<section class="panel prose"><h2>Contact</h2><p>For project issues, suggestions or code contributions, use the project repository.</p><p><a class="text-link" href="https://github.com/H-J-Wilson/planes" rel="noopener noreferrer">Open the Planes GitHub repository</a></p></section>'''
    return page("Contact", content)
