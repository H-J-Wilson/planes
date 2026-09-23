import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import webpage


class PlanesTests(unittest.TestCase):
    def setUp(self):
        self.original_settings_file = webpage.SETTINGS_FILE
        self.original_first_run_file = webpage.FIRST_RUN_FILE
        webpage.LAST_GOOD_DATA = {"aircraft": []}
        webpage.LAST_GOOD_AVAILABLE = False

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
