from __future__ import annotations

import unittest

from solarmax_analyzer.security import build_findings


class SecurityFindingTests(unittest.TestCase):
    def test_confirmed_plaintext_and_auth_findings_require_successful_read(self) -> None:
        findings = build_findings({502}, {"ok": True}, observed_rate_instability=False)
        by_id = {item["id"]: item for item in findings}
        self.assertEqual(by_id["SMX-LOCAL-001"]["status"], "confirmed")
        self.assertEqual(by_id["SMX-LOCAL-002"]["status"], "confirmed")
        self.assertEqual(by_id["SMX-LOCAL-003"]["status"], "confirmed")

    def test_sensitive_and_write_risks_stay_unverified(self) -> None:
        findings = build_findings({502}, {"ok": True})
        by_id = {item["id"]: item for item in findings}
        self.assertEqual(by_id["SMX-LOCAL-004"]["status"], "not tested")
        self.assertEqual(by_id["SMX-LOCAL-005"]["status"], "not tested")

    def test_secure_port_suppresses_missing_tls_finding(self) -> None:
        ids = {
            item["id"]
            for item in build_findings({502, 802}, {"ok": True}, False)
        }
        self.assertNotIn("SMX-LOCAL-003", ids)


if __name__ == "__main__":
    unittest.main()
