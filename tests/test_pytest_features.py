import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webpage


@pytest.fixture(autouse=True)
def reset_app_state(tmp_path, monkeypatch):
    monkeypatch.setattr(webpage, "SETTINGS_FILE", Path(tmp_path) / "settings.json")
    monkeypatch.setattr(webpage, "FIRST_RUN_FILE", Path(tmp_path) / ".planes_setup_complete")
    webpage.LAST_GOOD_DATA = {"aircraft": []}
    webpage.LAST_GOOD_AVAILABLE = False
    webpage._aircraft_metadata_cache = {}
    webpage.PLANES_SESSION_LAST_SNAPSHOT = None
    webpage.PLANES_SESSION_SAMPLES = 0
    webpage.PLANES_SESSION_AIRCRAFT_TOTAL = 0
    webpage.PLANES_SESSION_PEAK_AIRCRAFT = 0
    webpage.PLANES_SESSION_UNIQUE_HEX = set()
    webpage.PLANES_SESSION_HIGHEST_ALTITUDE = None
    webpage.PLANES_SESSION_FASTEST_SPEED = None
    webpage.PLANES_SESSION_FEED_UP = False
    webpage.PLANES_SESSION_FEED_INTERRUPTS = 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [("5", "5s"), ("65", "1m 5s"), ("3665", "1h 1m"), ("90061", "1d 1h 1m"), (None, "—")],
)
def test_format_duration(value, expected):
    assert webpage.format_duration(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0"), (1234567, "1,234,567"), (12.3, "12.3"), ("abc", "abc")],
)
def test_format_number(value, expected):
    assert webpage.format_number(value) == expected


def test_clean_escapes_markup():
    assert webpage.clean("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"


@pytest.mark.parametrize("identifier", ["4cad7d", "000001", "~3b8c8c", "~ffffff"])
def test_valid_identifiers(identifier):
    assert webpage.valid_aircraft_identifier(identifier)


@pytest.mark.parametrize("identifier", ["", "12345", "gggggg", "4cad7d8", "not-a-hex-id"])
def test_invalid_identifiers(identifier):
    assert not webpage.valid_aircraft_identifier(identifier)


def test_aircraft_rows_do_not_treat_message_source_as_aircraft_model():
    rows = webpage.aircraft_rows([{"hex": "4cad7d", "type": "adsb_icao", "gs": 390.3, "alt_baro": 30650}])
    assert "adsb_icao" not in rows
    assert "Type unavailable" in rows


def test_aircraft_rows_use_receiver_metadata_when_present():
    rows = webpage.aircraft_rows([{
        "hex": "4cad7d", "flight": "TEST123", "r": "G-TEST", "t": "A320",
        "gs": 390.3, "alt_baro": 30650,
    }])
    assert "TEST123" in rows
    assert "G-TEST" in rows
    assert "A320" in rows
    assert "/aircraft/4cad7d" in rows


def test_aircraft_rows_support_non_icao_ids():
    rows = webpage.aircraft_rows([{"hex": "~3b8c8c", "gs": 200}])
    assert "/aircraft/~3b8c8c" in rows
    assert "ICAO 3B8C8C" in rows


def test_metadata_lookup_caches_per_hex_and_callsign(monkeypatch):
    response = Mock(status_code=200)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "response": {
            "aircraft": {"registration": "G-TEST", "type": "B738", "icao_type": "B738", "manufacturer": "Boeing"},
            "flightroute": {"callsign_icao": "TEST01", "callsign_iata": "T01"},
        }
    }
    request = Mock(return_value=response)
    monkeypatch.setattr(webpage.requests, "get", request)
    first = webpage.aircraft_metadata_lookup("4cad7d", "TEST01")
    second = webpage.aircraft_metadata_lookup("4cad7d", "TEST01")
    assert first == second
    assert first["aircraft"]["type"] == "B738"
    assert first["flightroute"]["callsign_icao"] == "TEST01"
    assert request.call_count == 1


def test_metadata_404_is_cached(monkeypatch):
    response = Mock(status_code=404)
    request = Mock(return_value=response)
    monkeypatch.setattr(webpage.requests, "get", request)
    assert webpage.aircraft_metadata_lookup("4cad7d") is None
    assert webpage.aircraft_metadata_lookup("4cad7d") is None
    assert request.call_count == 1


def test_metadata_endpoint_uses_current_callsign(monkeypatch):
    monkeypatch.setattr(webpage, "get_aircraft_data", lambda: ({"aircraft": [{"hex": "4cad7d", "flight": "TEST123"}]}, 0.01))
    lookup = Mock(return_value={
        "ok": True,
        "aircraft": {"registration": "G-TEST", "type": "A320"},
        "flightroute": {"callsign_icao": "TEST123"},
    })
    monkeypatch.setattr(webpage, "metadata_for_aircraft", lookup)
    response = webpage.get_aircraft_metadata("4cad7d")
    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["aircraft"]["registration"] == "G-TEST"
    lookup.assert_called_once_with("4cad7d", "TEST123")


def test_dashboard_contains_metadata_enrichment_hook(monkeypatch):
    sample = {"aircraft": [{"hex": "4cad7d", "gs": 390.3, "alt_baro": 30650}]}
    monkeypatch.setattr(webpage, "get_aircraft_data", lambda: (sample, 0.01))
    html = webpage.dashboard_content()
    assert "aircraft-metadata/" in html
    assert "enrichVisibleAircraft" in html
    assert "Looking up" in html


def test_dashboard_handles_missing_type_without_using_source_type(monkeypatch):
    sample = {"aircraft": [{"hex": "4cad7d", "type": "adsb_icao", "gs": 390.3, "alt_baro": 30650}]}
    monkeypatch.setattr(webpage, "get_aircraft_data", lambda: (sample, 0.01))
    rows = webpage.aircraft_rows(sample["aircraft"])
    html = webpage.dashboard_content()
    assert "adsb_icao" not in rows
    assert "Looking up" in html


def test_record_feed_success_collects_session_metrics():
    webpage.record_feed_success({"now": 1000, "aircraft": [
        {"hex": "4cad7d", "alt_baro": 30000, "gs": 400},
        {"hex": "3c6566", "alt_baro": 28000, "gs": 350},
    ]})
    assert webpage.PLANES_SESSION_SAMPLES == 1
    assert webpage.PLANES_SESSION_AIRCRAFT_TOTAL == 2
    assert webpage.PLANES_SESSION_PEAK_AIRCRAFT == 2
    assert webpage.PLANES_SESSION_UNIQUE_HEX == {"4cad7d", "3c6566"}
    assert webpage.PLANES_SESSION_HIGHEST_ALTITUDE == 30000
    assert webpage.PLANES_SESSION_FASTEST_SPEED == 400


def test_record_feed_success_does_not_double_count_same_snapshot():
    sample = {"now": 1000, "aircraft": [{"hex": "4cad7d"}]}
    webpage.record_feed_success(sample)
    webpage.record_feed_success(sample)
    assert webpage.PLANES_SESSION_SAMPLES == 1
    assert webpage.PLANES_SESSION_AIRCRAFT_TOTAL == 1


def test_feed_failure_counts_transition():
    webpage.record_feed_success({"now": 1000, "aircraft": [{"hex": "4cad7d"}]})
    webpage.record_feed_failure()
    assert webpage.PLANES_SESSION_FEED_INTERRUPTS == 1
    webpage.record_feed_failure()
    assert webpage.PLANES_SESSION_FEED_INTERRUPTS == 1


def test_statistics_contains_all_three_periods(monkeypatch):
    sample = {"aircraft": [{"hex": "4cad7d", "gs": 400, "alt_baro": 30000, "lat": 51.0, "lon": -1.0}]}
    monkeypatch.setattr(webpage, "get_aircraft_data", lambda: (sample, 0.01))
    monkeypatch.setattr(webpage, "get_readsb_stats", lambda: {
        "total": {
            "start": 1000, "end": 2000, "messages": 1234,
            "tracks": {"all": 42}, "cpr": {"global_ok": 10},
            "local": {"blocks_processed": 100, "blocks_dropped": 2, "signal": -12.5},
        },
        "last15min": {"messages": 123},
    })
    webpage.record_feed_success({"now": 1500, **sample})
    html = webpage.read_statistics()
    assert "Live snapshot" in html
    assert "Since Planes started" in html
    assert "Since readsb started" in html
    assert "Messages accepted" in html
    assert "Tracks created" in html
    assert "15 min messages" in html


def test_setup_marker_round_trip(tmp_path):
    webpage.FIRST_RUN_FILE = tmp_path / ".planes_setup_complete"
    assert not webpage.setup_complete()
    webpage.mark_setup_complete()
    assert webpage.setup_complete()


def test_setup_content_contains_core_choices():
    html = webpage.setup_content()
    for text in ("FIRST-RUN SETUP", "Aircraft data URL", "Refresh interval", "Base theme", "Test feed"):
        assert text in html


def test_settings_reject_credentials_in_feed_url():
    with pytest.raises(ValueError):
        webpage.validate_data_url("http://user:password@example.com/feed.json")


def test_settings_accept_normal_https_url():
    assert webpage.validate_data_url("https://example.com/aircraft.json") == "https://example.com/aircraft.json"
