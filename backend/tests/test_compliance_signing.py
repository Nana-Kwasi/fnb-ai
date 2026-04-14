import unittest

from app.routers.admin import _sign_payload


class TestComplianceSigning(unittest.TestCase):
    def test_sign_payload_stable(self):
        p = "tenant_export:abc:tenant:123"
        self.assertEqual(_sign_payload(p), _sign_payload(p))

    def test_sign_payload_differs_for_diff_payloads(self):
        self.assertNotEqual(_sign_payload("a"), _sign_payload("b"))


if __name__ == "__main__":
    unittest.main()
