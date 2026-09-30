import unittest

from _load import load
from fakes import T0, at, lan

engine = load()
A, B, C = "00:00:5e:00:53:09", "c2:00:00:00:01:12", "00:00:5e:00:53:05"
GRACE = 300


class DevicePresenceTest(unittest.TestCase):
    def setUp(self):
        self.state = engine.empty_state()

    def step(self, seconds, seen):
        return engine.apply_sightings(self.state, seen, at(seconds), GRACE)

    def test_first_sighting_arrives_and_is_new(self):
        arrived, left, new = self.step(0, {A: "192.168.200.9"})
        self.assertEqual((arrived, left, new), ([A], [], [A]))
        device = self.state["devices"][A]
        self.assertEqual(device["ip"], "192.168.200.9")
        self.assertEqual(device["firstSeen"], "2026-09-17T21:00:00Z")
        self.assertEqual(device["lastSeen"], "2026-09-17T21:00:00Z")
        self.assertTrue(device["present"])
        self.assertEqual(device["since"], "2026-09-17T21:00:00Z")

    def test_missing_a_few_cycles_is_not_leaving(self):
        self.step(0, {A: "192.168.200.9"})
        for seconds in (20, 40, 300):
            self.assertEqual(self.step(seconds, {}), ([], [], []))
        self.assertTrue(self.state["devices"][A]["present"])

    def test_leaves_after_grace_and_arrives_again(self):
        self.step(0, {A: "192.168.200.9"})
        self.assertEqual(self.step(301, {}), ([], [A], []))
        device = self.state["devices"][A]
        self.assertFalse(device["present"])
        self.assertIsNone(device["since"])
        self.assertEqual(self.step(600, {A: "192.168.200.10"}), ([A], [], []))
        self.assertEqual(device["since"], "2026-09-17T21:10:00Z")
        self.assertEqual(device["firstSeen"], "2026-09-17T21:00:00Z")
        self.assertEqual(device["ip"], "192.168.200.10")


class EnrichTest(unittest.TestCase):
    def test_vendor_once_and_hostname_budget(self):
        state = engine.empty_state()
        seen = {f"00:00:5e:00:54:{i:02x}": f"192.168.200.{10 + i}" for i in range(10)}
        seen[B] = "192.168.200.112"
        _, _, new = engine.apply_sightings(state, seen, T0, GRACE)
        run = lan(avahi={"192.168.200.10": "Android_1.local"})
        loads = []
        engine.enrich(state, seen, new, T0, run, lambda: loads.append(1) or {"00005E": "Pearcorp"})
        self.assertEqual(loads, [1])
        self.assertEqual(state["devices"]["00:00:5e:00:54:00"]["vendor"], "Pearcorp")
        self.assertEqual(state["devices"]["00:00:5e:00:54:00"]["hostname"], "Android_1")
        self.assertEqual(state["devices"][B]["vendor"], "")
        self.assertTrue(state["devices"][B]["randomMac"])
        self.assertEqual(len(run.calls_to("avahi-resolve")), engine.HOSTNAME_BUDGET)

    def test_hostname_retried_only_after_an_hour(self):
        state = engine.empty_state()
        seen = {A: "192.168.200.9"}
        _, _, new = engine.apply_sightings(state, seen, T0, GRACE)
        run = lan()
        engine.enrich(state, seen, new, T0, run, dict)
        engine.enrich(state, seen, [], at(1800), run, dict)
        self.assertEqual(len(run.calls_to("avahi-resolve")), 1)
        engine.enrich(state, seen, [], at(3601), run, dict)
        self.assertEqual(len(run.calls_to("avahi-resolve")), 2)

    def test_a_known_hostname_is_refreshed_once_a_day(self):
        """A phone that renames itself must not keep its old name forever. suggest_owner
        pairs a rotated MAC with its owner by that name, so a stale one leaves the
        owner's own phone looking like a stranger's."""
        state = engine.empty_state()
        seen = {A: "192.168.200.9"}
        _, _, new = engine.apply_sightings(state, seen, T0, GRACE)
        engine.enrich(state, seen, new, T0, lan(avahi={"192.168.200.9": "Android_one.local"}), dict)
        self.assertEqual(state["devices"][A]["hostname"], "Android_one")

        renamed = lan(avahi={"192.168.200.9": "Android_two.local"})
        engine.enrich(state, seen, [], at(43200), renamed, dict)
        self.assertEqual(len(renamed.calls_to("avahi-resolve")), 0)
        self.assertEqual(state["devices"][A]["hostname"], "Android_one")

        engine.enrich(state, seen, [], at(86401), renamed, dict)
        self.assertEqual(state["devices"][A]["hostname"], "Android_two")

    def test_a_refresh_that_answers_nothing_keeps_the_name(self):
        """mDNS misses a sleeping phone all the time. Wiping the name on a miss would
        throw away the one thing that pairs its next MAC with its owner."""
        state = engine.empty_state()
        seen = {A: "192.168.200.9"}
        _, _, new = engine.apply_sightings(state, seen, T0, GRACE)
        engine.enrich(state, seen, new, T0, lan(avahi={"192.168.200.9": "Pixel.local"}), dict)

        silent = lan()
        engine.enrich(state, seen, [], at(86401), silent, dict)
        self.assertEqual(state["devices"][A]["hostname"], "Pixel")
        self.assertEqual(len(silent.calls_to("avahi-resolve")), 1)
        # The miss still counts as a check, or every cycle would ask again.
        engine.enrich(state, seen, [], at(86460), silent, dict)
        self.assertEqual(len(silent.calls_to("avahi-resolve")), 1)

    def test_no_oui_load_without_new_devices(self):
        state = engine.empty_state()
        engine.enrich(state, {}, [], T0, lan(), lambda: self.fail("loaded the OUI table"))


class PeoplePresenceTest(unittest.TestCase):
    def setUp(self):
        self.state = engine.empty_state()
        self.data = engine.empty_people()
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "🐻",
                                                  "devices": [{"mac": A}, {"mac": B}]})

    def cycle(self, seconds, seen):
        arrived, left, _ = engine.apply_sightings(self.state, seen, at(seconds), GRACE)
        return engine.update_people(self.state, self.data, arrived, left)

    def test_arrival_and_departure(self):
        self.assertEqual(self.cycle(0, {A: "192.168.200.9"}), ([self.ana], []))
        self.assertEqual(self.state["people"][self.ana["id"]],
                         {"present": True, "since": "2026-09-17T21:00:00Z"})
        self.assertEqual(self.cycle(301, {}), ([], [self.ana]))
        self.assertEqual(self.state["people"][self.ana["id"]], {"present": False, "since": None})

    def test_switching_devices_is_neither(self):
        self.cycle(0, {A: "192.168.200.9"})
        self.assertEqual(self.cycle(200, {B: "192.168.200.112"}), ([], []))
        self.assertEqual(self.cycle(400, {B: "192.168.200.112"}), ([], []))   # A left, B still here
        self.assertTrue(self.state["people"][self.ana["id"]]["present"])

    def test_assigning_a_present_device_is_silent(self):
        self.cycle(0, {C: "192.168.200.5"})
        juan = engine.save_person(self.data, {"name": "Juan", "emoji": "🦊", "devices": [{"mac": C}]})
        self.assertEqual(self.cycle(20, {C: "192.168.200.5"}), ([], []))
        self.assertTrue(self.state["people"][juan["id"]]["present"])

    def test_unassigning_is_silent_and_deleted_people_are_dropped(self):
        self.cycle(0, {A: "192.168.200.9"})
        self.data["people"][0]["devices"] = []
        self.assertEqual(self.cycle(20, {A: "192.168.200.9"}), ([], []))
        self.data["people"] = []
        self.cycle(40, {})
        self.assertEqual(self.state["people"], {})

    def test_person_presence_summary(self):
        self.cycle(0, {A: "192.168.200.9"})
        self.cycle(60, {B: "192.168.200.112"})
        present, since, last = engine.person_presence(self.data["people"][0], self.state["devices"])
        self.assertEqual((present, since, last),
                         (True, "2026-09-17T21:00:00Z", "2026-09-17T21:01:00Z"))

    def test_a_device_that_does_not_count_says_nothing_about_its_owner(self):
        # Not even "seen": an always-on printer would otherwise report its owner as
        # seen just now while they have been away for days.
        self.data["people"][0]["devices"][1]["counts"] = False
        self.cycle(0, {B: "192.168.200.112"})
        self.assertEqual(engine.person_presence(self.data["people"][0], self.state["devices"]),
                         (False, None, None))

    def test_plugging_in_a_printer_is_not_an_arrival(self):
        self.data["people"][0]["devices"][1]["counts"] = False
        self.assertEqual(self.cycle(0, {B: "192.168.200.112"}), ([], []))
        self.assertEqual(self.cycle(60, {A: "192.168.200.9", B: "192.168.200.112"}), ([self.ana], []))

    def test_a_freshly_added_person_does_not_arrive_when_only_the_printer_switches_on(self):
        # Ana's phone (A) is already up from a previous cycle, but she is not yet in
        # state["people"] (just created or edited, or state.json was rebuilt). This
        # cycle only the always-on printer (B, counts=False) newly turns on. Without
        # the counts filter on `macs`, B's mac would land in `macs & arrived` and
        # produce a spurious arrival for a printer being plugged in.
        self.data["people"][0]["devices"][1]["counts"] = False
        self.cycle(0, {A: "192.168.200.9"})
        self.state["people"] = {}
        self.assertEqual(self.cycle(60, {A: "192.168.200.9", B: "192.168.200.112"}), ([], []))
        present, _, _ = engine.person_presence(self.data["people"][0], self.state["devices"])
        self.assertTrue(present)

    def test_a_person_whose_devices_none_count_is_never_present(self):
        for device in self.data["people"][0]["devices"]:
            device["counts"] = False
        self.cycle(0, {A: "192.168.200.9", B: "192.168.200.112"})
        self.assertEqual(engine.person_presence(self.data["people"][0], self.state["devices"]),
                         (False, None, None))

    def test_the_house_is_empty_when_only_the_printer_is_on(self):
        self.data["people"][0]["devices"][1]["counts"] = False
        self.cycle(0, {B: "192.168.200.112"})
        self.assertEqual(engine.home_names(self.data, self.state), [])


if __name__ == "__main__":
    unittest.main()
