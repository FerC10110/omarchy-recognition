"""Runs bin/recognition against the real network, with config and state in a
temporary directory. Opt-in: RECOGNITION_SYSTEM_TEST=1 python3 -m unittest ..."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "bin", "recognition")
ENABLED = os.environ.get("RECOGNITION_SYSTEM_TEST") == "1"


@unittest.skipUnless(ENABLED and shutil.which("nmap"), "set RECOGNITION_SYSTEM_TEST=1 (needs nmap and a LAN)")
class RealNetworkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, XDG_CONFIG_HOME=os.path.join(self.tmp.name, "config"),
                        XDG_STATE_HOME=os.path.join(self.tmp.name, "state"))
        # R7: the first real scan can take close to or over the default guard
        # window (scanInterval / 2 = 10s), which flakes the final assertion.
        # Widen scanInterval to 300 so the guard window becomes 150s.
        people_dir = os.path.join(self.env["XDG_CONFIG_HOME"], "recognition")
        os.makedirs(people_dir, exist_ok=True)
        with open(os.path.join(people_dir, "people.json"), "w", encoding="utf-8") as fh:
            json.dump({"settings": {"scanInterval": 300}}, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def engine(self, *args, stdin=None):
        result = subprocess.run([ENGINE, *args], input=stdin, capture_output=True, text=True,
                                env=self.env, timeout=90)
        return result.returncode, json.loads(result.stdout)

    def test_scan_sees_the_router_and_is_silent_the_first_time(self):
        code, status = self.engine("scan")
        self.assertEqual(code, 0, status)
        self.assertIsNone(status["error"])
        self.assertTrue(status["subnet"])
        self.assertGreater(len(status["unknown"]), 0)
        self.assertTrue(any(u["present"] for u in status["unknown"]))
        with open(os.path.join(self.env["XDG_STATE_HOME"], "recognition", "state.json")) as fh:
            state = json.load(fh)
        self.assertTrue(state["gateway"]["acceptedMac"])
        code, again = self.engine("scan")
        self.assertEqual(again["lastScan"], status["lastScan"])   # guard: too soon
