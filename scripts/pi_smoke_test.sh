#!/usr/bin/env bash
set -u

# Safe Raspberry Pi smoke test for Planes.
# It never stops/restarts services and never edits settings.json.

PLANES_URL="${PLANES_URL:-http://127.0.0.1:8000}"
FEED_URL="${FEED_URL:-http://127.0.0.1:8504/data/aircraft.json}"
PYTHON="${PYTHON:-python3}"
if [ -x "venv/bin/python" ]; then
  PYTHON="venv/bin/python"
fi

PASS=0
WARN=0
FAIL=0
PLANES_RUNNING=false
AIRCRAFT_COUNT=0

pass() { printf 'PASS  %s\n' "$1"; PASS=$((PASS + 1)); }
warn() { printf 'WARN  %s\n' "$1"; WARN=$((WARN + 1)); }
fail() { printf 'FAIL  %s\n' "$1"; FAIL=$((FAIL + 1)); }

http_get() {
  curl -fsS --max-time 5 "$1"
}

http_code() {
  curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "$1" 2>/dev/null
}

echo
echo "=== Planes Raspberry Pi smoke test ==="
echo "Planes: $PLANES_URL"
echo "Feed:   $FEED_URL"
echo

command -v curl >/dev/null 2>&1 && pass "curl is installed" || fail "curl is not installed"
command -v "$PYTHON" >/dev/null 2>&1 && pass "Python is available ($PYTHON)" || fail "Python is not available"

if [ -f "main.py" ] && [ -f "webpage.py" ]; then
  pass "Planes source files found"
else
  fail "Run this test from the Planes project directory"
fi

[ -d "venv" ] && pass "Python virtual environment exists" || warn "venv directory not found"

if "$PYTHON" - <<'PY'
import fastapi
import requests
import uvicorn
print("imports-ok")
PY
then
  pass "FastAPI, requests and Uvicorn import successfully"
else
  fail "Python dependencies could not be imported"
fi

if "$PYTHON" -m py_compile main.py webpage.py >/dev/null 2>&1; then
  pass "main.py and webpage.py compile"
else
  fail "Python syntax/compile check failed"
fi

if command -v bash >/dev/null 2>&1 && bash -n scripts/pi_smoke_test.sh; then
  pass "Pi smoke-test script syntax is valid"
else
  fail "Pi smoke-test script syntax check failed"
fi

if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet readsb; then
    pass "readsb service is active"
  else
    fail "readsb service is not active"
  fi
else
  warn "systemctl not available; skipped readsb service check"
fi

FEED_TMP="$(mktemp)"
if http_get "$FEED_URL" >"$FEED_TMP"; then
  if "$PYTHON" - "$FEED_TMP" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)

if not isinstance(data, dict):
    raise SystemExit("feed is not a JSON object")
if not isinstance(data.get("aircraft"), list):
    raise SystemExit("feed has no aircraft list")
print(len(data["aircraft"]))
PY
  then
    AIRCRAFT_COUNT="$("$PYTHON" - "$FEED_TMP" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as f:
    print(len(json.load(f).get("aircraft", [])))
PY
)"
    pass "aircraft JSON feed is valid ($AIRCRAFT_COUNT aircraft)"
    if [ "$AIRCRAFT_COUNT" -eq 0 ]; then
      warn "aircraft feed is valid but currently contains zero aircraft"
    fi
  else
    fail "aircraft JSON feed is not in the expected format"
  fi
else
  fail "could not reach $FEED_URL"
fi
rm -f "$FEED_TMP"

ROOT_TMP="$(mktemp)"
if ROOT_CODE="$(curl -sS -o "$ROOT_TMP" -w '%{http_code}' --max-time 5 "$PLANES_URL/" 2>/dev/null)"; then
  if [ "$ROOT_CODE" = "200" ]; then
    PLANES_RUNNING=true
    pass "Planes server returns HTTP 200"
    if grep -q "FIRST-RUN SETUP" "$ROOT_TMP"; then
      warn "first-run setup has not been completed yet"
    else
      ROW_COUNT="$(grep -o 'data-aircraft-row' "$ROOT_TMP" | wc -l | tr -d ' ')"
      # The browser render template also contains the marker once, so subtract that copy.
      if [ "$ROW_COUNT" -gt 0 ]; then ROW_COUNT=$((ROW_COUNT - 1)); fi
      if [ "$AIRCRAFT_COUNT" -gt 0 ] && [ "$ROW_COUNT" -eq 0 ]; then
        fail "Dashboard HTML contains no aircraft rows even though the feed contains $AIRCRAFT_COUNT aircraft"
      elif [ "$ROW_COUNT" -gt 0 ]; then
        pass "Dashboard HTML contains $ROW_COUNT aircraft rows"
      else
        warn "Dashboard currently has no aircraft rows"
      fi
    fi
  else
    fail "Planes server returned HTTP $ROOT_CODE"
  fi
else
  fail "Planes is not reachable at $PLANES_URL (start it with: python main.py)"
fi
rm -f "$ROOT_TMP"

if [ "$PLANES_RUNNING" = true ]; then
  for path in /statistics /settings /documentation /about /contact /setup /static/output.css; do
    if code="$(http_code "$PLANES_URL$path")"; then
      if [ "$code" = "200" ]; then
        pass "$path returns HTTP 200"
      else
        fail "$path returned HTTP $code"
      fi
    else
      fail "$path could not be reached"
    fi
  done

  STATS_HTML_TMP="$(mktemp)"
  if curl -fsS --max-time 5 "$PLANES_URL/statistics" >"$STATS_HTML_TMP"; then
    if grep -q "Since Planes started" "$STATS_HTML_TMP" && grep -q "Since readsb started" "$STATS_HTML_TMP"; then
      pass "Statistics page contains live and running-period sections"
    else
      fail "Statistics page is missing the new period sections"
    fi
  else
    fail "Statistics page could not be read"
  fi
  rm -f "$STATS_HTML_TMP"


  DASH_TMP="$(mktemp)"
  if DASH_CODE="$(curl -sS -o "$DASH_TMP" -w '%{http_code}' --max-time 5 "$PLANES_URL/api/dashboard-data" 2>/dev/null)"; then
    if [ "$DASH_CODE" = "200" ]; then
      if "$PYTHON" - "$DASH_TMP" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
if not isinstance(data, dict):
    raise SystemExit("dashboard API did not return an object")
if not isinstance(data.get("aircraft"), list):
    raise SystemExit("dashboard API has no aircraft list")
if "feed_ok" not in data:
    raise SystemExit("dashboard API has no feed_ok field")
PY
      then
        FEED_OK="$("$PYTHON" - "$DASH_TMP" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as f:
    print(json.load(f).get("feed_ok"))
PY
)"
        if [ "$FEED_OK" = "True" ]; then
          pass "/api/dashboard-data is valid and feed_ok=true"
        else
          warn "/api/dashboard-data is valid but feed_ok is not true"
        fi
      else
        fail "/api/dashboard-data returned invalid JSON structure"
      fi
    else
      fail "/api/dashboard-data returned HTTP $DASH_CODE"
    fi
  else
    fail "/api/dashboard-data could not be reached"
  fi
  rm -f "$DASH_TMP"

  DETAIL_FEED_TMP="$(mktemp)"
  if http_get "$FEED_URL" >"$DETAIL_FEED_TMP"; then
    DETAIL_HEX="$("$PYTHON" - "$DETAIL_FEED_TMP" <<'PY'
import json
import re
import sys
with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
for aircraft in data.get("aircraft", []):
    value = str(aircraft.get("hex", "")).strip().lower()
    if re.fullmatch(r"~?[0-9a-f]{6}", value):
        print(value)
        break
PY
)"
  else
    DETAIL_HEX=""
  fi
  rm -f "$DETAIL_FEED_TMP"
  if [ -n "$DETAIL_HEX" ]; then
    DETAIL_CODE="$(http_code "$PLANES_URL/api/aircraft/$DETAIL_HEX")"
    if [ "$DETAIL_CODE" = "200" ]; then
      pass "valid aircraft detail endpoint returns HTTP 200 ($DETAIL_HEX)"
    else
      fail "valid aircraft detail endpoint returned HTTP $DETAIL_CODE ($DETAIL_HEX)"
    fi
    META_CODE="$(http_code "$PLANES_URL/api/aircraft-metadata/$DETAIL_HEX")"
    if [ "$META_CODE" = "200" ]; then
      pass "aircraft metadata endpoint returns HTTP 200 ($DETAIL_HEX)"
    else
      fail "aircraft metadata endpoint returned HTTP $META_CODE ($DETAIL_HEX)"
    fi
  else
    warn "no valid aircraft HEX available for detail/metadata endpoint test"
  fi

  TEST_TMP="$(mktemp)"
  if TEST_CODE="$(curl -sS -o "$TEST_TMP" -w '%{http_code}' --max-time 5 "$PLANES_URL/api/test-feed" 2>/dev/null)"; then
    if [ "$TEST_CODE" = "200" ]; then
      if "$PYTHON" - "$TEST_TMP" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
if data.get("ok") is not True:
    raise SystemExit("test-feed did not report ok=true")
if not isinstance(data.get("aircraft_count"), int):
    raise SystemExit("test-feed returned an invalid aircraft_count")
PY
      then
        pass "/api/test-feed reports the configured feed is working"
      else
        fail "/api/test-feed returned an unexpected response"
      fi
    else
      fail "/api/test-feed returned HTTP $TEST_CODE"
    fi
  else
    fail "/api/test-feed could not be reached"
  fi
  rm -f "$TEST_TMP"

  ENCODED_FEED="$("$PYTHON" - "$FEED_URL" <<'PY'
from urllib.parse import quote
import sys
print(quote(sys.argv[1], safe=""))
PY
)"
  UNSAVED_TMP="$(mktemp)"
  if UNSAVED_CODE="$(curl -sS -o "$UNSAVED_TMP" -w '%{http_code}' --max-time 5 "$PLANES_URL/api/test-feed-url?url=$ENCODED_FEED" 2>/dev/null)"; then
    if [ "$UNSAVED_CODE" = "200" ]; then
      if "$PYTHON" - "$UNSAVED_TMP" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
if data.get("ok") is not True:
    raise SystemExit("unsaved feed test did not report ok=true")
PY
      then
        pass "/api/test-feed-url accepts the current feed URL"
      else
        fail "/api/test-feed-url returned an unexpected response"
      fi
    else
      fail "/api/test-feed-url returned HTTP $UNSAVED_CODE"
    fi
  else
    fail "/api/test-feed-url could not be reached"
  fi
  rm -f "$UNSAVED_TMP"

  BAD_TMP="$(mktemp)"
  if BAD_CODE="$(curl -sS -o "$BAD_TMP" -w '%{http_code}' --max-time 5 "$PLANES_URL/api/test-feed-url?url=ftp%3A%2F%2Fexample.com%2Ffeed.json" 2>/dev/null)"; then
    if [ "$BAD_CODE" = "400" ]; then
      pass "invalid feed URL is rejected"
    else
      fail "invalid feed URL returned HTTP $BAD_CODE instead of 400"
    fi
  else
    fail "invalid feed URL test could not reach Planes"
  fi
  rm -f "$BAD_TMP"

  STATS_URL="$("$PYTHON" - "$FEED_URL" <<'PY'
from urllib.parse import urljoin
import sys
print(urljoin(sys.argv[1], "stats.json"))
PY
)"
  STATS_CODE="$(http_code "$STATS_URL")"
  if [ "$STATS_CODE" = "200" ]; then
    pass "readsb stats.json is available"
  else
    warn "readsb stats.json returned HTTP $STATS_CODE"
  fi

  BAD_AIRCRAFT_CODE="$(http_code "$PLANES_URL/api/aircraft/not-a-hex-id")"
  if [ "$BAD_AIRCRAFT_CODE" = "400" ]; then
    pass "invalid aircraft identifier is rejected"
  else
    fail "invalid aircraft identifier returned HTTP $BAD_AIRCRAFT_CODE"
  fi
fi

echo
echo "=== Results ==="
echo "PASS: $PASS"
echo "WARN: $WARN"
echo "FAIL: $FAIL"
echo

if [ "$FAIL" -gt 0 ]; then
  echo "Result: FAILED"
  exit 1
elif [ "$WARN" -gt 0 ]; then
  echo "Result: PASSED WITH WARNINGS"
  exit 0
else
  echo "Result: PASSED"
  exit 0
fi
