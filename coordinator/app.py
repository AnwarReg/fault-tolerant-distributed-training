"""HTTP entry points for the coordinator, enrollment, and local administration."""

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

from core import Coordinator, InvalidRequest
from gcp import CertificateIssuer, GcsStore, LocalStore


def make_handler(coordinator, role):
    # Each listener exposes only the routes meant for its network boundary.
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, payload):
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def read_json(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise InvalidRequest(400, "Invalid Content-Length") from exc
            if size < 1 or size > 65536:
                raise InvalidRequest(400, "Request body must be 1 to 65536 bytes")
            try:
                payload = json.loads(self.rfile.read(size))
            except (ValueError, UnicodeDecodeError) as exc:
                raise InvalidRequest(400, "Invalid JSON") from exc
            if not isinstance(payload, dict):
                raise InvalidRequest(400, "Expected a JSON object")
            return payload

        def worker_identity(self):
            # The mTLS load balancer replaces this header with the verified cert hash.
            fingerprint = self.headers.get("X-Worker-Cert-Fingerprint", "")
            if not fingerprint:
                raise InvalidRequest(401, "Worker certificate required")
            return fingerprint

        def do_GET(self):
            try:
                if self.path == "/health":
                    self.respond(200, {"status": "ok"})
                elif role == "worker" and self.path == "/v1/task":
                    self.respond(200, coordinator.get_task(self.worker_identity()))
                elif role == "worker" and self.path == "/v1/status":
                    self.worker_identity()
                    self.respond(200, coordinator.status())
                elif role == "admin" and self.path == "/admin/status":
                    self.respond(200, coordinator.status())
                else:
                    raise InvalidRequest(404, "Route not found")
            except InvalidRequest as exc:
                self.respond(exc.status, {"error": exc.message})
            except Exception:
                logging.exception("GET %s failed", self.path)
                self.respond(503, {"error": "Coordinator unavailable"})

        def do_POST(self):
            try:
                payload = self.read_json()
                if role == "enrollment" and self.path == "/enroll":
                    result = coordinator.enroll(payload.get("token"), payload.get("csr"))
                elif role == "worker" and self.path == "/v1/heartbeat":
                    result = coordinator.heartbeat(self.worker_identity())
                elif role == "worker" and self.path == "/v1/result":
                    result = coordinator.submit(self.worker_identity(), payload)
                elif role == "admin" and self.path == "/admin/invitations":
                    result = coordinator.create_invitation(payload.get("worker_id"))
                else:
                    raise InvalidRequest(404, "Route not found")
                self.respond(200, result)
            except InvalidRequest as exc:
                self.respond(exc.status, {"error": exc.message})
            except Exception:
                logging.exception("POST %s failed", self.path)
                self.respond(503, {"error": "Coordinator unavailable"})

    return Handler


def main():
    # Cloud mode persists every accepted change in the artifact bucket.
    bucket = os.getenv("ARTIFACT_BUCKET")
    store = GcsStore(bucket) if bucket else LocalStore(os.getenv("LOCAL_STATE_FILE", "state.json"))
    ca_pool = os.getenv("CA_POOL")
    issuer = CertificateIssuer(ca_pool) if ca_pool else None
    coordinator = Coordinator(store, issuer)

    # Enrollment is separate from strict mTLS; administration stays on loopback.
    listeners = [
        ("worker", "0.0.0.0", 8000),
        ("enrollment", "0.0.0.0", 8001),
        ("admin", "127.0.0.1", 8002),
    ]
    for role, host, port in listeners:
        server = ThreadingHTTPServer((host, port), make_handler(coordinator, role))
        Thread(target=server.serve_forever, daemon=True).start()
    Event().wait()


if __name__ == "__main__":
    main()
