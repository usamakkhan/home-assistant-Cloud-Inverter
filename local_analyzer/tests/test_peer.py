from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from solarmax_analyzer.peer import (
    DEFAULT_NEIGHBOR_SYSTEM,
    PRIMARY_SYSTEM,
    align_history,
    build_neighbor_snapshot,
    canonical_latest,
    comparison_payload,
    point_metrics,
)


class PeerComparisonTests(unittest.TestCase):
    def test_installed_capacity_and_normalized_equality(self) -> None:
        self.assertEqual(PRIMARY_SYSTEM.dc_nameplate_watts, 7020)
        self.assertEqual(DEFAULT_NEIGHBOR_SYSTEM.dc_nameplate_watts, 5850)
        mine = point_metrics({"pv_power": 7020}, PRIMARY_SYSTEM)
        neighbor = point_metrics({"pv_power": 5850}, DEFAULT_NEIGHBOR_SYSTEM)
        self.assertEqual(mine["power_per_panel_w"], 585)
        self.assertEqual(neighbor["power_per_panel_w"], 585)
        self.assertEqual(mine["specific_power_w_kwp"], 1000)
        self.assertEqual(neighbor["specific_power_w_kwp"], 1000)

    def test_alignment_uses_nearest_timestamp_and_rejects_excess_skew(self) -> None:
        start = datetime.now(timezone.utc)
        primary = [
            {"captured_at": start.isoformat(), "timestamp_ms": round(start.timestamp() * 1000), "pv_power": 1000},
            {"captured_at": (start + timedelta(seconds=30)).isoformat(), "timestamp_ms": round((start + timedelta(seconds=30)).timestamp() * 1000), "pv_power": 1100},
        ]
        neighbor = [
            {"captured_at": (start + timedelta(seconds=8)).isoformat(), "timestamp_ms": round((start + timedelta(seconds=8)).timestamp() * 1000), "pv_power": 800},
            {"captured_at": (start + timedelta(seconds=55)).isoformat(), "timestamp_ms": round((start + timedelta(seconds=55)).timestamp() * 1000), "pv_power": 900},
        ]
        pairs = align_history(primary, neighbor, max_skew_seconds=15)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["skew_ms"], 8000)
        self.assertTrue(pairs[0]["comparable"])

    def test_alignment_maximizes_pair_count_when_nearest_choice_is_ambiguous(self) -> None:
        start = datetime.now(timezone.utc)

        def point(offset: int) -> dict:
            captured = start + timedelta(seconds=offset)
            return {"captured_at": captured.isoformat(), "pv_power": 1000}

        pairs = align_history(
            [point(0), point(5)],
            [point(-4), point(1)],
            max_skew_seconds=4,
        )

        # Greedily taking +1 for the first primary point strands the second
        # point.  The globally optimal one-to-one assignment retains both.
        self.assertEqual(len(pairs), 2)
        self.assertEqual([pair["skew_ms"] for pair in pairs], [4000, 4000])

    def test_alignment_minimizes_total_skew_after_maximizing_pair_count(self) -> None:
        start = datetime.now(timezone.utc)

        def point(offset: int) -> dict:
            captured = start + timedelta(seconds=offset)
            return {"captured_at": captured.isoformat(), "pv_power": 1000}

        pairs = align_history(
            [point(0), point(10)],
            [point(-5), point(1), point(9)],
            max_skew_seconds=10,
        )

        self.assertEqual(len(pairs), 2)
        self.assertEqual([pair["skew_ms"] for pair in pairs], [1000, 1000])

    def test_zero_is_preserved_and_missing_is_not_zero(self) -> None:
        start = datetime.now(timezone.utc).isoformat()
        zero = [{"captured_at": start, "pv_power": 0}]
        missing = [{"captured_at": start, "pv_power": None}]
        pairs = comparison_payload(zero, zero)["points"]
        self.assertEqual(pairs[0]["primary"]["pv_power_w"], 0)
        self.assertEqual(pairs[0]["delta"]["neighbor_to_primary_percent"], 100)
        unavailable = comparison_payload(missing, zero)
        self.assertFalse(unavailable["points"][0]["comparable"])
        self.assertEqual(unavailable["alignment"]["pair_count"], 1)
        self.assertEqual(unavailable["alignment"]["comparable_pair_count"], 0)
        self.assertFalse(unavailable["available"])
        self.assertEqual(unavailable["reason"], "no_comparable_samples")
        self.assertFalse(unavailable["latest"]["comparable"])
        self.assertEqual(unavailable["latest"], unavailable["latest_aligned"])
        self.assertIsNone(unavailable["latest_comparable"])

    def test_latest_aligned_and_latest_comparable_are_explicitly_distinct(self) -> None:
        start = datetime.now(timezone.utc)
        primary = [
            {"captured_at": start.isoformat(), "pv_power": 1000},
            {"captured_at": (start + timedelta(seconds=10)).isoformat(), "pv_power": None},
        ]
        neighbor = [
            {"captured_at": start.isoformat(), "pv_power": 900},
            {"captured_at": (start + timedelta(seconds=10)).isoformat(), "pv_power": 950},
        ]

        payload = comparison_payload(primary, neighbor)

        self.assertTrue(payload["available"])
        self.assertEqual(payload["alignment"]["pair_count"], 2)
        self.assertEqual(payload["alignment"]["comparable_pair_count"], 1)
        self.assertEqual(payload["latest"], payload["latest_aligned"])
        self.assertFalse(payload["latest_aligned"]["comparable"])
        self.assertTrue(payload["latest_comparable"]["comparable"])

    def test_one_neighbor_sample_is_not_counted_as_multiple_pairs(self) -> None:
        start = datetime.now(timezone.utc)
        primary = [
            {"captured_at": (start + timedelta(seconds=offset)).isoformat(), "pv_power": 1000}
            for offset in (0, 10, 20)
        ]
        neighbor = [{"captured_at": (start + timedelta(seconds=10)).isoformat(), "pv_power": 900}]
        self.assertEqual(len(align_history(primary, neighbor, max_skew_seconds=15)), 1)

    def test_day_of_ten_second_samples_uses_sparse_alignment(self) -> None:
        count = 24 * 60 * 6
        primary = [
            {"timestamp_ms": index * 10_000, "pv_power": 1000}
            for index in range(count)
        ]
        neighbor = [
            {
                "timestamp_ms": index * 10_000 + (index % 7 - 3) * 250,
                "pv_power": 900,
            }
            for index in range(count)
        ]

        pairs = align_history(primary, neighbor, max_skew_seconds=15)

        self.assertEqual(len(pairs), count)
        self.assertLessEqual(max(pair["skew_ms"] for pair in pairs), 750)

    def test_protocol_neutral_ingest_rejects_nan_and_converts_kwh(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        snapshot = build_neighbor_snapshot(
            {"captured_at": now, "metrics": {"pv_dc_power_w": 1234.567, "energy_today_kwh": 4.321}},
            DEFAULT_NEIGHBOR_SYSTEM,
        )
        self.assertEqual(snapshot["sensors"]["pv_power"]["value"], 1234.567)
        self.assertEqual(snapshot["sensors"]["today_energy"]["value"], 4321)
        with self.assertRaises(ValueError):
            build_neighbor_snapshot(
                {"captured_at": now, "metrics": {"pv_dc_power_w": float("nan")}},
                DEFAULT_NEIGHBOR_SYSTEM,
            )

    def test_ingest_rejects_more_than_five_minutes_of_future_capture_skew(self) -> None:
        received = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
        accepted = build_neighbor_snapshot(
            {
                "captured_at": (received + timedelta(seconds=300)).isoformat(),
                "received_at": "2099-01-01T00:00:00+00:00",
                "metrics": {"pv_dc_power_w": 1000},
            },
            DEFAULT_NEIGHBOR_SYSTEM,
            received_at=received,
        )
        self.assertEqual(accepted["received_at"], received.isoformat())
        with self.assertRaisesRegex(ValueError, "300 seconds in the future"):
            build_neighbor_snapshot(
                {
                    "captured_at": (received + timedelta(seconds=301)).isoformat(),
                    "metrics": {"pv_dc_power_w": 1000},
                },
                DEFAULT_NEIGHBOR_SYSTEM,
                received_at=received,
            )

    def test_canonical_age_uses_trusted_receipt_but_preserves_capture_time(self) -> None:
        now = datetime.now(timezone.utc)
        captured = now - timedelta(hours=1)
        snapshot = build_neighbor_snapshot(
            {
                "captured_at": captured.isoformat(),
                "metrics": {"pv_dc_power_w": 1000},
            },
            DEFAULT_NEIGHBOR_SYSTEM,
            received_at=now,
        )
        latest = canonical_latest(snapshot, DEFAULT_NEIGHBOR_SYSTEM)
        self.assertEqual(latest["captured_at"], captured.isoformat())
        self.assertEqual(latest["received_at"], now.isoformat())
        self.assertEqual(latest["age_basis"], "received_at")
        self.assertLess(latest["age_seconds"], 1)


if __name__ == "__main__":
    unittest.main()
