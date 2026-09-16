"""Compatibility and reliability fixes applied before starting the Planes server.

This module keeps the existing v0.0.5 UI intact while fixing the dashboard's
state handling and feed failure behaviour. It is intentionally isolated so the
changes can be reviewed and folded into webpage.py cleanly for the next release.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

import requests


PATCHED = False


def _safe_settings(original: Callable[[], dict[str, Any]], module: Any) -> dict[str, Any]:
    """Return a validated settings dictionary even when settings.json is malformed."""
    try:
        raw = original()
    except Exception as exc:  # defensive: settings must never take the site down
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
    """Wrap the existing feed reader with a last-known-good cache."""
    original = module.get_aircraft_data
    last_good: dict[str, Any] = {"aircraft": []}
    last_good_received: float | None = None

    def get_aircraft_data() -> tuple[dict[str, Any], float | None]:
        nonlocal last_good, last_good_received
        try:
            data, elapsed = original()
        except Exception as exc:
            module.logger.warning("Aircraft feed reader crashed: %s", exc)
            data, elapsed = {"aircraft": []}, None

        if elapsed is not None and isinstance(data, dict) and isinstance(data.get("aircraft"), list):
            last_good = data
            last_good_received = time.time()
            return data, elapsed

        if last_good.get("aircraft"):
            stale = dict(last_good)
            if last_good_received is not None and "now" not in stale:
                # The API's data-age display still needs the receiver timestamp when
                # readsb supplied one. Do not manufacture a receiver timestamp here.
                pass
            return stale, None

        return {"aircraft": []}, None

    return get_aircraft_data


def _patch_dashboard(module: Any) -> None:
    original_dashboard = module.dashboard_content
    original_feed = module.get_aircraft_data

    def dashboard_content() -> str:
        data, _ = module.get_aircraft_data()
        aircraft = data.get("aircraft", []) if isinstance(data, dict) else []
        html = original_dashboard()
        initial_json = json.dumps(aircraft, separators=(",", ":"), ensure_ascii=True).replace("</", "<\\/")

        # The original v0.0.5 dashboard started its browser state as an empty
        # list. That made every control appear broken after a failed first poll.
        html = html.replace("let aircraftData = [];", f"let aircraftData = {initial_json};", 1)

        # Treat HTTP 200 + feed_ok:false as a stale-feed state, rather than a
        # successful refresh. The API already returns the cached aircraft list.
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

        # Unknown altitude/speed must not disappear from the default view. The
        # minimum filters should only apply when the user actually entered one.
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

        # Keep this name in the module so the wrapper remains easy to inspect.
        module._planes_original_dashboard = original_dashboard
        return html

    module.dashboard_content = dashboard_content


def _add_unsaved_feed_test(module: Any) -> None:
    """Add a settings-page test endpoint that tests the URL currently typed by the user."""
    try:
        module.app.add_api_route(
            "/api/test-feed-url",
            _test_feed_url,
            methods=["GET"],
            response_class=module.JSONResponse,
        )
    except Exception as exc:
        module.logger.warning("Could not add unsaved feed test endpoint: %s", exc)


def _test_feed_url(url: str) -> dict[str, Any]:
    # Import lazily to keep this module harmless during normal app startup.
    import webpage

    clean_url = webpage.validate_data_url(url)
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


def apply_patches(module: Any) -> None:
    global PATCHED
    if PATCHED:
        return

    # Settings wrapper first, because page rendering calls it immediately.
    original_settings = module.load_settings
    module.load_settings = lambda: _safe_settings(original_settings, module)

    # Feed wrapper fixes stale-data loss across dashboard, statistics and details.
    module.get_aircraft_data = _make_feed_reader(module)
    _patch_dashboard(module)
    _patch_settings_page(module)
    _patch_detail(module)
    _add_unsaved_feed_test(module)

    PATCHED = True
    module.logger.info('Runtime reliability fixes enabled')
