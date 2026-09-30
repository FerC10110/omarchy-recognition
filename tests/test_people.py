import json
import os
import stat
import tempfile
import unittest

from _load import load
from fakes import T0, at

engine = load()
PID = "a" * 32


class PathsAndTimeTest(unittest.TestCase):
    def test_paths_follow_xdg(self):
        environ = {"HOME": "/h", "XDG_CONFIG_HOME": "/c", "XDG_STATE_HOME": "/s"}
        self.assertEqual(engine.people_path(environ), "/c/recognition/people.json")
        self.assertEqual(engine.state_path(environ), "/s/recognition/state.json")
        self.assertEqual(engine.lock_path(environ), "/s/recognition/scan.lock")

    def test_paths_fall_back_to_home(self):
        environ = {"HOME": "/h"}
        self.assertEqual(engine.people_path(environ), "/h/.config/recognition/people.json")
        self.assertEqual(engine.state_path(environ), "/h/.local/state/recognition/state.json")

    def test_iso_round_trip_and_age(self):
        self.assertEqual(engine.iso(T0), "2026-09-17T21:00:00Z")
        self.assertEqual(engine.parse_iso("2026-09-17T21:00:00Z"), T0)
        self.assertIsNone(engine.parse_iso("yesterday"))
        self.assertIsNone(engine.parse_iso(None))
        self.assertEqual(engine.seconds_since(at(90), "2026-09-17T21:00:00Z"), 90)
        self.assertIsNone(engine.seconds_since(at(90), None))


class ValidationTest(unittest.TestCase):
    def test_mac_is_normalized(self):
        self.assertEqual(engine.normalize_mac(" 00-00-5E-00-53-09 "), "00:00:5e:00:53:09")
        for bad in ("00:00:5e:63:05", "zz:df:58:63:05:fe", "", None, 12):
            with self.assertRaises(engine.RecognitionError):
                engine.normalize_mac(bad)

    def test_name_emoji_label(self):
        self.assertEqual(engine.validate_name("  Juan "), "Juan")
        for bad in ("", "   ", "x" * 65, "a\tb", None, 3):
            with self.assertRaises(engine.RecognitionError):
                engine.validate_name(bad)
        self.assertEqual(engine.validate_emoji("🦊"), "🦊")
        self.assertEqual(engine.validate_emoji("👩‍👩‍👧"), "👩‍👩‍👧")
        for bad in ("", "🦊 🐻", "x" * 17):
            with self.assertRaises(engine.RecognitionError):
                engine.validate_emoji(bad)
        self.assertEqual(engine.validate_label(None), "")
        self.assertEqual(engine.validate_label(" iPhone "), "iPhone")
        with self.assertRaises(engine.RecognitionError):
            engine.validate_label("x" * 65)

    def test_subnet(self):
        self.assertEqual(engine.validate_subnet(""), "")
        self.assertEqual(engine.validate_subnet("192.168.200.5/24"), "192.168.200.0/24")
        with self.assertRaises(engine.RecognitionError) as ctx:
            engine.validate_subnet("10.0.0.0/16")
        self.assertIn("too large", str(ctx.exception))
        with self.assertRaises(engine.RecognitionError):
            engine.validate_subnet("casa")

    def test_subnet_must_be_a_private_range(self):
        for good in ("10.1.2.0/24", "172.16.5.0/24", "172.31.255.0/24", "192.168.1.0/24"):
            self.assertEqual(engine.validate_subnet(good), good)
        for bad in ("8.8.8.0/24", "127.0.0.0/24", "0.0.0.0/22", "169.254.1.0/24",
                    "100.64.0.0/24", "172.15.255.0/24", "172.32.0.0/24", "1.2.3.4/32"):
            with self.assertRaises(engine.RecognitionError) as ctx:
                engine.validate_subnet(bad)
            self.assertIn("private", str(ctx.exception))

    def test_a_private_network_that_is_too_large_says_so_and_not_that_it_is_public(self):
        with self.assertRaises(engine.RecognitionError) as ctx:
            engine.validate_subnet("10.0.0.0/8")
        self.assertIn("too large", str(ctx.exception))

    def test_repair_settings_drops_a_public_subnet(self):
        self.assertEqual(engine.repair_settings({"subnet": "8.8.8.0/24"})["subnet"], "")

    def test_settings_merge_partial_and_check_bounds(self):
        base = engine.empty_people()["settings"]
        merged = engine.validate_settings({"scanInterval": 30, "notify": {"leave": False}}, base)
        self.assertEqual(merged["scanInterval"], 30)
        self.assertEqual(merged["gracePeriod"], 300)
        self.assertEqual(merged["notify"],
                         {"arrive": True, "leave": False, "neighbor": True, "guest": True,
                          "unknown": True, "security": True, "home": False})
        self.assertEqual(base["scanInterval"], 20)   # base untouched
        for bad in ({"scanInterval": 5}, {"scanInterval": True}, {"gracePeriod": 4000},
                    {"notify": {"arrive": "yes"}}, {"notify": []}, []):
            with self.assertRaises(engine.RecognitionError):
                engine.validate_settings(bad, base)

    def test_repair_settings_keeps_good_keys_only(self):
        repaired = engine.repair_settings({"scanInterval": 45, "gracePeriod": "x", "subnet": "10.0.0.0/8",
                                           "notify": {"unknown": False, "arrive": 1}})
        self.assertEqual(repaired, {"scanInterval": 45, "gracePeriod": 300, "subnet": "",
                                    "guestsOccupyHome": True,
                                    "readily": False,
                                    "history": False, "historyDays": 30, "historyDevices": "none",
             "timelineLanes": [], "timelineCompare": [],
                                    "panelWidth": 0, "panelHeight": 0, "panelX": 0, "panelY": 0,
                                    "notify": {"arrive": True, "leave": True, "neighbor": True, "guest": True,
                                               "unknown": False, "security": True, "home": False}})
        self.assertEqual(engine.repair_settings(None), engine.DEFAULT_SETTINGS)

    def test_the_home_switch_is_the_only_one_that_starts_off(self):
        notify = engine.empty_people()["settings"]["notify"]
        self.assertEqual(notify, {"arrive": True, "leave": True, "neighbor": True, "guest": True,
                                  "unknown": True, "security": True, "home": False})

    def test_the_home_switch_can_be_turned_on_and_survives_a_repair(self):
        base = engine.empty_people()["settings"]
        self.assertIs(engine.validate_settings({"notify": {"home": True}}, base)["notify"]["home"], True)
        self.assertIs(engine.repair_settings({"notify": {"home": True}})["notify"]["home"], True)

    def test_guests_occupy_the_house_by_default(self):
        self.assertIs(engine.empty_people()["settings"]["guestsOccupyHome"], True)

    def test_the_occupancy_switch_can_be_turned_off(self):
        base = engine.empty_people()["settings"]
        self.assertIs(engine.validate_settings({"guestsOccupyHome": False}, base)["guestsOccupyHome"], False)
        with self.assertRaises(engine.RecognitionError) as caught:
            engine.validate_settings({"guestsOccupyHome": "yes"}, base)
        self.assertEqual(str(caught.exception), "Guests: true or false")

    def test_a_broken_occupancy_switch_goes_back_to_the_default(self):
        self.assertIs(engine.repair_settings({"guestsOccupyHome": "x"})["guestsOccupyHome"], True)
        self.assertIs(engine.repair_settings({"guestsOccupyHome": False})["guestsOccupyHome"], False)

    def test_readily_starts_off(self):
        self.assertIs(engine.empty_people()["settings"]["readily"], False)

    def test_the_readily_switch_can_be_turned_on(self):
        base = engine.empty_people()["settings"]
        self.assertIs(engine.validate_settings({"readily": True}, base)["readily"], True)
        with self.assertRaises(engine.RecognitionError) as caught:
            engine.validate_settings({"readily": "yes"}, base)
        self.assertEqual(str(caught.exception), "Readily: true or false")

    def test_a_broken_readily_switch_goes_back_to_off(self):
        self.assertIs(engine.repair_settings({"readily": "x"})["readily"], False)
        self.assertIs(engine.repair_settings({"readily": True})["readily"], True)

    def test_panel_geometry_defaults_to_automatic(self):
        settings = engine.empty_people()["settings"]
        self.assertEqual([settings["panelWidth"], settings["panelHeight"],
                          settings["panelX"], settings["panelY"]], [0, 0, 0, 0])

    def test_panel_geometry_takes_a_size_in_range_and_zero(self):
        base = engine.empty_people()["settings"]
        merged = engine.validate_settings({"panelWidth": 640, "panelHeight": 900,
                                           "panelX": -120, "panelY": 40}, base)
        self.assertEqual([merged["panelWidth"], merged["panelHeight"],
                          merged["panelX"], merged["panelY"]], [640, 900, -120, 40])
        back = engine.validate_settings({"panelWidth": 0, "panelHeight": 0}, merged)
        self.assertEqual([back["panelWidth"], back["panelHeight"]], [0, 0])

    def test_panel_geometry_out_of_range_says_the_range(self):
        base = engine.empty_people()["settings"]
        for field, value, message in (("panelWidth", 279, "Panel width: between 280 and 4000"),
                                      ("panelWidth", 4001, "Panel width: between 280 and 4000"),
                                      ("panelHeight", 239, "Panel height: between 240 and 3000"),
                                      ("panelHeight", 3001, "Panel height: between 240 and 3000"),
                                      ("panelX", -4001, "Panel x: between -4000 and 4000"),
                                      ("panelY", 4001, "Panel y: between -4000 and 4000")):
            with self.assertRaises(engine.RecognitionError) as ctx:
                engine.validate_settings({field: value}, base)
            self.assertEqual(str(ctx.exception), message)

    def test_panel_geometry_only_takes_whole_numbers(self):
        base = engine.empty_people()["settings"]
        for field, value in (("panelWidth", 640.5), ("panelWidth", False), ("panelHeight", "900"),
                             ("panelX", True), ("panelY", None)):
            with self.assertRaises(engine.RecognitionError) as ctx:
                engine.validate_settings({field: value}, base)
            self.assertIn("must be a whole number", str(ctx.exception))

    def test_broken_panel_geometry_goes_back_to_automatic(self):
        repaired = engine.repair_settings({"panelWidth": 10, "panelHeight": "big",
                                           "panelX": 99999, "panelY": 40})
        self.assertEqual([repaired["panelWidth"], repaired["panelHeight"],
                          repaired["panelX"], repaired["panelY"]], [0, 0, 0, 40])

    def test_person(self):
        person = engine.validate_person({"name": "Ana", "emoji": "🐻",
                                         "devices": [{"mac": "00:00:5e:00:53:09", "label": "Pixel"}]})
        self.assertEqual(person, {"name": "Ana", "emoji": "🐻", "group": "home", "notify": True,
                                  "devices": [{"mac": "00:00:5e:00:53:09", "label": "Pixel",
                                               "counts": True}]})
        self.assertEqual(engine.validate_person({"name": "Ana", "emoji": "🐻"})["devices"], [])
        with self.assertRaises(engine.RecognitionError):
            engine.validate_person({"name": "Ana", "emoji": "🐻", "devices": [
                {"mac": "00:00:5e:00:53:09"}, {"mac": "00:00:5e:00:53:09"}]})

    def test_a_device_counts_for_presence_unless_it_says_otherwise(self):
        devices = engine.validate_devices([{"mac": "00:00:5e:00:53:09", "label": "Pixel"},
                                           {"mac": "00:00:5e:00:53:0a", "label": "Printer", "counts": False},
                                           {"mac": "00:00:5e:00:53:0b", "label": "Old", "counts": None}])
        self.assertEqual([device["counts"] for device in devices], [True, False, True])

    def test_counts_must_be_a_boolean(self):
        with self.assertRaises(engine.RecognitionError) as ctx:
            engine.validate_devices([{"mac": "00:00:5e:00:53:09", "counts": 1}])
        self.assertIn("counts must be true or false", str(ctx.exception))

    def test_notify_defaults_to_on_and_only_takes_booleans(self):
        self.assertIs(engine.validate_notify(None), True)
        self.assertIs(engine.validate_notify(True), True)
        self.assertIs(engine.validate_notify(False), False)
        for bad in (1, 0, "yes", []):
            with self.assertRaises(engine.RecognitionError) as caught:
                engine.validate_notify(bad)
            self.assertIn("Notify", str(caught.exception))

    def test_a_person_written_before_the_switch_notifies(self):
        self.assertIs(engine.validate_person({"name": "Ana", "emoji": "🐻"})["notify"], True)

    def test_a_silent_person_keeps_the_switch_off(self):
        person = engine.validate_person({"name": "Ana", "emoji": "🐻", "notify": False})
        self.assertIs(person["notify"], False)

    def test_a_person_with_a_notify_that_is_not_a_boolean_is_an_error(self):
        with self.assertRaises(engine.RecognitionError) as caught:
            engine.validate_person({"name": "Ana", "emoji": "🐻", "notify": 1})
        self.assertIn("Notify", str(caught.exception))

    def test_command_text(self):
        self.assertEqual(engine.validate_command("  curl -s example.com "), "curl -s example.com")
        self.assertEqual(engine.validate_command("x" * 1000), "x" * 1000)
        for bad, message in (("", "Command: between 1 and 1000 characters"),
                             (None, "Command: between 1 and 1000 characters"),
                             ("x" * 1001, "Command: between 1 and 1000 characters"),
                             ("echo a\necho b", "Command: cannot contain control characters"),
                             (5, "Command: must be text")):
            with self.assertRaises(engine.RecognitionError) as ctx:
                engine.validate_command(bad)
            self.assertEqual(str(ctx.exception), message)

    def test_command_events_and_people(self):
        self.assertEqual(engine.validate_events(["alert", "arrive", "alert"]), ["arrive", "alert"])
        self.assertEqual(engine.validate_events(list(reversed(engine.EVENTS))), list(engine.EVENTS))
        for bad, message in (("arrive", "Events: must be a list"),
                             (None, "Events: must be a list"),
                             ([], "Events: pick at least one"),
                             (["arrive", "p" * 40], "Events: unknown event " + "p" * 32)):
            with self.assertRaises(engine.RecognitionError) as ctx:
                engine.validate_events(bad)
            self.assertEqual(str(ctx.exception), message)
        self.assertIsNone(engine.validate_command_people(None))
        self.assertEqual(engine.validate_command_people([PID, "b" * 32, PID]), [PID, "b" * 32])
        for bad in ("all", [1], {"id": PID}):
            with self.assertRaises(engine.RecognitionError) as ctx:
                engine.validate_command_people(bad)
            self.assertEqual(str(ctx.exception), "People: must be null or a list of person ids")

    def test_manual_is_an_event_and_comes_last(self):
        self.assertEqual(engine.EVENTS[-1], "manual")
        self.assertEqual(engine.validate_events(["manual", "arrive"]), ["arrive", "manual"])


class GroupTest(unittest.TestCase):
    def test_a_person_without_a_group_is_from_the_house(self):
        person = engine.validate_person({"name": "Ana", "emoji": "🐻"})
        self.assertEqual(person["group"], "home")

    def test_a_neighbor_keeps_its_group(self):
        person = engine.validate_person({"name": "Sam", "emoji": "🐸", "group": "neighbor"})
        self.assertEqual(person["group"], "neighbor")

    def test_a_guest_keeps_its_group(self):
        person = engine.validate_person({"name": "Sam", "emoji": "🦊", "group": "guest"})
        self.assertEqual(person["group"], "guest")

    def test_an_invented_group_is_an_error(self):
        with self.assertRaises(engine.RecognitionError) as caught:
            engine.validate_person({"name": "Sam", "emoji": "🐸", "group": "roommate"})
        self.assertEqual(str(caught.exception), "Group: home, neighbor or guest")


class LoadSaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "recognition", "people.json")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, payload):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(payload if isinstance(payload, str) else json.dumps(payload))

    def test_missing_file_is_empty(self):
        self.assertEqual(engine.load_people(self.path), engine.empty_people())

    def test_invalid_json_is_an_error(self):
        self.write("{nope")
        with self.assertRaises(engine.RecognitionError) as ctx:
            engine.load_people(self.path)
        self.assertIn("is not valid JSON", str(ctx.exception))

    def test_a_person_with_no_group_in_the_file_is_read_as_home(self):
        self.write({"people": [{"id": PID, "name": "Ana", "emoji": "🐻", "devices": []}]})
        data = engine.load_people(self.path)
        self.assertEqual(data["people"][0]["group"], "home")
        self.assertIs(data["people"][0]["notify"], True)

    def test_an_old_file_gains_the_flag(self):
        self.write({"people": [{"id": PID, "name": "Ana", "emoji": "🐻",
                                "devices": [{"mac": "00:00:5e:00:53:09", "label": "Pixel"}]}]})
        self.assertIs(engine.load_people(self.path)["people"][0]["devices"][0]["counts"], True)

    def test_a_device_that_does_not_count_survives_a_round_trip(self):
        self.write({"people": [{"id": PID, "name": "Ana", "emoji": "🐻",
                                "devices": [{"mac": "00:00:5e:00:53:09", "label": "Printer",
                                             "counts": False}]}]})
        data = engine.load_people(self.path)
        self.assertIs(data["people"][0]["devices"][0]["counts"], False)
        engine.save_people(self.path, data)
        self.assertIs(engine.load_people(self.path)["people"][0]["devices"][0]["counts"], False)

    def test_bad_person_id_is_an_error(self):
        self.write({"people": [{"id": "x", "name": "Ana", "emoji": "🐻", "devices": []}]})
        with self.assertRaises(engine.RecognitionError) as ctx:
            engine.load_people(self.path)
        self.assertIn("person 1", str(ctx.exception))

    def test_mac_used_twice_is_an_error(self):
        mac = "00:00:5e:00:53:09"
        self.write({"people": [{"id": PID, "name": "Ana", "emoji": "🐻", "devices": [{"mac": mac}]}],
                    "house": [{"mac": mac, "label": "x"}]})
        with self.assertRaises(engine.RecognitionError) as ctx:
            engine.load_people(self.path)
        self.assertIn("appears more than once", str(ctx.exception))

    def test_unknown_keys_survive_a_round_trip(self):
        self.write({"version": 1, "future": {"a": 1},
                    "people": [{"id": PID, "name": "Ana", "emoji": "🐻", "zone": "trabajo",
                                "devices": [{"mac": "00:00:5e:00:53:09", "label": "Pixel"}]}],
                    "house": [], "settings": {"scanInterval": 30}})
        data = engine.load_people(self.path)
        self.assertEqual(data["future"], {"a": 1})
        self.assertEqual(data["people"][0]["zone"], "trabajo")
        self.assertEqual(data["people"][0]["devices"][0]["mac"], "00:00:5e:00:53:09")
        self.assertEqual(data["settings"]["scanInterval"], 30)
        engine.save_people(self.path, data)
        self.assertEqual(engine.load_people(self.path), data)

    def test_save_is_private_and_atomic(self):
        engine.save_people(self.path, engine.empty_people())
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(self.path)).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["people.json"])

    def test_legacy_ignored_is_read_as_house_and_dropped_on_save(self):
        mac = "02:00:00:00:00:01"
        self.write({"people": [], "ignored": [{"mac": mac.upper(), "label": "Router"}]})
        data = engine.load_people(self.path)
        self.assertEqual(data["house"], [{"mac": mac, "label": "Router"}])
        self.assertNotIn("ignored", data)
        engine.save_people(self.path, data)
        with open(self.path, encoding="utf-8") as fh:
            self.assertNotIn("ignored", json.load(fh))
        self.assertEqual(engine.load_people(self.path)["house"], [{"mac": mac, "label": "Router"}])

    def test_house_and_legacy_ignored_are_merged(self):
        a, b = "02:00:00:00:00:01", "00:00:5e:00:53:30"
        self.write({"house": [{"mac": a, "label": "Router"}], "ignored": [{"mac": b, "label": "Switch"}]})
        self.assertEqual(engine.load_people(self.path)["house"],
                         [{"mac": a, "label": "Router"}, {"mac": b, "label": "Switch"}])

    def test_mac_in_house_and_legacy_ignored_is_an_error(self):
        mac = "02:00:00:00:00:01"
        self.write({"house": [{"mac": mac, "label": "Router"}], "ignored": [{"mac": mac, "label": "x"}]})
        with self.assertRaises(engine.RecognitionError) as ctx:
            engine.load_people(self.path)
        self.assertIn("appears more than once", str(ctx.exception))

    def test_bad_house_entry_is_named(self):
        self.write({"house": ["nope"]})
        with self.assertRaises(engine.RecognitionError) as ctx:
            engine.load_people(self.path)
        self.assertEqual(str(ctx.exception), "people.json: house entry 1 is not an object")

    def test_commands_are_read_and_checked(self):
        self.write({"people": [{"id": PID, "name": "Ana", "emoji": "🐻"}],
                    "commands": [{"id": "c" * 32, "command": "  echo hi ", "events": ["leave", "arrive", "leave"],
                                  "people": [PID, "d" * 32, PID], "note": "kept"},
                                 {"id": "e" * 32, "command": "true", "events": ["alert"]}]})
        data = engine.load_people(self.path)
        self.assertEqual(data["commands"], [
            {"id": "c" * 32, "command": "echo hi", "events": ["arrive", "leave"], "people": [PID], "note": "kept"},
            {"id": "e" * 32, "command": "true", "events": ["alert"], "people": None}])

    def test_missing_commands_is_an_empty_list(self):
        self.write({"people": []})
        self.assertEqual(engine.load_people(self.path)["commands"], [])

    def test_bad_command_entry_is_named(self):
        good = {"id": "c" * 32, "command": "true", "events": ["arrive"], "people": None}
        cases = [
            ({"commands": {}}, "people.json: commands must be a list"),
            ({"commands": ["x"]}, "people.json: command 1: not an object"),
            ({"commands": [dict(good, id="nope")]}, "people.json: command 1: doesn't have a valid id"),
            ({"commands": [good, good]}, f"people.json: command 2: id {'c' * 32} is repeated"),
            ({"commands": [dict(good, command="")]},
             "people.json: command 1: Command: between 1 and 1000 characters"),
            ({"commands": [dict(good, events=[])]}, "people.json: command 1: Events: pick at least one"),
            ({"commands": [dict(good, events=["party"])]}, "people.json: command 1: Events: unknown event party"),
            ({"commands": [dict(good, people="all")]},
             "people.json: command 1: People: must be null or a list of person ids"),
        ]
        for payload, message in cases:
            self.write(payload)
            with self.assertRaises(engine.RecognitionError) as ctx:
                engine.load_people(self.path)
            self.assertEqual(str(ctx.exception), message)


if __name__ == "__main__":
    unittest.main()
