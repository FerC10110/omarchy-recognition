import contextlib
import io
import json
import os
import tempfile
import unittest

from _load import load
from fakes import FakeRun, T0, env
from fakes import GATEWAY_MAC, PHONE_MAC, RANDOM_MAC, SWITCH_MAC, at, lan, neigh, nmap_out
from fakes import fake_readily, readily_item, readily_listing

engine = load()


def call(argv, environ, run=None, stdin="", now=T0, spawn=None):
    out = io.StringIO()
    code = engine.main(argv, environ=environ, run=run or FakeRun(), now=lambda: now,
                       stdin=io.StringIO(stdin), stdout=out, oui_loader=lambda: {},
                       spawn=spawn or (lambda jobs, environ: None))
    return code, json.loads(out.getvalue())


class ContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = env(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_command_is_usage_error(self):
        code, payload = call([], self.env)
        self.assertEqual(code, 1)
        self.assertEqual(payload, {"error": engine.USAGE})

    def test_unknown_command_is_an_error(self):
        code, payload = call(["frobnicate"], self.env)
        self.assertEqual(code, 1)
        self.assertEqual(payload, {"error": "Unknown command: frobnicate"})

    def test_utc_now_is_timezone_aware(self):
        self.assertIsNotNone(engine.utc_now().tzinfo)

    def test_a_neighbor_never_lands_in_people(self):
        code, status = call(["save-person"], self.env, stdin='{"name": "Sam", "emoji": "🐸", "group": "neighbor"}\n')
        self.assertEqual((code, status["people"]), (0, []))
        self.assertEqual([p["name"] for p in status["neighbors"]], ["Sam"])
        sid = status["neighbors"][0]["id"]
        code, status = call(["save-person"], self.env,
                            stdin=json.dumps({"id": sid, "name": "Sam", "emoji": "🐸", "group": "home"}) + "\n")
        self.assertEqual(([p["name"] for p in status["people"]], status["neighbors"]), (["Sam"], []))

    def test_unexpected_exception_still_answers_one_json_document(self):
        run = FakeRun({"ip": RuntimeError("boom")})
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = engine.main(["scan"], environ=self.env, run=run, now=lambda: T0,
                               stdin=io.StringIO(""), stdout=out, oui_loader=lambda: {})
        self.assertEqual(code, 1)
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertIn("Internal error", payload["error"])
        self.assertIn("RuntimeError", payload["error"])
        self.assertIn("RuntimeError", err.getvalue())

    def test_status_shows_the_readily_commands_when_the_switch_is_on(self):
        path, _ = fake_readily(self.tmp.name)
        environ = dict(self.env, RECOGNITION_READILY_BIN=path)
        call(["set-settings"], environ, stdin='{"readily": true}\n')
        listing = readily_listing({"commands": [readily_item("Wake", "true", tags=["recognition/arrive"])]})
        code, status = call(["status"], environ, run=FakeRun({path: (0, listing, "")}))
        self.assertEqual(code, 0)
        self.assertEqual(status["readily"], {"enabled": True, "ok": True, "warning": "",
                                             "count": 1, "skipped": 0})
        self.assertEqual([c["title"] for c in status["commands"]], ["Wake"])

    def test_the_switch_off_never_calls_readily(self):
        path, _ = fake_readily(self.tmp.name)
        environ = dict(self.env, RECOGNITION_READILY_BIN=path)
        run = FakeRun({path: (0, readily_listing({"commands": []}), "")})
        code, status = call(["status"], environ, run=run)
        self.assertEqual(run.calls, [])
        self.assertEqual(status["readily"]["enabled"], False)
        self.assertEqual(status["commands"], [])


def notifications(run):
    return [call[5] for call in run.calls_to("omarchy-notification-send")]


def router_only():
    return lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE")]), nmap=nmap_out(["192.168.200.1"]))


class Spawns:
    """spawn double: records each call's jobs and whether scan.lock was free at that moment."""

    def __init__(self, error=None):
        self.error = error
        self.calls, self.lock_free = [], []

    def __call__(self, jobs, environ):
        self.calls.append(jobs)
        with engine.scan_lock(environ) as locked:
            self.lock_free.append(locked)
        if self.error:
            raise self.error


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = env(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def scan(self, seconds, run, *extra, spawn=None):
        return call(["scan", *extra], self.env, run=run, now=at(seconds), spawn=spawn)

    def add_person(self, mac):
        payload = {"name": "Ana", "emoji": "🐻", "devices": [{"mac": mac}]}
        code, status = call(["save-person"], self.env, stdin=json.dumps(payload) + "\n")
        return status["people"][0]["id"]

    def add_command(self, events):
        payload = {"command": "true", "events": events, "people": None}
        code, status = call(["save-command"], self.env, stdin=json.dumps(payload) + "\n")
        self.assertEqual(code, 0, status)
        return status["commands"][-1]["id"]

    def test_first_scan_is_silent_and_reports_devices(self):
        run = lan()
        code, status = self.scan(0, run)
        self.assertEqual(code, 0)
        self.assertEqual(status["error"], None)
        self.assertEqual(status["subnet"], "192.168.200.0/24")
        self.assertEqual(status["lastScan"], "2026-09-17T21:00:00Z")
        self.assertEqual(sorted(u["mac"] for u in status["unknown"]), sorted([GATEWAY_MAC, PHONE_MAC, SWITCH_MAC]))
        self.assertEqual(notifications(run), [])

    def test_arrival_of_a_person_and_of_an_unknown_device(self):
        self.scan(0, lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE")]),
                         nmap=nmap_out(["192.168.200.1"])))
        call(["save-person"], self.env, stdin='{"name": "Ana", "emoji": "🐻", "devices": [{"mac": "%s"}]}\n' % PHONE_MAC)
        run = lan()
        code, status = self.scan(20, run)
        self.assertEqual(code, 0)
        self.assertEqual(notifications(run), ["Ana arrived home", "New device on the network"])
        self.assertEqual([p["name"] for p in status["people"] if p["present"]], ["Ana"])

    def test_home_occupied_notification_is_sent_when_the_home_switch_is_on(self):
        self.scan(0, router_only())
        self.add_person(PHONE_MAC)
        call(["set-settings"], self.env, stdin='{"notify": {"home": true}}\n')
        run = lan()
        code, status = self.scan(20, run)
        self.assertEqual(code, 0)
        # Ordering (house notifications last) and the settings plumbing, both
        # in one assertion: the person and unknown-device notifications this
        # scan also triggers (see test_arrival_of_a_person_and_of_an_unknown_device)
        # come before the house one.
        self.assertEqual(notifications(run),
                         ["Ana arrived home", "New device on the network", "Home is occupied (Ana arrived)"])

    def test_guard_skips_a_scan_too_soon_unless_forced(self):
        self.scan(0, lan())
        run = lan()
        self.scan(5, run)
        self.assertEqual(run.calls_to("nmap"), [])
        self.scan(6, run, "--force")
        self.assertEqual(len(run.calls_to("nmap")), 1)

    def test_scan_prunes_stale_unowned_devices(self):
        self.scan(0, lan())
        path = engine.state_path(self.env)
        with open(path) as fh:
            state = json.load(fh)
        state["devices"][SWITCH_MAC]["lastSeen"] = engine.iso(at(-31 * 86400))
        state["devices"][SWITCH_MAC]["present"] = False
        with open(path, "w") as fh:
            json.dump(state, fh)
        run = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE")]),
                 nmap=nmap_out(["192.168.200.1"]))
        code, status = self.scan(20, run)
        with open(path) as fh:
            state = json.load(fh)
        self.assertNotIn(SWITCH_MAC, state["devices"])

    def test_scan_error_is_recorded_and_the_next_good_scan_is_silent(self):
        self.scan(0, lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE")]),
                         nmap=nmap_out(["192.168.200.1"])))
        code, status = self.scan(20, lan(nmap=FileNotFoundError("nmap")))
        self.assertEqual(code, 0)
        self.assertEqual(status["error"], "nmap isn't installed (omarchy pkg add nmap)")
        self.assertEqual(status["lastScan"], "2026-09-17T21:00:00Z")
        run = lan()
        code, status = self.scan(40, run)
        self.assertIsNone(status["error"])
        self.assertEqual(notifications(run), [])   # silent right after an error
        run = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                    ("192.168.200.9", PHONE_MAC, "REACHABLE"),
                                    ("192.168.200.112", RANDOM_MAC, "REACHABLE")]))
        self.scan(60, run)
        self.assertEqual(notifications(run), ["New device on the network"])

    def test_error_cycles_let_presence_decay_without_notifying(self):
        # Attempts every 20s (scanInterval), well within scanInterval +
        # SCAN_ALLOWANCE (R26): this models a scanner that keeps trying and
        # failing, not one that stopped running.
        self.scan(0, lan())
        run = lan(nmap=FileNotFoundError("nmap"))
        for seconds in range(20, 321, 20):
            self.scan(seconds, run)
        self.assertEqual(notifications(run), [])
        code, status = call(["status"], self.env, now=at(320))
        self.assertTrue(all(not u["present"] for u in status["unknown"]))

    def test_router_mac_change_alerts_and_can_be_accepted(self):
        self.scan(0, lan())
        evil = neigh([("192.168.200.1", "aa:bb:cc:dd:ee:ff", "REACHABLE")])
        run = lan(neighbours=evil)
        code, status = self.scan(20, run)
        self.assertEqual([a["kind"] for a in status["alerts"]], ["gateway-mac"])
        self.assertIn("Router MAC changed", notifications(run))
        code, status = call(["accept-gateway"], self.env, now=at(30))
        self.assertEqual((code, status["alerts"]), (0, []))

    def test_scanner_downtime_does_not_count_against_grace(self):
        self.scan(0, lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                           ("192.168.200.9", PHONE_MAC, "REACHABLE")]),
                         nmap=nmap_out(["192.168.200.1", "192.168.200.9"])))
        call(["save-person"], self.env,
            stdin='{"name": "Ana", "emoji": "🐻", "devices": [{"mac": "%s"}]}\n' % PHONE_MAC)
        # 9 hours later (the PC was off/suspended, or the shell was down): the
        # phone is missed once. That must not read as a departure.
        missed = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE")]),
                    nmap=nmap_out(["192.168.200.1"]))
        code, status = self.scan(9 * 3600, missed)
        self.assertEqual(notifications(missed), [])
        ana = next(p for p in status["people"] if p["name"] == "Ana")
        self.assertTrue(ana["present"])
        self.assertEqual(ana["since"], "2026-09-17T21:00:00Z")
        # The scan after that sees her phone again: no arrival notification,
        # and since is unchanged (she never left).
        seen_again = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                           ("192.168.200.9", PHONE_MAC, "REACHABLE")]),
                         nmap=nmap_out(["192.168.200.1", "192.168.200.9"]))
        code, status = self.scan(9 * 3600 + 20, seen_again)
        self.assertEqual(notifications(seen_again), [])
        ana = next(p for p in status["people"] if p["name"] == "Ana")
        self.assertTrue(ana["present"])
        self.assertEqual(ana["since"], "2026-09-17T21:00:00Z")

    def test_genuine_absence_while_scanning_regularly_still_leaves(self):
        self.scan(0, lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                           ("192.168.200.9", PHONE_MAC, "REACHABLE")]),
                         nmap=nmap_out(["192.168.200.1", "192.168.200.9"])))
        call(["save-person"], self.env,
            stdin='{"name": "Ana", "emoji": "🐻", "devices": [{"mac": "%s"}]}\n' % PHONE_MAC)
        run = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE")]),
                 nmap=nmap_out(["192.168.200.1"]))
        status = None
        for seconds in range(20, 321, 20):
            code, status = self.scan(seconds, run)
        ana = next(p for p in status["people"] if p["name"] == "Ana")
        self.assertFalse(ana["present"])
        self.assertIn("Ana left", notifications(run))

    def test_downtime_cap_does_not_resurrect_already_absent_devices(self):
        # Ana's phone and an unowned device (RANDOM_MAC) both leave while the
        # scanner keeps running regularly, exactly like the genuine-departure
        # test above.
        self.scan(0, lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                           ("192.168.200.9", PHONE_MAC, "REACHABLE"),
                                           ("192.168.200.112", RANDOM_MAC, "REACHABLE")]),
                         nmap=nmap_out(["192.168.200.1", "192.168.200.9", "192.168.200.112"])))
        call(["save-person"], self.env,
            stdin='{"name": "Ana", "emoji": "🐻", "devices": [{"mac": "%s"}]}\n' % PHONE_MAC)
        run = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE")]),
                 nmap=nmap_out(["192.168.200.1"]))
        status = None
        for seconds in range(20, 321, 20):
            code, status = self.scan(seconds, run)
        ana = next(p for p in status["people"] if p["name"] == "Ana")
        self.assertFalse(ana["present"])
        self.assertIn("Ana left", notifications(run))
        random_device = next(u for u in status["unknown"] if u["mac"] == RANDOM_MAC)
        self.assertFalse(random_device["present"])

        # A 1h gap in scanning (PC off/suspended). The first scan after it
        # still does not see the phone or the unknown device: they were
        # already absent, so the scanner-downtime cap (I3) must not
        # resurrect them and fire arrival notifications.
        after_gap = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE")]),
                        nmap=nmap_out(["192.168.200.1"]))
        code, status = self.scan(320 + 3600, after_gap)
        self.assertEqual(notifications(after_gap), [])
        ana = next(p for p in status["people"] if p["name"] == "Ana")
        self.assertFalse(ana["present"])
        random_device = next(u for u in status["unknown"] if u["mac"] == RANDOM_MAC)
        self.assertFalse(random_device["present"])

    def test_slow_live_scanner_80s_cadence_still_lets_presence_decay(self):
        # scanInterval is 20s but each cycle takes long enough (nmap timeout,
        # a slow LAN, the hostname budget) that Panel.qml's next attempt only
        # starts 80s later. That must not look like scanner downtime (R26).
        self.scan(0, lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                           ("192.168.200.9", PHONE_MAC, "REACHABLE")]),
                         nmap=nmap_out(["192.168.200.1", "192.168.200.9"])))
        call(["save-person"], self.env,
            stdin='{"name": "Ana", "emoji": "🐻", "devices": [{"mac": "%s"}]}\n' % PHONE_MAC)
        run = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE")]),
                 nmap=nmap_out(["192.168.200.1"]))
        status = None
        for k in range(1, 7):
            code, status = self.scan(80 * k, run)
        ana = next(p for p in status["people"] if p["name"] == "Ana")
        self.assertFalse(ana["present"])
        self.assertEqual(notifications(run).count("Ana left"), 1)

    def test_slow_live_scanner_81s_cadence_still_lets_presence_decay(self):
        # Just over the old (broken) 2x scanInterval + iso() rounding
        # threshold: still well within scanInterval + SCAN_ALLOWANCE (R26).
        self.scan(0, lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                           ("192.168.200.9", PHONE_MAC, "REACHABLE")]),
                         nmap=nmap_out(["192.168.200.1", "192.168.200.9"])))
        call(["save-person"], self.env,
            stdin='{"name": "Ana", "emoji": "🐻", "devices": [{"mac": "%s"}]}\n' % PHONE_MAC)
        run = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE")]),
                 nmap=nmap_out(["192.168.200.1"]))
        status = None
        for k in range(1, 7):
            code, status = self.scan(81 * k, run)
        ana = next(p for p in status["people"] if p["name"] == "Ana")
        self.assertFalse(ana["present"])
        self.assertEqual(notifications(run).count("Ana left"), 1)

    def test_gap_of_exactly_scan_interval_plus_allowance_is_not_downtime(self):
        # since_attempt == scanInterval + SCAN_ALLOWANCE (110s) is NOT a gap,
        # so Ana's age keeps counting from lastSeen and she leaves once
        # gracePeriod (300s) has passed since T0.
        self.scan(0, lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                           ("192.168.200.9", PHONE_MAC, "REACHABLE")]),
                         nmap=nmap_out(["192.168.200.1", "192.168.200.9"])))
        call(["save-person"], self.env,
            stdin='{"name": "Ana", "emoji": "🐻", "devices": [{"mac": "%s"}]}\n' % PHONE_MAC)
        run = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE")]),
                 nmap=nmap_out(["192.168.200.1"]))
        status = None
        for seconds in range(110, 311, 20):
            code, status = self.scan(seconds, run)
        ana = next(p for p in status["people"] if p["name"] == "Ana")
        self.assertFalse(ana["present"])
        self.assertEqual(notifications(run).count("Ana left"), 1)

    def test_gap_over_scan_interval_plus_allowance_is_downtime(self):
        # since_attempt == scanInterval + SCAN_ALLOWANCE + 1 (111s) IS a gap:
        # the presence clock restarts, so she has not yet left by the time
        # the 110s-gap case above already has (T0+300 < t < T0+111+300).
        self.scan(0, lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                           ("192.168.200.9", PHONE_MAC, "REACHABLE")]),
                         nmap=nmap_out(["192.168.200.1", "192.168.200.9"])))
        call(["save-person"], self.env,
            stdin='{"name": "Ana", "emoji": "🐻", "devices": [{"mac": "%s"}]}\n' % PHONE_MAC)
        run = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE")]),
                 nmap=nmap_out(["192.168.200.1"]))
        status = None
        for seconds in range(111, 312, 20):
            code, status = self.scan(seconds, run)
        ana = next(p for p in status["people"] if p["name"] == "Ana")
        self.assertTrue(ana["present"])
        self.assertEqual(notifications(run), [])

    def test_gateway_mac_conflict_detected_even_when_attacker_ip_is_lower(self):
        # Router at .254 (high IP); the attacker's own address, .50, is lower.
        # The old MAC->lowest-IP map would have hidden the .254 sighting.
        route = json.dumps([{"dst": "default", "gateway": "192.168.200.254", "dev": "enp1s0",
                             "protocol": "dhcp", "prefsrc": "192.168.200.230", "metric": 100, "flags": []}])
        first = neigh([("192.168.200.254", GATEWAY_MAC, "REACHABLE")])
        self.scan(0, lan(route=route, neighbours=first, nmap=nmap_out(["192.168.200.254"])))
        evil = neigh([("192.168.200.254", "aa:bb:cc:dd:ee:ff", "REACHABLE"),
                      ("192.168.200.50", "aa:bb:cc:dd:ee:ff", "REACHABLE")])
        run = lan(route=route, neighbours=evil, nmap=nmap_out(["192.168.200.254", "192.168.200.50"]))
        code, status = self.scan(20, run)
        self.assertEqual([a["kind"] for a in status["alerts"]], ["gateway-mac"])
        self.assertIn("Router MAC changed", notifications(run))
        alert_call = next(c for c in run.calls_to("omarchy-notification-send") if "Router MAC changed" in c)
        self.assertEqual(alert_call[4], "critical")

    def test_ip_conflict_detected_even_when_attacker_ip_is_lower(self):
        # Victim at .30; the attacker's own address, .20, is lower. The old
        # MAC->lowest-IP map would have hidden the .30 sighting.
        victim = "00:00:5e:00:53:08"
        self.scan(0, lan(neighbours=neigh([("192.168.200.30", victim, "REACHABLE")]),
                         nmap=nmap_out(["192.168.200.30"])))
        attacker = "aa:bb:cc:dd:ee:ff"
        evil = neigh([("192.168.200.20", attacker, "REACHABLE"),
                      ("192.168.200.30", attacker, "REACHABLE")])
        run = lan(neighbours=evil, nmap=nmap_out(["192.168.200.20", "192.168.200.30"]))
        code, status = self.scan(20, run)
        self.assertEqual([a["kind"] for a in status["alerts"]], ["ip-conflict"])
        self.assertEqual(status["alerts"][0]["data"],
                         {"ip": "192.168.200.30", "previousMac": victim, "mac": attacker})

    def test_alerts_still_notify_right_after_an_error_cycle(self):
        self.scan(0, lan())
        self.scan(500, lan(nmap=FileNotFoundError("nmap")))
        evil = neigh([("192.168.200.1", "aa:bb:cc:dd:ee:ff", "REACHABLE"),
                      ("192.168.200.9", PHONE_MAC, "REACHABLE"),
                      ("192.168.200.5", SWITCH_MAC, "REACHABLE")])
        run = lan(neighbours=evil)
        code, status = self.scan(520, run)
        self.assertEqual(code, 0)
        self.assertEqual([a["kind"] for a in status["alerts"]], ["gateway-mac"])
        self.assertEqual(notifications(run), ["Router MAC changed"])
        calls = run.calls_to("omarchy-notification-send")
        self.assertEqual(calls[0][4], "critical")

    def test_notifications_are_sent_after_releasing_the_lock(self):
        self.scan(0, lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE")]),
                         nmap=nmap_out(["192.168.200.1"])))
        call(["save-person"], self.env, stdin='{"name": "Ana", "emoji": "🐻", "devices": [{"mac": "%s"}]}\n' % PHONE_MAC)
        acquired = []

        def check_lock(argv):
            with engine.scan_lock(self.env) as locked:
                acquired.append(locked)
            return (0, "", "")

        run = lan(extra={"omarchy-notification-send": check_lock})
        self.scan(20, run)
        self.assertTrue(acquired)
        self.assertTrue(all(acquired))

    def test_wrong_typed_state_entries_answer_a_valid_status_and_are_regenerated(self):
        path = engine.state_path(self.env)
        os.makedirs(os.path.dirname(path))
        for bad in (dict(engine.empty_state(), devices={PHONE_MAC: "oops"}),
                   dict(engine.empty_state(), alerts=["oops"])):
            with open(path, "w") as fh:
                json.dump(bad, fh)
            code, status = call(["status"], self.env)
            self.assertEqual(code, 0)
            self.assertEqual(status["people"], [])
            code, status = call(["scan", "--force"], self.env, run=lan())
            self.assertEqual(code, 0)
            self.assertIsNone(status["error"])

    def test_people_json_broken_fails_every_command(self):
        path = engine.people_path(self.env)
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as fh:
            fh.write("{broken")
        for argv in (["scan"], ["status"], ["unhouse", PHONE_MAC]):
            code, payload = call(argv, self.env, run=lan())
            self.assertEqual(code, 1)
            self.assertIn("is not valid JSON", payload["error"])

    def test_house_devices_never_notify(self):
        self.scan(0, lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE")]),
                         nmap=nmap_out(["192.168.200.1"])))
        call(["house", SWITCH_MAC], self.env, stdin='{"label": "Switch"}\n')
        here = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                     ("192.168.200.5", SWITCH_MAC, "REACHABLE")]),
                   nmap=nmap_out(["192.168.200.1", "192.168.200.5"]))
        code, status = self.scan(20, here)
        self.assertEqual(notifications(here), [])
        self.assertTrue(status["house"][0]["present"])
        gone = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE")]),
                   nmap=nmap_out(["192.168.200.1"]))
        for seconds in range(40, 401, 20):
            code, status = self.scan(seconds, gone)
        self.assertEqual(notifications(gone), [])
        self.assertFalse(status["house"][0]["present"])

    def test_an_arrival_runs_commands_after_the_lock_even_with_notifications_off(self):
        self.scan(0, router_only())
        self.add_person(PHONE_MAC)
        call(["set-settings"], self.env,
             stdin='{"notify": {"arrive": false, "leave": false, "unknown": false, "security": false}}\n')
        cid = self.add_command(["arrive", "home-occupied", "unknown"])
        spawned, run = Spawns(), lan()
        code, status = self.scan(20, run, spawn=spawned)
        self.assertEqual(code, 0)
        self.assertEqual(notifications(run), [])
        [jobs] = spawned.calls
        self.assertEqual([(job["id"], job["event"]) for job in jobs],
                         [(cid, "arrive"), (cid, "home-occupied"), (cid, "unknown")])
        self.assertEqual(jobs[0]["env"]["RECOGNITION_PERSON_NAME"], "Ana")
        self.assertEqual(jobs[1]["env"]["RECOGNITION_HOME"], "Ana")
        self.assertEqual(jobs[2]["env"]["RECOGNITION_DEVICE_MAC"], SWITCH_MAC)
        self.assertEqual(spawned.lock_free, [True])

    def test_the_last_person_leaving_runs_home_empty(self):
        self.scan(0, router_only())
        self.add_person(PHONE_MAC)
        self.add_command(["leave", "home-empty"])
        self.scan(20, lan())
        spawned = Spawns()
        for seconds in range(40, 401, 20):
            self.scan(seconds, router_only(), spawn=spawned)
        [jobs] = spawned.calls
        self.assertEqual([job["event"] for job in jobs], ["leave", "home-empty"])
        self.assertEqual(jobs[1]["env"]["RECOGNITION_MESSAGE"], "Home is empty (Ana left)")
        self.assertEqual((jobs[1]["env"]["RECOGNITION_HOME"], jobs[1]["env"]["RECOGNITION_HOME_COUNT"]), ("", "0"))

    def test_a_neighbor_still_online_does_not_count_as_home(self):
        self.scan(0, router_only())
        self.add_person(PHONE_MAC)
        call(["save-person"], self.env,
            stdin=json.dumps({"name": "Sam", "emoji": "🦊", "group": "neighbor",
                              "devices": [{"mac": RANDOM_MAC}]}) + "\n")
        both = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                     ("192.168.200.9", PHONE_MAC, "REACHABLE"),
                                     ("192.168.200.112", RANDOM_MAC, "REACHABLE")]),
                   nmap=nmap_out(["192.168.200.1", "192.168.200.9", "192.168.200.112"]))
        self.scan(20, both)
        self.add_command(["home-empty"])
        spawned = Spawns()
        ana_gone = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                         ("192.168.200.112", RANDOM_MAC, "REACHABLE")]),
                       nmap=nmap_out(["192.168.200.1", "192.168.200.112"]))
        for seconds in range(40, 401, 20):
            code, status = self.scan(seconds, ana_gone, spawn=spawned)
        [jobs] = spawned.calls
        self.assertEqual([job["event"] for job in jobs], ["home-empty"])
        self.assertEqual((jobs[0]["env"]["RECOGNITION_HOME"], jobs[0]["env"]["RECOGNITION_HOME_COUNT"]), ("", "0"))
        self.assertTrue(status["neighbors"][0]["present"])

    def test_a_guest_online_keeps_the_house_from_emptying(self):
        self.scan(0, router_only())
        self.add_person(PHONE_MAC)
        call(["save-person"], self.env,
             stdin=json.dumps({"name": "Sam", "emoji": "🦊", "group": "guest",
                               "devices": [{"mac": RANDOM_MAC}]}) + "\n")
        both = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                     ("192.168.200.9", PHONE_MAC, "REACHABLE"),
                                     ("192.168.200.112", RANDOM_MAC, "REACHABLE")]),
                   nmap=nmap_out(["192.168.200.1", "192.168.200.9", "192.168.200.112"]))
        self.scan(20, both)
        self.add_command(["home-empty"])
        spawned = Spawns()
        ana_gone = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                         ("192.168.200.112", RANDOM_MAC, "REACHABLE")]),
                       nmap=nmap_out(["192.168.200.1", "192.168.200.112"]))
        for seconds in range(40, 401, 20):
            code, status = self.scan(seconds, ana_gone, spawn=spawned)
        self.assertEqual(spawned.calls, [])
        self.assertTrue(status["guests"][0]["present"])

    def test_with_the_switch_off_the_house_empties_anyway(self):
        self.scan(0, router_only())
        self.add_person(PHONE_MAC)
        call(["save-person"], self.env,
             stdin=json.dumps({"name": "Sam", "emoji": "🦊", "group": "guest",
                               "devices": [{"mac": RANDOM_MAC}]}) + "\n")
        both = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                     ("192.168.200.9", PHONE_MAC, "REACHABLE"),
                                     ("192.168.200.112", RANDOM_MAC, "REACHABLE")]),
                   nmap=nmap_out(["192.168.200.1", "192.168.200.9", "192.168.200.112"]))
        self.scan(20, both)
        self.add_command(["home-empty"])
        call(["set-settings"], self.env, stdin='{"guestsOccupyHome": false}\n')
        spawned = Spawns()
        ana_gone = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                         ("192.168.200.112", RANDOM_MAC, "REACHABLE")]),
                       nmap=nmap_out(["192.168.200.1", "192.168.200.112"]))
        for seconds in range(40, 401, 20):
            self.scan(seconds, ana_gone, spawn=spawned)
        [jobs] = spawned.calls
        self.assertEqual([job["event"] for job in jobs], ["home-empty"])

    def test_a_neighbor_already_online_does_not_keep_the_house_occupied(self):
        """home_before must count the house only: a neighbor here first cannot swallow home-occupied."""
        self.scan(0, router_only())
        self.add_person(PHONE_MAC)
        call(["save-person"], self.env,
             stdin=json.dumps({"name": "Sam", "emoji": "🦊", "group": "neighbor",
                               "devices": [{"mac": RANDOM_MAC}]}) + "\n")
        neighbor_only = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                              ("192.168.200.112", RANDOM_MAC, "REACHABLE")]),
                            nmap=nmap_out(["192.168.200.1", "192.168.200.112"]))
        self.scan(20, neighbor_only)
        self.add_command(["home-occupied"])
        spawned = Spawns()
        ana_home = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                         ("192.168.200.9", PHONE_MAC, "REACHABLE"),
                                         ("192.168.200.112", RANDOM_MAC, "REACHABLE")]),
                       nmap=nmap_out(["192.168.200.1", "192.168.200.9", "192.168.200.112"]))
        code, status = self.scan(40, ana_home, spawn=spawned)
        self.assertEqual(len(spawned.calls), 1, "home-occupied never fired")
        [jobs] = spawned.calls
        self.assertEqual([job["event"] for job in jobs], ["home-occupied"])
        self.assertEqual((jobs[0]["env"]["RECOGNITION_HOME"], jobs[0]["env"]["RECOGNITION_HOME_COUNT"]),
                         ("Ana", "1"))

    def test_a_guest_already_online_does_not_keep_the_house_occupied(self):
        """home_before must count a guest too while guestsOccupyHome is on: a guest here first cannot swallow home-occupied."""
        self.scan(0, router_only())
        self.add_person(PHONE_MAC)
        call(["save-person"], self.env,
             stdin=json.dumps({"name": "Sam", "emoji": "🦊", "group": "guest",
                               "devices": [{"mac": RANDOM_MAC}]}) + "\n")
        guest_only = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                           ("192.168.200.112", RANDOM_MAC, "REACHABLE")]),
                         nmap=nmap_out(["192.168.200.1", "192.168.200.112"]))
        self.scan(20, guest_only)
        self.add_command(["home-occupied"])
        spawned = Spawns()
        ana_home = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                         ("192.168.200.9", PHONE_MAC, "REACHABLE"),
                                         ("192.168.200.112", RANDOM_MAC, "REACHABLE")]),
                       nmap=nmap_out(["192.168.200.1", "192.168.200.9", "192.168.200.112"]))
        code, status = self.scan(40, ana_home, spawn=spawned)
        self.assertEqual(spawned.calls, [])

    def test_with_guests_not_occupying_home_a_guest_already_online_still_lets_home_occupied_fire(self):
        """With guestsOccupyHome off, home_before ignores the guest, so the household member arriving fires home-occupied."""
        self.scan(0, router_only())
        self.add_person(PHONE_MAC)
        call(["save-person"], self.env,
             stdin=json.dumps({"name": "Sam", "emoji": "🦊", "group": "guest",
                               "devices": [{"mac": RANDOM_MAC}]}) + "\n")
        call(["set-settings"], self.env, stdin='{"guestsOccupyHome": false}\n')
        guest_only = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                           ("192.168.200.112", RANDOM_MAC, "REACHABLE")]),
                         nmap=nmap_out(["192.168.200.1", "192.168.200.112"]))
        self.scan(20, guest_only)
        self.add_command(["home-occupied"])
        spawned = Spawns()
        ana_home = lan(neighbours=neigh([("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
                                         ("192.168.200.9", PHONE_MAC, "REACHABLE"),
                                         ("192.168.200.112", RANDOM_MAC, "REACHABLE")]),
                       nmap=nmap_out(["192.168.200.1", "192.168.200.9", "192.168.200.112"]))
        code, status = self.scan(40, ana_home, spawn=spawned)
        self.assertEqual(len(spawned.calls), 1, "home-occupied never fired")
        [jobs] = spawned.calls
        self.assertEqual([job["event"] for job in jobs], ["home-occupied"])

    def test_no_commands_on_the_first_scan_or_around_errors(self):
        self.add_command(list(engine.EVENTS))
        spawned = Spawns()
        self.scan(0, lan(), spawn=spawned)
        self.scan(500, lan(nmap=FileNotFoundError("nmap")), spawn=spawned)
        self.assertEqual(spawned.calls, [])
        evil = neigh([("192.168.200.1", "aa:bb:cc:dd:ee:ff", "REACHABLE"),
                      ("192.168.200.9", PHONE_MAC, "REACHABLE"),
                      ("192.168.200.5", SWITCH_MAC, "REACHABLE")])
        self.scan(520, lan(neighbours=evil), spawn=spawned)
        self.assertEqual([[job["event"] for job in jobs] for jobs in spawned.calls], [["alert"]])

    def test_assigning_a_device_already_home_runs_nothing(self):
        self.scan(0, lan())
        code, status = call(["save-person"], self.env, stdin='{"name": "Ana", "emoji": "🐻"}\n')
        call(["assign", PHONE_MAC, status["people"][0]["id"]], self.env, stdin="{}\n")
        self.add_command(["arrive", "home-occupied"])
        spawned = Spawns()
        self.scan(20, lan(), spawn=spawned)
        self.assertEqual(spawned.calls, [])

    def test_no_jobs_means_no_spawn(self):
        self.scan(0, router_only())
        self.add_command(["alert"])
        spawned = Spawns()
        self.scan(20, lan(), spawn=spawned)
        self.assertEqual(spawned.calls, [])

    def test_a_failing_spawn_does_not_break_the_scan(self):
        self.scan(0, router_only())
        self.add_command(["unknown"])
        spawned = Spawns(error=OSError("no fork"))
        code, status = self.scan(20, lan(), spawn=spawned)
        self.assertEqual(code, 0)
        self.assertIsNone(status["error"])
        self.assertEqual(len(spawned.calls), 1)

    def test_the_guest_variables_reach_a_command(self):
        self.scan(0, router_only())
        call(["save-person"], self.env,
             stdin=json.dumps({"name": "Sam", "emoji": "🦊", "group": "guest",
                               "devices": [{"mac": PHONE_MAC}]}) + "\n")
        self.add_command(["guest-arrive"])
        spawned = Spawns()
        self.scan(20, lan(), spawn=spawned)
        [jobs] = spawned.calls
        self.assertEqual([job["event"] for job in jobs], ["guest-arrive"])
        self.assertEqual((jobs[0]["env"]["RECOGNITION_GUESTS"], jobs[0]["env"]["RECOGNITION_GUEST_COUNT"]),
                         ("Sam", "1"))
        self.assertEqual(jobs[0]["env"]["RECOGNITION_HOME"], "")

    def test_a_readily_command_runs_on_arrival(self):
        path, _ = fake_readily(self.tmp.name)
        self.env["RECOGNITION_READILY_BIN"] = path
        self.scan(0, router_only())
        self.add_person(PHONE_MAC)
        call(["set-settings"], self.env, stdin='{"readily": true}\n')
        listing = readily_listing({"commands": [readily_item("Wake", "true", tags=["recognition/arrive"])]})
        spawned, run = Spawns(), lan(extra={path: (0, listing, "")})
        code, status = self.scan(20, run, spawn=spawned)
        self.assertEqual(code, 0)
        [jobs] = spawned.calls
        self.assertEqual([(job["event"], job.get("source")) for job in jobs], [("arrive", "readily")])
        self.assertEqual(jobs[0]["id"], engine.readily_id("commands", "Wake"))
        self.assertEqual(jobs[0]["env"]["RECOGNITION_PERSON_NAME"], "Ana")
        self.assertEqual(status["readily"]["count"], 1)

    def test_a_scan_survives_a_broken_readily(self):
        path, _ = fake_readily(self.tmp.name)
        self.env["RECOGNITION_READILY_BIN"] = path
        self.scan(0, router_only())
        self.add_person(PHONE_MAC)
        call(["set-settings"], self.env, stdin='{"readily": true}\n')
        self.add_command(["arrive"])
        spawned, run = Spawns(), lan(extra={path: (1, "", "boom")})
        code, status = self.scan(20, run, spawn=spawned)
        self.assertEqual(code, 0)
        [jobs] = spawned.calls
        self.assertEqual([(job["event"], job.get("source")) for job in jobs], [("arrive", None)])
        self.assertEqual(status["readily"], {"enabled": True, "ok": False, "warning": "Readily isn't available",
                                             "count": 0, "skipped": 0})

    def test_a_scan_that_returns_early_still_lists_the_readily_commands(self):
        path, _ = fake_readily(self.tmp.name)
        self.env["RECOGNITION_READILY_BIN"] = path
        call(["set-settings"], self.env, stdin='{"readily": true}\n')
        listing = readily_listing({"commands": [readily_item("Wake", "true", tags=["recognition"])]})
        run = lan(extra={path: (0, listing, "")})
        self.scan(0, run)
        # Half an interval later the cycle returns early; its status must still carry them.
        code, status = self.scan(5, run)
        self.assertEqual(status["readily"]["count"], 1)
        self.assertEqual([c["title"] for c in status["commands"]], ["Wake"])


class EditCommandsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = env(self.tmp.name)
        call(["scan"], self.env, run=lan(avahi={"192.168.200.9": "Android_4f1c.local"}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_assign_with_auto_label_then_unassign(self):
        code, status = call(["save-person"], self.env, stdin='{"name": "Ana", "emoji": "🐻"}\n')
        pid = status["people"][0]["id"]
        code, status = call(["assign", PHONE_MAC, pid], self.env, stdin="{}\n")
        self.assertEqual(code, 0)
        self.assertEqual(status["people"][0]["devices"][0]["label"], "Android_4f1c")
        self.assertTrue(status["people"][0]["present"])
        self.assertNotIn(PHONE_MAC, [u["mac"] for u in status["unknown"]])
        code, status = call(["unassign", PHONE_MAC], self.env)
        self.assertEqual(status["people"][0]["devices"], [])

    def test_house_unhouse_forget(self):
        code, status = call(["house", SWITCH_MAC], self.env, stdin='{"label": "Switch"}\n')
        self.assertEqual(status["house"], [{"mac": SWITCH_MAC, "label": "Switch", "present": True,
                                            "ip": "192.168.200.5", "lastSeen": "2026-09-17T21:00:00Z"}])
        self.assertNotIn(SWITCH_MAC, [u["mac"] for u in status["unknown"]])
        code, payload = call(["forget", SWITCH_MAC], self.env)
        self.assertEqual((code, payload),
                         (1, {"error": "Only devices that are unassigned and not in House can be forgotten"}))
        code, status = call(["house", SWITCH_MAC], self.env, stdin="{}\n")
        self.assertEqual(status["house"][0]["label"], "Device")   # {} → auto label (no hostname, no vendor)
        code, status = call(["house", SWITCH_MAC], self.env, stdin='{"label": "  "}\n')
        self.assertEqual(status["house"][0]["label"], "Device")   # blank → auto label, the Rename UI's "empty" path
        call(["unhouse", SWITCH_MAC], self.env)
        code, payload = call(["unhouse", SWITCH_MAC], self.env)
        self.assertEqual((code, payload), (1, {"error": "That device isn't in House"}))
        code, status = call(["forget", SWITCH_MAC], self.env)
        self.assertEqual(code, 0)
        self.assertNotIn(SWITCH_MAC, [u["mac"] for u in status["unknown"]])

    def test_ignore_is_gone(self):
        for argv in (["ignore", SWITCH_MAC], ["unignore", SWITCH_MAC]):
            code, payload = call(argv, self.env, stdin="{}\n")
            self.assertEqual((code, payload), (1, {"error": "Unknown command: " + argv[0]}))

    def test_settings_and_delete(self):
        code, status = call(["set-settings"], self.env, stdin='{"scanInterval": 60, "notify": {"leave": false}}\n')
        self.assertEqual(status["settings"]["scanInterval"], 60)
        self.assertFalse(status["settings"]["notify"]["leave"])
        code, payload = call(["set-settings"], self.env, stdin='{"gracePeriod": 5}\n')
        self.assertEqual(code, 1)
        code, status = call(["save-person"], self.env, stdin='{"name": "Ana", "emoji": "🐻"}\n')
        code, status = call(["delete-person", status["people"][0]["id"]], self.env)
        self.assertEqual(status["people"], [])

    def test_saving_only_the_panel_geometry_leaves_the_rest_alone(self):
        code, status = call(["set-settings"], self.env,
                            stdin='{"scanInterval": 60, "subnet": "192.168.200.0/24",'
                                  ' "guestsOccupyHome": false, "notify": {"leave": false}}\n')
        self.assertEqual(code, 0)
        code, status = call(["set-settings"], self.env,
                            stdin='{"panelWidth": 640, "panelHeight": 900, "panelX": -20, "panelY": 8}\n')
        self.assertEqual(code, 0)
        settings = status["settings"]
        self.assertEqual([settings["panelWidth"], settings["panelHeight"],
                          settings["panelX"], settings["panelY"]], [640, 900, -20, 8])
        self.assertEqual(settings["scanInterval"], 60)
        self.assertEqual(settings["subnet"], "192.168.200.0/24")
        self.assertIs(settings["guestsOccupyHome"], False)
        self.assertIs(settings["notify"]["leave"], False)

    def test_save_and_delete_command(self):
        code, status = call(["save-person"], self.env, stdin='{"name": "Ana", "emoji": "🐻"}\n')
        pid = status["people"][0]["id"]
        fields = {"command": "echo hi", "events": ["arrive"], "people": [pid]}
        code, status = call(["save-command"], self.env, stdin=json.dumps(fields) + "\n")
        self.assertEqual(code, 0)
        cid = status["commands"][0]["id"]
        self.assertEqual(status["commands"], [dict(fields, id=cid, last=None)])
        with open(engine.people_path(self.env)) as fh:
            self.assertEqual(json.load(fh)["commands"], [dict(fields, id=cid)])
        code, status = call(["delete-person", pid], self.env)
        self.assertEqual(status["commands"][0]["people"], [])
        code, status = call(["delete-command", cid], self.env)
        self.assertEqual((code, status["commands"]), (0, []))
        self.assertEqual(call(["delete-command", cid], self.env), (1, {"error": "That command no longer exists"}))
        self.assertEqual(call(["delete-command"], self.env), (1, {"error": "Missing the command id"}))
        self.assertEqual(call(["save-command"], self.env, stdin='{"command": "", "events": ["arrive"]}\n'),
                         (1, {"error": "Command: between 1 and 1000 characters"}))
        self.assertEqual(call(["status"], self.env)[1]["commands"], [])

    def store_result(self, command_id, text):
        """The result the runner would have stored for this command."""
        engine.record_result(self.env, command_id, {"at": engine.iso(T0), "event": "arrive", "command": text,
                                                    "ok": True, "exit": 0, "message": "", "seconds": 0.0})

    def test_deleting_a_command_drops_its_stored_result(self):
        code, status = call(["save-command"], self.env, stdin='{"command": "echo secret", "events": ["arrive"]}\n')
        cid = status["commands"][0]["id"]
        self.store_result(cid, "echo secret")
        self.assertIn(cid, engine.load_results(self.env))
        call(["delete-command", cid], self.env)
        self.assertEqual(engine.load_results(self.env), {})

    def test_editing_a_command_drops_the_result_of_the_old_text(self):
        code, status = call(["save-command"], self.env, stdin='{"command": "echo secret", "events": ["arrive"]}\n')
        cid = status["commands"][0]["id"]
        self.store_result(cid, "echo secret")
        fields = {"id": cid, "command": "echo public", "events": ["arrive"], "people": None}
        call(["save-command"], self.env, stdin=json.dumps(fields) + "\n")
        self.assertEqual(engine.load_results(self.env), {})

    def test_editing_people_without_results_leaves_no_results_file(self):
        call(["save-person"], self.env, stdin='{"name": "Ana", "emoji": "🐻"}\n')
        self.assertFalse(os.path.exists(engine.results_path(self.env)))

    def test_bad_input(self):
        self.assertEqual(call(["save-person"], self.env, stdin="")[1], {"error": "Missing input data"})
        self.assertEqual(call(["save-person"], self.env, stdin="{x\n")[1], {"error": "Input isn't valid JSON"})
        self.assertEqual(call(["assign", PHONE_MAC], self.env, stdin="{}\n")[1],
                         {"error": "Missing the person id"})
        self.assertEqual(call(["dismiss-alert"], self.env)[1], {"error": "Missing the alert id"})


if __name__ == "__main__":
    unittest.main()
