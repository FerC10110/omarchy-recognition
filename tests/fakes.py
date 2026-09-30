"""Test doubles and fixtures for the engine."""
import contextlib
import datetime
import json
import os
import subprocess
import time

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 9, 17, 21, 0, 0, tzinfo=UTC)


def at(seconds):
    """T0 plus a number of seconds."""
    return T0 + datetime.timedelta(seconds=seconds)


def env(tmpdir):
    """An environ whose config, state and data live under tmpdir."""
    return {"HOME": tmpdir,
            "XDG_CONFIG_HOME": os.path.join(tmpdir, "config"),
            "XDG_STATE_HOME": os.path.join(tmpdir, "state"),
            "XDG_DATA_HOME": os.path.join(tmpdir, "data")}


@contextlib.contextmanager
def tz(name="America/Argentina/Buenos_Aires"):
    """Pin the local timezone. The history cuts spans at LOCAL midnight, so a test that
    does not pin it passes or fails depending on where it runs."""
    before = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = before
        time.tzset()


class FakeRun:
    """subprocess.run double. `answers` maps a program name to a
    (code, stdout, stderr) tuple, an exception instance to raise, or a
    callable taking the argv and returning either. Unknown programs answer
    (0, "", ""). Every argv is recorded in `calls`, and the keyword arguments it
    was called with in `kwargs`, so a test can pin how a program is run."""

    def __init__(self, answers=None):
        self.calls = []
        self.kwargs = []
        self.answers = dict(answers or {})

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        self.kwargs.append(kwargs)
        answer = self.answers.get(argv[0], (0, "", ""))
        if callable(answer):
            answer = answer(argv)
        if isinstance(answer, BaseException):
            raise answer
        code, out, err = answer
        return subprocess.CompletedProcess(argv, code, out, err)

    def calls_to(self, program):
        return [call for call in self.calls if call[0] == program]


ROUTE_JSON = json.dumps([{"dst": "default", "gateway": "192.168.200.1", "dev": "enp1s0",
                          "protocol": "dhcp", "prefsrc": "192.168.200.230", "metric": 100, "flags": []}])

ADDR_JSON = json.dumps([{"ifindex": 2, "ifname": "enp1s0", "operstate": "UP",
                         "addr_info": [{"family": "inet", "local": "192.168.200.230", "prefixlen": 24,
                                        "broadcast": "192.168.200.255", "scope": "global"}]}])

GATEWAY_MAC = "02:00:00:00:00:01"    # locally administered: no real vendor
# 00:00:5e:00:53:xx is the range IANA reserves for documentation: global, but no real vendor owns it.
PHONE_MAC = "00:00:5e:00:53:09"      # Pearcorp, 192.168.200.9, REACHABLE
RANDOM_MAC = "c2:00:00:00:01:12"     # locally administered, 192.168.200.112, STALE
SWITCH_MAC = "00:00:5e:00:53:05"     # Netgadget, 192.168.200.5, STALE


def neigh(entries):
    """ip -j -4 neigh JSON from (ip, mac or None, state) triples."""
    out = []
    for ip, mac, state in entries:
        item = {"dst": ip, "dev": "enp1s0", "state": [state]}
        if mac:
            item["lladdr"] = mac
        out.append(item)
    return json.dumps(out)


NEIGH_JSON = neigh([
    ("192.168.200.1", GATEWAY_MAC, "REACHABLE"),
    ("192.168.200.9", PHONE_MAC, "REACHABLE"),
    ("192.168.200.112", RANDOM_MAC, "STALE"),
    ("192.168.200.5", SWITCH_MAC, "STALE"),
    ("192.168.200.196", None, "FAILED"),
    ("172.17.0.2", "02:42:ac:11:00:02", "REACHABLE"),
])


def nmap_out(ips):
    lines = ["Starting Nmap 7.991 ( https://nmap.org ) at 2026-09-17 22:38 -0300"]
    for ip in ips:
        lines += [f"Nmap scan report for {ip}", "Host is up (0.00078s latency)."]
    lines.append(f"Nmap done: 256 IP addresses ({len(ips)} hosts up) scanned in 3.74 seconds")
    return "\n".join(lines) + "\n"


NMAP_OUT = nmap_out(["192.168.200.1", "192.168.200.5", "192.168.200.9", "192.168.200.230"])


def lan(route=ROUTE_JSON, addr=ADDR_JSON, neighbours=NEIGH_JSON, nmap=NMAP_OUT, avahi=None, extra=None):
    """A FakeRun that looks like the user's LAN. `nmap`/`neighbours` may be
    strings or exceptions; `avahi` maps ip -> hostname ('.local' included)."""
    avahi = dict(avahi or {})

    def ip(argv):
        if "route" in argv:
            return (0, route, "")
        if "addr" in argv:
            return (0, addr, "")
        if isinstance(neighbours, BaseException):
            return neighbours
        return (0, neighbours, "")

    def resolve(argv):
        name = avahi.get(argv[-1])
        return (0, f"{argv[-1]}\t{name}\n", "") if name else (1, "", "Failed to resolve address")

    answers = {"ip": ip, "avahi-resolve": resolve,
               "nmap": nmap if isinstance(nmap, BaseException) else (0, nmap, "")}
    answers.update(extra or {})
    return FakeRun(answers)


def readily_item(title, search, tags=(), inherited=(), kind="text"):
    """One item as `readily list --json` prints it."""
    return {"index": 0, "kind": kind, "title": title, "description": "",
            "tags": list(tags), "inheritedTags": list(inherited),
            "preview": search[:240], "lineCount": len(search.split("\n")),
            "search": search, "image": "", "missing": False, "hash": "0" * 16}


def readily_listing(notes):
    """`readily list --tag recognition --json` output. `notes` maps a note name to items."""
    return json.dumps({"folder": "/home/tester/vault/Readily", "tags": [],
                       "sections": [{"name": name, "error": "", "tags": [], "items": items}
                                    for name, items in notes.items()]})


def fake_readily(tmpdir, answer=(0, "", "")):
    """A file that passes for the readily binary, plus a FakeRun that answers when it
    is the program being run. Returns (path, run): put the path in the environ as
    RECOGNITION_READILY_BIN."""
    path = os.path.join(tmpdir, "readily")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n")
    os.chmod(path, 0o755)   # shutil.which only finds executables
    return path, FakeRun({path: answer})
