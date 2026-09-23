#!/usr/bin/env bash
set -u

# Planes Raspberry Pi smoke test
# Safe by design: it does not stop/restart readsb or Planes and does not edit
# settings.json. Run it on the Pi from the Planes project directory.

PLANES_URL="${PLANES_URL:-http://127.0.0.1:8000}"
FEED_URL="${FEED_URL:-http://127.0.0.1:8504/data/aircraft.json}"

PASS=0
WARN=0
FAIL=0

pass() {
  printf 'PASS  %s\n' "$1"
  PASS=$((PASS + 1))
}

warn() {
  printf 'WARN  %s\n' "$1"
  WARN=$((WARN + 1))
}

fail() {
  printf 'FAIL  %s\n' "$1"
  FAIL=$((FAIL + 1))
}

check_command() {
  command -v "$1" >/dev/null 2>&1
}

http_code() {
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "$1" 2>/dev/null)" || return 1
  printf '%s' "$code"
}

echo
echo "=== Planes Raspberry Pi smoke test ==="
echo "Planes: $PLANES_URL"
echo "Feed:   $FEED_URL"
echo

# Basic tools
if check_command curl; then
  pass "curl is installed"
else
  fail "curl is not installed"
fi

if check_command python3; then
  pass "python3 is installed"
else
  fail "python3 is not installed"
fi

# Project files
if [ -f "main.py" ] && [ -f "webpage.py" ]; then
  pass "Planes source files found"
else
  fail "Run this script from the Planes project directory"
fi

if [ -d "venv" ]; then
  pass "Python virtual environment exists"
else
  warn "venv directory not found"
fi

# Python dependency/import check
if python3 - <<'PY'
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

# Python syntax
if python3 -m py_compile main.py webpage.py >/dev/null 2>&1; then
  pass "main.py and webpage.py compile"
else
  fail "Python syntax/compile check failed"
fi

# readsb service
if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet readsb; then
    pass "readsb service is active"
  else
    fail "readsb service is not active"
  fi
else
  warn "systemctl not available; skipped readsb service check"
fi

# Live aircraft feed
FEED_TMP="$(mktemp)"
if curl -fsS --max-time 5 "$FEED_URL" -o "$FEED_TMP"; then
  if python3 - "$FEED_TMP" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)

if not isinstance(data, dict):
    raise SystemExit("feed is not a JSON object")
if not isinstance(data.get("aircraft"), list):
    raise SystemExit("feed has no aircraft list")

print(len(data["aircraft"]))
PY
  then
    AIRCRAFT_COUNT="$(python3 - "$FEED_TMP" <<'PY'
import json
import sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    print(len(json.load(f).get("aircraft", [])))
PY
)"
    pass "aircraft JSON feed is valid ($AIRCRAFT_COUNT aircraft)"
  else
    fail "aircraft JSON feed is not in the expected format"
  fi
else
  fail "could not reach $FEED_URL"
fi
rm -f "$FEED_TMP"

# Planes HTTP server
if ROOT_CODE="$(http_code "$PLANES_URL/")"; then
  if [ "$ROOT_CODE" = "200" ]; then
    pass "Planes dashboard returns HTTP 200"
  else
    fail "Planes dashboard returned HTTP $ROOT_CODE"
  fi
else
  fail "Planes is not reachable at $PLANES_URL (is python main.py running?)"
  echo "INFO  Start Planes with: python main.py"
  PLANES_RUNNING=false
fi

PLANES_RUNNING=${PLANES_RUNNING:-true}

# Main HTML pages
if [ "$PLANES_RUNNING" = true ]; then
  for path in /statistics /settings /documentation /about /contact; do
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
fi

# Dashboard API
if [ "$PLANES_RUNNING" = true ]; then
DASH_TMP="$(mktemp)"
if DASH_CODE="$(curl -sS -o "$DASH_TMP" -w '%{http_code}' --max-time 5 "$PLANES_URL/api/dashboard-data" 2>/dev/null)"; then
if [ "$DASH_CODE" = "200" ]; then
  if python3 - "$DASH_TMP" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)

if not isinstance(data, dict):
    raise SystemExit("dashboard API did not return an object")
if not isinstance(data.get("aircraft"), list):
    raise SystemExit("dashboard API has no aircraft list")
if "feed_ok" not in data:
    raise SystemExit("dashboard API has no feed_ok field")
PY
  then
    FEED_OK="$(python3 - "$DASH_TMP" <<'PY'
import json
import sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
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
fi

# Saved feed test
if [ "$PLANES_RUNNING" = true ]; then
TEST_TMP="$(mktemp)"
if TEST_CODE="$(curl -sS -o "$TEST_TMP" -w '%{http_code}' --max-time 5 "$PLANES_URL/api/test-feed" 2>/dev/null)"; then
if [ "$TEST_CODE" = "200" ]; then
  if python3 - "$TEST_TMP" <<'PY'
import json
import sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
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
fi

# Unsaved feed URL test
if [ "$PLANES_RUNNING" = true ]; then
ENCODED_FEED="$(python3 - "$FEED_URL" <<'PY'
from urllib.parse import quote
import sys
print(quote(sys.argv[1], safe=""))
PY
)"
UNSAVED_TMP="$(mktemp)"
UNSAVED_CODE="$(curl -sS -o "$UNSAVED_TMP" -w '%{http_code}' --max-time 5 "$PLANES_URL/api/test-feed-url?url=$ENCODED_FEED" 2>/dev/null || printf '000')"
if [ "$UNSAVED_CODE" = "200" ]; then
  if python3 - "$UNSAVED_TMP" <<'PY'
import json
import sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
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
