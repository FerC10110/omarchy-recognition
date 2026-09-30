import ipaddress
import os
import subprocess
import tempfile
import unittest

from _load import load
from fakes import (ADDR_JSON, GATEWAY_MAC, NMAP_OUT, PHONE_MAC, RANDOM_MAC, SWITCH_MAC, FakeRun, lan,
                   neigh)

engine = load()
NET = ipaddress.IPv4Network("192.168.200.0/24")
AUTO = {"subnet": ""}


class ResolveNetworkTest(unittest.TestCase):
    def test_autodetects_from_default_route(self):
        run = lan()
        self.assertEqual(engine.resolve_network(AUTO, run), {"network": NET, "gateway": "192.168.200.1"})
        self.assertEqual(run.calls_to("ip"), [["ip", "-j", "-4", "route", "show", "default"],
                                              ["ip", "-j", "-4", "addr", "show", "dev", "enp1s0"]])

    def test_configured_subnet_wins_and_keeps_gateway_inside_it(self):
        self.assertEqual(engine.resolve_network({"subnet": "192.168.200.0/24"}, lan()),
                         {"network": NET, "gateway": "192.168.200.1"})
        other = engine.resolve_network({"subnet": "10.1.2.0/24"}, lan())
        self.assertEqual(other["gateway"], "")

    def test_no_default_route_is_a_scan_error(self):
        with self.assertRaises(engine.ScanError) as ctx:
            engine.resolve_network(AUTO, lan(route="[]"))
        self.assertEqual(str(ctx.exception), engine.NO_NETWORK)

    def test_too_big_network_is_a_scan_error(self):
        wide = ADDR_JSON.replace('"prefixlen": 24', '"prefixlen": 16')
        with self.assertRaises(engine.ScanError) as ctx:
            engine.resolve_network(AUTO, lan(addr=wide))
        self.assertIn("too large", str(ctx.exception))

    def test_ip_failure_is_a_scan_error(self):
        run = FakeRun({"ip": (1, "", "Cannot find device")})
        with self.assertRaises(engine.ScanError):
            engine.resolve_network(AUTO, run)

    def test_malformed_interface_address_is_a_scan_error(self):
        bad_addr = ADDR_JSON.replace('"local": "192.168.200.230"', '"local": "nope"')
        with self.assertRaises(engine.ScanError) as ctx:
            engine.resolve_network(AUTO, lan(addr=bad_addr))
        self.assertEqual(str(ctx.exception), engine.NO_NETWORK)


class NmapTest(unittest.TestCase):
    def test_parses_reports(self):
        run = lan()
        self.assertEqual(engine.nmap_up(run, NET),
                         {"192.168.200.1", "192.168.200.5", "192.168.200.9", "192.168.200.230"})
        self.assertEqual(run.calls_to("nmap"), [["nmap", "-sn", "-n", "-T4", "192.168.200.0/24"]])

    def test_missing_nmap(self):
        with self.assertRaises(engine.ScanError) as ctx:
            engine.nmap_up(lan(nmap=FileNotFoundError("nmap")), NET)
        self.assertEqual(str(ctx.exception), engine.NMAP_MISSING)

    def test_timeout(self):
        with self.assertRaises(engine.ScanError) as ctx:
            engine.nmap_up(lan(nmap=subprocess.TimeoutExpired("nmap", 60)), NET)
        self.assertIn("didn't finish", str(ctx.exception))


class NeighboursTest(unittest.TestCase):
    def test_keeps_entries_with_mac_inside_network(self):
        table = engine.read_neighbors(lan(), NET)
        self.assertEqual(table, {
            "192.168.200.1": {"mac": GATEWAY_MAC, "reachable": True},
            "192.168.200.9": {"mac": PHONE_MAC, "reachable": True},
            "192.168.200.112": {"mac": RANDOM_MAC, "reachable": False},
            "192.168.200.5": {"mac": SWITCH_MAC, "reachable": False},
        })

    def test_sightings_need_reachable_or_nmap(self):
        table = engine.read_neighbors(lan(), NET)
        seen = engine.sightings(table, engine.nmap_up(lan(), NET))
        # .112 is STALE and nmap did not see it: not seen. .5 is STALE but nmap saw it: seen.
        self.assertEqual(seen, {GATEWAY_MAC: "192.168.200.1", SWITCH_MAC: "192.168.200.5",
                                PHONE_MAC: "192.168.200.9"})

    def test_delay_and_probe_are_not_sightings(self):
        run = lan(neighbours=neigh([("192.168.200.40", "aa:bb:cc:dd:ee:01", "DELAY"),
                                    ("192.168.200.41", "aa:bb:cc:dd:ee:02", "PROBE")]))
        self.assertEqual(engine.sightings(engine.read_neighbors(run, NET), set()), {})

    def test_one_mac_on_two_ips_keeps_the_lowest(self):
        table = {"192.168.200.20": {"mac": PHONE_MAC, "reachable": True},
                 "192.168.200.3": {"mac": PHONE_MAC, "reachable": True}}
        self.assertEqual(engine.sightings(table, set()), {PHONE_MAC: "192.168.200.3"})


class ConfirmedIpsTest(unittest.TestCase):
    def test_confirmed_needs_reachable_or_nmap(self):
        table = engine.read_neighbors(lan(), NET)
        confirmed = engine.confirmed_ips(table, engine.nmap_up(lan(), NET))
        # .112 is STALE and nmap did not see it: not confirmed. .5 is STALE but nmap saw it: confirmed.
        self.assertEqual(confirmed, {"192.168.200.1": GATEWAY_MAC, "192.168.200.5": SWITCH_MAC,
                                     "192.168.200.9": PHONE_MAC})

    def test_confirmed_keeps_every_ip_for_one_mac(self):
        table = {"192.168.200.20": {"mac": PHONE_MAC, "reachable": True},
                 "192.168.200.3": {"mac": PHONE_MAC, "reachable": True}}
        self.assertEqual(engine.confirmed_ips(table, set()),
                         {"192.168.200.20": PHONE_MAC, "192.168.200.3": PHONE_MAC})


class EnrichmentTest(unittest.TestCase):
    def test_oui_longest_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prefixes")
            with open(path, "w") as fh:
                fh.write("# comment\nAABBCC Acme Electronics\n00005E Generic\n00005EE Fictional Corp\n")
            table = engine.load_oui(path)
        self.assertEqual(engine.vendor_for("aa:bb:cc:00:00:01", table), "Acme Electronics")
        self.assertEqual(engine.vendor_for("00:00:5e:e0:00:2b", table), "Fictional Corp")
        self.assertEqual(engine.vendor_for("00:00:5e:00:00:2b", table), "Generic")
        self.assertEqual(engine.vendor_for("00:00:00:00:00:01", table), "")
        self.assertEqual(engine.load_oui("/nonexistent"), {})

    def test_random_mac(self):
        self.assertTrue(engine.is_random_mac(RANDOM_MAC))           # c2
        self.assertTrue(engine.is_random_mac("7a:00:00:00:00:54"))  # 7a
        self.assertFalse(engine.is_random_mac(PHONE_MAC))           # bc
        self.assertFalse(engine.is_random_mac("00:00:5e:e0:00:2b"))

    def test_hostname(self):
        run = lan(avahi={"192.168.200.9": "Android_4f1c.local"})
        self.assertEqual(engine.resolve_hostname(run, "192.168.200.9"), "Android_4f1c")
        self.assertEqual(run.calls_to("avahi-resolve"), [["avahi-resolve", "-a", "192.168.200.9"]])
        self.assertEqual(engine.resolve_hostname(run, "192.168.200.5"), "")
        slow = FakeRun({"avahi-resolve": subprocess.TimeoutExpired("avahi-resolve", 1)})
        self.assertEqual(engine.resolve_hostname(slow, "192.168.200.5"), "")
        missing = FakeRun({"avahi-resolve": FileNotFoundError("avahi-resolve")})
        self.assertEqual(engine.resolve_hostname(missing, "192.168.200.5"), "")

    def test_hostname_sanitized_against_option_injection(self):
        run = lan(avahi={"192.168.200.9": "--urgency=x.local"})
        hostname = engine.resolve_hostname(run, "192.168.200.9")
        self.assertFalse(hostname.startswith("-"))
        self.assertEqual(hostname, "urgency=x")

    def test_hostname_strips_non_printable_characters(self):
        run = lan(avahi={"192.168.200.9": "ok\x07bell.local"})
        self.assertEqual(engine.resolve_hostname(run, "192.168.200.9"), "okbell")


if __name__ == "__main__":
    unittest.main()
