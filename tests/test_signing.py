"""Contract checks for the portal's public request-signing format."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest

try:
    import aiohttp  # noqa: F401
except ModuleNotFoundError:
    # Signing tests do not make HTTP requests; permit a minimal Python runtime.
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = type("ClientSession", (), {})
    aiohttp.ClientError = type("ClientError", (Exception,), {})
    sys.modules["aiohttp"] = aiohttp


COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "cloud_inverter"
package = types.ModuleType("cloud_inverter")
package.__path__ = [str(COMPONENT)]
sys.modules["cloud_inverter"] = package

spec = importlib.util.spec_from_file_location("cloud_inverter.api", COMPONENT / "api.py")
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)


class SigningTests(unittest.TestCase):
    def test_login_signature_matches_portal_aes_format(self):
        # Independent AES-256-CBC reference generated with Node's crypto module.
        payload = {
            "type": "1",
            "remember": True,
            "Password": "example-password",
            "MemberID": "ABCDE123456789",
        }
        self.assertEqual(
            api.sign_payload(payload),
            "6wr/TkW9aanHO9hNVIbQtM5Xj7HFRL47mpHkZ9ra+2METPS2NJui8kdT4mNes0xNvW75hBcy4l04iRfQpYaVJkjf1qMGTpjcFhsOpyHbPcmFteKHg4GNtJ9Gs3n4mvLy",
        )

    def test_signature_is_computed_from_each_request(self):
        payload = {"MemberID": "ABCDE123456789", "Password": "example-password", "type": "1"}
        signed = api.signed_payload(payload)
        self.assertEqual(payload, {"MemberID": "ABCDE123456789", "Password": "example-password", "type": "1"})
        self.assertEqual(signed["sign"], api.sign_payload(payload))
        self.assertNotEqual(signed["sign"], api.sign_payload({**payload, "Password": "another-example"}))


if __name__ == "__main__":
    unittest.main()
