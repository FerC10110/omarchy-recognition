import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest

from _load import load
from fakes import env

engine = load()


class StateFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "recognition", "state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_missing_is_fresh_and_not_existing(self):
        state, existed = engine.load_state(self.path)
        self.assertEqual(state, engine.empty_state())
        self.assertFalse(existed)

    def test_broken_json_or_shape_is_fresh(self):
        for text in ("{nope", "[]", json.dumps({"devices": []})):
            self.write(text)
            state, existed = engine.load_state(self.path)
            self.assertEqual(state, engine.empty_state())
            self.assertFalse(existed)

    def test_wrong_typed_entries_are_fresh(self):
        base = engine.empty_state()
        variants = [
            dict(base, devices={"aa:bb:cc:dd:ee:ff": "oops"}),
            dict(base, people={"a" * 32: "oops"}),
            dict(base, ipOwners={"192.168.1.1": "oops"}),
            dict(base, alerts=["oops"]),
        ]
        for variant in variants:
            self.write(json.dumps(variant))
            state, existed = engine.load_state(self.path)
            self.assertEqual(state, engine.empty_state())
            self.assertFalse(existed)

    def test_round_trip_is_private(self):
        state = engine.empty_state()
        state["devices"]["00:00:5e:00:53:09"] = {"ip": "192.168.200.9"}
        state["gateway"] = {"ip": "192.168.200.1"}          # partial on purpose
        engine.save_state(self.path, state)
        loaded, existed = engine.load_state(self.path)
        self.assertTrue(existed)
        self.assertEqual(loaded["devices"], state["devices"])
        self.assertEqual(loaded["gateway"], {"ip": "192.168.200.1", "acceptedMac": "", "seenMac": ""})
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)


HOLDER = textwrap.dedent("""
    import fcntl, sys, time
    fh = open(sys.argv[1], "a")
    fcntl.flock(fh, fcntl.LOCK_EX)
    print("held", flush=True)
    time.sleep(5)
""")


class LockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = env(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_lock_acquires_when_free(self):
        with engine.scan_lock(self.env) as locked:
            self.assertTrue(locked)
        with engine.state_lock(self.env) as locked:
            self.assertTrue(locked)

    def test_scan_lock_does_not_block_when_held_elsewhere(self):
        path = engine.lock_path(self.env)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        holder = subprocess.Popen([sys.executable, "-c", HOLDER, path], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            with engine.scan_lock(self.env) as locked:
                self.assertFalse(locked)
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()


if __name__ == "__main__":
    unittest.main()
