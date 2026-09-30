import unittest

from _load import load
from fakes import GATEWAY_MAC, PHONE_MAC, T0, at

engine = load()
GW = "192.168.200.1"
EVIL = "aa:bb:cc:dd:ee:ff"
OTHER = "00:00:5e:00:53:05"


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.state = engine.empty_state()

    def test_first_sighting_is_accepted_silently(self):
        self.assertEqual(engine.check_gateway(self.state, GW, {GW: GATEWAY_MAC}, T0), [])
        self.assertEqual(self.state["gateway"], {"ip": GW, "acceptedMac": GATEWAY_MAC, "seenMac": GATEWAY_MAC})

    def test_new_mac_raises_one_alert(self):
        engine.check_gateway(self.state, GW, {GW: GATEWAY_MAC}, T0)
        alerts = engine.check_gateway(self.state, GW, {GW: EVIL}, at(20))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["kind"], "gateway-mac")
        self.assertEqual(alerts[0]["key"], f"gateway-mac:{GW}|{EVIL}")
        self.assertEqual(alerts[0]["data"], {"ip": GW, "expectedMac": GATEWAY_MAC, "seenMac": EVIL})
        self.assertEqual(engine.check_gateway(self.state, GW, {GW: EVIL}, at(40)), [])   # deduplicated
        self.assertEqual(len(self.state["alerts"]), 1)

    def test_new_mac_raises_one_alert_even_when_it_also_holds_a_lower_ip(self):
        # Same MAC answers for the gateway IP and for a lower IP of its own: the
        # old MAC->lowest-IP map would have hidden the gateway sighting entirely.
        engine.check_gateway(self.state, GW, {GW: GATEWAY_MAC}, T0)
        alerts = engine.check_gateway(self.state, GW, {GW: EVIL, "192.168.200.50": EVIL}, at(20))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["data"], {"ip": GW, "expectedMac": GATEWAY_MAC, "seenMac": EVIL})

    def test_no_gateway_or_not_seen_does_nothing(self):
        self.assertEqual(engine.check_gateway(self.state, "", {GW: GATEWAY_MAC}, T0), [])
        self.assertEqual(engine.check_gateway(self.state, GW, {}, T0), [])
        self.assertEqual(self.state["gateway"]["acceptedMac"], "")

    def test_other_router_ip_is_a_new_network(self):
        engine.check_gateway(self.state, GW, {GW: GATEWAY_MAC}, T0)
        self.assertEqual(engine.check_gateway(self.state, "10.0.0.1", {"10.0.0.1": EVIL}, at(20)), [])
        self.assertEqual(self.state["gateway"]["acceptedMac"], EVIL)

    def test_accept_and_dismiss(self):
        engine.check_gateway(self.state, GW, {GW: GATEWAY_MAC}, T0)
        engine.check_gateway(self.state, GW, {GW: EVIL}, at(20))
        engine.accept_gateway(self.state)
        self.assertEqual(self.state["gateway"]["acceptedMac"], EVIL)
        self.assertEqual(self.state["alerts"], [])
        self.assertEqual(engine.check_gateway(self.state, GW, {GW: EVIL}, at(40)), [])
        with self.assertRaises(engine.RecognitionError):
            engine.accept_gateway(engine.empty_state())

    def test_dismissed_alert_waits_an_hour(self):
        engine.check_gateway(self.state, GW, {GW: GATEWAY_MAC}, T0)
        alert = engine.check_gateway(self.state, GW, {GW: EVIL}, at(20))[0]
        engine.dismiss_alert(self.state, alert["id"], at(30))
        self.assertEqual(self.state["alerts"], [])
        self.assertEqual(engine.check_gateway(self.state, GW, {GW: EVIL}, at(60)), [])
        engine.prune_dismissed(self.state, at(30 + 3600))
        self.assertEqual(self.state["dismissed"], {})
        self.assertEqual(len(engine.check_gateway(self.state, GW, {GW: EVIL}, at(30 + 3600))), 1)
        with self.assertRaises(engine.RecognitionError):
            engine.dismiss_alert(self.state, "nope", at(99))


class IpConflictTest(unittest.TestCase):
    def setUp(self):
        self.state = engine.empty_state()

    def cycle(self, seconds, seen, grace=300):
        """seen is mac -> ip (test-friendly); check_ip_conflicts wants confirmed
        ip -> mac, so invert it here."""
        engine.apply_sightings(self.state, seen, at(seconds), grace)
        confirmed = {ip: mac for mac, ip in seen.items()}
        return engine.check_ip_conflicts(self.state, confirmed, at(seconds), grace, GW)

    def test_ip_taken_by_new_mac_while_old_is_recent(self):
        self.assertEqual(self.cycle(0, {PHONE_MAC: "192.168.200.9"}), [])
        alerts = self.cycle(20, {EVIL: "192.168.200.9"})
        self.assertEqual([a["data"] for a in alerts],
                         [{"ip": "192.168.200.9", "previousMac": PHONE_MAC, "mac": EVIL}])
        self.assertEqual(self.state["ipOwners"]["192.168.200.9"]["mac"], EVIL)

    def test_ip_taken_by_new_mac_even_when_attacker_also_holds_a_lower_ip(self):
        # The attacker answers for both its own (lower) IP and the victim's IP:
        # the old MAC->lowest-IP map would have hidden the victim's IP entirely.
        self.assertEqual(self.cycle(0, {PHONE_MAC: "192.168.200.9"}), [])
        confirmed = {"192.168.200.9": EVIL, "192.168.200.2": EVIL}
        engine.apply_sightings(self.state, {EVIL: "192.168.200.2"}, at(20), 300)
        alerts = engine.check_ip_conflicts(self.state, confirmed, at(20), 300, GW)
        self.assertEqual([a["data"] for a in alerts],
                         [{"ip": "192.168.200.9", "previousMac": PHONE_MAC, "mac": EVIL}])

    def test_renumbering_is_not_a_conflict(self):
        self.cycle(0, {PHONE_MAC: "192.168.200.9", OTHER: "192.168.200.5"})
        self.assertEqual(self.cycle(20, {OTHER: "192.168.200.9", PHONE_MAC: "192.168.200.50"}), [])

    def test_old_owner_long_gone_is_not_a_conflict(self):
        self.cycle(0, {PHONE_MAC: "192.168.200.9"})
        self.assertEqual(self.cycle(400, {EVIL: "192.168.200.9"}), [])

    def test_gateway_ip_is_excluded(self):
        self.cycle(0, {GATEWAY_MAC: GW})
        self.assertEqual(self.cycle(20, {EVIL: GW}), [])


class ForgetTest(unittest.TestCase):
    def test_forget_only_unowned_known_devices(self):
        state, data = engine.empty_state(), engine.empty_people()
        engine.apply_sightings(state, {PHONE_MAC: "192.168.200.9", OTHER: "192.168.200.5"}, T0, 300)
        engine.check_ip_conflicts(state, {"192.168.200.9": PHONE_MAC}, T0, 300, GW)
        engine.house(data, OTHER, "")
        engine.forget_device(state, data, PHONE_MAC.upper())
        self.assertNotIn(PHONE_MAC, state["devices"])
        self.assertEqual(state["ipOwners"], {})
        with self.assertRaises(engine.RecognitionError):
            engine.forget_device(state, data, OTHER)
        with self.assertRaises(engine.RecognitionError):
            engine.forget_device(state, data, PHONE_MAC)


class PruneDevicesTest(unittest.TestCase):
    def device(self, days_ago, present=False):
        return {"lastSeen": engine.iso(at(-days_ago * 86400)), "present": present}

    def test_prunes_only_stale_unowned_absent_devices(self):
        state, data = engine.empty_state(), engine.empty_people()
        engine.save_person(data, {"name": "Ana", "emoji": "🐻", "devices": [{"mac": PHONE_MAC}]})
        engine.house(data, OTHER, "Switch")
        unowned_old, unowned_recent = "00:00:5e:00:53:30", "aa:bb:cc:00:11:22"
        state["devices"] = {
            PHONE_MAC: self.device(31),          # owned: kept
            OTHER: self.device(31),              # in House: kept
            unowned_old: self.device(31),        # unowned, stale: pruned
            unowned_recent: self.device(29),     # unowned, not stale yet: kept
        }
        state["ipOwners"] = {"192.168.200.9": {"mac": unowned_old, "seenAt": engine.iso(T0)}}
        engine.prune_devices(state, data, T0)
        self.assertEqual(sorted(state["devices"]), sorted([PHONE_MAC, OTHER, unowned_recent]))
        self.assertEqual(state["ipOwners"], {})

    def test_present_device_is_never_pruned(self):
        state, data = engine.empty_state(), engine.empty_people()
        mac = "00:00:5e:00:53:30"
        state["devices"] = {mac: self.device(31, present=True)}
        engine.prune_devices(state, data, T0)
        self.assertIn(mac, state["devices"])


if __name__ == "__main__":
    unittest.main()
