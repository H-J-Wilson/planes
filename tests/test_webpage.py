import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webpage


class PlanesTests(unittest.TestCase):
    def setUp(self):
        self.original_settings_file = webpage.SETTINGS_FILE
        self.original_first_run_file = webpage.FIRST_RUN_FILE
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

    def tearDown(self):
        webpage.SETTINGS_FILE = self.original_settings_file
        webpage.FIRST_RUN_FILE = self.original_first_run_file
        webpage.LAST_GOOD_DATA = {"aircraft": []}
        webpage.LAST_GOOD_AVAILABLE = False

    def test_validate_data_url(self):
        self.assertEqual(
            webpage.validate_data_url(" http://127.0.0.1:8504/data/aircraft.json "),
            "http://127.0.0.1:8504/data/aircraft.json",
        )
        with self.assertRaises(ValueError):
            webpage.validate_data_url("ftp://example.com/feed.json")
        with self.assertRaises(ValueError):
            webpage.validate_data_url("http://user:password@example.com/feed.json")

    def test_load_settings_recovers_from_bad_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text("[bad shape]", encoding="utf-8")
            webpage.SETTINGS_FILE = settings_path
            settings = webpage.load_settings()
            self.assertEqual(settings["refresh_seconds"], 5)
            self.assertEqual(
                settings["aircraft_data_url"],
                webpage.DEFAULT_SETTINGS["aircraft_data_url"],
            )

    def test_valid_aircraft_identifier_accepts_readsb_non_icao_hex(self):
        self.assertTrue(webpage.valid_aircraft_identifier("abc123"))
        self.assertTrue(webpage.valid_aircraft_identifier("~3b8c8c"))
        self.assertFalse(webpage.valid_aircraft_identifier("abc12"))
        self.assertFalse(webpage.valid_aircraft_identifier("not-a-hex-id"))

    def test_aircraft_rows_escape_and_validate_links(self):
        rows = webpage.aircraft_rows([
            {
                "hex": "abc123",
                "flight": "<TEST>",
                "r": "G-TEST",
                "t": "A320",
                "gs": 420,
                "alt_baro": 12000,
            },
            {
                "hex": "not-valid",
                "flight": "BAD",
                "t": "Unknown",
            },
        ])
        self.assertIn("&lt;TEST&gt;", rows)
        self.assertIn("G-TEST", rows)
        self.assertIn("/aircraft/abc123", rows)
        self.assertNotIn("/aircraft/not-valid", rows)

        source_type_rows = webpage.aircraft_rows([{"hex": "abc123", "type": "adsb_icao"}])
        self.assertIn("Type unavailable", source_type_rows)
        self.assertNotIn(">adsb_icao<", source_type_rows)

        tilde_rows = webpage.aircraft_rows([{"hex": "~3b8c8c", "gs": 10}])
        self.assertIn("/aircraft/~3b8c8c", tilde_rows)

    def test_feed_keeps_last_successful_data_after_failure(self):
        webpage.load_settings = lambda: dict(webpage.DEFAULT_SETTINGS)

        success = Mock()
        success.raise_for_status.return_value = None
        success.json.return_value = {
            "now": 1234567890,
            "aircraft": [{"hex": "abc123", "flight": "TEST01"}],
        }

        with patch("webpage.requests.get", return_value=success):
            data, elapsed = webpage.get_aircraft_data()

        self.assertIsNotNone(elapsed)
        self.assertEqual(len(data["aircraft"]), 1)

        with patch(
            "webpage.requests.get",
            side_effect=requests.RequestException("receiver offline"),
        ):
            stale, stale_elapsed = webpage.get_aircraft_data()

        self.assertIsNone(stale_elapsed)
        self.assertEqual(stale["aircraft"][0]["hex"], "abc123")

    def test_feed_can_remember_a_successful_empty_feed(self):
        webpage.load_settings = lambda: dict(webpage.DEFAULT_SETTINGS)

        success = Mock()
        success.raise_for_status.return_value = None
        success.json.return_value = {"aircraft": []}

        with patch("webpage.requests.get", return_value=success):
            data, elapsed = webpage.get_aircraft_data()

        self.assertIsNotNone(elapsed)
        self.assertEqual(data["aircraft"], [])

        with patch(
            "webpage.requests.get",
            side_effect=requests.RequestException("receiver offline"),
        ):
            stale, stale_elapsed = webpage.get_aircraft_data()

        self.assertIsNone(stale_elapsed)
        self.assertEqual(stale["aircraft"], [])
        self.assertTrue(webpage.LAST_GOOD_AVAILABLE)

    def test_aircraft_metadata_lookup_uses_hex_and_cache(self):
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "response": {
                "aircraft": {
                    "registration": "G-TEST",
                    "type": "B738",
                    "icao_type": "B738",
                    "manufacturer": "Boeing",
                },
                "flightroute": {
                    "callsign": "TEST01",
                    "callsign_icao": "TEST01",
                },
            }
        }
        with patch("webpage.requests.get", return_value=response) as request:
            result = webpage.aircraft_metadata_lookup("abc123", "TEST01")
            cached = webpage.aircraft_metadata_lookup("abc123", "TEST01")
        self.assertEqual(result, cached)
        self.assertEqual(result["aircraft"]["type"], "B738")
        self.assertEqual(result["flightroute"]["callsign_icao"], "TEST01")
        self.assertEqual(request.call_count, 1)
        self.assertIn("/v0/aircraft/abc123?callsign=TEST01", request.call_args[0][0])

    def test_aircraft_metadata_endpoint_returns_json(self):
        sample = {"aircraft": [{"hex": "abc123", "flight": "TEST01"}]}
        webpage.load_settings = lambda: dict(webpage.DEFAULT_SETTINGS)
        with patch("webpage.get_aircraft_data", return_value=(sample, 0.01)), patch(
            "webpage.metadata_for_aircraft",
            return_value={
                "ok": True,
                "aircraft": {"registration": "G-TEST", "type": "B738"},
                "flightroute": {"callsign_icao": "TEST01"},
            },
        ):
            response = webpage.get_aircraft_metadata("abc123")
        self.assertEqual(response.status_code, 200)
        body = response.body.decode("utf-8")
        self.assertIn('"registration":"G-TEST"', body)
        self.assertIn('"type":"B738"', body)
        self.assertIn('"callsign_icao":"TEST01"', body)

    def test_detail_fragment_contains_live_telemetry_sections(self):
        sample = {
            "aircraft": [{
                "hex": "abc123",
                "flight": "TEST01",
                "gs": 250,
                "ias": 230,
                "tas": 270,
                "mach": 0.71,
                "alt_baro": 18000,
                "alt_geom": 19000,
                "track": 270,
                "baro_rate": -500,
                "lat": 51.0,
                "lon": -1.0,
                "r_dst": 40,
                "r_dir": 180,
                "squawk": "1234",
                "messages": 1000,
                "seen": 0.5,
                "rssi": -20,
            }]
        }
        webpage.load_settings = lambda: dict(webpage.DEFAULT_SETTINGS)
        with patch("webpage.get_aircraft_data", return_value=(sample, 0.01)), patch(
            "webpage.aircraft_metadata_lookup",
            return_value={},
        ):
            content = webpage.detail_fragment("abc123")
        for text in ("Aircraft identity", "Live flight data", "Navigation and transponder", "Receiver / signal data", "Ground speed", "Mach", "Squawk", "RSSI"):
            self.assertIn(text, content)

    def test_detail_fragment_uses_metadata_when_feed_is_missing_identity(self):
        sample = {"aircraft": [{"hex": "abc123", "gs": 250, "alt_baro": 18000}]}
        webpage.load_settings = lambda: dict(webpage.DEFAULT_SETTINGS)
        with patch("webpage.get_aircraft_data", return_value=(sample, 0.01)), patch(
            "webpage.aircraft_metadata_lookup",
            return_value={
                "aircraft": {"registration": "G-TEST", "type": "B738", "icao_type": "B738", "manufacturer": "Boeing"},
                "flightroute": {"callsign_icao": "TEST01", "callsign_iata": "T01"},
            },
        ):
            content = webpage.detail_fragment("abc123")
        self.assertIn("G-TEST", content)
        self.assertIn("B738", content)
        self.assertIn("TEST01", content)
        self.assertIn("Boeing", content)

    def test_statistics_page_contains_session_and_readsb_period_sections(self):
        sample = {"aircraft": [{"hex": "abc123", "gs": 300, "alt_baro": 12000, "lat": 51.0, "lon": -1.0}]}
        webpage.load_settings = lambda: dict(webpage.DEFAULT_SETTINGS)
        webpage.record_feed_success({"now": 1234, **sample})
        with patch("webpage.get_aircraft_data", return_value=(sample, 0.01)), patch(
            "webpage.get_readsb_stats",
            return_value={"total": {"start": 1000, "end": 1240, "messages": 123456, "tracks": {"all": 42}, "cpr": {"global_ok": 7}, "local": {"blocks_processed": 100, "blocks_dropped": 2, "signal": -12.3}}},
        ):
            content = webpage.read_statistics()
        self.assertIn("Live snapshot", content)
        self.assertIn("Since Planes started", content)
        self.assertIn("Since readsb started", content)
        self.assertIn("123,456", content)
        self.assertIn("42", content)

    def test_asbdb_negative_result_is_cached(self):
        webpage.load_settings = lambda: {
            **webpage.DEFAULT_SETTINGS,
            "asbdb_enabled": True,
            "asbdb_cache_seconds": 30,
        }

        response = Mock()
        response.status_code = 404

        with patch("webpage.requests.get", return_value=response) as request:
            self.assertIsNone(webpage.asbdb_lookup("TEST01"))
            self.assertIsNone(webpage.asbdb_lookup("TEST01"))
            self.assertEqual(request.call_count, 1)

    def test_invalid_aircraft_identifier_is_rejected(self):
        result = webpage.detail_fragment("not-hex")
        self.assertIn("Invalid aircraft identifier", result)

    def test_dashboard_contains_reliability_state(self):
        webpage.LAST_GOOD_AVAILABLE = True
        webpage.LAST_GOOD_DATA = {
            "aircraft": [{"hex": "abc123", "flight": "TEST01"}],
            "now": 1234567890,
        }
        webpage.load_settings = lambda: dict(webpage.DEFAULT_SETTINGS)
        with patch(
            "webpage.get_aircraft_data",
            return_value=(webpage.LAST_GOOD_DATA, None),
        ):
            content = webpage.dashboard_content()
        self.assertIn("Using last good data", content)
        self.assertIn("let aircraftData =", content)


    def test_aircraft_rows_fallback_to_receiver_alternate_fields(self):
        rows = webpage.aircraft_rows([
            {
                "hex": "abc123",
                "callsign": "TEST99",
                "registration": "G-TEST",
                "type": "B738",
                "gs": 250,
                "alt_baro": 18000,
            }
        ])
        self.assertIn("TEST99", rows)
        self.assertIn("G-TEST", rows)
        self.assertIn("B738", rows)

    def test_dashboard_html_contains_server_rendered_aircraft_row(self):
        sample = {
            "aircraft": [{
                "hex": "abc123",
                "flight": "TEST01",
                "r": "G-TEST",
                "t": "A320",
                "gs": 300,
                "alt_baro": 12000,
            }]
        }
        webpage.load_settings = lambda: dict(webpage.DEFAULT_SETTINGS)
        with patch("webpage.get_aircraft_data", return_value=(sample, 0.01)):
            content = webpage.dashboard_content()
        self.assertIn("data-aircraft-row", content)
        self.assertIn("TEST01", content)
        self.assertIn("A320", content)
        self.assertIn("G-TEST", content)
        self.assertIn("let aircraftData =", content)

    def test_setup_content_contains_first_run_options(self):
        content = webpage.setup_content()
        self.assertIn("FIRST-RUN SETUP", content)
        self.assertIn("Aircraft data URL", content)
        self.assertIn("Base theme", content)
        self.assertIn("Refresh interval", content)
        self.assertIn("Test feed", content)
        self.assertIn("Save and open Planes", content)

    def test_setup_marker_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / ".planes_setup_complete"
            webpage.FIRST_RUN_FILE = marker
            self.assertFalse(webpage.setup_complete())
            webpage.mark_setup_complete()
            self.assertTrue(webpage.setup_complete())

    def test_invalid_detail_api_returns_400(self):
        response = webpage.get_aircraft_details_fragment("not-a-hex-id", webpage.Response())
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid aircraft identifier", response.body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
