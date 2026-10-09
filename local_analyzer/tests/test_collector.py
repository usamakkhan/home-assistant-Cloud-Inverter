from __future__ import annotations

from datetime import datetime, timezone
import unittest

from solarmax_analyzer.collector import CollectorController, CollectorUnavailable


class CollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 100.0
        self.events = []
        self.errors = []

        def capture(host, unit_id):
            return {
                "ok": True,
                "host": host,
                "unit_id": unit_id,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "sensors": {},
            }

        self.controller = CollectorController(
            capture,
            lambda snapshot, source: self.events.append((source, snapshot)) or {},
            lambda source, error, details: self.errors.append((source, error, details)) or {},
            "192.168.50.10",
            clock=lambda: self.now,
            monotonic=lambda: self.now,
        )

    def test_original_mode_blocks_all_device_access(self):
        self.assertTrue(self.controller.status()["original_path_active"])
        with self.assertRaises(CollectorUnavailable):
            self.controller.capture_now()
        with self.assertRaises(CollectorUnavailable):
            self.controller.ensure_maintenance()

    def test_cooperative_mode_needs_confirmation_and_honors_quiet_window(self):
        with self.assertRaises(ValueError):
            self.controller.set_mode("cooperative")
        self.controller.set_mode("cooperative", confirmed=True)
        self.now = 290.0
        with self.assertRaisesRegex(CollectorUnavailable, "quiet window"):
            self.controller.capture_now()
        self.now = 100.0
        snapshot = self.controller.capture_now()
        self.assertTrue(snapshot["ok"])
        self.assertEqual(self.events[0][0], "manual_live")

    def test_original_button_clears_active_polling(self):
        self.controller.set_mode("cooperative", confirmed=True)
        state = self.controller.set_mode("original")
        self.assertEqual(state["mode"], "original")
        self.assertFalse(state["background_polling"])

    def test_local_mode_requires_confirmation_and_ignores_cloud_quiet_window(self):
        self.now = 290.0
        with self.assertRaises(ValueError):
            self.controller.set_mode("local")
        state = self.controller.set_mode("local", confirmed=True, interval_seconds=120)
        self.assertTrue(state["background_polling"])
        self.assertFalse(state["quiet_windows_enabled"])
        self.assertFalse(state["in_cloud_quiet_window"])
        self.assertEqual(state["interval_seconds"], 120)
        self.assertTrue(self.controller.capture_now()["ok"])
        with self.assertRaises(CollectorUnavailable):
            self.controller.ensure_maintenance()

    def test_local_background_loop_captures_during_cloud_window(self):
        self.now = 290.0
        original_capture = self.controller._capture
        def once(host, unit):
            self.controller._stop.set()
            return original_capture(host, unit)
        self.controller._capture = once
        self.controller.set_mode("local", confirmed=True)
        self.controller._run()
        self.assertEqual(self.events[0][0], "local")
        self.assertEqual(self.controller.status()["quiet_skips"], 0)
        self.assertEqual(self.controller.status()["next_capture_seconds"], 180)

    def test_ten_second_cadence_is_anchored_to_capture_start(self):
        original_capture = self.controller._capture
        def four_second_capture(host, unit):
            result = original_capture(host, unit)
            self.now += 4
            self.controller._stop.set()
            return result
        self.controller._capture = four_second_capture
        self.controller.set_mode("local", confirmed=True, interval_seconds=10)
        self.controller._run()
        self.assertEqual(self.controller._next_due_monotonic, 110)
        self.assertEqual(self.controller.status()["next_capture_seconds"], 6)
        self.assertEqual(self.controller.status()["cadence_overruns"], 0)

    def test_slow_capture_skips_missed_deadline_without_overlap(self):
        original_capture = self.controller._capture
        def twelve_second_capture(host, unit):
            result = original_capture(host, unit)
            self.now += 12
            self.controller._stop.set()
            return result
        self.controller._capture = twelve_second_capture
        self.controller.set_mode("local", confirmed=True, interval_seconds=10)
        self.controller._run()
        self.assertEqual(self.controller._next_due_monotonic, 120)
        self.assertEqual(self.controller.status()["next_capture_seconds"], 8)
        self.assertEqual(self.controller.status()["cadence_overruns"], 1)

    def test_restore_cancels_queued_local_work_before_device_access(self):
        self.controller.set_mode("local", confirmed=True)
        generation = self.controller._generation
        self.controller.set_mode("original")
        with self.assertRaises(CollectorUnavailable):
            self.controller._perform_capture("192.168.50.10", 1, "local", generation)
        self.assertEqual(self.events, [])
        self.assertEqual(self.errors, [])
        self.assertIsNone(self.controller.status()["next_capture_seconds"])

    def test_local_failures_fall_back_but_old_failures_do_not_reset_new_mode(self):
        def broken(*_):
            raise TimeoutError("bridge busy")
        self.controller._capture = broken
        self.controller.set_mode("local", confirmed=True)
        for _ in range(2):
            with self.assertRaises(TimeoutError): self.controller.capture_now()
        self.assertEqual(self.controller.status()["mode"], "original")
        self.controller.set_mode("local", confirmed=True)
        def changed(*_):
            self.controller.set_mode("original")
            self.controller.set_mode("cooperative", confirmed=True)
            raise TimeoutError("old request failed")
        self.controller._capture = changed
        with self.assertRaises(TimeoutError): self.controller.capture_now()
        self.assertEqual(self.controller.status()["mode"], "cooperative")
        self.assertEqual(self.controller.status()["consecutive_failures"], 0)

    def test_local_interval_stays_bounded(self):
        for interval in (0, 9, 901):
            with self.assertRaises(ValueError): self.controller.set_mode("local", confirmed=True, interval_seconds=interval)
        self.assertEqual(self.controller.status()["mode"], "original")

    def test_temporary_settings_read_works_in_local_but_not_original(self):
        with self.assertRaisesRegex(CollectorUnavailable, "cloud-only"):
            with self.controller.temporary_read_session():
                pass
        self.controller.set_mode("local", confirmed=True, interval_seconds=10)
        with self.controller.temporary_read_session() as (host, unit, generation):
            self.assertEqual((host, unit), ("192.168.50.10", 1))
            self.controller.ensure_read_session(generation)
            self.assertTrue(self.controller.status()["manual_read_active"])
        state = self.controller.status()
        self.assertFalse(state["manual_read_active"])
        self.assertEqual(state["next_capture_seconds"], 0)

    def test_cooperative_settings_read_honors_quiet_window(self):
        self.controller.set_mode("cooperative", confirmed=True)
        self.now = 290
        with self.assertRaisesRegex(CollectorUnavailable, "quiet window"):
            with self.controller.temporary_read_session():
                pass

    def test_repeated_failures_fall_back_to_original(self):
        def broken_capture(_host, _unit):
            raise TimeoutError("bridge busy")

        controller = CollectorController(
            broken_capture,
            lambda *_args, **_kwargs: {},
            lambda *_args, **_kwargs: {},
            "192.168.50.10",
            clock=lambda: 100.0,
            monotonic=lambda: 100.0,
        )
        controller.set_mode("cooperative", confirmed=True)
        for _ in range(2):
            with self.assertRaises(TimeoutError):
                controller.capture_now()
        state = controller.status()
        self.assertEqual(state["mode"], "original")
        self.assertIn("Automatic fallback", state["fallback_reason"])


if __name__ == "__main__":
    unittest.main()
