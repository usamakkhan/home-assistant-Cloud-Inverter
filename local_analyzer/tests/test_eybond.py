from __future__ import annotations

import unittest

from solarmax_analyzer.eybond import (
    _build_pi30_request,
    _build_pi18_request,
    _crc16_xmodem,
    _encode_frame,
    _parse_qpigs,
    _parse_pi18_gs,
    callback_messages,
)


class EybondProtocolTests(unittest.TestCase):
    def test_callback_payload_variants_are_bounded_and_exact(self) -> None:
        messages = callback_messages("192.168.50.20", 8899)
        self.assertEqual(messages[0], b"set>server=192.168.50.20:8899;")
        self.assertEqual(messages[1], messages[0] + b"\r\n")
        self.assertEqual(messages[2], messages[0] + b"\n")

    def test_binary_header_uses_eybond_wire_length_offset(self) -> None:
        frame = _encode_frame(1, 1, 1, 2, b"\x02")
        self.assertEqual(frame.hex(), "000100010003010202")
        self.assertEqual(len(frame), 9)

    def test_pi30_request_has_crc_and_carriage_return(self) -> None:
        frame = _build_pi30_request("QPI")
        self.assertEqual(frame[:-3], b"QPI")
        self.assertEqual(frame[-1:], b"\r")
        self.assertEqual(len(frame), 6)
        self.assertNotEqual(_crc16_xmodem(b"QPI"), 0)

    def test_qpigs_decoder_keeps_precision_and_prefers_reported_pv_power(self) -> None:
        payload = "230.1 50.0 229.9 50.0 1200 1100 18 400 52.34 10 81 41 6.7 321.4 53.0 2 10101010 0 1 2145 000 0 0 0"
        values = _parse_qpigs(payload)
        self.assertEqual(values["field_count"], 24)
        self.assertEqual(values["pv_power_w"], 2145)
        self.assertAlmostEqual(values["pv_calculated_power_w"], 2153.38)
        self.assertAlmostEqual(values["battery_power_w"], 418.72)

    def test_pi18_request_uses_prefixed_command_crc(self) -> None:
        frame = _build_pi18_request("^P005PI")
        self.assertEqual(frame[:-3], b"^P005PI")
        self.assertEqual(frame[-1:], b"\r")

    def test_pi18_gs_decoder_sums_both_trackers(self) -> None:
        fields = [2301, 500, 2300, 500, 1000, 900, 15, 520, 520, 520, 2, 8, 77, 43, 39, 40, 2100, 300, 3200, 1800, 0, 2, 2, 1, 1, 2, 1, 0]
        values = _parse_pi18_gs(",".join(str(item) for item in fields))
        self.assertEqual(values["pv_power_w"], 2400)
        self.assertAlmostEqual(values["battery_voltage_v"], 52.0)
        self.assertAlmostEqual(values["battery_power_w"], 312.0)


if __name__ == "__main__":
    unittest.main()
