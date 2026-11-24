"""Verify round transitions and recovery without Google Cloud credentials."""

import tempfile
import unittest
from pathlib import Path

from core import Coordinator, InvalidRequest
from gcp import LocalStore


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = LocalStore(Path(self.directory.name) / "state.json")
        self.now = 1000
        self.clock = lambda: self.now
        self.coordinator = Coordinator(self.store, clock=self.clock)
        # These two enrolled identities stand in for completed CA enrollment.
        state = self.coordinator.state
        state["workers"] = {
            "alice": {"fingerprint": "alice-cert", "last_heartbeat": 0, "assigned_round": 0},
            "bob": {"fingerprint": "bob-cert", "last_heartbeat": 0, "assigned_round": 0},
        }
        self.store.save(state)

    def test_two_updates_aggregate_and_survive_restart(self):
        first = self.coordinator.get_task("alice-cert")
        second = self.coordinator.get_task("bob-cert")
        self.assertEqual(first["round_id"], second["round_id"])
        self.coordinator.submit("alice-cert", {"round_id": 1, "value": 2, "weight": 1})
        self.coordinator.submit("bob-cert", {"round_id": 1, "value": 4, "weight": 3})

        restarted = Coordinator(self.store, clock=self.clock)
        self.assertEqual(restarted.status()["round_id"], 2)
        self.assertEqual(restarted.status()["last_aggregate"], 3.5)
        self.assertEqual(restarted.status()["completed_rounds"], 1)
        self.assertEqual(restarted.submit("alice-cert", {"round_id": 1, "value": 2}), {
            "status": "duplicate", "round_id": 1,
        })

    def test_stale_and_bad_updates_are_rejected(self):
        self.coordinator.get_task("alice-cert")
        for payload, status in [
            ({"round_id": 0, "value": 1}, 409),
            ({"round_id": 1, "value": "NaN"}, 400),
            ({"round_id": 1, "value": 1e9}, 400),
        ]:
            with self.subTest(payload=payload):
                with self.assertRaises(InvalidRequest) as error:
                    self.coordinator.submit("alice-cert", payload)
                self.assertEqual(error.exception.status, status)
        with self.assertRaises(InvalidRequest):
            self.coordinator.get_task("unknown-cert")

    def test_slow_worker_is_skipped_after_deadline(self):
        self.coordinator.get_task("alice-cert")
        self.coordinator.get_task("bob-cert")
        self.coordinator.submit("alice-cert", {"round_id": 1, "value": 7})
        self.now += 46
        task = self.coordinator.get_task("alice-cert")
        self.assertEqual(task["round_id"], 2)
        self.assertEqual(self.coordinator.status()["last_aggregate"], 7)
        self.assertEqual(self.coordinator.status()["live_workers"], 1)
        with self.assertRaises(InvalidRequest):
            self.coordinator.submit("bob-cert", {"round_id": 1, "value": 9})

    def test_invitation_is_hashed_and_expires(self):
        self.coordinator.issuer = object()
        invitation = self.coordinator.create_invitation("laptop-c")
        saved = self.store.load()
        self.assertNotIn(invitation["token"], str(saved))
        self.now += 601
        with self.assertRaises(InvalidRequest) as error:
            self.coordinator.enroll(invitation["token"], "-----BEGIN CERTIFICATE REQUEST-----")
        self.assertEqual(error.exception.status, 403)


if __name__ == "__main__":
    unittest.main()
