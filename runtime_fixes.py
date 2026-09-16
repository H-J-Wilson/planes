"""Reliability fixes and the code-focused Documentation page for the audit branch."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

import requests

PATCHED = False


def _safe_settings(original: Callable[[], dict[str, Any]], module: Any) -> dict[str, Any]:
    try:
        raw = original()
    except Exception as exc:
        module.logger.warning("Settings load failed; using defaults: %s", exc)
        raw = dict(module.DEFAULT_SETTINGS)
    if not isinstance(raw, dict):
        raw = dict(module.DEFAULT_SETTINGS)
    settings = dict(module.DEFAULT_SETTINGS)
    settings.update(raw)
    try:
        settings["aircraft_data_url"] = module.validate_data_url(
            str(settings.get("aircraft_data_url", module.DEFAULT_SETTINGS["aircraft_data_url"]))
        )
    except (ValueError, TypeError):
        settings["aircraft_data_url"] = module.DEFAULT_SETTINGS["aircraft_data_url"]
    try:
        refresh = int(settings.get("refresh_seconds", 5))
    except (TypeError, ValueError):
        refresh = 5
    settings["refresh_seconds"] = max(2, min(60, refresh))
    settings["asbdb_enabled"] = bool(settings.get("asbdb_enabled", True))
    try:
        cache_seconds = int(settings.get("asbdb_cache_seconds", 30))
    except (TypeError, ValueError):
        cache_seconds = 30
    settings["asbdb_cache_seconds"] = max(5, min(3600, cache_seconds))
    return settings


def _make_feed_reader(module: Any) -> Callable[[], tuple[dict[str, Any], float | None]]:
    original = module.get_aircraft_data
    last_good: dict[str, Any] = {"aircraft": []}

    def get_aircraft_data() -> tuple[dict[str, Any], float | None]:
        nonlocal last_good
        try:
            data, elapsed = original()
        except Exception as exc:
            module.logger.warning("Aircraft feed reader crashed: %s", exc)
            data, elapsed = {"aircraft": []}, None
        if elapsed is not None and isinstance(data, dict) and isinstance(data.get("aircraft"), list):
            last_good = data
            return data, elapsed
        if last_good.get("aircraft"):
            return dict(last_good), None
        return {"aircraft": []}, None

    return get_aircraft_data


def _patch_dashboard(module: Any) -> None:
    original_dashboard = module.dashboard_content

    def dashboard_content() -> str:
        data, _ = module.get_aircraft_data()
        aircraft = data.get("aircraft", []) if isinstance(data, dict) else []
        html = original_dashboard()
        initial_json = json.dumps(aircraft, separators=(",", ":"), ensure_ascii=True).replace("</", "<\\/")
        html = html.replace("let aircraftData = [];", f"let aircraftData = {initial_json};", 1)
        html = html.replace(
            "status.textContent='Feed responding';",
            "status.textContent = (payload.feed_ok === false) ? (aircraftData.length ? 'Using last good data' : 'Feed unavailable') : 'Feed responding';",
            1,
        )
        html = html.replace(
            "status.className='status-ok';",
            "status.className = payload.feed_ok === false ? (aircraftData.length ? 'status-warning' : 'status-error') : 'status-ok';",
            1,
        )
        html = html.replace(
            "tableStatus.textContent='Aircraft list updated.';",
            "tableStatus.textContent = payload.feed_ok === false ? 'Feed unavailable; showing the last successful aircraft data.' : 'Aircraft list updated.';",
            1,
        )
        html = html.replace(
            "const minAlt = Number(minAltitude.value) || 0; const minSpd = Number(minSpeed.value) || 0;",
            "const hasMinAlt = minAltitude.value.trim() !== ''; const hasMinSpd = minSpeed.value.trim() !== ''; const minAlt = Number(minAltitude.value); const minSpd = Number(minSpeed.value);",
            1,
        )
        html = html.replace(
            "return text.includes(q) && alt >= minAlt && gs >= minSpd && matchesFilter;",
            "const altitudeMatches = !hasMinAlt || (Number.isFinite(alt) && alt >= minAlt); const speedMatches = !hasMinSpd || (Number.isFinite(gs) && gs >= minSpd); return text.includes(q) && altitudeMatches && speedMatches && matchesFilter;",
            1,
        )
        return html

    module.dashboard_content = dashboard_content


def _test_feed_url(url: str) -> dict[str, Any]:
    import webpage
    clean_url = webpage.validate_data_url(url)
    started = time.monotonic()
    response = requests.get(clean_url, timeout=2)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("aircraft"), list):
        raise ValueError("Aircraft feed did not return the expected JSON structure.")
    return {"ok": True, "aircraft_count": len(data["aircraft"]), "response_ms": round((time.monotonic() - started) * 1000)}


def _add_unsaved_feed_test(module: Any) -> None:
    try:
        module.app.add_api_route(
            "/api/test-feed-url",
            _test_feed_url,
            methods=["GET"],
            response_class=module.JSONResponse,
        )
    except Exception as exc:
        module.logger.warning("Could not add unsaved feed test endpoint: %s", exc)


def _patch_settings_page(module: Any) -> None:
    if not hasattr(module, "settings_content"):
        return
    original = module.settings_content

    def settings_content() -> str:
        html = original()
        script = """
<script>
(() => {
  const button = document.getElementById('test-feed');
  if (!button) return;
  button.addEventListener('click', async event => {
    event.preventDefault();
    event.stopImmediatePropagation();
    const status = document.getElementById('save-status');
    const input = document.getElementById('aircraft-data-url');
    status.textContent = 'Testing feed…';
    try {
      const url = input.value.trim();
      const response = await fetch('/api/test-feed-url?url=' + encodeURIComponent(url), {cache: 'no-store'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Feed test failed');
      status.textContent = 'Feed OK · ' + result.aircraft_count + ' aircraft · ' + result.response_ms + ' ms';
    } catch (error) {
      status.textContent = error.message || 'Feed test failed';
    }
  }, true);
})();
</script>
"""
        return html.replace('</body>', script + '</body>')

    module.settings_content = settings_content


def _patch_detail(module: Any) -> None:
    if not hasattr(module, "detail_fragment"):
        return
    original = module.detail_fragment

    def detail_fragment(hex_code: str) -> str:
        value = str(hex_code or '').strip().lower()
        if not re.fullmatch(r'[0-9a-f]{6}', value):
            return '<div class="notice error">Invalid aircraft identifier.</div>'
        return original(value)

    module.detail_fragment = detail_fragment


def _documentation_endpoint(module: Any) -> str:
    content = r'''
<section class="panel">
  <h2>Architecture</h2>
  <pre><code>Browser
  │ HTTP :8000
  ▼
main.py
  │ starts Uvicorn
  ▼
webpage.py
  ├─ settings.json
  ├─ readsb/tar1090 aircraft JSON
  ├─ ASBDB route lookup
  └─ HTML + browser JavaScript
  ▼
static/ CSS, images and client assets</code></pre>
  <p>Planes is a small FastAPI application. The server reads the receiver JSON, generates HTML and exposes small JSON endpoints for browser refreshes.</p>
</section>
<section class="panel">
  <h2>1. main.py</h2>
  <p><code>main.py</code> is the startup file. It imports the FastAPI module, applies the audit fixes, then starts Uvicorn on port 8000.</p>
  <pre><code>import uvicorn
import webpage
from runtime_fixes import apply_patches

apply_patches(webpage)
uvicorn.run(webpage.app, host="0.0.0.0", port=8000)</code></pre>
  <p>It contains no aircraft-processing logic.</p>
</section>
<section class="panel">
  <h2>2. webpage.py</h2>
  <p><code>webpage.py</code> contains the FastAPI application, configuration handling, feed access, HTML generation, routes and Dashboard JavaScript.</p>
  <ul class="clean-list">
    <li><code>app</code> creates the FastAPI application.</li>
    <li><code>SETTINGS_FILE</code> points to <code>settings.json</code>.</li>
    <li><code>DEFAULT_SETTINGS</code> provides safe defaults.</li>
    <li><code>ASBDB_BASE</code> is the optional route lookup API base URL.</li>
    <li><code>APP_VERSION</code> controls displayed/cache-busting version text.</li>
    <li><code>logger</code> records feed failures and other diagnostics.</li>
  </ul>
</section>
<section class="panel">
  <h2>3. Configuration</h2>
  <pre><code>{
  "aircraft_data_url": "http://127.0.0.1:8504/data/aircraft.json",
  "refresh_seconds": 5,
  "asbdb_enabled": true,
  "asbdb_cache_seconds": 30
}</code></pre>
  <p><code>load_settings()</code> reads the JSON file and <code>save_settings()</code> writes it. The audit branch validates the URL and numeric settings before they are used by page rendering.</p>
</section>
<section class="panel">
  <h2>4. Feed loading</h2>
  <p><code>validate_data_url()</code> checks that the configured feed is HTTP/HTTPS and has a host.</p>
  <p>The feed path is:</p>
  <pre><code>settings
  ↓
validate URL
  ↓
requests.get(timeout=2)
  ↓
raise_for_status()
  ↓
response.json()
  ↓
check data['aircraft'] is a list
  ↓
return aircraft data + request time</code></pre>
  <p>The audit branch retains the last successful aircraft list when a later request fails. A failed request is therefore different from zero aircraft.</p>
</section>
<section class="panel">
  <h2>5. Dashboard rendering</h2>
  <p><code>dashboard_content()</code> performs the first feed read and creates the initial table. It also embeds the initial aircraft list into the browser's JavaScript state so search/filter/favourites work before the first refresh completes.</p>
  <pre><code>Initial page
  ├─ server-rendered aircraft rows
  └─ initial aircraftData

After page load
  └─ GET /api/dashboard-data every N seconds
       ├─ feed OK → replace aircraftData
       └─ feed failed → keep last good data</code></pre>
</section>
<section class="panel">
  <h2>6. Dashboard JavaScript</h2>
  <p>The browser code handles the controls locally:</p>
  <ul class="clean-list">
    <li>Search checks flight/callsign, type, description, HEX and registration.</li>
    <li>Filters check movement, vertical rate, valid position, favourites, minimum altitude and minimum speed.</li>
    <li>Sort orders by flight, type, speed, altitude or distance.</li>
    <li>The refresh loop requests fresh JSON without page reload.</li>
    <li>Favourite state is stored in browser <code>localStorage</code>.</li>
  </ul>
  <p>An empty minimum-altitude/speed box means no minimum. Missing altitude or speed therefore does not remove aircraft from the default list.</p>
</section>
<section class="panel">
  <h2>7. Favourites</h2>
  <p>Favourites are stored under <code>planes-favourites</code> as a JSON array of HEX identifiers.</p>
  <pre><code>localStorage
    ↓
planes-favourites
    ↓
JSON array of HEX values
    ↓
star state + Favourite filter</code></pre>
  <p>They are browser-local and are not synchronised to a server.</p>
</section>
<section class="panel">
  <h2>8. Aircraft details and ASBDB</h2>
  <p>The detail page receives an aircraft HEX identifier, validates it and finds the aircraft in the current feed. The page can show ICAO HEX, callsign, type/description, squawk, altitude, speed, position, distance and bearing when supplied.</p>
  <p>ASBDB is an optional supplementary lookup for scheduled route/airline information. It is not the source of live aircraft position.</p>
</section>
<section class="panel">
  <h2>9. Statistics</h2>
  <p>The Statistics page reads the current aircraft feed and derives counts and averages from the fields currently available. Missing or invalid numeric values are excluded where required. There is no historical database in v0.0.5.</p>
</section>
<section class="panel">
  <h2>10. HTTP routes and API endpoints</h2>
  <ul class="clean-list">
    <li><code>/</code> — Dashboard.</li>
    <li><code>/statistics</code> — current statistics.</li>
    <li><code>/settings</code> — configuration UI.</li>
    <li><code>/documentation</code> — this page.</li>
    <li><code>/aircraft/&lt;hex&gt;</code> — aircraft details.</li>
    <li><code>/api/dashboard-data</code> — JSON for Dashboard refresh.</li>
    <li><code>/api/dashboard-table</code> — server-rendered aircraft table.</li>
    <li><code>/api/settings</code> — settings read/write.</li>
    <li><code>/api/test-feed</code> — test the saved feed URL.</li>
    <li><code>/api/test-feed-url</code> — audit-branch test of the URL currently typed in Settings.</li>
  </ul>
</section>
<section class="panel">
  <h2>11. Failure handling</h2>
  <ol class="clean-list">
    <li>Receiver failure: timeout, HTTP error or invalid JSON is logged.</li>
    <li>Server state: the last known-good aircraft list is retained.</li>
    <li>API state: the dashboard can see <code>feed_ok: false</code>.</li>
    <li>Browser state: the current table is kept rather than wiped.</li>
  </ol>
  <p>This is the main reliability change made after the v0.0.5 manual test.</p>
</section>
<section class="panel">
  <h2>12. runtime_fixes.py</h2>
  <p>This file exists on the audit branch to wrap the v0.0.5 application without rewriting its existing UI.</p>
  <p><code>apply_patches()</code> installs safe settings parsing, last-known-good feed handling, Dashboard state fixes, unsaved feed testing, HEX validation and this Documentation page.</p>
  <p>After Pi testing, these changes should be folded into the main code and this compatibility layer removed.</p>
</section>
<section class="panel">
  <h2>13. static/</h2>
  <p><code>static/</code> contains CSS, images and other browser assets. FastAPI mounts it at <code>/static</code>. Visual styling is separate from the aircraft-feed logic.</p>
</section>
<section class="panel">
  <h2>14. Repository files</h2>
  <pre><code>main.py            server startup
webpage.py         FastAPI app, routes, rendering and browser JS
runtime_fixes.py   audit-branch reliability layer
settings.json      receiver/app configuration
requirements.txt   Python dependencies
static/            CSS, images and frontend assets
README.md          setup, update and testing guide</code></pre>
  <p>Generated files such as virtual environments, Python bytecode caches and macOS metadata should not be committed.</p>
</section>
'''
    return module.page("Documentation", content, "documentation")


def _patch_documentation(module: Any) -> None:
    for route in module.app.routes:
        if getattr(route, "path", None) == "/documentation":
            route.endpoint = lambda: _documentation_endpoint(module)
            route.response_class = module.HTMLResponse
            return


def apply_patches(module: Any) -> None:
    global PATCHED
    if PATCHED:
        return
    original_settings = module.load_settings
    module.load_settings = lambda: _safe_settings(original_settings, module)
    module.get_aircraft_data = _make_feed_reader(module)
    _patch_dashboard(module)
    _patch_settings_page(module)
    _patch_detail(module)
    _add_unsaved_feed_test(module)
    _patch_documentation(module)
    PATCHED = True
    module.logger.info("Runtime reliability fixes enabled")
