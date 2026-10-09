from __future__ import annotations

import re
import unittest

from solarmax_analyzer.peer_openapi import build_openapi_document


class PeerOpenApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = build_openapi_document(8767)

    def test_every_operation_declares_responses(self) -> None:
        for path, path_item in self.document["paths"].items():
            for method, operation in path_item.items():
                with self.subTest(path=path, method=method):
                    self.assertIn("operationId", operation)
                    self.assertTrue(operation.get("responses"))

    def test_every_path_placeholder_has_a_required_path_parameter(self) -> None:
        for path, path_item in self.document["paths"].items():
            placeholders = set(re.findall(r"\{([^}]+)\}", path))
            for method, operation in path_item.items():
                parameters = {
                    item["name"]: item
                    for item in operation.get("parameters", [])
                    if item.get("in") == "path"
                }
                with self.subTest(path=path, method=method):
                    self.assertEqual(placeholders, set(parameters))
                    self.assertTrue(all(item.get("required") is True for item in parameters.values()))

    def test_document_covers_read_and_local_admin_surfaces(self) -> None:
        paths = self.document["paths"]
        for path in ("/alerts/events", "/rules", "/config"):
            self.assertIn("get", paths[path])
        for path in ("/admin/config", "/admin/probe", "/admin/ingest", "/admin/rules"):
            operation = paths[path]["post"]
            self.assertTrue(operation["x-local-only"])
            self.assertFalse(operation["x-inverter-writes"])
            self.assertIn("requestBody", operation)


if __name__ == "__main__":
    unittest.main()
