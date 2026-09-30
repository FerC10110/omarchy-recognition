"""The command runner with a real sh: run-commands, test-command and launch_runner (spec §3.5, §3.7)."""
import io
import json
import os
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from _load import load
from fakes import (FakeRun, GATEWAY_MAC, PHONE_MAC, RANDOM_MAC, SWITCH_MAC, T0, at, env,
                   fake_readily, readily_item, readily_listing)

engine = load()


def call(argv, environ, stdin="", run=None):
    out = io.StringIO()
    code = engine.main(argv, environ=environ, run=run or FakeRun(), now=lambda: T0, stdin=io.StringIO(stdin),
                       stdout=out, oui_loader=lambda: {}, spawn=lambda jobs, environ: None)
    return code, json.loads(out.getvalue())


def gone(pid):
    """True once pid has exited (a zombie waiting for its parent counts as gone)."""
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().rsplit(") ", 1)[1].startswith("Z")
    except FileNotFoundError:
        return True


class RunnerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(env(self.tmp.name), PATH=os.environ.get("PATH", os.defpath))

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def read(self, name):
        with open(self.path(name), encoding="utf-8") as fh:
            return fh.read()

    def save_commands(self, *texts):
        data = engine.empty_people()
        ids = [engine.save_command(data, {"command": text, "events": ["arrive"]})["id"] for text in texts]
        engine.save_people(engine.people_path(self.env), data)
        return ids

    def job(self, command_id, text):
        return {"id": command_id, "command": text, "event": "arrive", "env": {"RECOGNITION_EVENT": "arrive"}}


class RunJobTest(RunnerCase):
    def test_success(self):
        result = engine.run_job("true", {}, self.env)
        self.assertEqual((result["ok"], result["exit"], result["message"]), (True, 0, ""))
        self.assertIsInstance(result["seconds"], float)

    def test_failure_keeps_the_last_stderr_line(self):
        result = engine.run_job("echo first >&2; echo 'curl: (6) no host' >&2; echo >&2; exit 3", {}, self.env)
        self.assertEqual((result["ok"], result["exit"], result["message"]), (False, 3, "curl: (6) no host"))

    def test_last_line_is_cleaned_and_cut(self):
        self.assertEqual(engine._last_line(b"one\n\x1b[31mtwo\t\n  \n"), "[31mtwo")
        self.assertEqual(engine._last_line(b"x" * 300), "x" * 200)
        self.assertEqual(engine._last_line(b""), "")

    def test_runs_in_home_with_only_the_job_recognition_variables(self):
        environ = dict(self.env, RECOGNITION_STALE="old")
        result = engine.run_job("pwd > out; env | grep ^RECOGNITION_ | sort >> out",
                                {"RECOGNITION_EVENT": "arrive"}, environ)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.read("out").splitlines(),
                         [os.path.realpath(self.tmp.name), "RECOGNITION_EVENT=arrive"])

    def test_hostile_values_stay_data(self):
        marker = self.path("pwned")
        hostile = f"$(touch {marker}); touch {marker}; `touch {marker}`"
        result = engine.run_job('echo $RECOGNITION_DEVICE_HOSTNAME > out; echo "$RECOGNITION_DEVICE_HOSTNAME" >> out',
                                {"RECOGNITION_DEVICE_HOSTNAME": hostile}, self.env)
        self.assertTrue(result["ok"], result)
        self.assertFalse(os.path.exists(marker))
        self.assertEqual(self.read("out").splitlines()[1], hostile)

    def test_timeout_kills_the_whole_group(self):
        started = time.monotonic()
        result = engine.run_job("sleep 30 & echo $! > child; wait", {}, self.env, timeout=0.5, grace=1)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual((result["ok"], result["exit"], result["message"]), (False, None, "timed out after 0.5 s"))
        child = int(self.read("child"))
        deadline = time.monotonic() + 3
        while not gone(child) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(gone(child))

    def test_a_command_that_ignores_sigterm_gets_sigkill(self):
        started = time.monotonic()
        result = engine.run_job("trap '' TERM; sleep 30 & echo $! > child; wait", {}, self.env,
                                timeout=0.3, grace=0.3)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual((result["exit"], result["message"]), (None, "timed out after 0.3 s"))
        child = int(self.read("child"))
        deadline = time.monotonic() + 3
        while not gone(child) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(gone(child))

    def test_background_process_does_not_delay_the_result(self):
        started = time.monotonic()
        result = engine.run_job("sleep 3 &", {}, self.env)
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(result["ok"], result)

    def test_a_command_that_cannot_start_is_a_failure(self):
        result = engine.run_job("true", {}, dict(self.env, HOME=self.path("missing")))
        self.assertEqual((result["ok"], result["exit"]), (False, None))
        self.assertIn("missing", result["message"])


class CaptureJobTest(RunnerCase):
    """Spec §3.1: the runner that keeps what the command printed."""

    def test_stdout_and_stderr_come_back_merged_in_order(self):
        result = engine.capture_job('printf one; printf two >&2; printf three', {}, self.env)
        self.assertEqual((result["ok"], result["exit"], result["message"], result["truncated"]),
                         (True, 0, "", False))
        self.assertEqual(result["output"], "onetwothree")

    def test_control_characters_go_except_newline_and_tab(self):
        result = engine.capture_job(r"printf 'a\rb\tc\n'", {}, self.env)
        self.assertEqual(result["output"], "ab\tc\n")

    def test_a_long_output_is_cut_at_the_head_and_marked(self):
        result = engine.capture_job("yes abcdefgh | head -c 20000", {}, self.env)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["output"]), engine.OUTPUT_MAX)
        self.assertTrue(result["output"].startswith("abcdefgh\nabcdefgh\n"))

    def test_a_failing_command_still_brings_its_output(self):
        result = engine.capture_job("echo boom >&2; exit 3", {}, self.env)
        self.assertEqual((result["ok"], result["exit"], result["message"]), (False, 3, ""))
        self.assertEqual(result["output"], "boom\n")

    def test_a_command_that_hangs_times_out_and_keeps_what_it_printed(self):
        result = engine.capture_job("printf hi; sleep 5", {}, self.env, timeout=0.3, grace=0.2)
        self.assertEqual((result["ok"], result["exit"], result["message"]),
                         (False, None, "timed out after 0.3 s"))
        self.assertEqual(result["output"], "hi")

    def test_a_command_that_cannot_start_is_a_failure_without_output(self):
        result = engine.capture_job("true", {}, dict(self.env, HOME=self.path("missing")))
        self.assertEqual((result["ok"], result["exit"], result["output"]), (False, None, ""))
        self.assertIn("missing", result["message"])

    def test_the_environment_reaches_the_command(self):
        result = engine.capture_job('printf "%s" "$RECOGNITION_EVENT"', {"RECOGNITION_EVENT": "manual"}, self.env)
        self.assertEqual(result["output"], "manual")


class RunJobsTest(RunnerCase):
    def test_each_result_is_stored_and_deleted_commands_are_dropped(self):
        ok_id, bad_id = self.save_commands("true", "echo nope >&2; exit 2")
        path = engine.results_path(self.env)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"version": 1, "results": {"f" * 32: {"ok": True}}}, fh)
        jobs = [self.job(ok_id, "true"), self.job(bad_id, "echo nope >&2; exit 2")]
        self.assertEqual(engine.run_jobs(jobs, self.env, clock=lambda: T0), 2)
        with open(path) as fh:
            stored = json.load(fh)
        self.assertEqual((stored["version"], sorted(stored["results"])), (1, sorted([ok_id, bad_id])))
        bad = stored["results"][bad_id]
        self.assertEqual(sorted(bad), ["at", "command", "event", "exit", "message", "ok", "seconds"])
        self.assertEqual({key: bad[key] for key in ("at", "event", "command", "ok", "exit", "message")},
                         {"at": "2026-09-17T21:00:00Z", "event": "arrive", "command": "echo nope >&2; exit 2",
                          "ok": False, "exit": 2, "message": "nope"})
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_a_broken_results_file_counts_as_empty(self):
        [cid] = self.save_commands("true")
        path = engine.results_path(self.env)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("{broken")
        engine.run_jobs([self.job(cid, "true")], self.env)
        self.assertEqual(list(engine.load_results(self.env)), [cid])

    def test_a_result_for_text_no_longer_current_is_dropped(self):
        [cid] = self.save_commands("true")
        stale = {"at": engine.iso(T0), "event": "arrive", "command": "echo old", "ok": True, "exit": 0,
                 "message": "", "seconds": 0.0}
        engine.record_result(self.env, cid, stale)
        self.assertNotIn(cid, engine.load_results(self.env))
        current = dict(stale, command="true")
        engine.record_result(self.env, cid, current)
        self.assertEqual(engine.load_results(self.env)[cid], current)

    def test_at_most_eight_at_once(self):
        lock, active, peak = threading.Lock(), [0], [0]

        def fake_run_job(command, extra_env, environ, timeout):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.1)
            with lock:
                active[0] -= 1
            return {"ok": True, "exit": 0, "message": "", "seconds": 0.1}

        with mock.patch.object(engine, "run_job", fake_run_job):
            self.assertEqual(engine.run_jobs([self.job("a" * 32, "true")] * 20, self.env), 20)
        self.assertEqual(peak[0], engine.RUNNER_WORKERS)


class RunCommandsTest(RunnerCase):
    def test_run_commands(self):
        [cid] = self.save_commands("exit 4")
        payload = {"jobs": [self.job(cid, "exit 4")]}
        self.assertEqual(call(["run-commands"], self.env, stdin=json.dumps(payload) + "\n"), (0, {"ran": 1}))
        self.assertEqual(engine.load_results(self.env)[cid]["exit"], 4)

    def test_bad_jobs_are_rejected(self):
        good = self.job("a" * 32, "true")
        for payload in ({}, {"jobs": {}}, {"jobs": [{"id": "x"}]}, {"jobs": [dict(good, event="party")]},
                        {"jobs": [dict(good, env={"PATH": "/tmp"})]},
                        {"jobs": [dict(good, env={"RECOGNITION_X": 1})]}):
            self.assertEqual(call(["run-commands"], self.env, stdin=json.dumps(payload) + "\n"),
                             (1, {"error": "Jobs: must be a list of jobs"}), payload)

    def test_launch_runner_returns_at_once_and_the_runner_stores_the_result(self):
        [cid] = self.save_commands("sleep 1")
        started = time.monotonic()
        proc = engine.launch_runner([self.job(cid, "sleep 1")], self.env)
        self.assertLess(time.monotonic() - started, 0.9)
        deadline = time.monotonic() + 10
        while cid not in engine.load_results(self.env) and time.monotonic() < deadline:
            time.sleep(0.1)
        proc.wait(timeout=10)
        self.assertTrue(engine.load_results(self.env)[cid]["ok"])


class TestCommandTest(RunnerCase):
    def try_it(self, fields):
        return call(["test-command"], self.env, stdin=json.dumps(fields) + "\n")

    def sample(self, event, people=None):
        code, payload = self.try_it({"command": 'printf "%s" "$RECOGNITION_JSON" > event.json; '
                                                'printf "%s|%s" "$RECOGNITION_TEST" "$RECOGNITION_HOME" > extra',
                                     "event": event, "people": people})
        self.assertEqual((code, payload["test"]["ok"]), (0, True), payload)
        return json.loads(self.read("event.json")), self.read("extra")

    def test_result_and_nothing_stored(self):
        code, payload = self.try_it({"command": "echo boom >&2; exit 3", "event": "arrive"})
        self.assertEqual(code, 0)
        self.assertEqual(sorted(payload["test"]), ["exit", "message", "ok", "seconds"])
        self.assertEqual({key: payload["test"][key] for key in ("ok", "exit", "message")},
                         {"ok": False, "exit": 3, "message": "boom"})
        self.assertFalse(os.path.exists(engine.results_path(self.env)))

    def test_samples_without_people_or_devices(self):
        event, extra = self.sample("arrive")
        self.assertEqual((event["person"], extra), ({"id": "0" * 32, "name": "Test", "emoji": "🧪"}, "1|Test"))
        event, extra = self.sample("home-empty")
        self.assertEqual((event["message"], extra), ("Home is empty (Test left)", "1|"))
        event, _ = self.sample("unknown")
        self.assertEqual(event["device"], {"mac": "02:00:00:00:00:01", "ip": "192.168.1.50", "vendor": "Example",
                                           "hostname": "test-device"})
        self.assertEqual(event["message"], "New device on the network: Example · test-device · 192.168.1.50")
        event, _ = self.sample("alert")
        self.assertEqual(event["message"],
                         "IP address conflict: 192.168.1.50 moved from 02:00:00:00:00:01 to 02:00:00:00:00:02")

    def test_samples_use_the_chosen_person_and_the_latest_unknown_device(self):
        data = engine.empty_people()
        engine.save_person(data, {"name": "Ana", "emoji": "🐻", "devices": []})
        juan = engine.save_person(data, {"name": "Juan", "emoji": "🦊", "devices": []})
        engine.save_people(engine.people_path(self.env), data)
        state = engine.empty_state()
        engine.apply_sightings(state, {PHONE_MAC: "192.168.200.9"}, T0, 300)
        engine.apply_sightings(state, {SWITCH_MAC: "192.168.200.5"}, at(60), 300)
        engine.save_state(engine.state_path(self.env), state)
        event, _ = self.sample("leave", ["f" * 32, juan["id"]])
        self.assertEqual(event["person"]["name"], "Juan")
        event, _ = self.sample("arrive")
        self.assertEqual(event["person"]["name"], "Ana")
        event, _ = self.sample("unknown")
        self.assertEqual(event["device"]["mac"], SWITCH_MAC)

    def test_validation_errors(self):
        self.assertEqual(self.try_it({"command": "", "event": "arrive"}),
                         (1, {"error": "Command: between 1 and 1000 characters"}))
        self.assertEqual(self.try_it({"command": "true", "event": "party"}),
                         (1, {"error": "Events: unknown event party"}))
        self.assertEqual(self.try_it({"command": "true", "event": "arrive", "people": "x"}),
                         (1, {"error": "People: must be null or a list of person ids"}))


class RunCommandTest(RunnerCase):
    """Spec §3.1: run one Manual command against a device or a person."""

    def setUp(self):
        super().setUp()
        self.data = engine.empty_people()
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "🐻"})
        self.bare = engine.save_person(self.data, {"name": "Bo", "emoji": "🦉"})
        self.unseen = engine.save_person(self.data, {"name": "Cy", "emoji": "🦕"})
        engine.assign(self.data, GATEWAY_MAC, self.unseen["id"], "Old laptop")
        engine.assign(self.data, PHONE_MAC, self.ana["id"], "Pixel")
        engine.house(self.data, SWITCH_MAC, "Switch")
        self.show = 'printf "%s|%s|%s|%s" "$RECOGNITION_EVENT" "$RECOGNITION_MESSAGE" ' \
                    '"$RECOGNITION_DEVICE_IP" "$RECOGNITION_PERSON_NAME"'
        self.manual = engine.save_command(self.data, {"command": self.show, "events": ["manual"]})["id"]
        self.macs = engine.save_command(self.data, {"command": 'printf "%s" "$RECOGNITION_DEVICE_MAC"',
                                                    "events": ["manual"]})["id"]
        self.both = engine.save_command(self.data, {"command": "true", "events": ["manual", "arrive"]})["id"]
        self.auto = engine.save_command(self.data, {"command": "true", "events": ["arrive"]})["id"]
        engine.save_people(engine.people_path(self.env), self.data)
        state = engine.empty_state()
        state["devices"] = {PHONE_MAC: {"present": True, "ip": "192.168.200.9", "vendor": "Pearcorp",
                                        "hostname": "pixel", "lastSeen": engine.iso(T0)},
                            SWITCH_MAC: {"present": False, "ip": "192.168.200.5", "vendor": "Netgadget",
                                         "hostname": "", "lastSeen": engine.iso(at(-60))}}
        engine.save_state(engine.state_path(self.env), state)

    def run_it(self, command_id, target):
        return call(["run-command", command_id], self.env, stdin=json.dumps(target) + "\n")

    def test_a_device_target_gets_its_own_variables(self):
        code, payload = self.run_it(self.manual, {"mac": SWITCH_MAC})
        self.assertEqual(code, 0)
        self.assertEqual(sorted(payload["run"]), ["exit", "message", "ok", "output", "seconds", "truncated"])
        self.assertEqual(payload["run"]["output"], "manual|Switch|192.168.200.5|")

    def test_a_person_target_gets_the_person_and_the_chosen_device(self):
        code, payload = self.run_it(self.manual, {"personId": self.ana["id"]})
        self.assertEqual((code, payload["run"]["ok"]), (0, True))
        self.assertEqual(payload["run"]["output"], "manual|Ana|192.168.200.9|Ana")

    def test_a_person_without_devices_runs_without_device_variables(self):
        code, payload = self.run_it(self.manual, {"personId": self.bare["id"]})
        self.assertEqual((code, payload["run"]["ok"]), (0, True))
        self.assertEqual(payload["run"]["output"], "manual|Bo||Bo")

    def test_a_person_whose_device_was_never_seen_still_gets_its_mac(self):
        """What wake-on-LAN needs: the device is off, or the state knows nothing about it
        (a fresh or deleted state.json) — but the MAC is still the person's."""
        code, payload = self.run_it(self.manual, {"personId": self.unseen["id"]})
        self.assertEqual((code, payload["run"]["ok"]), (0, True))
        self.assertEqual(payload["run"]["output"], "manual|Cy||Cy")
        code, payload = self.run_it(self.macs, {"personId": self.unseen["id"]})
        self.assertEqual(payload["run"]["output"], GATEWAY_MAC)

    def test_a_person_target_with_a_mac_runs_on_the_device_the_user_picked(self):
        """The whole point: RANDOM_MAC is in no scan, so chosen_device would hand back the
        phone. Naming it in the target must win, and the person's variables must still
        arrive -- that is what a bare {"mac": ...} target cannot do."""
        engine.assign(self.data, RANDOM_MAC, self.ana["id"], "Desktop")
        engine.save_people(engine.people_path(self.env), self.data)
        code, payload = self.run_it(self.macs, {"personId": self.ana["id"], "mac": RANDOM_MAC})
        self.assertEqual((code, payload["run"]["output"]), (0, RANDOM_MAC))
        code, payload = self.run_it(self.manual, {"personId": self.ana["id"], "mac": RANDOM_MAC})
        self.assertEqual(payload["run"]["output"], "manual|Ana||Ana")

    def test_a_mac_that_is_not_theirs_is_refused(self):
        """The menu can sit open while the device is reassigned in another view. Running
        the command against someone else's device -- or against the house switch -- is
        worse than refusing."""
        for mac in (SWITCH_MAC, GATEWAY_MAC, "00:00:5e:00:53:77"):
            self.assertEqual(self.run_it(self.manual, {"personId": self.ana["id"], "mac": mac}),
                             (1, {"error": "That device is no longer theirs"}), mac)

    def test_an_empty_mac_falls_back_to_the_chosen_device(self):
        """A panel that was not restarted after the update still sends {"personId": ...}
        alone, and an empty string must read the same way as no key at all."""
        for target in ({"personId": self.ana["id"]}, {"personId": self.ana["id"], "mac": ""}):
            code, payload = self.run_it(self.manual, target)
            self.assertEqual((code, payload["run"]["output"]), (0, "manual|Ana|192.168.200.9|Ana"), target)

    def test_a_mac_in_a_different_case_still_matches(self):
        """people.json stores MACs lowercase; a target that shouts must not be refused."""
        engine.assign(self.data, RANDOM_MAC, self.ana["id"], "Desktop")
        engine.save_people(engine.people_path(self.env), self.data)
        code, payload = self.run_it(self.macs, {"personId": self.ana["id"], "mac": RANDOM_MAC.upper()})
        self.assertEqual((code, payload["run"]["output"]), (0, RANDOM_MAC))

    def test_the_other_groups_can_pick_a_device_too(self):
        """The person menu serves Home, Neighbors and Guests with the same code, so the
        target has to work for all three."""
        for group in ("neighbor", "guest"):
            person = engine.save_person(self.data, {"name": "Sam", "emoji": "🐸", "group": group})
            # The phone comes first, so chosen_device would hand it back: the test only
            # says something because the desktop can lose on its own.
            engine.assign(self.data, "00:00:5e:00:53:44", person["id"], "Phone")
            engine.assign(self.data, RANDOM_MAC, person["id"], "Desktop")  # assign releases the old owner
            engine.save_people(engine.people_path(self.env), self.data)
            code, payload = self.run_it(self.macs, {"personId": person["id"], "mac": RANDOM_MAC})
            self.assertEqual((code, payload["run"]["output"]), (0, RANDOM_MAC), group)

    def test_an_unassigned_device_is_named_by_what_the_panel_shows(self):
        """device_label's fallback: nobody owns this MAC, so the command is told the
        `vendor · hostname · ip` description the engine uses for an unowned device."""
        state = engine.load_state(engine.state_path(self.env))[0]
        state["devices"][RANDOM_MAC] = {"present": True, "ip": "192.168.200.30",
                                        "vendor": "Acme", "hostname": "printer",
                                        "lastSeen": engine.iso(T0)}
        engine.save_state(engine.state_path(self.env), state)
        code, payload = self.run_it(self.manual, {"mac": RANDOM_MAC})
        self.assertEqual((code, payload["run"]["ok"]), (0, True))
        self.assertEqual(payload["run"]["output"], "manual|Acme · printer · 192.168.200.30|192.168.200.30|")

    def test_a_house_device_the_state_has_forgotten_still_runs(self):
        """state.json is only a cache: deleting it must not make a House device — the
        NAS a wake-on-LAN command is for — unrunnable while the panel still shows it."""
        engine.save_state(engine.state_path(self.env), engine.empty_state())
        code, payload = self.run_it(self.macs, {"mac": SWITCH_MAC})
        self.assertEqual((code, payload["run"]["ok"]), (0, True))
        self.assertEqual(payload["run"]["output"], SWITCH_MAC)

    def test_a_mac_nobody_knows_is_still_unknown(self):
        engine.save_state(engine.state_path(self.env), engine.empty_state())
        self.assertEqual(self.run_it(self.manual, {"mac": "00:00:5e:00:53:77"}),
                         (1, {"error": "Unknown device"}))

    def test_running_by_hand_stores_nothing(self):
        code, _ = self.run_it(self.both, {"mac": SWITCH_MAC})
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(engine.results_path(self.env)))
        stored = engine.load_people(engine.people_path(self.env))["commands"]
        self.assertEqual([c["events"] for c in stored if c["id"] == self.both], [["arrive", "manual"]])

    def test_the_errors(self):
        for target, command_id, message in (
                ({"mac": SWITCH_MAC}, "f" * 32, "That command no longer exists"),
                ({"mac": SWITCH_MAC}, self.auto, "That command is not manual"),
                ({"mac": "00:00:5e:00:53:77"}, self.manual, "Unknown device"),
                ({"personId": "f" * 32}, self.manual, "That person no longer exists"),
                ({"personId": "f" * 32, "mac": PHONE_MAC}, self.manual, "That person no longer exists"),
                ({}, self.manual, "Not a valid MAC address")):
            self.assertEqual(self.run_it(command_id, target), (1, {"error": message}), (command_id, target))

    def test_a_missing_id_and_a_bad_body(self):
        self.assertEqual(call(["run-command"], self.env, stdin='{"mac": "%s"}\n' % SWITCH_MAC),
                         (1, {"error": "Missing the command id"}))
        self.assertEqual(call(["run-command", self.manual], self.env, stdin="[]\n"),
                         (1, {"error": "Input must be a JSON object"}))


class ReadilyCommandTest(RunnerCase):
    """A command that lives in a note: running it by hand, testing it, opening it."""

    def setUp(self):
        super().setUp()
        # RunnerCase.path() is a method, so the binary goes in `self.readily`.
        self.readily, _ = fake_readily(self.tmp.name)
        self.env["RECOGNITION_READILY_BIN"] = self.readily
        # The installed plugin has Readily as a sibling; pin PLUGIN_DIR so "not found"
        # means the same thing in a worktree and in ~/.config/omarchy/plugins.
        patch = mock.patch.object(engine, "PLUGIN_DIR", os.path.join(self.tmp.name, "plugins", "recognition"))
        patch.start()
        self.addCleanup(patch.stop)
        data = engine.empty_people()
        data["settings"]["readily"] = True
        self.ana = engine.save_person(data, {"name": "Ana", "emoji": "🐻"})
        engine.assign(data, PHONE_MAC, self.ana["id"], "Pixel")
        engine.save_people(engine.people_path(self.env), data)
        state = engine.empty_state()
        state["devices"] = {PHONE_MAC: {"present": True, "ip": "192.168.200.9", "vendor": "Pearcorp",
                                        "hostname": "pixel", "lastSeen": engine.iso(T0)}}
        engine.save_state(engine.state_path(self.env), state)
        self.show = 'printf "%s|%s" "$RECOGNITION_EVENT" "$RECOGNITION_PERSON_NAME"'
        self.wake = engine.readily_id("commands", "Wake")

    def listing(self, tags=("recognition/manual",), command=None):
        items = [readily_item("Wake", command or self.show, tags=list(tags))]
        return FakeRun({self.readily: (0, readily_listing({"commands": items}), "")})

    def on_ana(self):
        return json.dumps({"personId": self.ana["id"]}) + "\n"

    def test_a_readily_manual_command_runs_on_a_person(self):
        code, payload = call(["run-command", self.wake], self.env, stdin=self.on_ana(), run=self.listing())
        self.assertEqual(code, 0)
        self.assertEqual(payload["run"]["output"], "manual|Ana")

    def test_a_readily_command_runs_on_the_device_the_user_picked(self):
        """run_manual is the same path for a stored command and one that lives in a note."""
        run = self.listing(command='printf "%s|%s" "$RECOGNITION_PERSON_NAME" "$RECOGNITION_DEVICE_MAC"')
        target = json.dumps({"personId": self.ana["id"], "mac": PHONE_MAC}) + "\n"
        code, payload = call(["run-command", self.wake], self.env, stdin=target, run=run)
        self.assertEqual((code, payload["run"]["output"]), (0, "Ana|" + PHONE_MAC))

    def test_a_multi_line_readily_command_runs(self):
        run = self.listing(command='printf "one"\nprintf "|two"')
        code, payload = call(["run-command", self.wake], self.env, stdin=self.on_ana(), run=run)
        self.assertEqual(payload["run"]["output"], "one|two")

    def test_a_readily_command_that_is_not_manual_is_refused(self):
        code, payload = call(["run-command", self.wake], self.env, stdin=self.on_ana(),
                             run=self.listing(tags=["recognition/arrive"]))
        self.assertEqual((code, payload), (1, {"error": "That command is not manual"}))

    def test_an_id_no_note_has_any_more(self):
        code, payload = call(["run-command", "d" * 32], self.env, stdin=self.on_ana(), run=self.listing())
        self.assertEqual((code, payload), (1, {"error": "That command no longer exists"}))

    def test_with_the_switch_off_a_readily_id_is_gone_and_readily_is_never_called(self):
        data = engine.load_people(engine.people_path(self.env))
        data["settings"]["readily"] = False
        engine.save_people(engine.people_path(self.env), data)
        run = self.listing()
        code, payload = call(["run-command", self.wake], self.env, stdin=self.on_ana(), run=run)
        self.assertEqual((code, payload), (1, {"error": "That command no longer exists"}))
        self.assertEqual(run.calls, [])

    def test_testing_a_readily_command_uses_its_first_event(self):
        run = self.listing(tags=["recognition/arrive", "recognition/manual"],
                           command='printf "%s" "$RECOGNITION_EVENT"')
        code, payload = call(["test-command"], self.env, stdin='{"readilyId": "%s"}\n' % self.wake, run=run)
        self.assertEqual(code, 0)
        self.assertTrue(payload["test"]["ok"])

    def test_testing_a_readily_id_that_is_gone(self):
        code, payload = call(["test-command"], self.env, stdin='{"readilyId": "%s"}\n' % ("d" * 32),
                             run=self.listing())
        self.assertEqual((code, payload), (1, {"error": "That command no longer exists"}))

    def test_a_native_test_never_reads_readily(self):
        run = self.listing()
        code, payload = call(["test-command"], self.env, stdin='{"command": "true", "event": "arrive"}\n', run=run)
        self.assertEqual(code, 0)
        self.assertEqual(run.calls, [])

    def test_opening_a_note_hands_it_to_readily(self):
        run = FakeRun({self.readily: (0, "", "")})
        code, payload = call(["readily-open", "commands"], self.env, run=run)
        self.assertEqual((code, payload), (0, {"opened": "commands"}))
        self.assertEqual(run.calls, [[self.readily, "open", "commands"]])

    def test_opening_a_note_is_bounded(self):
        run = FakeRun({self.readily: (0, "", "")})
        call(["readily-open", "commands"], self.env, run=run)
        self.assertEqual(run.kwargs[0]["timeout"], engine.READILY_TIMEOUT)
        self.assertIs(run.kwargs[0]["stdin"], subprocess.DEVNULL)

    def test_opening_without_readily_installed(self):
        environ = dict(self.env, RECOGNITION_READILY_BIN="/nonexistent/readily", PATH="")
        self.assertEqual(call(["readily-open", "commands"], environ), (1, {"error": "Readily not found"}))

    def test_a_note_readily_cannot_open(self):
        run = FakeRun({self.readily: (1, "", "readily: There is no section named ghost\n")})
        code, payload = call(["readily-open", "ghost"], self.env, run=run)
        self.assertEqual((code, payload), (1, {"error": "readily: There is no section named ghost"}))

    def test_a_failure_readily_says_nothing_about(self):
        run = FakeRun({self.readily: (1, "", "")})
        code, payload = call(["readily-open", "commands"], self.env, run=run)
        self.assertEqual((code, payload), (1, {"error": "Readily couldn't open that note"}))

    def test_opening_needs_a_note(self):
        self.assertEqual(call(["readily-open"], self.env), (1, {"error": "Missing the note"}))


class ReadilyResultsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = env(self.tmp.name)

    def result(self, at, ok=True):
        return {"at": at, "event": "arrive", "command": "true", "source": "readily",
                "ok": ok, "exit": 0 if ok else 1, "message": "", "seconds": 0.1}

    def test_a_readily_result_is_kept_although_no_command_in_people_json_has_that_id(self):
        engine.record_result(self.env, "d" * 32, self.result("2026-09-23T18:00:00Z"))
        self.assertIn("d" * 32, engine.load_results(self.env))

    def test_pruning_after_an_edit_leaves_readily_results_alone(self):
        engine.record_result(self.env, "d" * 32, self.result("2026-09-23T18:00:00Z"))
        engine.prune_results(self.env, engine.empty_people())
        self.assertIn("d" * 32, engine.load_results(self.env))

    def test_only_the_newest_fifty_readily_results_are_kept(self):
        for n in range(engine.READILY_RESULTS_MAX + 5):
            engine.record_result(self.env, "%032x" % n, self.result("2026-09-23T18:%02d:00Z" % n))
        kept = engine.load_results(self.env)
        self.assertEqual(len(kept), engine.READILY_RESULTS_MAX)
        self.assertNotIn("%032x" % 0, kept)
        self.assertIn("%032x" % (engine.READILY_RESULTS_MAX + 4), kept)

    def test_the_cap_never_touches_a_native_result(self):
        data = engine.empty_people()
        data["commands"].append({"id": "c" * 32, "command": "true", "events": ["arrive"], "people": None})
        engine.save_people(engine.people_path(self.env), data)
        engine.record_result(self.env, "c" * 32, {"at": "2026-09-23T17:00:00Z", "event": "arrive",
                                                  "command": "true", "ok": True, "exit": 0, "message": "",
                                                  "seconds": 0.1})
        for n in range(engine.READILY_RESULTS_MAX + 5):
            engine.record_result(self.env, "%032x" % n, self.result("2026-09-23T18:%02d:00Z" % n))
        kept = engine.load_results(self.env)
        self.assertIn("c" * 32, kept)
        self.assertEqual(len(kept), engine.READILY_RESULTS_MAX + 1)

    def test_the_runner_records_where_the_command_came_from(self):
        job = {"id": "d" * 32, "command": "true", "event": "arrive", "env": {}, "source": "readily"}
        engine.run_jobs([job], self.env, clock=lambda: T0)
        self.assertEqual(engine.load_results(self.env)["d" * 32]["source"], "readily")

    def test_a_native_result_has_no_source_key(self):
        # record_result only keeps a native result whose command text still matches
        # people.json, so the fixture needs a real current command for "c" * 32.
        data = engine.empty_people()
        data["commands"].append({"id": "c" * 32, "command": "true", "events": ["arrive"], "people": None})
        engine.save_people(engine.people_path(self.env), data)
        job = {"id": "c" * 32, "command": "true", "event": "arrive", "env": {}}
        engine.run_jobs([job], self.env, clock=lambda: T0)
        self.assertNotIn("source", engine.load_results(self.env)["c" * 32])


if __name__ == "__main__":
    unittest.main()
