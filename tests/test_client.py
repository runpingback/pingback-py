import json
import time
import unittest
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

from pingback import Pingback
from pingback.hmac import compute_hmac


def signed_headers(body: str, secret: str) -> dict:
    ts = str(int(time.time()))
    sig = compute_hmac(ts, body, secret)
    return {
        "X-Pingback-Signature": sig,
        "X-Pingback-Timestamp": ts,
        "Content-Type": "application/json",
    }


class TestDecorators(unittest.TestCase):
    def test_cron_registers_function(self):
        pb = Pingback("key", "secret")

        @pb.cron("cleanup", "0 3 * * *", retries=2)
        def cleanup(ctx):
            pass

        self.assertIn("cleanup", pb._functions)
        self.assertEqual(pb._functions["cleanup"]["type"], "cron")
        self.assertEqual(pb._functions["cleanup"]["schedule"], "0 3 * * *")
        self.assertEqual(pb._functions["cleanup"]["retries"], 2)

    def test_task_registers_function(self):
        pb = Pingback("key", "secret")

        @pb.task("send-email", timeout="15s")
        def send_email(ctx):
            pass

        self.assertIn("send-email", pb._functions)
        self.assertEqual(pb._functions["send-email"]["type"], "task")
        self.assertEqual(pb._functions["send-email"]["timeout"], "15s")


class TestHandle(unittest.TestCase):
    def _make_pb(self):
        pb = Pingback("key", "secret")
        pb._registered = True
        return pb

    def test_success(self):
        pb = self._make_pb()

        @pb.cron("cleanup", "0 3 * * *")
        def cleanup(ctx):
            ctx.log("cleaned up", count=42)
            return {"removed": 42}

        body = '{"function":"cleanup","executionId":"exec-1","attempt":1,"scheduledAt":"2026-04-22T03:00:00Z"}'
        headers = signed_headers(body, "secret")
        result = pb.handle(body.encode(), headers)

        self.assertEqual(result["_status"], 200)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"], {"removed": 42})
        self.assertEqual(len(result["logs"]), 1)
        self.assertEqual(result["logs"][0]["level"], "info")
        self.assertEqual(result["logs"][0]["meta"], {"count": 42})

    def test_unknown_function(self):
        pb = self._make_pb()
        body = '{"function":"nonexistent","executionId":"exec-1","attempt":1,"scheduledAt":"2026-04-22T03:00:00Z"}'
        headers = signed_headers(body, "secret")
        result = pb.handle(body.encode(), headers)
        self.assertEqual(result["_status"], 404)

    def test_invalid_signature(self):
        pb = self._make_pb()

        @pb.task("job")
        def job(ctx):
            pass

        body = '{"function":"job","executionId":"exec-1","attempt":1,"scheduledAt":"2026-04-22T03:00:00Z"}'
        headers = signed_headers(body, "wrong-secret")
        result = pb.handle(body.encode(), headers)
        self.assertEqual(result["_status"], 401)

    def test_handler_error(self):
        pb = self._make_pb()

        @pb.task("fail")
        def fail(ctx):
            raise RuntimeError("something broke")

        body = '{"function":"fail","executionId":"exec-1","attempt":1,"scheduledAt":"2026-04-22T03:00:00Z"}'
        headers = signed_headers(body, "secret")
        result = pb.handle(body.encode(), headers)
        self.assertEqual(result["_status"], 500)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "something broke")

    def test_fan_out(self):
        pb = self._make_pb()

        @pb.cron("parent", "* * * * *")
        def parent(ctx):
            ctx.task("child-a", {"id": "1"})
            ctx.task("child-b", {"id": "2"})

        body = '{"function":"parent","executionId":"exec-1","attempt":1,"scheduledAt":"2026-04-22T03:00:00Z"}'
        headers = signed_headers(body, "secret")
        result = pb.handle(body.encode(), headers)
        self.assertEqual(len(result["tasks"]), 2)
        self.assertEqual(result["tasks"][0]["name"], "child-a")

    def test_payload(self):
        pb = self._make_pb()

        @pb.task("echo")
        def echo(ctx):
            return ctx.payload

        body = '{"function":"echo","executionId":"exec-1","attempt":1,"scheduledAt":"2026-04-22T03:00:00Z","payload":{"msg":"hello"}}'
        headers = signed_headers(body, "secret")
        result = pb.handle(body.encode(), headers)
        self.assertEqual(result["result"], {"msg": "hello"})


class TestTrigger(unittest.TestCase):
    def test_trigger_success(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert body["task"] == "send-email"
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"executionId": "exec-123", "task": "send-email"}).encode())
            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        t = Thread(target=server.handle_request)
        t.start()

        pb = Pingback("test-key", "secret", platform_url=f"http://127.0.0.1:{port}")
        exec_id = pb.trigger("send-email", {"to": "a@b.com"})
        self.assertEqual(exec_id, "exec-123")
        t.join(timeout=2)
        server.server_close()

    def test_trigger_error(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b'Task "nope" not found')
            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        t = Thread(target=server.handle_request)
        t.start()

        pb = Pingback("test-key", "secret", platform_url=f"http://127.0.0.1:{port}")
        with self.assertRaises(RuntimeError):
            pb.trigger("nope")
        t.join(timeout=2)
        server.server_close()


class TestRegister(unittest.TestCase):
    def test_register_sends_correct_payload(self):
        received = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received["auth"] = self.headers["Authorization"]
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"jobs": [{"name": "cleanup", "status": "active"}]}).encode())
            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        t = Thread(target=server.handle_request)
        t.start()

        pb = Pingback("test-key", "secret", platform_url=f"http://127.0.0.1:{port}")

        @pb.cron("cleanup", "0 3 * * *", retries=2)
        def cleanup(ctx):
            pass

        @pb.task("send-email", timeout="15s")
        def send_email(ctx):
            pass

        pb._ensure_registered()
        t.join(timeout=2)
        server.server_close()

        self.assertEqual(received["auth"], "Bearer test-key")
        self.assertEqual(len(received["body"]["functions"]), 2)


if __name__ == "__main__":
    unittest.main()
