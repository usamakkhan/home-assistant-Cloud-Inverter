from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from html.parser import HTMLParser
import threading
import unittest
import json
from unittest.mock import Mock

from app import Handler, STATIC
from solarmax_analyzer.collector import CollectorController
from solarmax_analyzer.controls import ControlService


class ActiveMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.template_depth = 0
        self.ids = []

    def handle_starttag(self, tag, attrs):
        if tag == "template":
            self.template_depth += 1
        if not self.template_depth:
            attributes = dict(attrs)
            if "id" in attributes:
                self.ids.append(attributes["id"])

    def handle_endtag(self, tag):
        if tag == "template":
            self.template_depth -= 1


class AssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.collector = CollectorController(Mock(), Mock(), Mock(), "192.168.50.10")
        cls.server.controls = ControlService(cls.server.collector, threading.Lock())
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_images_are_served_as_local_pngs(self):
        for asset in ("home-energy-v1.png", "inverter-kit-v1.png"):
            status, headers, body = self.request("/assets/" + asset)
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "image/png")
            self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_css_and_js_have_correct_mime_types(self):
        for asset, content_type in (("dashboard-v2.css", "text/css"), ("portal.css", "text/css"), ("peer-dashboard.css", "text/css"), ("dashboard-ui.js", "application/javascript"), ("peer-dashboard.js", "application/javascript")):
            status, headers, _ = self.request("/assets/" + asset + "?v=1")
            self.assertEqual(status, 200)
            self.assertTrue(headers["Content-Type"].startswith(content_type))

    def test_unlisted_paths_and_traversal_are_not_served(self):
        for path in ("/assets/../app.py", "/assets/%2e%2e/app.py", "/assets/ARTWORK.md", "/assets/unknown.png"):
            self.assertEqual(self.request(path)[0], 404)

    def test_visible_controls_have_unique_ids(self):
        markup = ActiveMarkup()
        markup.feed((STATIC / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(len(markup.ids), len(set(markup.ids)))
        self.assertIn("restoreOriginalBtn", markup.ids)
        self.assertIn("telemetryBadge", markup.ids)
        self.assertIn("peerChart", markup.ids)
        self.assertIn("peerHost", markup.ids)

    def test_controls_get_is_offline_and_disabled(self):
        status, _, body = self.request("/api/controls")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertFalse(data["enabled"])
        self.assertGreater(len(data["fields"]), 150)

    def control_post(self, origin, host=None, content_type="application/json", path="read", body=None):
        connection=HTTPConnection("127.0.0.1",self.server.server_port,timeout=3)
        headers={"Content-Type":content_type}
        if origin is not None: headers["Origin"]=origin
        if host is not None: headers["Host"]=host
        try:
            connection.request("POST","/api/controls/"+path,body=json.dumps(body or {}),headers=headers)
            response=connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_physical_controls_require_local_origin_json_and_allowed_host(self):
        origin=f"http://127.0.0.1:{self.server.server_port}"
        for bad_origin in (None,"https://example.com", "null"):
            self.assertEqual(self.control_post(bad_origin)[0],403)
        self.assertEqual(self.control_post("http://attacker.example",host="attacker.example")[0],403)
        self.assertEqual(self.control_post(origin,content_type="text/plain")[0],403)

    def test_original_mode_blocks_setting_reads_and_startup_blocks_prepare(self):
        origin=f"http://127.0.0.1:{self.server.server_port}"
        self.assertEqual(self.control_post(origin)[0],409)
        self.assertEqual(self.control_post(origin,path="prepare")[0],400)

    def test_single_editing_session_gate_pauses_and_restores_collection(self):
        origin=f"http://127.0.0.1:{self.server.server_port}"
        status,body=self.control_post(origin,path="session",body={"action":"start","confirmation":"ENABLE ABCDE123456789"})
        data=json.loads(body)
        self.assertEqual(status,200)
        self.assertTrue(data["enabled"])
        self.assertTrue(data["session_active"])
        self.assertEqual(data["collector"]["mode"],"maintenance")
        status,body=self.control_post(origin,path="session",body={"action":"end"})
        data=json.loads(body)
        self.assertEqual(status,200)
        self.assertFalse(data["enabled"])
        self.assertEqual(data["collector"]["mode"],"original")


if __name__ == "__main__":
    unittest.main()
