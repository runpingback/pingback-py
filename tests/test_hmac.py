import time
import unittest

from pingback.hmac import compute_hmac, verify_signature


class TestHMAC(unittest.TestCase):
    def test_valid_signature(self):
        secret = "test-secret"
        body = '{"function":"cleanup"}'
        ts = str(int(time.time()))
        sig = compute_hmac(ts, body, secret)
        verify_signature(sig, ts, body, secret)

    def test_invalid_signature(self):
        secret = "test-secret"
        body = '{"function":"cleanup"}'
        ts = str(int(time.time()))
        with self.assertRaises(ValueError):
            verify_signature("bad-signature", ts, body, secret)

    def test_expired_timestamp(self):
        secret = "test-secret"
        body = '{"function":"cleanup"}'
        ts = str(int(time.time()) - 360)
        sig = compute_hmac(ts, body, secret)
        with self.assertRaises(ValueError):
            verify_signature(sig, ts, body, secret)

    def test_tampered_body(self):
        secret = "test-secret"
        body = '{"function":"cleanup"}'
        ts = str(int(time.time()))
        sig = compute_hmac(ts, body, secret)
        with self.assertRaises(ValueError):
            verify_signature(sig, ts, '{"function":"malicious"}', secret)


if __name__ == "__main__":
    unittest.main()
