from __future__ import annotations

import unittest

from app import validate_listener_ports


class ListenerPortTests(unittest.TestCase):
    def test_dashboard_and_enabled_peer_api_must_use_distinct_ports(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be different"):
            validate_listener_ports(8765, 8765)

    def test_peer_collision_is_irrelevant_when_peer_api_is_disabled(self) -> None:
        validate_listener_ports(8765, 8765, peer_enabled=False)

    def test_ports_must_be_valid_tcp_listener_ports(self) -> None:
        for main_port, peer_port in ((0, 8767), (8765, 0), (65536, 8767), (8765, 65536)):
            with self.subTest(main_port=main_port, peer_port=peer_port):
                with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
                    validate_listener_ports(main_port, peer_port)


if __name__ == "__main__":
    unittest.main()
