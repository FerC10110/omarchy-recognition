import json
import os
import subprocess
import tempfile
import unittest

from _load import load
from fakes import FakeRun, PHONE_MAC, T0, at, env

engine = load()
A, B, C, D = "00:00:5e:00:53:09", "c2:00:00:00:01:12", "00:00:5e:00:53:05", "00:00:5e:00:53:30"
SUMMON = ["--exec", "omarchy-shell", "shell", "summon", "io.github.ferc10110.recognition"]


class NotificationTest(unittest.TestCase):
    def setUp(self):
        self.settings = engine.empty_people()["settings"]
        self.ana = {"id": "a" * 32, "name": "Ana", "emoji": "🐻", "devices": []}
        self.devices = {B: {"ip": "192.168.200.55", "hostname": "Android_3f2a", "vendor": "Samsung",
                            "randomMac": False}}

    def test_every_kind(self):
        gateway = {"kind": "gateway-mac", "data": {"ip": "192.168.200.1", "expectedMac": "02:00:00:00:00:01",
                                                    "seenMac": "aa:bb:cc:dd:ee:ff"}}
        conflict = {"kind": "ip-conflict", "data": {"ip": "192.168.200.9", "previousMac": A, "mac": C}}
        calls = engine.build_notifications(self.settings, [self.ana], [self.ana], [B],
                                           [gateway, conflict], self.devices)
        self.assertEqual(calls, [
            ["omarchy-notification-send", "-g", "🐻", "-u", "normal", "Ana arrived home"],
            ["omarchy-notification-send", "-g", "🐻", "-u", "low", "Ana left"],
            ["omarchy-notification-send", "-g", engine.WARNING_GLYPH, "-u", "normal", "New device on the network",
             "Samsung · Android_3f2a · 192.168.200.55"] + SUMMON,
            ["omarchy-notification-send", "-g", engine.WARNING_GLYPH, "-u", "critical", "Router MAC changed",
             "192.168.200.1: expected 02:00:00:00:00:01, answered aa:bb:cc:dd:ee:ff"] + SUMMON,
            ["omarchy-notification-send", "-g", engine.WARNING_GLYPH, "-u", "normal", "IP address conflict",
             f"192.168.200.9 moved from {A} to {C}"] + SUMMON,
        ])

    def test_switches_silence_each_kind(self):
        self.settings["notify"] = {"arrive": False, "leave": False, "neighbor": False, "guest": False,
                                   "unknown": False, "security": False, "home": False}
        alert = {"kind": "ip-conflict", "data": {"ip": "x", "previousMac": A, "mac": C}}
        self.assertEqual(engine.build_notifications(self.settings, [self.ana], [self.ana], [B], [alert],
                                                    self.devices), [])

    def test_describe_device_fallbacks(self):
        self.assertEqual(engine.describe_device({"randomMac": True, "ip": "192.168.200.7"}, B),
                         "Random MAC · 192.168.200.7")
        self.assertEqual(engine.describe_device({}, D), D)

    def test_send_ignores_failures(self):
        run = FakeRun({"omarchy-notification-send": FileNotFoundError("x")})
        engine.send_notifications([["omarchy-notification-send", "hola"]], run)
        slow = FakeRun({"omarchy-notification-send": subprocess.TimeoutExpired("x", 5)})
        engine.send_notifications([["omarchy-notification-send", "hola"]], slow)
        self.assertEqual(len(run.calls) + len(slow.calls), 2)


class NeighborNotifyTest(unittest.TestCase):
    def setUp(self):
        self.data = engine.empty_people()
        self.sam = engine.save_person(self.data, {"name": "Sam", "emoji": "🐸", "group": "neighbor"})
        self.settings = engine.empty_people()["settings"]

    def test_a_neighbor_uses_its_own_texts(self):
        calls = engine.build_notifications(self.settings, [self.sam], [], [], [], {})
        self.assertEqual(calls[0][-1], "Sam joined the Wi-Fi")

    def test_the_neighbor_switch_silences_them(self):
        settings = dict(self.settings, notify=dict(self.settings["notify"], neighbor=False))
        self.assertEqual(engine.build_notifications(settings, [self.sam], [self.sam], [], [], {}), [])

    def test_the_arrive_switch_does_not_cover_neighbors(self):
        settings = dict(self.settings, notify=dict(self.settings["notify"], arrive=False))
        calls = engine.build_notifications(settings, [self.sam], [], [], [], {})
        self.assertEqual(len(calls), 1)


class GuestNotifyTest(unittest.TestCase):
    def setUp(self):
        self.data = engine.empty_people()
        self.sam = engine.save_person(self.data, {"name": "Sam", "emoji": "🦊", "group": "guest"})
        self.settings = engine.empty_people()["settings"]

    def test_a_guest_uses_its_own_texts(self):
        calls = engine.build_notifications(self.settings, [self.sam], [self.sam], [], [], {})
        self.assertEqual([call[-1] for call in calls], ["Sam is visiting", "Sam went home"])

    def test_the_guest_switch_silences_them(self):
        settings = dict(self.settings, notify=dict(self.settings["notify"], guest=False))
        self.assertEqual(engine.build_notifications(settings, [self.sam], [self.sam], [], [], {}), [])

    def test_the_arrive_switch_does_not_cover_guests(self):
        settings = dict(self.settings, notify=dict(self.settings["notify"], guest=False, arrive=True, leave=True))
        self.assertEqual(engine.build_notifications(settings, [self.sam], [self.sam], [], [], {}), [])


class PersonSwitchNotifyTest(unittest.TestCase):
    def setUp(self):
        self.data = engine.empty_people()
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "🐻"})
        self.quiet = engine.save_person(self.data, {"name": "Juan", "emoji": "🦊", "notify": False})
        self.sam = engine.save_person(self.data, {"name": "Sam", "emoji": "🐸",
                                                  "group": "neighbor", "notify": False})
        self.settings = engine.empty_people()["settings"]

    def test_a_silent_person_notifies_neither_arriving_nor_leaving(self):
        self.assertEqual(engine.build_notifications(self.settings, [self.quiet], [self.quiet],
                                                    [], [], {}), [])

    def test_the_others_still_notify(self):
        calls = engine.build_notifications(self.settings, [self.ana, self.quiet], [], [], [], {})
        self.assertEqual([call[-1] for call in calls], ["Ana arrived home"])

    def test_the_master_switch_still_wins_over_a_person_who_notifies(self):
        settings = dict(self.settings, notify=dict(self.settings["notify"], arrive=False))
        self.assertEqual(engine.build_notifications(settings, [self.ana], [], [], [], {}), [])

    def test_the_master_switch_still_wins_over_a_person_who_notifies_leaving(self):
        settings = dict(self.settings, notify=dict(self.settings["notify"], leave=False))
        self.assertEqual(engine.build_notifications(settings, [], [self.ana], [], [], {}), [])

    def test_a_silent_neighbor_does_not_notify_either(self):
        self.assertEqual(engine.build_notifications(self.settings, [self.sam], [self.sam],
                                                    [], [], {}), [])


class HomeNotifyTest(unittest.TestCase):
    def setUp(self):
        self.data = engine.empty_people()
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "🐻"})
        self.settings = engine.empty_people()["settings"]
        self.on = dict(self.settings, notify=dict(self.settings["notify"], home=True))

    def occupied(self):
        return engine.build_events([self.ana], [], [], [], {}, 0, ["Ana"], T0)

    def empty(self):
        return engine.build_events([], [self.ana], [], [], {}, 1, [], T0)

    def test_off_by_default_nothing_is_sent(self):
        self.assertEqual(engine.build_home_notifications(self.settings, self.occupied()), [])
        self.assertEqual(engine.build_home_notifications(self.settings, self.empty()), [])

    def test_the_house_filling_up_notifies_with_the_text_of_the_event(self):
        events = self.occupied()
        message = [e["message"] for e in events if e["event"] == "home-occupied"][0]
        calls = engine.build_home_notifications(self.on, events)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], engine.HOME_GLYPH)
        self.assertEqual(calls[0][-1], message)
        self.assertEqual(calls[0][-2], "normal")

    def test_the_house_emptying_out_is_low_urgency(self):
        calls = engine.build_home_notifications(self.on, self.empty())
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][-1], "Home is empty (Ana left)")
        self.assertEqual(calls[0][-2], "low")

    def test_a_plain_arrival_that_does_not_change_the_house_notifies_nothing(self):
        events = engine.build_events([self.ana], [], [], [], {}, 2, ["Ana"], T0)
        self.assertEqual(engine.build_home_notifications(self.on, events), [])

    def test_a_silent_person_still_names_the_house_in_the_home_notification(self):
        # README ruling: "Silent" silences the person's own arrive/leave
        # notification, but Home is about the house, not the person, so the
        # first one home (or the last one out) is still named in its text.
        quiet = engine.save_person(self.data, {"name": "Juan", "emoji": "🦊", "notify": False})
        self.assertEqual(engine.build_notifications(self.settings, [quiet], [], [], [], {}), [])
        events = engine.build_events([quiet], [], [], [], {}, 0, ["Juan"], T0)
        calls = engine.build_home_notifications(self.on, events)
        self.assertEqual(len(calls), 1)
        self.assertIn("Juan", calls[0][-1])


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.state = engine.empty_state()
        self.data = engine.empty_people()
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "🐻", "devices": [{"mac": A, "label": "Pixel"}]})
        self.juan = engine.save_person(self.data, {"name": "Juan", "emoji": "🦊", "devices": [{"mac": C}]})
        self.zoe = engine.save_person(self.data, {"name": "Zoe", "emoji": "🐱", "devices": []})
        engine.house(self.data, D, "Tele")

    def test_shape_and_order(self):
        engine.apply_sightings(self.state, {C: "192.168.200.5", D: "192.168.200.102"}, T0, 300)
        engine.apply_sightings(self.state, {A: "192.168.200.9", B: "192.168.200.112"}, at(60), 300)
        engine.apply_sightings(self.state, {A: "192.168.200.9", B: "192.168.200.112"}, at(400), 300)
        status = engine.build_status(self.data, self.state, at(400))
        self.assertEqual(sorted(status), ["alerts", "commands", "error", "guests", "house", "lastScan",
                                          "neighbors", "people", "readily", "settings", "subnet", "unknown"])
        self.assertEqual([p["name"] for p in status["people"]], ["Ana", "Juan", "Zoe"])
        ana, juan, zoe = status["people"]
        self.assertEqual((ana["present"], ana["since"], ana["lastSeen"]),
                         (True, "2026-09-17T21:01:00Z", "2026-09-17T21:06:40Z"))
        self.assertEqual(ana["devices"], [{"mac": A, "label": "Pixel", "counts": True, "present": True,
                                           "ip": "192.168.200.9", "lastSeen": "2026-09-17T21:06:40Z"}])
        self.assertEqual((juan["present"], juan["lastSeen"]), (False, "2026-09-17T21:00:00Z"))
        self.assertEqual((zoe["present"], zoe["lastSeen"], zoe["devices"]), (False, None, []))
        self.assertEqual([u["mac"] for u in status["unknown"]], [B])
        self.assertEqual(status["unknown"][0]["present"], True)
        self.assertEqual(status["house"], [{"mac": D, "label": "Tele", "present": False, "ip": "192.168.200.102",
                                            "lastSeen": "2026-09-17T21:00:00Z"}])
        self.assertEqual(status["settings"], self.data["settings"])

    def test_a_device_that_does_not_count_says_so(self):
        self.data["people"][0]["devices"][0]["counts"] = False
        status = engine.build_status(self.data, self.state, at(400))
        ana = next(person for person in status["people"] if person["name"] == "Ana")
        self.assertIs(ana["devices"][0]["counts"], False)

    def test_present_people_ordered_by_arrival(self):
        engine.apply_sightings(self.state, {C: "192.168.200.5"}, T0, 300)
        engine.apply_sightings(self.state, {A: "192.168.200.9", C: "192.168.200.5"}, at(60), 300)
        names = [p["name"] for p in engine.build_status(self.data, self.state, at(60))["people"]]
        self.assertEqual(names, ["Juan", "Ana", "Zoe"])

    def test_unknown_older_than_a_day_is_hidden(self):
        engine.apply_sightings(self.state, {B: "192.168.200.112"}, T0, 300)
        self.assertEqual(engine.build_status(self.data, self.state, at(86400))["unknown"][0]["mac"], B)
        self.assertEqual(engine.build_status(self.data, self.state, at(86401))["unknown"], [])

    def test_house_lists_online_first_then_by_label(self):
        engine.house(self.data, B, "tv")
        engine.house(self.data, "aa:bb:cc:00:11:22", "Printer")
        engine.apply_sightings(self.state, {B: "192.168.200.112"}, T0, 300)
        house = engine.build_status(self.data, self.state, T0)["house"]
        self.assertEqual([(d["label"], d["present"]) for d in house],
                         [("tv", True), ("Printer", False), ("Tele", False)])
        self.assertEqual((house[1]["ip"], house[1]["lastSeen"]), ("", None))
        self.assertEqual(house[0]["ip"], "192.168.200.112")

    def test_house_order_is_case_insensitive_with_mac_tie_break(self):
        # "apple" sorts before "Banana" only when the label compare is
        # case-insensitive (raw string compare puts capitals first). The two
        # "Banana" entries share a label but differ only by MAC, inserted in
        # the "wrong" (descending) order, to prove the MAC tie-break sorts
        # them ascending rather than leaving them in insertion order.
        banana_hi, banana_lo = "22:22:22:22:22:02", "22:22:22:22:22:01"
        apple_mac = "11:22:33:44:55:66"
        engine.house(self.data, banana_hi, "Banana")
        engine.house(self.data, apple_mac, "apple")
        engine.house(self.data, banana_lo, "Banana")
        house = engine.build_status(self.data, self.state, T0)["house"]
        self.assertEqual([(d["label"], d["mac"]) for d in house],
                         [("apple", apple_mac), ("Banana", banana_lo), ("Banana", banana_hi), ("Tele", D)])

    def test_commands_show_their_last_result_only_for_the_same_text(self):
        same = engine.save_command(self.data, {"command": "true", "events": ["arrive"], "people": None})
        edited = engine.save_command(self.data, {"command": "echo new", "events": ["leave"],
                                                 "people": [self.ana["id"]]})
        never = engine.save_command(self.data, {"command": "false", "events": ["alert"], "people": None})
        result = {"at": "2026-09-17T21:00:00Z", "event": "arrive", "ok": True, "exit": 0, "message": "",
                  "seconds": 0.1}
        results = {same["id"]: dict(result, command="true"), edited["id"]: dict(result, command="echo old")}
        status = engine.build_status(self.data, self.state, T0, results)
        self.assertEqual(status["commands"], [
            {"id": same["id"], "command": "true", "events": ["arrive"], "people": None, "last": result},
            {"id": edited["id"], "command": "echo new", "events": ["leave"], "people": [self.ana["id"]],
             "last": None},
            {"id": never["id"], "command": "false", "events": ["alert"], "people": None, "last": None}])
        self.assertIsNone(engine.build_status(self.data, self.state, T0)["commands"][0]["last"])


class NeighborStatusTest(unittest.TestCase):
    def setUp(self):
        self.data = engine.empty_people()
        self.home = engine.save_person(self.data, {"name": "Ana", "emoji": "🐻"})
        self.neighbor = engine.save_person(self.data, {"name": "Sam", "emoji": "🐸", "group": "neighbor"})
        self.state = {"devices": {}, "people": {}, "alerts": [], "lastScan": None}

    def test_people_holds_the_house_and_neighbors_holds_the_rest(self):
        status = engine.build_status(self.data, self.state, T0)
        self.assertEqual([p["name"] for p in status["people"]], ["Ana"])
        self.assertEqual([p["name"] for p in status["neighbors"]], ["Sam"])

    def test_a_neighbor_view_has_the_same_shape_as_a_person(self):
        status = engine.build_status(self.data, self.state, T0)
        keys = ["id", "name", "emoji", "group", "notify", "present", "since", "lastSeen", "devices"]
        self.assertEqual(sorted(status["neighbors"][0]), sorted(keys))
        self.assertEqual(sorted(status["people"][0]), sorted(keys))

    def test_a_neighbors_device_is_not_an_unknown_device(self):
        engine.assign(self.data, PHONE_MAC, self.neighbor["id"], "Sam's phone")
        state = dict(self.state, devices={PHONE_MAC: {"present": True, "since": engine.iso(T0),
                                                      "lastSeen": engine.iso(T0),
                                                      "firstSeen": engine.iso(T0), "ip": "192.168.1.50"}})
        status = engine.build_status(self.data, state, T0)
        self.assertEqual(status["unknown"], [])
        self.assertTrue(status["neighbors"][0]["present"])

    def test_a_neighbors_device_that_does_not_count_says_so(self):
        engine.assign(self.data, PHONE_MAC, self.neighbor["id"], "Sam's phone")
        self.neighbor["devices"][0]["counts"] = False
        status = engine.build_status(self.data, self.state, T0)
        self.assertIs(status["neighbors"][0]["devices"][0]["counts"], False)


class ResultsFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = env(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_paths(self):
        environ = {"HOME": "/h", "XDG_STATE_HOME": "/s"}
        self.assertEqual(engine.results_path(environ), "/s/recognition/commands.json")
        self.assertEqual(engine.results_lock_path(environ), "/s/recognition/commands.lock")

    def test_missing_or_broken_file_is_empty(self):
        self.assertEqual(engine.load_results(self.env), {})
        path = engine.results_path(self.env)
        os.makedirs(os.path.dirname(path))
        for text in ("{broken", "[]", '{"results": []}', '{"results": {"x": 1}}'):
            with open(path, "w") as fh:
                fh.write(text)
            self.assertEqual(engine.load_results(self.env), {}, text)
        with open(path, "w") as fh:
            json.dump({"version": 1, "results": {"x": {"ok": True}, "y": "bad"}}, fh)
        self.assertEqual(engine.load_results(self.env), {"x": {"ok": True}})


class SuggestOwnerTest(unittest.TestCase):
    """A phone that rotates its MAC keeps its network name: the old device dies and a
    new one is born with the same hostname."""

    def setUp(self):
        self.data = engine.empty_people()
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "🐻",
                                                  "devices": [{"mac": A, "label": "Pixel"}]})

    def devices(self, old=None, new=None):
        """The state's device table: Ana's old phone, gone, and the unknown that replaced it."""
        old = dict({"hostname": "Pixel", "present": False, "lastSeen": engine.iso(T0)}, **(old or {}))
        new = dict({"hostname": "Pixel", "present": True, "firstSeen": engine.iso(at(60)),
                    "lastSeen": engine.iso(at(60))}, **(new or {}))
        return {A: old, B: new}

    def suggest(self, old=None, new=None):
        table = self.devices(old, new)
        return engine.suggest_owner(table[B], self.data, table)

    def test_the_new_device_is_suggested_for_the_owner_of_the_old_one(self):
        self.assertEqual(self.suggest(),
                         {"personId": self.ana["id"], "name": "Ana", "emoji": "🐻",
                          "mac": A, "label": "Pixel", "lastSeen": engine.iso(T0)})

    def test_an_unknown_without_a_hostname_is_not_matched(self):
        self.assertIsNone(self.suggest(new={"hostname": ""}))

    def test_a_different_hostname_is_not_matched(self):
        self.assertIsNone(self.suggest(new={"hostname": "Galaxy"}))

    def test_a_device_still_on_the_network_is_not_the_one_that_left(self):
        self.assertIsNone(self.suggest(old={"present": True}))

    def test_an_old_device_seen_after_the_new_one_appeared_is_not_matched(self):
        self.assertIsNone(self.suggest(old={"lastSeen": engine.iso(at(120))}))

    def test_an_old_device_last_seen_when_the_new_one_appeared_is_not_matched(self):
        self.assertIsNone(self.suggest(old={"lastSeen": engine.iso(at(60))}))

    def test_the_domain_suffix_and_the_case_are_noise(self):
        self.assertIsNotNone(self.suggest(old={"hostname": "pixel"}, new={"hostname": "Pixel.local"}))

    def test_two_candidates_suggest_nothing(self):
        juan = engine.save_person(self.data, {"name": "Juan", "emoji": "🦊",
                                              "devices": [{"mac": C, "label": "Phone"}]})
        table = self.devices()
        table[C] = {"hostname": "Pixel", "present": False, "lastSeen": engine.iso(T0)}
        self.assertIsNone(engine.suggest_owner(table[B], self.data, table))

    def test_two_devices_of_the_same_person_point_at_that_person(self):
        """A second rotation: Ana already owns the MAC her first rotation left behind."""
        engine.assign(self.data, C, self.ana["id"], "Spare")
        table = self.devices()
        table[C] = {"hostname": "Pixel", "present": False, "lastSeen": engine.iso(at(30))}
        suggestion = engine.suggest_owner(table[B], self.data, table)
        self.assertEqual((suggestion["personId"], suggestion["mac"], suggestion["label"]),
                         (self.ana["id"], C, "Spare"))

    def test_a_missing_timestamp_is_not_an_exception(self):
        self.assertIsNone(self.suggest(new={"firstSeen": None}))
        self.assertIsNone(self.suggest(old={"lastSeen": None}))

    def test_a_state_record_with_the_wrong_types_is_not_an_exception(self):
        """`load_state` only checks that a device record is a dict: a hand-edited or
        corrupted state file reaches here with anything inside."""
        self.assertIsNone(self.suggest(new={"hostname": ["Pixel"]}))
        self.assertIsNone(self.suggest(new={"firstSeen": 1758391200}))
        self.assertIsNone(self.suggest(old={"hostname": 42}))
        self.assertIsNone(self.suggest(old={"lastSeen": 1758391200}))
        self.assertIsNone(self.suggest(new={"firstSeen": ""}))
        self.assertIsNone(self.suggest(old={"lastSeen": ""}))

    def test_an_old_device_with_no_record_in_the_state_is_not_a_candidate(self):
        table = self.devices()
        del table[A]
        self.assertIsNone(engine.suggest_owner(table[B], self.data, table))

    def test_accepting_leaves_the_person_with_both_devices(self):
        suggestion = self.suggest()
        engine.assign(self.data, B, suggestion["personId"], suggestion["label"])
        self.assertEqual([(d["mac"], d["label"]) for d in self.data["people"][0]["devices"]],
                         [(A, "Pixel"), (B, "Pixel")])

    def test_a_neighbor_gets_the_suggestion_too(self):
        data = engine.empty_people()
        sam = engine.save_person(data, {"name": "Sam", "emoji": "🐸", "group": "neighbor",
                                        "devices": [{"mac": A, "label": "Phone"}]})
        table = self.devices()
        self.assertEqual(engine.suggest_owner(table[B], data, table)["personId"], sam["id"])


class SuggestionInStatusTest(unittest.TestCase):
    def setUp(self):
        self.data = engine.empty_people()
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "🐻",
                                                  "devices": [{"mac": A, "label": "Pixel"}]})
        self.state = engine.empty_state()
        self.state["devices"] = {
            A: {"hostname": "Pixel", "present": False, "lastSeen": engine.iso(T0)},
            B: {"hostname": "Pixel", "present": True, "ip": "192.168.200.7",
                "firstSeen": engine.iso(at(60)), "lastSeen": engine.iso(at(60))},
            C: {"hostname": "", "present": True, "ip": "192.168.200.8",
                "firstSeen": engine.iso(at(60)), "lastSeen": engine.iso(at(60))}}

    def test_only_the_matching_unknown_carries_the_key(self):
        status = engine.build_status(self.data, self.state, at(90))
        by_mac = {device["mac"]: device for device in status["unknown"]}
        self.assertEqual(by_mac[B]["suggestion"]["name"], "Ana")
        self.assertNotIn("suggestion", by_mac[C])

    def test_a_suggestion_does_not_outlive_the_listing_window(self):
        """The same device that carries a suggestion is gone once it is too old to list."""
        recent = engine.build_status(self.data, self.state, at(90))
        self.assertIn("suggestion", {device["mac"]: device for device in recent["unknown"]}[B])
        stale = engine.build_status(self.data, self.state, at(engine.RECENT_UNKNOWN + 120))
        self.assertEqual(stale["unknown"], [])


class GuestStatusTest(unittest.TestCase):
    def setUp(self):
        self.data = engine.empty_people()
        self.home = engine.save_person(self.data, {"name": "Ana", "emoji": "🐻"})
        self.guest = engine.save_person(self.data, {"name": "Sam", "emoji": "🦊", "group": "guest"})
        self.state = {"devices": {}, "people": {}, "alerts": [], "lastScan": None}

    def test_each_group_has_its_own_list(self):
        status = engine.build_status(self.data, self.state, T0)
        self.assertEqual([p["name"] for p in status["people"]], ["Ana"])
        self.assertEqual(status["neighbors"], [])
        self.assertEqual([p["name"] for p in status["guests"]], ["Sam"])

    def test_guests_ordered_present_then_away_then_never_seen(self):
        engine.save_person(self.data, {"name": "Kim", "emoji": "🐨", "group": "guest",
                                       "devices": [{"mac": A}]})
        engine.save_person(self.data, {"name": "Val", "emoji": "🐢", "group": "guest",
                                       "devices": [{"mac": B}]})
        engine.save_person(self.data, {"name": "Zoe", "emoji": "🐱", "group": "guest",
                                       "devices": [{"mac": C}]})
        engine.save_person(self.data, {"name": "Uma", "emoji": "🐧", "group": "guest",
                                       "devices": [{"mac": D}]})
        engine.save_person(self.data, {"name": "Kai", "emoji": "🦁", "group": "guest"})
        engine.apply_sightings(self.state, {D: "192.168.200.102", A: "192.168.200.9"}, T0, 300)
        engine.apply_sightings(self.state, {C: "192.168.200.5", A: "192.168.200.9"}, at(100), 300)
        engine.apply_sightings(self.state, {A: "192.168.200.9", B: "192.168.200.112"}, at(500), 300)
        names = [p["name"] for p in engine.build_status(self.data, self.state, at(500))["guests"]]
        self.assertEqual(names, ["Kim", "Val", "Zoe", "Uma", "Kai", "Sam"])

    def test_a_guest_view_has_the_same_shape_as_a_person(self):
        status = engine.build_status(self.data, self.state, T0)
        keys = ["id", "name", "emoji", "group", "notify", "present", "since", "lastSeen", "devices"]
        self.assertEqual(sorted(status["guests"][0]), sorted(keys))

    def test_a_guests_device_is_not_an_unknown_device(self):
        engine.assign(self.data, PHONE_MAC, self.guest["id"], "Sam's phone")
        state = dict(self.state, devices={PHONE_MAC: {"present": True, "since": engine.iso(T0),
                                                      "lastSeen": engine.iso(T0),
                                                      "firstSeen": engine.iso(T0), "ip": "192.168.1.50"}})
        self.assertEqual(engine.build_status(self.data, state, T0)["unknown"], [])

    def test_a_guests_device_that_does_not_count_says_so(self):
        engine.assign(self.data, PHONE_MAC, self.guest["id"], "Sam's phone")
        self.guest["devices"][0]["counts"] = False
        status = engine.build_status(self.data, self.state, T0)
        self.assertIs(status["guests"][0]["devices"][0]["counts"], False)


READILY_COMMAND = {"id": "d" * 32, "command": "true", "events": ["arrive", "manual"], "people": None,
                   "source": "readily", "note": "commands", "title": "Wake the desktop"}


class ReadilyStatusTest(unittest.TestCase):
    def setUp(self):
        self.data = engine.empty_people()
        self.state = engine.empty_state()

    def test_readily_commands_come_after_the_native_ones(self):
        self.data["commands"] = [{"id": "c" * 32, "command": "false", "events": ["leave"], "people": None}]
        readily = {"commands": [READILY_COMMAND], "ok": True, "warning": "", "skipped": 0}
        status = engine.build_status(self.data, self.state, T0, {}, readily)
        self.assertEqual([c["id"] for c in status["commands"]], ["c" * 32, "d" * 32])
        self.assertNotIn("source", status["commands"][0])
        self.assertEqual(status["commands"][1]["source"], "readily")
        self.assertEqual(status["commands"][1]["note"], "commands")
        self.assertEqual(status["commands"][1]["title"], "Wake the desktop")

    def test_the_readily_block_reports_a_genuine_read(self):
        self.data["settings"]["readily"] = True
        readily = {"commands": [READILY_COMMAND], "ok": True, "warning": "", "skipped": 2}
        status = engine.build_status(self.data, self.state, T0, {}, readily)
        self.assertEqual(status["readily"],
                         {"enabled": True, "ok": True, "warning": "", "count": 1, "skipped": 2})

    def test_the_readily_block_carries_the_warning(self):
        self.data["settings"]["readily"] = True
        readily = {"commands": [], "ok": False, "warning": "Readily not found", "skipped": 0}
        status = engine.build_status(self.data, self.state, T0, {}, readily)
        self.assertEqual(status["readily"],
                         {"enabled": True, "ok": False, "warning": "Readily not found", "count": 0, "skipped": 0})

    def test_without_a_read_the_block_only_says_whether_the_switch_is_on(self):
        status = engine.build_status(self.data, self.state, T0, {})
        self.assertEqual(status["readily"],
                         {"enabled": False, "ok": False, "warning": "", "count": 0, "skipped": 0})
        self.assertEqual(status["commands"], [])

    def test_a_readily_result_shows_like_a_native_one(self):
        readily = {"commands": [READILY_COMMAND], "ok": True, "warning": "", "skipped": 0}
        results = {"d" * 32: {"at": "2026-09-23T18:00:00Z", "event": "arrive", "command": "true",
                              "source": "readily", "ok": True, "exit": 0, "message": "", "seconds": 0.1}}
        status = engine.build_status(self.data, self.state, T0, results, readily)
        self.assertEqual(status["commands"][0]["last"]["exit"], 0)
        self.assertNotIn("command", status["commands"][0]["last"])


if __name__ == "__main__":
    unittest.main()
