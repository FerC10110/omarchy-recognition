"""Events, their environment and the jobs of a scan (spec §3.3, §3.4)."""
import json
import unittest
import unittest.mock

from _load import load
from fakes import GATEWAY_MAC, PHONE_MAC, RANDOM_MAC, SWITCH_MAC, T0, at

engine = load()
ANA = {"id": "a" * 32, "name": "Ana", "emoji": "🐻", "devices": []}
JUAN = {"id": "b" * 32, "name": "Juan", "emoji": "🦊", "devices": []}
ANA_VIEW = {"id": "a" * 32, "name": "Ana", "emoji": "🐻"}
OTHER_MAC = "aa:bb:cc:dd:ee:ff"
GATEWAY = {"kind": "gateway-mac", "data": {"ip": "192.168.200.1", "expectedMac": GATEWAY_MAC,
                                           "seenMac": OTHER_MAC}}
CONFLICT = {"kind": "ip-conflict", "data": {"ip": "192.168.200.9", "previousMac": PHONE_MAC, "mac": OTHER_MAC}}
DEVICES = {RANDOM_MAC: {"ip": "192.168.200.112", "hostname": "Android_4f1c", "vendor": "", "randomMac": True}}


def command(events, people=None, text="true", command_id="c" * 32):
    return {"id": command_id, "command": text, "events": events, "people": people}


def summary(events):
    return [(event["event"], event["message"]) for event in events]


class EventsTest(unittest.TestCase):
    def test_arrivals_unknown_and_alerts_in_job_order(self):
        events = engine.build_events([ANA, JUAN], [], [RANDOM_MAC], [GATEWAY, CONFLICT], DEVICES, 0,
                                     ["Ana", "Juan"], T0)
        self.assertEqual(summary(events), [
            ("arrive", "Ana arrived home"),
            ("arrive", "Juan arrived home"),
            ("home-occupied", "Home is occupied (Ana, Juan arrived)"),
            ("unknown", "New device on the network: Random MAC · Android_4f1c · 192.168.200.112"),
            ("alert", f"Router MAC changed: 192.168.200.1: expected {GATEWAY_MAC}, answered {OTHER_MAC}"),
            ("alert", f"IP address conflict: 192.168.200.9 moved from {PHONE_MAC} to {OTHER_MAC}")])
        occupied = events[2]
        self.assertEqual(occupied["person"], ANA_VIEW)
        self.assertEqual([person["name"] for person in occupied["people"]], ["Ana", "Juan"])
        self.assertEqual(occupied["at"], "2026-09-17T21:00:00Z")

    def test_departures_and_home_empty(self):
        events = engine.build_events([], [ANA, JUAN], [], [], {}, 2, [], T0)
        self.assertEqual(summary(events), [("leave", "Ana left"), ("leave", "Juan left"),
                                           ("home-empty", "Home is empty (Ana, Juan left)")])

    def test_group_events_need_an_empty_home_on_one_side(self):
        events = engine.build_events([ANA], [JUAN], [], [], {}, 1, ["Ana"], T0)
        self.assertEqual([event["event"] for event in events], ["arrive", "leave"])


class EnvTest(unittest.TestCase):
    def test_person_event(self):
        arrive = engine.build_events([ANA], [], [], [], {}, 0, ["Ana"], T0)[0]
        env = engine.event_env(arrive)
        self.assertEqual({key: value for key, value in env.items() if key != "RECOGNITION_JSON"}, {
            "RECOGNITION_EVENT": "arrive", "RECOGNITION_MESSAGE": "Ana arrived home",
            "RECOGNITION_PERSON_ID": "a" * 32, "RECOGNITION_PERSON_NAME": "Ana", "RECOGNITION_PERSON_EMOJI": "🐻",
            "RECOGNITION_HOME": "Ana", "RECOGNITION_HOME_COUNT": "1",
            "RECOGNITION_GUESTS": "", "RECOGNITION_GUEST_COUNT": "0"})
        self.assertEqual(json.loads(env["RECOGNITION_JSON"]), {
            "event": "arrive", "at": "2026-09-17T21:00:00Z", "message": "Ana arrived home", "person": ANA_VIEW,
            "people": [ANA_VIEW], "home": ["Ana"], "guests": [], "device": None, "alert": None})

    def test_unknown_and_alert_events(self):
        unknown, alert = engine.build_events([], [], [RANDOM_MAC], [CONFLICT], DEVICES, 2, ["Ana", "Juan"], T0)
        env = engine.event_env(unknown)
        self.assertEqual({key: value for key, value in env.items() if key.startswith("RECOGNITION_DEVICE_")}, {
            "RECOGNITION_DEVICE_MAC": RANDOM_MAC, "RECOGNITION_DEVICE_IP": "192.168.200.112",
            "RECOGNITION_DEVICE_VENDOR": "", "RECOGNITION_DEVICE_HOSTNAME": "Android_4f1c"})
        self.assertEqual((env["RECOGNITION_HOME"], env["RECOGNITION_HOME_COUNT"]), ("Ana, Juan", "2"))
        self.assertNotIn("RECOGNITION_PERSON_ID", env)
        self.assertNotIn("RECOGNITION_ALERT_KIND", env)
        env = engine.event_env(alert)
        self.assertEqual((env["RECOGNITION_ALERT_KIND"], env["RECOGNITION_ALERT_IP"]),
                         ("ip-conflict", "192.168.200.9"))
        self.assertEqual(json.loads(env["RECOGNITION_JSON"])["alert"],
                         {"kind": "ip-conflict", "ip": "192.168.200.9", "previousMac": PHONE_MAC, "mac": OTHER_MAC})
        self.assertNotIn("RECOGNITION_DEVICE_MAC", env)

    def test_a_device_without_data_gets_empty_values(self):
        [event] = engine.build_events([], [], ["02:00:00:00:00:07"], [], {}, 0, [], T0)
        env = engine.event_env(event)
        self.assertEqual(env["RECOGNITION_MESSAGE"], "New device on the network: 02:00:00:00:00:07")
        self.assertEqual([env[f"RECOGNITION_DEVICE_{key}"] for key in ("IP", "VENDOR", "HOSTNAME")], ["", "", ""])
        self.assertEqual((env["RECOGNITION_HOME"], env["RECOGNITION_HOME_COUNT"]), ("", "0"))
        # A None in state.json (not just a missing key) must not leak into a
        # non-string env value, or _valid_job would reject the whole batch.
        none_device = {"02:00:00:00:00:07": {"ip": None, "vendor": None, "hostname": None}}
        [event] = engine.build_events([], [], ["02:00:00:00:00:07"], [], none_device, 0, [], T0)
        env = engine.event_env(event)
        self.assertEqual([env[f"RECOGNITION_DEVICE_{key}"] for key in ("IP", "VENDOR", "HOSTNAME")], ["", "", ""])


class JobsTest(unittest.TestCase):
    def test_people_filter_applies_to_the_person_events_only(self):
        events = engine.build_events([ANA, JUAN], [], [], [], {}, 0, ["Ana", "Juan"], T0)
        everyone = command(["arrive", "home-occupied"], None, "a", "1" * 32)
        only_juan = command(["arrive", "home-occupied"], [JUAN["id"]], "b", "2" * 32)
        nobody = command(["arrive", "home-occupied"], [], "c", "3" * 32)
        jobs = engine.build_jobs([everyone, only_juan, nobody], events)
        self.assertEqual([(job["event"], job["command"], job["env"]["RECOGNITION_PERSON_NAME"]) for job in jobs], [
            ("arrive", "a", "Ana"), ("arrive", "a", "Juan"), ("arrive", "b", "Juan"),
            ("home-occupied", "a", "Ana"), ("home-occupied", "b", "Ana"), ("home-occupied", "c", "Ana")])
        self.assertEqual(jobs[0], {"id": "1" * 32, "command": "a", "event": "arrive",
                                   "env": engine.event_env(events[0])})

    def test_only_marked_events_in_event_order(self):
        events = engine.build_events([ANA], [JUAN], [RANDOM_MAC], [GATEWAY], DEVICES, 1, ["Ana"], T0)
        every = command(list(engine.EVENTS))
        some = command(["alert", "leave"], text="false", command_id="d" * 32)
        self.assertEqual([(job["event"], job["command"]) for job in engine.build_jobs([every, some], events)], [
            ("arrive", "true"), ("leave", "true"), ("leave", "false"), ("unknown", "true"),
            ("alert", "true"), ("alert", "false")])

    def test_network_data_only_travels_in_the_environment(self):
        devices = {RANDOM_MAC: {"ip": "192.168.200.112", "hostname": "$(touch x); y", "vendor": "",
                                "randomMac": True}}
        events = engine.build_events([], [], [RANDOM_MAC], [], devices, 0, [], T0)
        text = 'echo "$RECOGNITION_DEVICE_HOSTNAME"'
        [job] = engine.build_jobs([command(["unknown"], text=text)], events)
        self.assertEqual(job["command"], text)
        self.assertEqual(job["env"]["RECOGNITION_DEVICE_HOSTNAME"], "$(touch x); y")

    def test_a_readily_command_carries_where_it_came_from(self):
        readily = {"id": "d" * 32, "command": "true", "events": ["arrive"], "people": None,
                   "source": "readily", "note": "commands", "title": "Wake"}
        events = engine.build_events([ANA], [], [], [], {}, 0, ["Ana"], T0)
        jobs = engine.build_jobs([command(["arrive"]), readily], events)
        self.assertEqual([job.get("source") for job in jobs], [None, "readily"])
        self.assertTrue(engine._valid_job(jobs[1]))

    def test_a_readily_command_has_no_people_filter_unlike_a_native_one(self):
        """Two people arrive; a native command filtered to just one of them, and a note
        command, which never carries a filter. The native one fires once, the note one
        for both — the single-person test above cannot tell "no filter" apart from
        "a filter that happened to say yes"."""
        readily = {"id": "d" * 32, "command": "true", "events": ["arrive"], "people": None,
                   "source": "readily", "note": "commands", "title": "Wake"}
        only_ana = command(["arrive"], [ANA["id"]], "a", "1" * 32)
        events = engine.build_events([ANA, JUAN], [], [], [], {}, 0, ["Ana", "Juan"], T0)
        jobs = engine.build_jobs([only_ana, readily], events)
        self.assertEqual([(job["command"], job["env"]["RECOGNITION_PERSON_NAME"], job.get("source"))
                          for job in jobs],
                         [("a", "Ana", None), ("true", "Ana", "readily"), ("true", "Juan", "readily")])


class NeighborJobsTest(unittest.TestCase):
    def setUp(self):
        self.data = engine.empty_people()
        self.sam = engine.save_person(self.data, {"name": "Sam", "emoji": "🐸", "group": "neighbor"})
        self.other = engine.save_person(self.data, {"name": "Val", "emoji": "🦊", "group": "neighbor"})

    def test_the_people_filter_applies_to_neighbor_events(self):
        command = engine.save_command(self.data, {"command": "true", "events": ["neighbor-arrive"],
                                                  "people": [self.sam["id"]]})
        events = engine.build_events([self.other], [], [], [], {}, 0, [], T0)
        self.assertEqual(engine.build_jobs([command], events), [])
        events = engine.build_events([self.sam], [], [], [], {}, 0, [], T0)
        self.assertEqual([job["event"] for job in engine.build_jobs([command], events)], ["neighbor-arrive"])


class GuestJobsTest(unittest.TestCase):
    def setUp(self):
        self.data = engine.empty_people()
        self.sam = engine.save_person(self.data, {"name": "Sam", "emoji": "🦊", "group": "guest"})
        self.other = engine.save_person(self.data, {"name": "Kim", "emoji": "🐨", "group": "guest"})

    def test_the_people_filter_applies_to_guest_events(self):
        command = engine.save_command(self.data, {"command": "true",
                                                  "events": ["guest-arrive", "guest-leave"],
                                                  "people": [self.sam["id"]]})
        # An occupied house, so the arrival does not also raise home-occupied: what this
        # test is about is which person the command runs for.
        mine = engine.build_events([self.sam], [], [], [], {}, 1, ["Ana"], T0, guests=["Sam"])
        theirs = engine.build_events([self.other], [], [], [], {}, 1, ["Ana"], T0, guests=["Kim"])
        self.assertEqual([job["event"] for job in engine.build_jobs([command], mine)], ["guest-arrive"])
        self.assertEqual(engine.build_jobs([command], theirs), [])


class SilentPersonJobsTest(unittest.TestCase):
    def test_a_command_runs_for_a_person_whose_notifications_are_off(self):
        data = engine.empty_people()
        quiet = engine.save_person(data, {"name": "Juan", "emoji": "🦊", "notify": False})
        command = engine.save_command(data, {"command": "true", "events": ["arrive"],
                                             "people": [quiet["id"]]})
        events = engine.build_events([quiet], [], [], [], {}, 0, ["Juan"], T0)
        self.assertEqual([job["event"] for job in engine.build_jobs([command], events)], ["arrive"])


class NeighborEventsTest(unittest.TestCase):
    def setUp(self):
        self.data = engine.empty_people()
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "🐻"})
        self.sam = engine.save_person(self.data, {"name": "Sam", "emoji": "🐸", "group": "neighbor"})

    def test_a_neighbor_arrives_on_its_own_event(self):
        events = engine.build_events([self.sam], [], [], [], {}, 0, [], T0)
        self.assertEqual([(e["event"], e["message"]) for e in events],
                         [("neighbor-arrive", "Sam joined the Wi-Fi")])

    def test_a_neighbor_leaving_does_not_empty_the_house(self):
        events = engine.build_events([], [self.sam], [], [], {}, 1, ["Ana"], T0)
        self.assertEqual([e["event"] for e in events], ["neighbor-leave"])

    def test_the_house_still_empties_with_a_neighbor_connected(self):
        events = engine.build_events([], [self.ana], [], [], {}, 1, [], T0)
        self.assertEqual([e["event"] for e in events], ["leave", "home-empty"])

    def test_house_events_come_before_neighbor_events(self):
        events = engine.build_events([self.ana, self.sam], [], [], [], {}, 1, ["Ana"], T0)
        self.assertEqual([e["event"] for e in events], ["arrive", "neighbor-arrive"])


class GuestEventsTest(unittest.TestCase):
    def setUp(self):
        self.data = engine.empty_people()
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "🐻"})
        self.sam = engine.save_person(self.data, {"name": "Sam", "emoji": "🦊", "group": "guest"})

    def test_a_guest_arrives_on_its_own_event(self):
        events = engine.build_events([self.sam], [], [], [], {}, 1, ["Ana"], T0, guests=["Sam"])
        self.assertEqual([(e["event"], e["message"]) for e in events],
                         [("guest-arrive", "Sam is visiting")])

    def test_a_guest_leaving_uses_its_own_text(self):
        events = engine.build_events([], [self.sam], [], [], {}, 1, ["Ana"], T0)
        self.assertEqual([(e["event"], e["message"]) for e in events],
                         [("guest-leave", "Sam went home")])

    def test_house_events_come_before_guest_events(self):
        events = engine.build_events([self.ana, self.sam], [], [], [], {}, 1, ["Ana"], T0)
        self.assertEqual([e["event"] for e in events], ["arrive", "guest-arrive"])


class NeighborSampleTest(unittest.TestCase):
    def test_a_neighbor_event_uses_a_neighbor_and_the_real_house(self):
        data = engine.empty_people()
        engine.save_person(data, {"name": "Ana", "emoji": "🐻", "devices": [{"mac": PHONE_MAC}]})
        engine.save_person(data, {"name": "Sam", "emoji": "🐸", "group": "neighbor"})
        state = {"devices": {PHONE_MAC: {"present": True, "since": engine.iso(T0), "lastSeen": engine.iso(T0)}},
                "people": {}, "alerts": []}
        event = engine.sample_event("neighbor-arrive", None, data, state, T0)
        self.assertEqual((event["event"], event["person"]["name"], event["home"]),
                         ("neighbor-arrive", "Sam", ["Ana"]))

    def test_home_empty_still_reports_an_empty_house_even_with_someone_home(self):
        data = engine.empty_people()
        engine.save_person(data, {"name": "Ana", "emoji": "🐻", "devices": [{"mac": PHONE_MAC}]})
        state = {"devices": {PHONE_MAC: {"present": True, "since": engine.iso(T0), "lastSeen": engine.iso(T0)}},
                "people": {}, "alerts": []}
        event = engine.sample_event("home-empty", None, data, state, T0)
        self.assertEqual(event["home"], [])

    def test_without_neighbors_the_sample_invents_one(self):
        data = engine.empty_people()
        state = {"devices": {}, "people": {}, "alerts": []}
        event = engine.sample_event("neighbor-leave", None, data, state, T0)
        self.assertEqual(event["event"], "neighbor-leave")
        self.assertEqual(event["person"], {"id": engine.SAMPLE_NEIGHBOR["id"],
                                           "name": engine.SAMPLE_NEIGHBOR["name"],
                                           "emoji": engine.SAMPLE_NEIGHBOR["emoji"]})


class GuestSampleTest(unittest.TestCase):
    def test_a_guest_event_uses_a_guest_and_the_real_house(self):
        data = engine.empty_people()
        engine.save_person(data, {"name": "Ana", "emoji": "🐻", "devices": [{"mac": PHONE_MAC}]})
        engine.save_person(data, {"name": "Sam", "emoji": "🦊", "group": "guest"})
        state = {"devices": {PHONE_MAC: {"present": True, "since": engine.iso(T0), "lastSeen": engine.iso(T0)}},
                 "people": {}, "alerts": []}
        event = engine.sample_event("guest-arrive", None, data, state, T0)
        self.assertEqual((event["event"], event["person"]["name"], event["home"]),
                         ("guest-arrive", "Sam", ["Ana"]))

    def test_without_guests_the_sample_invents_one(self):
        event = engine.sample_event("guest-leave", None, engine.empty_people(),
                                    {"devices": {}, "people": {}, "alerts": []}, T0)
        self.assertEqual(event["event"], "guest-leave")
        self.assertEqual(event["person"], {"id": engine.SAMPLE_GUEST["id"],
                                           "name": "Guest",
                                           "emoji": "🧪"})

    def test_the_home_empty_sample_works_with_a_guest_connected(self):
        data = engine.empty_people()
        sam = engine.save_person(data, {"name": "Sam", "emoji": "🦊", "group": "guest",
                                        "devices": [{"mac": PHONE_MAC}]})
        state = {"devices": {PHONE_MAC: {"present": True, "since": engine.iso(T0), "lastSeen": engine.iso(T0)}},
                 "people": {}, "alerts": []}
        event = engine.sample_event("home-empty", None, data, state, T0)
        self.assertEqual((event["event"], event["home"], event["guests"]), ("home-empty", [], []))


class SampleEventPeopleFilterTest(unittest.TestCase):
    """F1: sample_event must not hand build_events a person outside the
    requested event's group. Before the fix, checking a person of the wrong
    group made build_events emit that person's own group's event instead of
    the one asked for, and the final next() blew up with StopIteration."""

    def setUp(self):
        self.data = engine.empty_people()
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "🐻"})
        self.sam = engine.save_person(self.data, {"name": "Sam", "emoji": "🐸", "group": "neighbor"})
        self.kim = engine.save_person(self.data, {"name": "Kim", "emoji": "🐨", "group": "guest"})
        self.state = {"devices": {}, "people": {}, "alerts": []}

    def test_a_household_pick_does_not_break_a_neighbor_event(self):
        event = engine.sample_event("neighbor-arrive", [self.ana["id"]], self.data, self.state, T0)
        self.assertEqual(event["event"], "neighbor-arrive")
        self.assertEqual(event["person"]["name"], "Sam")

    def test_a_neighbor_pick_does_not_break_a_household_event(self):
        event = engine.sample_event("arrive", [self.sam["id"]], self.data, self.state, T0)
        self.assertEqual(event["event"], "arrive")
        self.assertEqual(event["person"]["name"], "Ana")

    def test_a_household_pick_does_not_break_a_guest_event(self):
        event = engine.sample_event("guest-arrive", [self.ana["id"]], self.data, self.state, T0)
        self.assertEqual(event["event"], "guest-arrive")
        self.assertEqual(event["person"]["name"], "Kim")

    def test_a_guest_pick_does_not_break_a_household_event(self):
        event = engine.sample_event("arrive", [self.kim["id"]], self.data, self.state, T0)
        self.assertEqual(event["event"], "arrive")
        self.assertEqual(event["person"]["name"], "Ana")

    def test_a_missing_event_answers_a_recognition_error_not_a_crash(self):
        with unittest.mock.patch.object(engine, "build_events", return_value=[]):
            with self.assertRaises(engine.RecognitionError):
                engine.sample_event("arrive", None, self.data, self.state, T0)


class HomeNamesTest(unittest.TestCase):
    def test_present_people_in_arrival_order(self):
        data = engine.empty_people()
        engine.save_person(data, {"name": "ana", "emoji": "🐻", "devices": [{"mac": PHONE_MAC}]})
        engine.save_person(data, {"name": "Juan", "emoji": "🦊", "devices": [{"mac": RANDOM_MAC}]})
        engine.save_person(data, {"name": "Zoe", "emoji": "🐱", "devices": []})
        state = engine.empty_state()
        engine.apply_sightings(state, {RANDOM_MAC: "192.168.200.112"}, T0, 300)
        engine.apply_sightings(state, {PHONE_MAC: "192.168.200.9", RANDOM_MAC: "192.168.200.112"}, at(60), 300)
        self.assertEqual(engine.home_names(data, state), ["Juan", "ana"])


class GuestNamesTest(unittest.TestCase):
    def test_connected_guests_in_arrival_order_others_absent(self):
        data = engine.empty_people()
        engine.save_person(data, {"name": "Sam", "emoji": "🦊", "group": "guest",
                                  "devices": [{"mac": PHONE_MAC}]})
        engine.save_person(data, {"name": "Kim", "emoji": "🐨", "group": "guest",
                                  "devices": [{"mac": RANDOM_MAC}]})
        engine.save_person(data, {"name": "Zoe", "emoji": "🐱", "group": "guest", "devices": []})
        engine.save_person(data, {"name": "Val", "emoji": "🐢", "group": "guest",
                                  "devices": [{"mac": OTHER_MAC}]})
        state = engine.empty_state()
        engine.apply_sightings(state, {RANDOM_MAC: "192.168.200.112"}, T0, 300)
        engine.apply_sightings(state, {PHONE_MAC: "192.168.200.9", RANDOM_MAC: "192.168.200.112"}, at(60), 300)
        self.assertEqual(engine.guest_names(data, state), ["Kim", "Sam"])


class GuestEnvTest(unittest.TestCase):
    def setUp(self):
        self.data = engine.empty_people()
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "🐻"})
        self.sam = engine.save_person(self.data, {"name": "Sam", "emoji": "🦊", "group": "guest"})

    def test_the_guests_travel_in_their_own_variables(self):
        event = engine.build_events([self.ana], [], [], [], {}, 0, ["Ana"], T0, guests=["Sam", "Kim"])[0]
        env = engine.event_env(event)
        self.assertEqual((env["RECOGNITION_GUESTS"], env["RECOGNITION_GUEST_COUNT"]), ("Sam, Kim", "2"))

    def test_the_house_variables_never_count_guests(self):
        event = engine.build_events([self.sam], [], [], [], {}, 0, ["Ana"], T0, guests=["Sam"])[0]
        env = engine.event_env(event)
        self.assertEqual((env["RECOGNITION_HOME"], env["RECOGNITION_HOME_COUNT"]), ("Ana", "1"))
        self.assertEqual(env["RECOGNITION_GUESTS"], "Sam")

    def test_without_guests_the_variables_are_empty(self):
        event = engine.build_events([self.ana], [], [], [], {}, 0, ["Ana"], T0)[0]
        env = engine.event_env(event)
        self.assertEqual((env["RECOGNITION_GUESTS"], env["RECOGNITION_GUEST_COUNT"]), ("", "0"))


class GuestOccupancyTest(unittest.TestCase):
    def setUp(self):
        self.data = engine.empty_people()
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "🐻"})
        self.sam = engine.save_person(self.data, {"name": "Sam", "emoji": "🦊", "group": "guest"})

    def test_everyone_leaving_at_once_empties_the_house_once(self):
        """The household member and the guest go out the door together."""
        events = engine.build_events([], [self.ana, self.sam], [], [], {}, 2, [], T0,
                                     guests=[], guests_occupy=True)
        self.assertEqual([(e["event"], e["message"]) for e in events],
                         [("leave", "Ana left"), ("guest-leave", "Sam went home"),
                          ("home-empty", "Home is empty (Ana, Sam left)")])

    def test_the_house_is_not_empty_while_a_guest_is_connected(self):
        events = engine.build_events([], [self.ana], [], [], {}, 2, [], T0,
                                     guests=["Sam"], guests_occupy=True)
        self.assertEqual([e["event"] for e in events], ["leave"])

    def test_with_the_switch_off_a_guest_does_not_hold_the_house(self):
        events = engine.build_events([], [self.ana], [], [], {}, 1, [], T0,
                                     guests=["Sam"], guests_occupy=False)
        self.assertEqual([e["event"] for e in events], ["leave", "home-empty"])

    def test_a_guest_arriving_at_an_empty_house_occupies_it(self):
        events = engine.build_events([self.sam], [], [], [], {}, 0, [], T0,
                                     guests=["Sam"], guests_occupy=True)
        self.assertEqual([(e["event"], e["message"]) for e in events],
                         [("guest-arrive", "Sam is visiting"),
                          ("home-occupied", "Home is occupied (Sam arrived)")])

    def test_with_the_switch_off_a_guest_never_occupies_the_house(self):
        events = engine.build_events([self.sam], [], [], [], {}, 0, [], T0,
                                     guests=["Sam"], guests_occupy=False)
        self.assertEqual([e["event"] for e in events], ["guest-arrive"])

    def test_the_last_guest_leaving_empties_the_house(self):
        events = engine.build_events([], [self.sam], [], [], {}, 1, [], T0,
                                     guests=[], guests_occupy=True)
        self.assertEqual([e["event"] for e in events], ["guest-leave", "home-empty"])


class ChosenDeviceTest(unittest.TestCase):
    """Spec §3.2: which of a person's devices a manual run targets."""

    def person(self, *macs):
        return {"id": "a" * 32, "name": "Ana", "emoji": "🐻",
                "devices": [{"mac": mac, "label": "D"} for mac in macs]}

    def test_the_first_present_device_in_the_persons_own_order(self):
        devices = {PHONE_MAC: {"present": False, "lastSeen": engine.iso(at(90))},
                   SWITCH_MAC: {"present": True, "lastSeen": engine.iso(at(10))},
                   RANDOM_MAC: {"present": True, "lastSeen": engine.iso(at(20))}}
        self.assertEqual(engine.chosen_device(self.person(PHONE_MAC, SWITCH_MAC, RANDOM_MAC), devices), SWITCH_MAC)

    def test_without_anyone_present_the_one_seen_most_recently(self):
        devices = {PHONE_MAC: {"present": False, "lastSeen": engine.iso(at(10))},
                   SWITCH_MAC: {"present": False, "lastSeen": engine.iso(at(90))}}
        self.assertEqual(engine.chosen_device(self.person(PHONE_MAC, SWITCH_MAC), devices), SWITCH_MAC)

    def test_a_device_never_seen_is_not_chosen(self):
        devices = {PHONE_MAC: {"present": False}, SWITCH_MAC: {"present": False, "lastSeen": engine.iso(at(5))}}
        self.assertEqual(engine.chosen_device(self.person(PHONE_MAC, SWITCH_MAC), devices), SWITCH_MAC)

    def test_none_of_them_ever_seen_falls_back_to_the_first_one(self):
        """A device the scan never saw, or that the state knows nothing about (a fresh or
        deleted state.json), still has the MAC a wake-on-LAN command needs."""
        self.assertEqual(engine.chosen_device(self.person(PHONE_MAC, SWITCH_MAC), {PHONE_MAC: {}}), PHONE_MAC)

    def test_a_person_without_devices_is_none(self):
        self.assertIsNone(engine.chosen_device(self.person(), {}))

    def test_a_device_that_does_not_count_can_still_be_the_target(self):
        """Presence and "which device do I act on" are different questions: a wake-on-LAN
        is exactly what you want to send to the desktop that must not mark you home. Each
        fixture below also has a counting phone that cannot win on its own (never present,
        never seen), so a counts filter -- whether applied to the whole device list or to
        just one of chosen_device's two loops -- would make the wrong loop, or the
        fallback, hand back the phone instead of the non-counting device."""
        present = {"id": "a" * 32, "name": "Ana", "emoji": "🐻",
                   "devices": [{"mac": PHONE_MAC, "label": "Phone"},
                               {"mac": SWITCH_MAC, "label": "Desktop", "counts": False}]}
        present_devices = {PHONE_MAC: {"present": False}, SWITCH_MAC: {"present": True}}
        self.assertEqual(engine.chosen_device(present, present_devices), SWITCH_MAC)

        seen = {"id": "a" * 32, "name": "Ana", "emoji": "🐻",
                "devices": [{"mac": PHONE_MAC, "label": "Phone"},
                            {"mac": SWITCH_MAC, "label": "Desktop", "counts": False}]}
        seen_devices = {PHONE_MAC: {"present": False, "lastSeen": engine.iso(at(10))},
                         SWITCH_MAC: {"present": False, "lastSeen": engine.iso(at(90))}}
        self.assertEqual(engine.chosen_device(seen, seen_devices), SWITCH_MAC)


class ManualEventTest(unittest.TestCase):
    """Spec §3.3: the synthetic event a manual run passes through event_env."""

    def test_a_person_target_carries_person_and_device(self):
        device = {"ip": "192.168.200.9", "vendor": "Pearcorp", "hostname": "pixel"}
        event = engine.manual_event(ANA, PHONE_MAC, device, "", ["Ana"], [], T0)
        env = engine.event_env(event)
        self.assertEqual(event["event"], "manual")
        self.assertEqual({key: env[key] for key in ("RECOGNITION_EVENT", "RECOGNITION_MESSAGE",
                                                    "RECOGNITION_PERSON_NAME", "RECOGNITION_DEVICE_IP",
                                                    "RECOGNITION_DEVICE_MAC", "RECOGNITION_HOME")},
                         {"RECOGNITION_EVENT": "manual", "RECOGNITION_MESSAGE": "Ana",
                          "RECOGNITION_PERSON_NAME": "Ana", "RECOGNITION_DEVICE_IP": "192.168.200.9",
                          "RECOGNITION_DEVICE_MAC": PHONE_MAC, "RECOGNITION_HOME": "Ana"})

    def test_a_device_target_has_no_person_and_is_named_by_its_label(self):
        event = engine.manual_event(None, SWITCH_MAC, {"ip": "192.168.200.5"}, "Switch", [], [], T0)
        env = engine.event_env(event)
        self.assertIsNone(event["person"])
        self.assertEqual(event["people"], [])
        self.assertEqual(env["RECOGNITION_MESSAGE"], "Switch")
        self.assertNotIn("RECOGNITION_PERSON_NAME", env)

    def test_a_person_without_a_device_has_no_device_variables(self):
        env = engine.event_env(engine.manual_event(ANA, None, None, "", [], [], T0))
        self.assertEqual(env["RECOGNITION_PERSON_NAME"], "Ana")
        self.assertNotIn("RECOGNITION_DEVICE_MAC", env)


class ManualJobsTest(unittest.TestCase):
    def test_a_manual_command_never_runs_on_a_scan(self):
        events = engine.build_events([ANA], [JUAN], [RANDOM_MAC], [GATEWAY], DEVICES, 1, ["Ana"], T0)
        self.assertNotIn("manual", [event["event"] for event in events])
        self.assertEqual(engine.build_jobs([command(["manual"])], events), [])
        self.assertEqual([job["event"] for job in engine.build_jobs([command(["manual", "arrive"])], events)],
                         ["arrive"])


class ManualSampleTest(unittest.TestCase):
    """The Test button has to keep working on a command marked only Manual."""

    def setUp(self):
        self.data = engine.empty_people()
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "🐻"})
        engine.assign(self.data, PHONE_MAC, self.ana["id"], "Pixel")
        self.state = {"devices": {PHONE_MAC: {"present": True, "ip": "192.168.200.9", "vendor": "Pearcorp",
                                              "hostname": "pixel", "lastSeen": engine.iso(T0)}},
                      "people": {}, "alerts": []}

    def test_the_sample_uses_a_real_person_and_their_device(self):
        event = engine.sample_event("manual", None, self.data, self.state, T0)
        self.assertEqual((event["event"], event["person"]["name"]), ("manual", "Ana"))
        self.assertEqual(event["device"]["mac"], PHONE_MAC)

    def test_without_people_the_sample_invents_one(self):
        event = engine.sample_event("manual", None, engine.empty_people(), {"devices": {}, "people": {},
                                                                            "alerts": []}, T0)
        self.assertEqual((event["event"], event["person"]["name"]), ("manual", "Test"))
        self.assertEqual(event["device"]["mac"], engine.SAMPLE_MAC)


if __name__ == "__main__":
    unittest.main()
