import datetime
import io
import json
import os
import tempfile
import unittest

from _load import load
from fakes import at, env, lan, neigh, nmap_out, tz

engine = load()

A, B, C = "00:00:5e:00:53:31", "00:00:5e:00:53:44", "00:00:5e:00:53:55"
STRANGER = "c2:11:22:33:44:55"


class SubjectsTest(unittest.TestCase):
    def setUp(self):
        self.data = engine.empty_people()
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "\U0001f43b",
                                                  "devices": [{"mac": A}]})
        self.data["house"].append({"mac": B, "label": "printer"})
        self.state = engine.empty_state()
        self.state["devices"] = {A: {"present": True}, B: {"present": False},
                                 STRANGER: {"present": True}}

    def subjects(self, scope):
        settings = dict(engine.DEFAULT_SETTINGS, history=True, historyDevices=scope)
        return engine._history_subjects(self.data, self.state, settings)

    def test_none_follows_only_the_people(self):
        self.assertEqual(self.subjects("none"), [("person", self.ana["id"])])

    def test_owned_adds_the_devices_you_assigned(self):
        self.assertEqual(self.subjects("owned"),
                         [("person", self.ana["id"]), ("mac", A)])

    def test_owned_keeps_each_person_next_to_their_own_devices(self):
        leo = engine.save_person(self.data, {"name": "Leo", "emoji": "\U0001f98a",
                                             "devices": [{"mac": C}]})
        self.assertEqual(self.subjects("owned"),
                         [("person", self.ana["id"]), ("mac", A),
                          ("person", leo["id"]), ("mac", C)])

    def test_all_adds_house_and_the_strangers(self):
        # Sorted, so the walk is the same on every run.
        self.assertEqual(self.subjects("all"),
                         [("person", self.ana["id"]), ("mac", A), ("mac", B),
                          ("mac", STRANGER)])

    def test_all_ignores_an_assigned_device_that_was_never_seen(self):
        engine.save_person(self.data, {"name": "Leo", "emoji": "\U0001f98a",
                                       "devices": [{"mac": C}]})
        self.assertNotIn(("mac", C), self.subjects("all"))


class WriterTest(unittest.TestCase):
    """One cycle, one write per month -- not one per subject."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = env(self.tmp.name)
        self.data = engine.empty_people()
        self.data["settings"].update(history=True, historyDevices="all")
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "\U0001f43b",
                                                  "devices": [{"mac": A}]})
        self.state = engine.empty_state()
        self.writes = []
        self.real_write = engine.atomic_write_json

        def spy(path, payload):
            self.writes.append(path)
            self.real_write(path, payload)

        engine.atomic_write_json = spy

    def tearDown(self):
        engine.atomic_write_json = self.real_write
        self.tmp.cleanup()

    def month_writes(self):
        return [path for path in self.writes if path.endswith("2026-09.json")]

    def test_twenty_subjects_leaving_at_once_write_the_month_once(self):
        with tz():
            macs = ["00:00:5e:00:53:%02d" % n for n in range(20)] + [A]
            self.state["devices"] = {mac: {"present": True, "since": engine.iso(at(0))}
                                     for mac in macs}
            start = at(0)
            engine.history_tick(self.environ, self.state, self.data,
                                self.data["settings"], start)
            # Twenty-one devices and the person A belongs to.
            self.assertEqual(len(self.state["history"]["open"]), 22)
            self.writes = []
            # Everyone gone: twenty-two spans close in the same tick.
            self.state["devices"] = {mac: {"present": False, "lastSeen": engine.iso(at(60))}
                                     for mac in macs}
            engine.history_tick(self.environ, self.state, self.data,
                                self.data["settings"], at(600))
            self.assertEqual(len(self.month_writes()), 1)

    def test_the_spans_are_all_there(self):
        with tz():
            self.state["devices"] = {A: {"present": True, "since": engine.iso(at(0))}}
            engine.history_tick(self.environ, self.state, self.data,
                                self.data["settings"], at(0))
            self.state["devices"] = {A: {"present": False, "lastSeen": engine.iso(at(60))}}
            engine.history_tick(self.environ, self.state, self.data,
                                self.data["settings"], at(600))
            days = engine.load_month(self.environ, "2026-09")["days"]
            spans = [span for day in sorted(days) for span in days[day].get("spans", [])]
            self.assertEqual(sorted(span.get("person") or span.get("mac") for span in spans),
                             sorted([self.ana["id"], A]))

    def test_a_span_across_the_end_of_the_month_still_writes_both_files(self):
        with tz():
            engine.record_span(self.environ, ("person", "p1"),
                               datetime.datetime(2026, 8, 31, 20, 0, tzinfo=engine.UTC),
                               datetime.datetime(2026, 9, 1, 20, 0, tzinfo=engine.UTC),
                               "home")
            self.assertIn("2026-08-31", engine.load_month(self.environ, "2026-08")["days"])
            self.assertIn("2026-09-01", engine.load_month(self.environ, "2026-09")["days"])


class NameBookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = env(self.tmp.name)
        self.data = engine.empty_people()
        self.data["settings"].update(history=True, historyDevices="all")
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "\U0001f43b",
                                                  "devices": [{"mac": A, "label": "phone"}]})
        self.data["house"].append({"mac": B, "label": "printer"})
        self.state = engine.empty_state()
        self.state["devices"] = {
            A: {"present": True, "vendor": "Samsung"},
            B: {"present": True, "vendor": "Brother"},
            STRANGER: {"present": True, "vendor": "", "randomMac": True}}

    def tearDown(self):
        self.tmp.cleanup()

    def book(self, month="2026-09"):
        return engine.load_month(self.environ, month)["devices"]

    def tick(self, seconds, devices):
        self.state["devices"] = devices
        engine.history_tick(self.environ, self.state, self.data,
                            self.data["settings"], at(seconds))

    def test_a_fresh_month_has_an_empty_book(self):
        self.assertEqual(engine.empty_month("2026-09")["devices"], {})

    def test_writing_a_span_stamps_the_name(self):
        with tz():
            seen = dict(self.state["devices"])
            self.tick(0, seen)
            # Going absent is what apply_sightings does to the cache entry: the flags
            # change, the vendor it guessed stays.
            gone = {mac: dict(entry, present=False, lastSeen=engine.iso(at(60)))
                    for mac, entry in seen.items()}
            self.tick(600, gone)
            book = self.book()
            self.assertEqual(book[A], {"label": "phone", "vendor": "Samsung",
                                       "randomMac": False})
            self.assertEqual(book[B], {"label": "printer", "vendor": "Brother",
                                       "randomMac": False})
            self.assertEqual(book[STRANGER], {"label": "", "vendor": "",
                                              "randomMac": True})

    def test_a_person_never_lands_in_the_device_book(self):
        with tz():
            self.tick(0, {A: {"present": True, "vendor": "Samsung"}})
            self.tick(600, {A: {"present": False, "lastSeen": engine.iso(at(60))}})
            self.assertEqual(sorted(self.book()), [A])

    def test_renaming_the_device_wins_on_the_next_write(self):
        with tz():
            self.tick(0, {B: {"present": True, "vendor": "Brother"}})
            self.tick(600, {B: {"present": False, "lastSeen": engine.iso(at(60))}})
            self.data["house"][0]["label"] = "the printer"
            self.tick(1200, {B: {"present": True, "vendor": "Brother"}})
            self.tick(1800, {B: {"present": False, "lastSeen": engine.iso(at(1260))}})
            self.assertEqual(self.book()[B]["label"], "the printer")

    def test_a_device_the_cache_will_forget_is_named_while_it_is_still_there(self):
        with tz():
            # The order that makes this safe: a span closes as soon as the device reads
            # absent (one gracePeriod), and prune_devices only drops it after
            # DEVICE_RETENTION -- thirty days later. So the vendor is always still in the
            # cache when the span is written, and the book keeps it afterwards.
            self.tick(0, {STRANGER: {"present": True, "vendor": "TP-Link",
                                     "randomMac": True}})
            self.tick(600, {STRANGER: {"present": False, "vendor": "TP-Link",
                                       "randomMac": True,
                                       "lastSeen": engine.iso(at(60))}})
            self.assertEqual(self.book()[STRANGER],
                             {"label": "", "vendor": "TP-Link", "randomMac": True})
            # Thirty days on, the cache drops it. The name stays where it was written.
            self.state["devices"] = {}
            self.assertEqual(self.book()[STRANGER]["vendor"], "TP-Link")

    def test_a_broken_book_is_dropped_without_touching_the_days(self):
        path = engine.history_path(self.environ, "2026-09")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        span = {"mac": A, "from": "2026-09-25T10:00:00Z", "to": "2026-09-25T11:00:00Z",
                "state": "on"}
        for bad in ("oops", ["a"], {A: "oops"}, None):
            with self.subTest(bad=bad), open(path, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "month": "2026-09", "devices": bad,
                           "days": {"2026-09-25": {"spans": [span]}}}, fh)
            payload = engine.load_month(self.environ, "2026-09")
            self.assertEqual(payload["days"]["2026-09-25"]["spans"], [span])
            self.assertEqual(payload["devices"], {})

    def test_the_fields_inside_an_entry_are_checked_one_by_one(self):
        path = engine.history_path(self.environ, "2026-09")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "month": "2026-09", "days": {},
                       "devices": {A: {"label": 7, "vendor": "Samsung",
                                       "randomMac": "yes", "extra": 1}}}, fh)
        self.assertEqual(engine.load_month(self.environ, "2026-09")["devices"][A],
                         {"label": "", "vendor": "Samsung", "randomMac": False})


class SelectionSettingTest(unittest.TestCase):
    def test_the_defaults_are_empty(self):
        self.assertEqual(engine.DEFAULT_SETTINGS["timelineLanes"], [])
        self.assertEqual(engine.DEFAULT_SETTINGS["timelineCompare"], [])

    def test_it_takes_a_list_of_strings(self):
        base = engine.DEFAULT_SETTINGS
        merged = engine.validate_settings({"timelineLanes": ["person:a", "mac:b"]}, base)
        self.assertEqual(merged["timelineLanes"], ["person:a", "mac:b"])

    def test_repeats_collapse_and_the_order_survives(self):
        base = engine.DEFAULT_SETTINGS
        merged = engine.validate_settings({"timelineLanes": ["b", "a", "b"]}, base)
        self.assertEqual(merged["timelineLanes"], ["b", "a"])

    def test_it_rejects_the_shapes_it_cannot_use(self):
        base = engine.DEFAULT_SETTINGS
        for bad in ("person:a", {"a": 1}, [1], ["a", None], [""], None):
            with self.assertRaises(engine.RecognitionError):
                engine.validate_settings({"timelineLanes": bad}, base)

    def test_each_list_has_its_own_ceiling(self):
        base = engine.DEFAULT_SETTINGS
        engine.validate_settings({"timelineLanes": ["k%d" % n for n in range(500)]}, base)
        with self.assertRaises(engine.RecognitionError):
            engine.validate_settings({"timelineLanes": ["k%d" % n for n in range(501)]}, base)
        engine.validate_settings({"timelineCompare": ["k%d" % n for n in range(20)]}, base)
        with self.assertRaises(engine.RecognitionError):
            engine.validate_settings({"timelineCompare": ["k%d" % n for n in range(21)]}, base)

    def test_junk_on_disk_falls_back_to_empty(self):
        for bad in ("nope", {"a": 1}, [1, 2], 7):
            self.assertEqual(engine.repair_settings({"timelineLanes": bad})["timelineLanes"], [])
        self.assertEqual(engine.repair_settings({"timelineLanes": ["mac:x"]})["timelineLanes"],
                         ["mac:x"])


class PruneGateTest(unittest.TestCase):
    """Saving settings only runs the forced tick and prune when a key the history cares
    about actually moved. Closing the lane picker must not read every month file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = env(self.tmp.name)
        data = engine.empty_people()
        data["settings"].update(history=True, historyDays=30)
        engine.save_person(data, {"name": "Ana", "emoji": "\U0001f43b", "devices": [{"mac": A}]})
        engine.save_people(engine.people_path(self.environ), data)
        # A state file has to exist, or nothing is saved at all (the silent-rebuild rule).
        state = engine.empty_state()
        engine.save_state(engine.state_path(self.environ), state)

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, payload):
        engine.main(["set-settings"], environ=self.environ, now=lambda: at(0),
                    stdin=io.StringIO(json.dumps(payload)), stdout=io.StringIO())

    def pruned_on(self):
        state, _ = engine.load_state(engine.state_path(self.environ))
        return state["history"]["prunedOn"]

    def test_saving_only_the_selection_does_not_prune(self):
        with tz():
            self.save({"timelineLanes": ["mac:" + A]})
            self.assertIsNone(self.pruned_on())

    def test_saving_the_retention_prunes(self):
        with tz():
            self.save({"historyDays": 7})
            self.assertEqual(self.pruned_on(), "2026-09-17")

    def test_saving_the_scope_prunes(self):
        with tz():
            self.save({"historyDevices": "all"})
            self.assertEqual(self.pruned_on(), "2026-09-17")


class TimelineReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = env(self.tmp.name)
        self.data = engine.empty_people()
        self.data["settings"].update(history=True, historyDevices="all", historyDays=30)
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "\U0001f43b",
                                                  "devices": [{"mac": A, "label": "phone"}]})
        self.leo = engine.save_person(self.data, {"name": "Leo", "emoji": "\U0001f98a",
                                                  "devices": []})
        self.data["house"].append({"mac": B, "label": "printer"})
        self.state = engine.empty_state()
        self.now = datetime.datetime(2026, 9, 26, 15, 0, tzinfo=engine.UTC)

    def tearDown(self):
        self.tmp.cleanup()

    def span(self, who, start, end, state="home"):
        kind = "person" if who in (self.ana["id"], self.leo["id"]) else "mac"
        return {kind: who, "from": "2026-09-24T%s:00Z" % start,
                "to": "2026-09-24T%s:00Z" % end, "state": state}

    def put(self, day, slot, book=None):
        payload = engine.load_month(self.environ, day[:7])
        payload["days"][day] = slot
        if book:
            payload["devices"].update(book)
        engine.save_month(self.environ, day[:7], payload)

    def seed(self):
        self.put("2026-09-24", {"spans": [
            self.span(self.ana["id"], "12:00", "17:00"),
            self.span(A, "12:00", "16:00", "on"),
            self.span(B, "14:00", "14:30", "on"),
            self.span(STRANGER, "18:00", "18:20", "on"),
            self.span(self.ana["id"], "20:00", "21:00", "unknown"),
        ]}, book={A: {"label": "phone", "vendor": "Samsung", "randomMac": False},
                  B: {"label": "printer", "vendor": "Brother", "randomMac": False},
                  STRANGER: {"label": "", "vendor": "TP-Link", "randomMac": True}})

    def report(self, period="day", day="2026-09-24"):
        return engine.timeline_report(self.environ, self.data, self.state,
                                      self.data["settings"], self.now, period, day)

    def test_earliest_is_the_oldest_day_the_calendar_can_reach(self):
        with tz():
            self.assertIsNone(self.report()["earliest"])
            self.seed()
            self.assertEqual(self.report()["earliest"], "2026-09-24")

    def test_the_day_brings_people_and_devices_in_drawing_order(self):
        with tz():
            self.seed()
            keys = [lane["key"] for lane in self.report()["lanes"]]
            self.assertEqual(keys, ["person:" + self.ana["id"], "mac:" + A,
                                    "person:" + self.leo["id"], "mac:" + B,
                                    "mac:" + STRANGER])

    def test_a_lane_carries_its_spans_and_the_number_for_the_column(self):
        with tz():
            self.seed()
            lane = self.report()["lanes"][0]
            day = lane["days"][0]
            self.assertEqual(day["day"], "2026-09-24")
            self.assertEqual(day["total"], 5 * 3600)
            self.assertEqual(day["unknown"], 3600)
            self.assertEqual(day["arrivals"], 1)
            self.assertEqual([span["state"] for span in day["spans"]], ["home", "unknown"])
            self.assertEqual(day["spans"][0]["from"], "2026-09-24T12:00:00Z")

    def test_a_device_lane_carries_the_name_out_of_the_book(self):
        with tz():
            self.seed()
            lanes = {lane["key"]: lane for lane in self.report()["lanes"]}
            phone = lanes["mac:" + A]
            self.assertEqual(phone["label"], "phone")
            self.assertEqual(phone["vendor"], "Samsung")
            self.assertIs(phone["randomMac"], False)
            self.assertEqual(phone["owner"], self.ana["id"])
            self.assertEqual(lanes["mac:" + B]["owner"], "house")
            self.assertIsNone(lanes["mac:" + STRANGER]["owner"])
            self.assertIs(lanes["mac:" + STRANGER]["randomMac"], True)

    def test_a_device_taken_away_from_its_person_moves_out_of_their_block(self):
        with tz():
            self.seed()
            self.ana["devices"] = []
            keys = [lane["key"] for lane in self.report()["lanes"]]
            lanes = {lane["key"]: lane for lane in self.report()["lanes"]}
            self.assertIsNone(lanes["mac:" + A]["owner"])
            self.assertEqual(lanes["mac:" + A]["label"], "phone")
            # Out of Ana's block and down with the rest of the unclaimed ones.
            self.assertGreater(keys.index("mac:" + A), keys.index("person:" + self.leo["id"]))

    def test_a_name_in_the_book_with_no_span_gets_no_lane(self):
        with tz():
            self.seed()
            self.put("2026-09-24", engine.load_month(self.environ, "2026-09")["days"]["2026-09-24"],
                     book={C: {"label": "ghost", "vendor": "", "randomMac": False}})
            keys = [lane["key"] for lane in self.report()["lanes"]]
            self.assertNotIn("mac:" + C, keys)

    def test_a_lane_whose_only_span_is_unknown_still_exists(self):
        with tz():
            self.put("2026-09-24", {"spans": [self.span(B, "10:00", "11:00", "unknown")]},
                     book={B: {"label": "printer", "vendor": "", "randomMac": False}})
            lanes = {lane["key"]: lane for lane in self.report()["lanes"]}
            day = lanes["mac:" + B]["days"][0]
            self.assertEqual(day["total"], 0)
            self.assertEqual(day["unknown"], 3600)
            self.assertEqual(len(day["spans"]), 1)

    def test_a_person_with_nothing_still_gets_a_lane(self):
        with tz():
            self.seed()
            lanes = {lane["key"]: lane for lane in self.report()["lanes"]}
            day = lanes["person:" + self.leo["id"]]["days"][0]
            self.assertEqual((day["total"], day["unknown"], day["spans"]), (0, 0, []))

    def test_the_week_is_seven_days_and_people_only(self):
        with tz():
            self.seed()
            report = self.report(period="week")
            self.assertEqual(report["from"], "2026-09-21")
            self.assertEqual(report["to"], "2026-09-27")
            self.assertEqual([row["day"] for row in report["days"]],
                             ["2026-09-2%d" % n for n in range(1, 8)])
            self.assertEqual([lane["kind"] for lane in report["lanes"]],
                             ["person", "person"])
            for lane in report["lanes"]:
                self.assertEqual([day["day"] for day in lane["days"]],
                                 [row["day"] for row in report["days"]])

    def test_a_sealed_day_says_so_and_brings_no_spans(self):
        with tz():
            self.seed()
            self.put("2026-09-23", {"totals": engine.seal_spans([])})
            report = self.report(period="week")
            rows = {row["day"]: row["detail"] for row in report["days"]}
            self.assertIs(rows["2026-09-23"], False)
            self.assertIs(rows["2026-09-24"], True)
            lane = report["lanes"][0]
            sealed = [day for day in lane["days"] if day["day"] == "2026-09-23"][0]
            self.assertEqual(sealed["spans"], [])

    def test_an_empty_period_is_lanes_of_zeros_and_creates_nothing(self):
        with tz():
            report = self.report(period="month", day="2020-01-15")
            self.assertEqual([lane["kind"] for lane in report["lanes"]],
                             ["person", "person"])
            self.assertEqual(sum(day["total"] for lane in report["lanes"]
                                 for day in lane["days"]), 0)
            self.assertIsNone(report["prev"])
            self.assertFalse(os.path.exists(engine.history_dir(self.environ)))

    def test_the_header_carries_the_scope_and_the_retention(self):
        with tz():
            report = self.report()
            self.assertIs(report["enabled"], True)
            self.assertEqual(report["scope"], "all")
            self.assertEqual(report["keepDays"], 30)

    def test_the_command_answers(self):
        with tz():
            self.seed()
            engine.save_people(engine.people_path(self.environ), self.data)
            out = io.StringIO()
            engine.main(["timeline", "day", "2026-09-24"], environ=self.environ,
                        now=lambda: self.now, stdout=out)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["period"], "day")
            self.assertEqual(len(payload["lanes"]), 5)

    def test_the_command_checks_its_arguments(self):
        engine.save_people(engine.people_path(self.environ), self.data)
        for argv in (["timeline"], ["timeline", "day"], ["timeline", "fortnight", "2026-09-24"],
                     ["timeline", "day", "nope"]):
            out = io.StringIO()
            engine.main(argv, environ=self.environ, now=lambda: self.now, stdout=out)
            self.assertIn("error", json.loads(out.getvalue()))
