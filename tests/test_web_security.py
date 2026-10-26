import tempfile
import unittest
from pathlib import Path
from deck.web_security import Security, contained_path


class SecurityTests(unittest.TestCase):
    def test_containment(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'served'
            root.mkdir()
            secret = Path(d) / 'secret'
            secret.write_text('PRIVATE')
            (root / 'link').symlink_to(secret)
            for name in ('/' + str(secret), '../secret', '%2e%2e/secret', 'link', r'..\secret', '%252e%252e/secret'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    contained_path(root, name)

    def test_session_expiry_logout_and_rate_limit(self):
        with tempfile.TemporaryDirectory() as d:
            s = Security(Path(d) / 'token', ttl=1)
            cookie = s.login(s.token, 'client')
            self.assertTrue(s.valid(cookie))
            s.logout(cookie)
            self.assertFalse(s.valid(cookie))
            cookie = s.login(s.token, 'client')
            s.sessions[cookie] = 0
            self.assertFalse(s.valid(cookie))
            for _ in range(5):
                self.assertIsNone(s.login('wrong', 'bad'))
            self.assertIsNone(s.login(s.token, 'bad'))
            self.assertEqual(s.path.stat().st_mode & 0o777, 0o600)
