"""HTTP integration tests using a fake Roku. No real TV is contacted."""
import http.client
import json
import threading
import unittest
from remote import RemoteServer, RemoteState, RokuClient, RemoteError, validate_tv_host

class FakeRoku(RokuClient):
    def __init__(self):
        super().__init__("192.168.1.50")
        self.actions = []

    def request(self, method, path):
        if method == "POST":
            self.actions.append(path)
            return b""
        if path == "/query/device-info":
            return b"<device-info><model-name>Test TV</model-name><power-mode>PowerOn</power-mode></device-info>"
        if path == "/query/active-app":
            return b'<active-app><app id="562859">Home</app></active-app>'
        if path == "/query/apps":
            return b'<apps><app id="837" type="appl">YouTube</app><app id="12" type="appl">Netflix</app><app id="13" type="appl">Prime Video</app><app id="tvinput.hdmi1" type="tvin">HDMI 1</app></apps>'
        raise AssertionError("Unexpected TV request: " + path)

class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.roku = FakeRoku()
        self.state = RemoteState(self.roku, code="123456")
        self.server = RemoteServer(("127.0.0.1", 0), self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.cookie = ""

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        request_headers = {"Content-Type": "application/json", "X-Remote-Request": "1"}
        if self.cookie:
            request_headers["Cookie"] = self.cookie
        if headers:
            request_headers.update(headers)
        connection.request(method, path, body=None if body is None else json.dumps(body), headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        result = (response.status, dict(response.getheaders()), raw)
        connection.close()
        return result

    def pair(self):
        status, headers, body = self.request("POST", "/api/pair", {"code": "123456"})
        self.assertEqual(status, 200)
        self.cookie = headers["Set-Cookie"].split(";")[0]
        return headers

    def test_page_is_self_contained_and_framing_disabled(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Simple Roku Remote", body)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertIn("no-store", headers["Cache-Control"])

    def test_unauthenticated_requests_cannot_reach_tv(self):
        self.assertEqual(self.request("GET", "/api/status")[0], 401)
        self.assertEqual(self.request("POST", "/api/key", {"key": "Home"})[0], 401)
        self.assertEqual(self.roku.actions, [])

    def test_pairing_cookie_and_live_status_shape(self):
        headers = self.pair()
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        status, _, body = self.request("GET", "/api/status")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["model"], "Test TV")
        self.assertEqual(len(data["apps"]), 3)

    def test_wrong_and_non_ascii_pairing_codes_rejected(self):
        for code in ["000000", "\u00e9\u00e9\u00e9\u00e9\u00e9\u00e9", None]:
            self.assertEqual(self.request("POST", "/api/pair", {"code": code})[0], 401)

    def test_pairing_attempts_are_limited(self):
        for _ in range(5):
            self.assertEqual(self.request("POST", "/api/pair", {"code": "000000"})[0], 401)
        self.assertEqual(self.request("POST", "/api/pair", {"code": "123456"})[0], 429)

    def test_cross_origin_commands_are_blocked(self):
        self.pair()
        status = self.request("POST", "/api/key", {"key": "Home"}, {"Origin": "https://example.com"})[0]
        self.assertEqual(status, 403)
        self.assertEqual(self.roku.actions, [])

    def test_simple_cross_site_form_requests_are_blocked(self):
        self.pair()
        status = self.request("POST", "/api/key", {"key": "Home"}, {"X-Remote-Request": ""})[0]
        self.assertEqual(status, 403)

    def test_dns_rebinding_host_is_blocked(self):
        self.assertEqual(self.request("GET", "/", headers={"Host": "untrusted.example"})[0], 400)

    def test_navigation_key_is_forwarded_and_unknown_key_is_not(self):
        self.pair()
        self.assertEqual(self.request("POST", "/api/key", {"key": "Home"})[0], 200)
        self.assertEqual(self.roku.actions, ["/keypress/Home"])
        self.assertEqual(self.request("POST", "/api/key", {"key": "../factory-reset"})[0], 400)
        self.assertEqual(self.request("POST", "/api/key", {"key": []})[0], 400)
        self.assertEqual(len(self.roku.actions), 1)

    def test_only_installed_apps_can_be_launched(self):
        self.pair()
        self.assertEqual(self.request("POST", "/api/launch", {"id": "837"})[0], 200)
        self.assertEqual(self.request("POST", "/api/launch", {"id": "999999"})[0], 400)
        self.assertEqual(self.request("POST", "/api/launch", {"id": "../keypress/Home"})[0], 400)
        self.assertEqual(self.roku.actions, ["/launch/837"])

    def test_unicode_text_is_encoded_one_character_at_a_time(self):
        self.pair()
        status, _, body = self.request("POST", "/api/text", {"text": "A\u00e9 "})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["sent"], 3)
        self.assertEqual(self.roku.actions, ["/keypress/Lit_A", "/keypress/Lit_%C3%A9", "/keypress/Lit_%20"])
        self.assertEqual(self.request("POST", "/api/text", {"text": "x" * 81})[0], 400)
        self.assertEqual(self.request("POST", "/api/text", {"text": "two\nlines"})[0], 400)

    def test_logout_revokes_session(self):
        self.pair()
        self.assertEqual(self.request("POST", "/api/unpair", {})[0], 200)
        self.assertEqual(self.request("GET", "/api/status")[0], 401)

    def test_command_rate_is_bounded(self):
        self.pair()
        for _ in range(100):
            self.assertEqual(self.request("POST", "/api/key", {"key": "Home"})[0], 200)
        self.assertEqual(self.request("POST", "/api/key", {"key": "Home"})[0], 429)
        self.assertEqual(len(self.roku.actions), 100)

class HostTests(unittest.TestCase):
    def test_private_ipv4_required(self):
        for value in ["10.0.0.10", "172.16.1.5", "192.168.2.20"]:
            self.assertEqual(validate_tv_host(value), value)
        for value in ["127.0.0.1", "169.254.169.254", "8.8.8.8", "192.0.2.1", "::1", "localhost", "http://192.168.1.5/path"]:
            with self.assertRaises(ValueError):
                validate_tv_host(value)

if __name__ == "__main__":
    unittest.main()
