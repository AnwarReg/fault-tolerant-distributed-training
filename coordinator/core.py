"""Round state transitions shared by the HTTP listeners."""

import base64
import copy
import hashlib
import re
import secrets
import ssl
import threading
import time


class InvalidRequest(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(message)


class Coordinator:
    def __init__(self, store, issuer=None, clock=time.time, round_seconds=45,
                 heartbeat_seconds=20, required_updates=2):
        self.store = store
        self.issuer = issuer
        self.clock = clock
        self.round_seconds = round_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.required_updates = required_updates
        self.lock = threading.RLock()
        self.state = store.load() or {
            "round_id": 1,
            "round_started": clock(),
            "workers": {},
            "invitations": {},
            "updates": {},
            "completed_rounds": 0,
            "last_aggregate": None,
            "last_round_workers": [],
        }

    def _save(self, new_state):
        # Publish a transition only after durable storage acknowledges it.
        self.store.save(new_state)
        self.state = new_state

    def _worker(self, state, fingerprint):
        for worker_id, worker in state["workers"].items():
            if secrets.compare_digest(worker["fingerprint"], fingerprint):
                return worker_id, worker
        raise InvalidRequest(403, "Unknown worker certificate")

    def _finish_round(self, state, now):
        updates = list(state["updates"].values())
        if not updates:
            state["round_started"] = now
            return
        total_weight = sum(update["weight"] for update in updates)
        state["last_aggregate"] = sum(
            update["value"] * update["weight"] for update in updates
        ) / total_weight
        state["last_round_workers"] = list(state["updates"])
        state["completed_rounds"] += 1
        state["round_id"] += 1
        state["round_started"] = now
        state["updates"] = {}

    def create_invitation(self, worker_id):
        if not isinstance(worker_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", worker_id):
            raise InvalidRequest(400, "Invalid worker_id")
        with self.lock:
            if worker_id in self.state["workers"]:
                raise InvalidRequest(409, "Worker already enrolled")
            token = secrets.token_urlsafe(32)
            state = copy.deepcopy(self.state)
            state["invitations"][hashlib.sha256(token.encode()).hexdigest()] = {
                "worker_id": worker_id,
                "expires_at": self.clock() + 600,
            }
            self._save(state)
            return {"worker_id": worker_id, "token": token, "expires_in_seconds": 600}

    def enroll(self, token, csr):
        if not isinstance(token, str) or not isinstance(csr, str) or len(csr) > 16384:
            raise InvalidRequest(400, "Token and CSR are required")
        if "-----BEGIN CERTIFICATE REQUEST-----" not in csr:
            raise InvalidRequest(400, "CSR must be PEM encoded")
        if self.issuer is None:
            raise InvalidRequest(503, "Certificate issuer is not configured")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            invitation = self.state["invitations"].get(token_hash)
            if invitation is None or invitation["expires_at"] < self.clock():
                raise InvalidRequest(403, "Invitation is invalid or expired")
            worker_id = invitation["worker_id"]
            if worker_id in self.state["workers"]:
                raise InvalidRequest(409, "Worker already enrolled")
            certificate, chain = self.issuer.sign(csr)
            fingerprint = base64.b64encode(hashlib.sha256(
                ssl.PEM_cert_to_DER_cert(certificate)
            ).digest()).decode("ascii")
            state = copy.deepcopy(self.state)
            del state["invitations"][token_hash]
            state["workers"][worker_id] = {
                "fingerprint": fingerprint,
                "last_heartbeat": 0,
                "assigned_round": 0,
            }
            self._save(state)
            return {"worker_id": worker_id, "certificate": certificate, "chain": chain}

    def get_task(self, fingerprint):
        with self.lock:
            state = copy.deepcopy(self.state)
            worker_id, worker = self._worker(state, fingerprint)
            now = self.clock()
            if now - state["round_started"] >= self.round_seconds:
                self._finish_round(state, now)
            worker["last_heartbeat"] = now
            worker["assigned_round"] = state["round_id"]
            self._save(state)
            return {
                "worker_id": worker_id,
                "round_id": state["round_id"],
                "model_version": state["round_id"] - 1,
                "task": "dummy-training",
            }

    def heartbeat(self, fingerprint):
        with self.lock:
            state = copy.deepcopy(self.state)
            worker_id, worker = self._worker(state, fingerprint)
            worker["last_heartbeat"] = self.clock()
            self._save(state)
            return {"worker_id": worker_id, "status": "alive"}

    def submit(self, fingerprint, payload):
        try:
            round_id = int(payload["round_id"])
            value = float(payload["value"])
            weight = int(payload.get("weight", 1))
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidRequest(400, "round_id, value, and weight must be numeric") from exc
        if not (-1e6 <= value <= 1e6) or not (1 <= weight <= 1000000):
            raise InvalidRequest(400, "Update is non-finite or outside allowed limits")
        with self.lock:
            state = copy.deepcopy(self.state)
            worker_id, worker = self._worker(state, fingerprint)
            if round_id == state["round_id"] - 1 and worker_id in state["last_round_workers"]:
                return {"status": "duplicate", "round_id": round_id}
            if round_id != state["round_id"]:
                raise InvalidRequest(409, "Update belongs to a stale round")
            if worker["assigned_round"] != round_id:
                raise InvalidRequest(409, "Worker has no assignment for this round")
            if worker_id in state["updates"]:
                return {"status": "duplicate", "round_id": round_id}
            state["updates"][worker_id] = {"value": value, "weight": weight}
            worker["last_heartbeat"] = self.clock()
            if len(state["updates"]) >= self.required_updates or (
                self.clock() - state["round_started"] >= self.round_seconds
            ):
                self._finish_round(state, self.clock())
            self._save(state)
            return {"status": "accepted", "round_id": round_id}

    def status(self):
        with self.lock:
            now = self.clock()
            return {
                "round_id": self.state["round_id"],
                "completed_rounds": self.state["completed_rounds"],
                "live_workers": sum(
                    now - worker["last_heartbeat"] <= self.heartbeat_seconds
                    for worker in self.state["workers"].values()
                ),
                "pending_updates": len(self.state["updates"]),
                "last_aggregate": self.state["last_aggregate"],
            }
