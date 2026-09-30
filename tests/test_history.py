import datetime
import io
import json
import os
import tempfile
import unittest

from _load import load
from fakes import at, env, lan, neigh, nmap_out, tz

engine = load()

A, B = "00:00:5e:00:53:31", "00:00:5e:00:53:44"
GRACE = 300


class HistorySettingsTest(unittest.TestCase):
    def test_the_defaults_are_off(self):
        settings = engine.DEFAULT_SETTINGS
        self.assertIs(settings["history"], False)
        self.assertEqual(settings["historyDevices"], "none")
        self.assertEqual(settings["historyDays"], 30)

    def test_the_history_switch_takes_only_booleans(self):
        base = engine.DEFAULT_SETTINGS
        self.assertIs(engine.validate_settings({"history": True}, base)["history"], True)
        with self.assertRaises(engine.RecognitionError):
            engine.validate_settings({"history": "yes"}, base)

    def test_the_scope_takes_only_its_three_words(self):
        base = engine.DEFAULT_SETTINGS
        for scope in ("none", "owned", "all"):
            self.assertEqual(engine.validate_settings({"historyDevices": scope},
                                                      base)["historyDevices"], scope)
        for bad in (True, False, "yes", "", None, 1, ["all"]):
            with self.assertRaises(engine.RecognitionError):
                engine.validate_settings({"historyDevices": bad}, base)

    def test_the_boolean_the_previous_version_wrote_still_means_something(self):
        # feat/history wrote a boolean here. true meant "the devices I assigned".
        self.assertEqual(engine.repair_settings({"historyDevices": True})["historyDevices"],
                         "owned")
        self.assertEqual(engine.repair_settings({"historyDevices": False})["historyDevices"],
                         "none")
        self.assertEqual(engine.repair_settings({"historyDevices": "nonsense"})["historyDevices"],
                         "none")
        self.assertEqual(engine.repair_settings({"historyDevices": "all"})["historyDevices"],
                         "all")

    def test_the_days_stay_inside_their_range(self):
        base = engine.DEFAULT_SETTINGS
        self.assertEqual(engine.validate_settings({"historyDays": 1}, base)["historyDays"], 1)
        self.assertEqual(engine.validate_settings({"historyDays": 365}, base)["historyDays"], 365)
        for bad in (0, 366, "30", None):
            with self.assertRaises(engine.RecognitionError):
                engine.validate_settings({"historyDays": bad}, base)

    def test_a_broken_days_value_on_disk_falls_back(self):
        repaired = engine.repair_settings({"historyDays": 9999, "history": True})
        self.assertEqual(repaired["historyDays"], 30)
        self.assertIs(repaired["history"], True)


class HistoryPathTest(unittest.TestCase):
    def test_the_history_lives_in_the_data_home(self):
        environ = {"HOME": "/home/x", "XDG_DATA_HOME": "/home/x/.local/share"}
        self.assertEqual(engine.history_dir(environ), "/home/x/.local/share/recognition/history")
        self.assertEqual(engine.history_path(environ, "2026-09"),
                         "/home/x/.local/share/recognition/history/2026-09.json")

    def test_without_the_variable_it_falls_back_to_the_home(self):
        self.assertEqual(engine.history_dir({"HOME": "/home/x"}),
                         "/home/x/.local/share/recognition/history")


class HistoryStateTest(unittest.TestCase):
    def test_a_fresh_state_has_an_empty_book(self):
        self.assertEqual(engine.empty_state()["history"],
                         {"open": {}, "cont": [], "gap": None, "prunedOn": None})

    def test_a_state_from_the_previous_version_still_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            old = engine.empty_state()
            del old["history"]
            old["devices"] = {"00:00:5e:00:53:31": {"present": True}}
            engine.atomic_write_json(path, old)
            state, existed = engine.load_state(path)
            self.assertTrue(existed)
            self.assertEqual(state["devices"], old["devices"])
            self.assertEqual(state["history"], {"open": {}, "cont": [], "gap": None, "prunedOn": None})


class DataHomeFakeTest(unittest.TestCase):
    def test_the_test_environ_points_the_data_home_at_the_tmpdir(self):
        self.assertEqual(env("/tmp/x")["XDG_DATA_HOME"], "/tmp/x/data")


class MonthFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = env(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_missing_month_is_empty(self):
        payload = engine.load_month(self.environ, "2026-09")
        self.assertEqual(payload, {"version": 1, "month": "2026-09",
                                   "devices": {}, "days": {}})
        self.assertFalse(os.path.exists(engine.history_dir(self.environ)))

    def test_a_broken_file_is_moved_aside_not_overwritten(self):
        path = engine.history_path(self.environ, "2026-09")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{ this is not json")
        payload = engine.load_month(self.environ, "2026-09")
        self.assertEqual(payload["days"], {})
        moved = engine.history_path(self.environ, "2026-09.broken")
        self.assertTrue(os.path.exists(moved))
        with open(moved, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{ this is not json")

    def test_a_round_trip_keeps_the_days(self):
        payload = engine.empty_month("2026-09")
        payload["days"]["2026-09-26"] = {"spans": []}
        engine.save_month(self.environ, "2026-09", payload)
        self.assertEqual(engine.load_month(self.environ, "2026-09"), payload)


class SplitByDayTest(unittest.TestCase):
    def test_a_span_inside_one_day_is_one_piece(self):
        with tz():
            start = datetime.datetime(2026, 9, 26, 14, 0, tzinfo=engine.UTC)
            end = datetime.datetime(2026, 9, 26, 18, 0, tzinfo=engine.UTC)
            pieces = engine.split_by_day(start, end)
            self.assertEqual([p[0] for p in pieces], ["2026-09-26"])
            self.assertEqual((pieces[0][1], pieces[0][2]), (start, end))

    def test_a_span_across_local_midnight_is_two(self):
        with tz():
            # 20:00Z is 17:00 local on the 26th; 03:30Z of the 27th is 00:30 local,
            # already the 27th. The cut is 03:00Z, which is local midnight.
            start = datetime.datetime(2026, 9, 26, 20, 0, tzinfo=engine.UTC)
            end = datetime.datetime(2026, 9, 27, 3, 30, tzinfo=engine.UTC)
            pieces = engine.split_by_day(start, end)
            self.assertEqual([p[0] for p in pieces], ["2026-09-26", "2026-09-27"])
            self.assertEqual(pieces[0][2], pieces[1][1])
            self.assertEqual(pieces[0][2], datetime.datetime(2026, 9, 27, 3, 0, tzinfo=engine.UTC))


class RecordSpanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = env(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_writes_the_span_into_its_day(self):
        with tz():
            engine.record_span(self.environ, ("person", "p1"),
                               datetime.datetime(2026, 9, 26, 14, 0, tzinfo=engine.UTC),
                               datetime.datetime(2026, 9, 26, 18, 0, tzinfo=engine.UTC), "home")
            days = engine.load_month(self.environ, "2026-09")["days"]
            self.assertEqual(days["2026-09-26"]["spans"], [
                {"person": "p1", "from": "2026-09-26T14:00:00Z",
                 "to": "2026-09-26T18:00:00Z", "state": "home"}])

    def test_the_second_piece_of_a_split_is_marked_as_a_continuation(self):
        with tz():
            engine.record_span(self.environ, ("mac", "00:00:5e:00:53:31"),
                               datetime.datetime(2026, 9, 26, 20, 0, tzinfo=engine.UTC),
                               datetime.datetime(2026, 9, 27, 3, 30, tzinfo=engine.UTC), "on")
            days = engine.load_month(self.environ, "2026-09")["days"]
            self.assertNotIn("cont", days["2026-09-26"]["spans"][0])
            self.assertIs(days["2026-09-27"]["spans"][0]["cont"], True)

    def test_a_span_across_the_end_of_the_month_writes_two_files(self):
        with tz():
            engine.record_span(self.environ, ("person", "p1"),
                               datetime.datetime(2026, 9, 30, 20, 0, tzinfo=engine.UTC),
                               datetime.datetime(2026, 10, 1, 12, 0, tzinfo=engine.UTC), "home")
            self.assertIn("2026-09-30", engine.load_month(self.environ, "2026-09")["days"])
            self.assertIn("2026-10-01", engine.load_month(self.environ, "2026-10")["days"])

    def test_an_end_before_the_start_writes_nothing(self):
        with tz():
            moment = datetime.datetime(2026, 9, 26, 18, 0, tzinfo=engine.UTC)
            engine.record_span(self.environ, ("person", "p1"),
                               moment, moment - datetime.timedelta(hours=2), "home")
            engine.record_span(self.environ, ("person", "p1"), moment, moment, "home")
            self.assertFalse(os.path.exists(engine.history_dir(self.environ)))

    def test_a_sealed_day_does_not_take_new_spans(self):
        with tz():
            payload = engine.empty_month("2026-09")
            payload["days"]["2026-09-26"] = {"totals": {"people": {}, "devices": {}}}
            engine.save_month(self.environ, "2026-09", payload)
            engine.record_span(self.environ, ("person", "p1"),
                               datetime.datetime(2026, 9, 26, 14, 0, tzinfo=engine.UTC),
                               datetime.datetime(2026, 9, 26, 18, 0, tzinfo=engine.UTC), "home")
            slot = engine.load_month(self.environ, "2026-09")["days"]["2026-09-26"]
            self.assertNotIn("spans", slot)


class WriterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = env(self.tmp.name)
        self.state = engine.empty_state()
        self.data = engine.empty_people()
        self.data["settings"]["history"] = True
        self.data["settings"]["historyDevices"] = "owned"
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "\U0001f43b",
                                                  "devices": [{"mac": A}]})

    def tearDown(self):
        self.tmp.cleanup()

    def cycle(self, seconds, seen):
        moment = at(seconds)
        engine.apply_sightings(self.state, seen, moment, GRACE)
        engine.update_people(self.state, self.data, [], [])
        engine.history_tick(self.environ, self.state, self.data, self.data["settings"], moment)
        return moment

    def spans(self, month="2026-09"):
        days = engine.load_month(self.environ, month)["days"]
        return [span for day in sorted(days) for span in days[day].get("spans", [])]

    def test_an_arrival_opens_a_span_without_writing(self):
        with tz():
            self.cycle(0, {A: "192.168.200.9"})
            self.assertEqual(self.state["history"]["open"]["person:" + self.ana["id"]],
                             "2026-09-17T21:00:00Z")
            self.assertFalse(os.path.exists(engine.history_dir(self.environ)))

    def test_a_departure_closes_at_the_last_sighting_not_at_the_notice(self):
        with tz():
            self.cycle(0, {A: "192.168.200.9"})
            self.cycle(60, {A: "192.168.200.9"})
            self.cycle(400, {})          # 340 s without the phone: past the grace
            person = [s for s in self.spans() if s.get("person")]
            self.assertEqual(len(person), 1)
            # Last seen at +60 s, noticed at +400 s. The span ends at the sighting.
            self.assertEqual(person[0]["to"], "2026-09-17T21:01:00Z")
            self.assertEqual(person[0]["from"], "2026-09-17T21:00:00Z")
            self.assertEqual(person[0]["state"], "home")
            self.assertNotIn("person:" + self.ana["id"], self.state["history"]["open"])

    def test_a_device_gets_its_own_span(self):
        with tz():
            self.cycle(0, {A: "192.168.200.9"})
            self.cycle(60, {A: "192.168.200.9"})
            self.cycle(400, {})
            device = [s for s in self.spans() if s.get("mac")]
            self.assertEqual(len(device), 1)
            self.assertEqual(device[0]["mac"], A)
            self.assertEqual(device[0]["state"], "on")

    def test_a_person_with_no_devices_never_opens_a_span(self):
        with tz():
            engine.save_person(self.data, {"name": "Leo", "emoji": "\U0001f98a", "devices": []})
            self.cycle(0, {A: "192.168.200.9"})
            self.cycle(60, {A: "192.168.200.9"})
            self.cycle(400, {})
            self.assertEqual(len([s for s in self.spans() if s.get("person")]), 1)

    def test_a_device_that_does_not_count_keeps_its_own_history(self):
        with tz():
            self.ana["devices"] = [{"mac": A, "label": "PC", "counts": False}]
            self.cycle(0, {A: "192.168.200.9"})
            self.cycle(60, {A: "192.168.200.9"})
            self.cycle(400, {})
            self.assertEqual([s.get("mac") for s in self.spans() if s.get("mac")], [A])
            self.assertEqual([s for s in self.spans() if s.get("person")], [])

    def test_with_the_switch_off_nothing_is_written(self):
        with tz():
            self.data["settings"]["history"] = False
            self.cycle(0, {A: "192.168.200.9"})
            self.cycle(400, {})
            self.assertFalse(os.path.exists(engine.history_dir(self.environ)))
            self.assertEqual(self.state["history"]["open"], {})

    def test_with_the_device_switch_off_only_people_are_written(self):
        with tz():
            self.data["settings"]["historyDevices"] = "none"
            self.cycle(0, {A: "192.168.200.9"})
            self.cycle(60, {A: "192.168.200.9"})
            self.cycle(400, {})
            self.assertEqual([bool(s.get("person")) for s in self.spans()], [True])

    def test_turning_the_switch_off_closes_the_open_spans(self):
        with tz():
            self.cycle(0, {A: "192.168.200.9"})
            self.cycle(60, {A: "192.168.200.9"})
            self.data["settings"]["history"] = False
            self.cycle(120, {A: "192.168.200.9"})
            self.assertEqual(self.state["history"]["open"], {})
            person = [s for s in self.spans() if s.get("person")]
            self.assertEqual(person[0]["to"], "2026-09-17T21:02:00Z")

    def test_turning_it_on_does_not_record_backwards(self):
        with tz():
            self.data["settings"]["history"] = False
            self.cycle(0, {A: "192.168.200.9"})
            self.cycle(60, {A: "192.168.200.9"})
            self.data["settings"]["history"] = True
            self.cycle(120, {A: "192.168.200.9"})
            # Ana has been home since +0, but nobody asked for a history until +120.
            self.assertEqual(self.state["history"]["open"]["person:" + self.ana["id"]],
                             "2026-09-17T21:02:00Z")


class GapTest(WriterTest):
    def gap(self, seconds, seen, gap_from):
        moment = at(seconds)
        engine.apply_sightings(self.state, seen, moment, GRACE)
        engine.update_people(self.state, self.data, [], [])
        engine.history_tick(self.environ, self.state, self.data,
                            self.data["settings"], moment, gap_from=gap_from)
        return moment

    def test_a_pending_gap_decides_nothing(self):
        with tz():
            self.cycle(0, {A: "192.168.200.9"})
            self.gap(40000, {}, "2026-09-17T21:01:00Z")
            self.assertEqual(self.state["history"]["gap"]["lastSeen"], "2026-09-17T21:01:00Z")
            self.assertFalse(os.path.exists(engine.history_dir(self.environ)))
            self.assertIn("person:" + self.ana["id"], self.state["history"]["open"])

    def test_a_second_gap_keeps_the_first_last_seen(self):
        with tz():
            self.cycle(0, {A: "192.168.200.9"})
            self.gap(40000, {}, "2026-09-17T21:01:00Z")
            self.gap(80000, {}, "2026-09-18T08:00:00Z")
            self.assertEqual(self.state["history"]["gap"]["lastSeen"], "2026-09-17T21:01:00Z")

    def test_a_bridged_gap_leaves_one_unbroken_span(self):
        with tz():
            self.cycle(0, {A: "192.168.200.9"})
            self.gap(40000, {A: "192.168.200.9"}, "2026-09-17T21:01:00Z")
            self.cycle(40400, {A: "192.168.200.9"})      # past the grace: trustworthy
            self.assertIsNone(self.state["history"]["gap"])
            self.assertEqual(self.spans(), [])           # still open, nothing written
            self.cycle(41000, {})
            person = [s for s in self.spans() if s.get("person")]
            self.assertEqual(len(person), 2)             # cut at local midnight only
            self.assertEqual(person[0]["from"], "2026-09-17T21:00:00Z")
            self.assertEqual(person[0]["state"], "home")
            self.assertEqual(person[1]["state"], "home")
            self.assertIs(person[1]["cont"], True)
            self.assertEqual(person[1]["to"], "2026-09-18T08:13:20Z")

    def test_a_gap_where_they_left_is_unknown_not_home(self):
        with tz():
            self.cycle(0, {A: "192.168.200.9"})
            self.gap(40000, {}, "2026-09-17T21:01:00Z")
            self.cycle(40400, {})
            person = [s for s in self.spans() if s.get("person")]
            # home up to the last measurement, then the gap as unknown -- cut at local
            # midnight, which is 03:00Z here.
            self.assertEqual([s["state"] for s in person], ["home", "unknown", "unknown"])
            self.assertEqual(person[0]["to"], "2026-09-17T21:01:00Z")
            self.assertEqual(person[1]["from"], "2026-09-17T21:01:00Z")
            self.assertEqual(person[1]["to"], "2026-09-18T03:00:00Z")
            self.assertEqual(person[2]["to"], "2026-09-18T08:13:20Z")
            self.assertIs(person[2]["cont"], True)
            self.assertNotIn("person:" + self.ana["id"], self.state["history"]["open"])

    def test_a_gap_where_they_came_back_is_unknown_then_home(self):
        with tz():
            self.cycle(0, {})
            self.gap(40000, {A: "192.168.200.9"}, "2026-09-17T21:01:00Z")
            moment = self.cycle(40400, {A: "192.168.200.9"})
            unknown = [s for s in self.spans() if s["state"] == "unknown" and s.get("person")]
            self.assertEqual(len(unknown), 2)
            self.assertEqual(unknown[0]["from"], "2026-09-17T21:01:00Z")
            self.assertEqual(unknown[1]["to"], "2026-09-18T08:13:20Z")
            self.assertEqual(self.state["history"]["open"]["person:" + self.ana["id"]],
                             engine.iso(moment))

    def test_a_gap_where_nothing_changed_writes_nothing(self):
        with tz():
            self.cycle(0, {})
            self.gap(40000, {}, "2026-09-17T21:01:00Z")
            self.cycle(40400, {})
            self.assertEqual(self.spans(), [])


class SealTest(unittest.TestCase):
    def test_it_adds_up_by_state_and_counts_arrivals(self):
        totals = engine.seal_spans([
            {"person": "p1", "from": "2026-09-26T00:00:00Z", "to": "2026-09-26T01:00:00Z",
             "state": "home"},
            {"person": "p1", "from": "2026-09-26T05:00:00Z", "to": "2026-09-26T06:00:00Z",
             "state": "home"},
            {"person": "p1", "from": "2026-09-26T09:00:00Z", "to": "2026-09-26T09:30:00Z",
             "state": "unknown"},
            {"mac": A, "from": "2026-09-26T00:00:00Z", "to": "2026-09-26T02:00:00Z",
             "state": "on"}])
        self.assertEqual(totals["people"]["p1"], {"home": 7200, "unknown": 1800, "arrivals": 2})
        self.assertEqual(totals["devices"][A], {"on": 7200, "unknown": 0, "arrivals": 1})

    def test_a_continuation_is_not_a_second_arrival(self):
        totals = engine.seal_spans([
            {"person": "p1", "from": "2026-09-26T20:00:00Z", "to": "2026-09-27T03:00:00Z",
             "state": "home"},
            {"person": "p1", "from": "2026-09-27T03:00:00Z", "to": "2026-09-27T09:00:00Z",
             "state": "home", "cont": True}])
        self.assertEqual(totals["people"]["p1"]["arrivals"], 1)

    def test_a_malformed_span_is_skipped_not_counted_backwards(self):
        totals = engine.seal_spans([
            {"person": "p1", "from": "2026-09-26T06:00:00Z", "to": "2026-09-26T05:00:00Z",
             "state": "home"},
            {"person": "p1", "from": "nope", "to": "2026-09-26T05:00:00Z", "state": "home"},
            {"from": "2026-09-26T05:00:00Z", "to": "2026-09-26T06:00:00Z", "state": "home"}])
        self.assertEqual(totals, {"people": {}, "devices": {}})


class PruneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = env(self.tmp.name)
        self.state = engine.empty_state()
        self.settings = dict(engine.DEFAULT_SETTINGS, historyDays=30)
        self.now = datetime.datetime(2026, 9, 26, 15, 0, tzinfo=engine.UTC)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, month, day, spans):
        payload = engine.load_month(self.environ, month)
        payload["days"][day] = {"spans": spans}
        engine.save_month(self.environ, month, payload)

    def span(self, day, hours=1):
        return {"person": "p1", "from": day + "T05:00:00Z",
                "to": day + "T0%d:00:00Z" % (5 + hours), "state": "home"}

    def test_it_seals_the_old_day_and_leaves_the_recent_one(self):
        with tz():
            self.put("2026-09", "2026-09-25", [self.span("2026-09-25")])
            self.put("2026-08", "2026-08-01", [self.span("2026-08-01")])
            engine.prune_history(self.environ, self.state, self.settings, self.now)
            recent = engine.load_month(self.environ, "2026-09")["days"]["2026-09-25"]
            old = engine.load_month(self.environ, "2026-08")["days"]["2026-08-01"]
            self.assertIn("spans", recent)
            self.assertNotIn("spans", old)
            self.assertEqual(old["totals"]["people"]["p1"],
                             {"home": 3600, "unknown": 0, "arrivals": 1})

    def test_running_it_twice_changes_nothing(self):
        with tz():
            self.put("2026-08", "2026-08-01", [self.span("2026-08-01")])
            engine.prune_history(self.environ, self.state, self.settings, self.now)
            once = engine.load_month(self.environ, "2026-08")
            engine.prune_history(self.environ, self.state, self.settings, self.now, force=True)
            self.assertEqual(engine.load_month(self.environ, "2026-08"), once)

    def test_it_runs_once_a_day_unless_forced(self):
        with tz():
            engine.prune_history(self.environ, self.state, self.settings, self.now)
            self.assertEqual(self.state["history"]["prunedOn"], "2026-09-26")
            self.put("2026-08", "2026-08-01", [self.span("2026-08-01")])
            engine.prune_history(self.environ, self.state, self.settings, self.now)
            self.assertIn("spans",
                          engine.load_month(self.environ, "2026-08")["days"]["2026-08-01"])
            engine.prune_history(self.environ, self.state, self.settings, self.now, force=True)
            self.assertNotIn("spans",
                             engine.load_month(self.environ, "2026-08")["days"]["2026-08-01"])

    def test_one_day_of_retention_seals_everything_but_today(self):
        with tz():
            self.put("2026-09", "2026-09-25", [self.span("2026-09-25")])
            self.put("2026-09", "2026-09-26", [self.span("2026-09-26")])
            settings = dict(self.settings, historyDays=1)
            engine.prune_history(self.environ, self.state, settings, self.now)
            days = engine.load_month(self.environ, "2026-09")["days"]
            self.assertNotIn("spans", days["2026-09-25"])
            self.assertIn("spans", days["2026-09-26"])

    def test_it_runs_with_the_history_switched_off(self):
        with tz():
            self.put("2026-08", "2026-08-01", [self.span("2026-08-01")])
            settings = dict(self.settings, history=False)
            engine.prune_history(self.environ, self.state, settings, self.now)
            self.assertNotIn("spans",
                             engine.load_month(self.environ, "2026-08")["days"]["2026-08-01"])

    def test_it_folds_a_still_open_span_into_the_day_it_seals(self):
        with tz():
            # Ana came home at 20:00 local on the 25th and has not left: those hours are
            # in the open book and nowhere on disk. Sealing the day from the file alone
            # would lose them for good.
            self.state["history"]["open"]["person:p1"] = "2026-09-25T23:00:00Z"
            self.put("2026-09", "2026-09-25", [self.span("2026-09-25")])
            engine.prune_history(self.environ, self.state,
                                 dict(self.settings, historyDays=1), self.now)
            totals = engine.load_month(self.environ, "2026-09")["days"]["2026-09-25"]["totals"]
            self.assertEqual(totals["people"]["p1"]["home"], 3600 + 4 * 3600)
            self.assertEqual(totals["people"]["p1"]["arrivals"], 2)

    def test_the_sealed_hours_are_not_written_a_second_time(self):
        with tz():
            self.state["history"]["open"]["person:p1"] = "2026-09-25T23:00:00Z"
            engine.prune_history(self.environ, self.state,
                                 dict(self.settings, historyDays=1), self.now)
            # The span now starts at the local midnight that opens the oldest kept day,
            # and is marked as a continuation so closing it is not a second arrival.
            self.assertEqual(self.state["history"]["open"]["person:p1"], "2026-09-26T03:00:00Z")
            engine._history_close(self.environ, self.state, ("person", "p1"),
                                  "person:p1", engine.iso(self.now))
            days = engine.load_month(self.environ, "2026-09")["days"]
            self.assertEqual(days["2026-09-25"]["totals"]["people"]["p1"]["home"], 4 * 3600)
            spans = days["2026-09-26"]["spans"]
            self.assertEqual([span["from"] for span in spans], ["2026-09-26T03:00:00Z"])
            self.assertIs(spans[0].get("cont"), True)

    def test_a_span_opened_after_the_seal_is_a_fresh_arrival(self):
        with tz():
            self.state["history"]["open"]["person:p1"] = "2026-09-25T23:00:00Z"
            engine.prune_history(self.environ, self.state,
                                 dict(self.settings, historyDays=1), self.now)
            engine._history_close(self.environ, self.state, ("person", "p1"),
                                  "person:p1", engine.iso(self.now))
            self.state["history"]["open"]["person:p1"] = engine.iso(self.now)
            engine._history_close(self.environ, self.state, ("person", "p1"), "person:p1",
                                  engine.iso(self.now + datetime.timedelta(hours=1)))
            spans = engine.load_month(self.environ, "2026-09")["days"]["2026-09-26"]["spans"]
            self.assertEqual([span.get("cont") for span in spans], [True, None])

    def test_a_broken_file_is_left_alone(self):
        with tz():
            path = engine.history_path(self.environ, "2026-07")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("nope")
            engine.prune_history(self.environ, self.state, self.settings, self.now)
            self.assertTrue(os.path.exists(engine.history_path(self.environ, "2026-07.broken")))


class PeriodTest(unittest.TestCase):
    def test_the_week_runs_monday_to_sunday(self):
        # 2026-09-26 is a Saturday.
        self.assertEqual(engine.history_period("week", "2026-09-26"),
                         ("2026-09-21", "2026-09-27"))
        self.assertEqual(engine.history_period("week", "2026-09-21"),
                         ("2026-09-21", "2026-09-27"))

    def test_the_month_ends_on_its_last_day(self):
        self.assertEqual(engine.history_period("month", "2026-09-26"),
                         ("2026-09-01", "2026-09-30"))
        self.assertEqual(engine.history_period("month", "2026-12-05"),
                         ("2026-12-01", "2026-12-31"))
        self.assertEqual(engine.history_period("month", "2028-02-10"),
                         ("2028-02-01", "2028-02-29"))

    def test_a_day_is_itself(self):
        self.assertEqual(engine.history_period("day", "2026-09-26"),
                         ("2026-09-26", "2026-09-26"))

    def test_the_errors(self):
        for period, day, message in (
                ("year", "2026-09-26", "History: period must be day, week or month"),
                ("day", "26/09/2026", "History: date must be YYYY-MM-DD"),
                ("day", "2026-13-01", "History: date must be YYYY-MM-DD"),
                ("day", None, "History: date must be YYYY-MM-DD")):
            with self.assertRaises(engine.RecognitionError) as caught:
                engine.history_period(period, day)
            self.assertEqual(str(caught.exception), message)


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = env(self.tmp.name)
        self.state = engine.empty_state()
        self.data = engine.empty_people()
        self.data["settings"].update(history=True, historyDevices="owned", historyDays=30)
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "\U0001f43b",
                                                  "devices": [{"mac": A}]})
        self.leo = engine.save_person(self.data, {"name": "Leo", "emoji": "\U0001f98a",
                                                  "devices": []})
        self.now = datetime.datetime(2026, 9, 26, 15, 0, tzinfo=engine.UTC)

    def tearDown(self):
        self.tmp.cleanup()

    def report(self, period="month", day="2026-09-26", person_id=None):
        return engine.history_report(self.environ, self.data, self.state,
                                     self.data["settings"], self.now, period, day, person_id)

    def put(self, day, slot):
        payload = engine.load_month(self.environ, day[:7])
        payload["days"][day] = slot
        engine.save_month(self.environ, day[:7], payload)

    def test_an_empty_period_is_zeros_and_creates_nothing(self):
        with tz():
            report = self.report(period="month", day="2020-01-15")
            self.assertEqual([row["home"] for row in report["people"]], [0, 0])
            self.assertIsNone(report["prev"])
            self.assertEqual(report["next"], "2020-02-01")
            self.assertFalse(os.path.exists(engine.history_dir(self.environ)))

    def test_it_adds_the_sealed_and_the_detailed_days(self):
        with tz():
            self.put("2026-09-02", {"totals": {"people": {self.ana["id"]:
                                    {"home": 3600, "unknown": 0, "arrivals": 1}},
                                    "devices": {}}})
            self.put("2026-09-25", {"spans": [
                {"person": self.ana["id"], "from": "2026-09-25T10:00:00Z",
                 "to": "2026-09-25T12:00:00Z", "state": "home"}]})
            report = self.report()
            row = [r for r in report["people"] if r["id"] == self.ana["id"]][0]
            self.assertEqual(row["home"], 3600 + 7200)
            self.assertEqual(row["arrivals"], 2)

    def test_the_ranking_is_sorted_and_keeps_the_people_with_nothing(self):
        with tz():
            self.put("2026-09-25", {"spans": [
                {"person": self.ana["id"], "from": "2026-09-25T10:00:00Z",
                 "to": "2026-09-25T12:00:00Z", "state": "home"}]})
            report = self.report()
            self.assertEqual([row["id"] for row in report["people"]],
                             [self.ana["id"], self.leo["id"]])

    def test_the_open_span_counts_up_to_now(self):
        with tz():
            self.state["history"]["open"]["person:" + self.ana["id"]] = "2026-09-26T13:00:00Z"
            row = [r for r in self.report()["people"] if r["id"] == self.ana["id"]][0]
            self.assertEqual(row["home"], 7200)

    def test_a_pending_gap_stops_the_open_span_at_the_last_measurement(self):
        with tz():
            self.state["history"]["open"]["person:" + self.ana["id"]] = "2026-09-26T13:00:00Z"
            self.state["history"]["gap"] = {"lastSeen": "2026-09-26T14:00:00Z",
                                            "resolveAfter": "2026-09-26T19:00:00Z"}
            row = [r for r in self.report()["people"] if r["id"] == self.ana["id"]][0]
            self.assertEqual(row["home"], 3600)

    def test_next_is_closed_on_the_current_period_and_open_on_a_past_one(self):
        with tz():
            self.assertIsNone(self.report()["next"])
            self.put("2026-08-01", {"spans": []})
            self.assertEqual(self.report(day="2026-08-15")["next"], "2026-09-01")
            self.assertIsNone(self.report(day="2026-08-15")["prev"])

    def test_earliest_is_the_oldest_day_the_calendar_can_reach(self):
        with tz():
            self.assertIsNone(self.report()["earliest"])
            self.put("2026-08-11", {"spans": [
                {"person": self.ana["id"], "from": "2026-08-11T10:00:00Z",
                 "to": "2026-08-11T12:00:00Z", "state": "home"}]})
            self.put("2026-09-02", {"totals": {"people": {}, "devices": {}}})
            self.assertEqual(self.report()["earliest"], "2026-08-11")
            self.assertEqual(self.report(person_id=self.ana["id"])["earliest"], "2026-08-11")

    def test_the_detail_lists_the_days_and_the_devices(self):
        with tz():
            self.put("2026-09-02", {"totals": {"people": {}, "devices": {}}})
            self.put("2026-09-25", {"spans": [
                {"person": self.ana["id"], "from": "2026-09-25T10:00:00Z",
                 "to": "2026-09-25T12:00:00Z", "state": "home"},
                {"mac": A, "from": "2026-09-25T10:00:00Z",
                 "to": "2026-09-25T11:00:00Z", "state": "on"}]})
            report = self.report(person_id=self.ana["id"])
            self.assertEqual(len(report["days"]), 30)
            sealed = [d for d in report["days"] if d["day"] == "2026-09-02"][0]
            kept = [d for d in report["days"] if d["day"] == "2026-09-25"][0]
            self.assertFalse(sealed["detail"])
            self.assertTrue(kept["detail"])
            self.assertEqual(report["person"]["home"], 7200)
            self.assertEqual(report["devices"],
                             [{"mac": A, "on": 3600, "unknown": 0, "arrivals": 1}])
            self.assertNotIn("spans", report)

    def test_the_day_period_no_longer_brings_spans(self):
        with tz():
            # The timeline answers "when" now; history answers "how much".
            self.assertNotIn("spans", self.report(period="day", day="2026-09-25",
                                                  person_id=self.ana["id"]))

    def test_a_sealed_day_says_it_has_no_detail(self):
        with tz():
            self.put("2026-09-25", {"totals": {"people": {}, "devices": {}}})
            report = self.report(period="day", day="2026-09-25", person_id=self.ana["id"])
            self.assertFalse(report["days"][0]["detail"])

    def test_a_day_older_than_the_cutoff_that_kept_its_spans_says_it_has_detail(self):
        with tz():
            # Between local midnight and that day's prune, a day is below the cutoff and
            # still has its spans. Saying "no detail" there makes the panel deny a list
            # it is showing at the same time.
            self.put("2026-08-01", {"spans": [
                {"person": self.ana["id"], "from": "2026-08-01T10:00:00Z",
                 "to": "2026-08-01T11:00:00Z", "state": "home"}]})
            report = self.report(period="month", day="2026-08-15", person_id=self.ana["id"])
            row = [entry for entry in report["days"] if entry["day"] == "2026-08-01"][0]
            self.assertIs(row["detail"], True)
            sealed = [entry for entry in report["days"] if entry["day"] == "2026-08-02"][0]
            self.assertIs(sealed["detail"], True)

    def test_an_unknown_person_is_an_error(self):
        with tz():
            with self.assertRaises(engine.RecognitionError) as caught:
                self.report(person_id="0" * 32)
            self.assertEqual(str(caught.exception), "That person no longer exists")

    def test_the_devices_list_is_empty_with_the_device_switch_off(self):
        with tz():
            self.data["settings"]["historyDevices"] = "none"
            self.assertEqual(self.report(person_id=self.ana["id"])["devices"], [])


class ForgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = env(self.tmp.name)
        self.state = engine.empty_state()
        payload = engine.empty_month("2026-09")
        payload["days"]["2026-09-25"] = {"spans": [
            {"person": "p1", "from": "2026-09-25T10:00:00Z", "to": "2026-09-25T12:00:00Z",
             "state": "home"},
            {"person": "p2", "from": "2026-09-25T10:00:00Z", "to": "2026-09-25T12:00:00Z",
             "state": "home"},
            {"mac": A, "from": "2026-09-25T10:00:00Z", "to": "2026-09-25T11:00:00Z",
             "state": "on"}]}
        payload["days"]["2026-09-01"] = {"totals": {
            "people": {"p1": {"home": 10, "unknown": 0, "arrivals": 1},
                       "p2": {"home": 20, "unknown": 0, "arrivals": 1}},
            "devices": {A: {"on": 30, "unknown": 0, "arrivals": 1}}}}
        engine.save_month(self.environ, "2026-09", payload)
        self.state["history"]["open"] = {"person:p1": "2026-09-26T10:00:00Z",
                                         "person:p2": "2026-09-26T10:00:00Z"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_drops_the_person_and_their_devices_everywhere(self):
        engine.forget_history(self.environ, self.state, [("person", "p1"), ("mac", A)])
        days = engine.load_month(self.environ, "2026-09")["days"]
        self.assertEqual([s.get("person") for s in days["2026-09-25"]["spans"]], ["p2"])
        self.assertEqual(list(days["2026-09-01"]["totals"]["people"]), ["p2"])
        self.assertEqual(days["2026-09-01"]["totals"]["devices"], {})
        self.assertEqual(list(self.state["history"]["open"]), ["person:p2"])

    def test_it_leaves_everyone_it_was_not_asked_about(self):
        # Unassigning a device is routine, and routine must not destroy anything:
        # nothing calls forget_history for it, and this pins that nothing does.
        engine.forget_history(self.environ, self.state, [("person", "p1")])
        days = engine.load_month(self.environ, "2026-09")["days"]
        self.assertEqual([s.get("mac") for s in days["2026-09-25"]["spans"] if s.get("mac")],
                         [A])
        self.assertIn(A, days["2026-09-01"]["totals"]["devices"])

    def test_deleting_everything_removes_the_directory_and_the_book(self):
        engine.delete_history(self.environ, self.state)
        self.assertFalse(os.path.exists(engine.history_dir(self.environ)))
        self.assertEqual(self.state["history"], {"open": {}, "cont": [], "gap": None, "prunedOn": None})

    def test_deleting_everything_twice_is_fine(self):
        engine.delete_history(self.environ, self.state)
        engine.delete_history(self.environ, self.state)
        self.assertFalse(os.path.exists(engine.history_dir(self.environ)))


class DeletePersonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = env(self.tmp.name)
        self.data = engine.empty_people()
        self.data["settings"].update(history=True, historyDevices="owned")
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "\U0001f43b",
                                                  "devices": [{"mac": A}]})
        engine.save_people(engine.people_path(self.environ), self.data)
        payload = engine.empty_month("2026-09")
        payload["days"]["2026-09-25"] = {"spans": [
            {"person": self.ana["id"], "from": "2026-09-25T10:00:00Z",
             "to": "2026-09-25T12:00:00Z", "state": "home"},
            {"mac": A, "from": "2026-09-25T10:00:00Z", "to": "2026-09-25T11:00:00Z",
             "state": "on"}]}
        engine.save_month(self.environ, "2026-09", payload)

    def tearDown(self):
        self.tmp.cleanup()

    def test_deleting_a_person_takes_their_history_with_them(self):
        engine.main(["delete-person", self.ana["id"]], environ=self.environ,
                    now=lambda: at(0), stdout=io.StringIO())
        days = engine.load_month(self.environ, "2026-09")["days"]
        self.assertEqual(days["2026-09-25"]["spans"], [])

    def test_delete_history_removes_the_files(self):
        engine.main(["delete-history"], environ=self.environ, now=lambda: at(0),
                    stdout=io.StringIO())
        self.assertFalse(os.path.exists(engine.history_dir(self.environ)))


class BrokenMonthTest(unittest.TestCase):
    """A month file is the only copy of what happened, so it is never thrown away -- and
    the README invites reading and editing it. A hand-edit that still parses must not be
    able to stop the scanner or the dashboard."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = env(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, days):
        path = engine.history_path(self.environ, "2026-09")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "month": "2026-09", "days": days}, fh)
        return path

    def test_a_slot_whose_spans_are_not_a_list_is_dropped_not_crashed_on(self):
        path = self.write({"2026-09-25": {"spans": "oops"}})
        self.assertEqual(engine.load_month(self.environ, "2026-09")["days"]["2026-09-25"], {})
        # It parses, so it is not the broken-file case: the bytes stay where they are.
        self.assertTrue(os.path.exists(path))

    def test_the_junk_inside_a_span_list_is_filtered(self):
        good = {"person": "p1", "from": "2026-09-25T10:00:00Z",
                "to": "2026-09-25T11:00:00Z", "state": "home"}
        self.write({"2026-09-25": {"spans": [42, "x", good]}})
        self.assertEqual(engine.load_month(self.environ, "2026-09")["days"]["2026-09-25"],
                         {"spans": [good]})

    def test_broken_totals_come_out_in_the_shape_the_report_expects(self):
        self.write({"2026-09-24": {"totals": "oops"},
                    "2026-09-23": {"totals": {"people": "oops"}},
                    "2026-09-22": {"totals": {"people": {"p1": "oops"}, "devices": {}}},
                    "2026-09-21": {"totals": {"people": {"p1": {"home": "oops"}},
                                              "devices": {}}}})
        days = engine.load_month(self.environ, "2026-09")["days"]
        self.assertEqual(days["2026-09-24"], {})
        self.assertEqual(days["2026-09-23"]["totals"], {"people": {}, "devices": {}})
        self.assertEqual(days["2026-09-22"]["totals"], {"people": {}, "devices": {}})
        self.assertEqual(days["2026-09-21"]["totals"]["people"]["p1"], {"home": "oops"})

    def test_a_hand_edited_file_still_records_and_still_reports(self):
        data = engine.empty_people()
        data["settings"].update(history=True, historyDays=30)
        ana = engine.save_person(data, {"name": "Ana", "emoji": "\U0001f43b",
                                        "devices": [{"mac": A}]})
        self.write({"2026-09-25": {"spans": "oops"},
                    "2026-09-24": {"totals": {"people": {ana["id"]: {"home": "oops"}},
                                              "devices": {}}}})
        state = engine.empty_state()
        with tz():
            start = datetime.datetime(2026, 9, 25, 13, 0, tzinfo=engine.UTC)
            engine.record_span(self.environ, ("person", ana["id"]), start,
                               start + datetime.timedelta(hours=2), "home")
            report = engine.history_report(self.environ, data, state, data["settings"],
                                           datetime.datetime(2026, 9, 26, 15, 0, tzinfo=engine.UTC),
                                           "month", "2026-09-26")
        self.assertEqual([row["home"] for row in report["people"]], [7200])


class BrokenBookTest(unittest.TestCase):
    """The same, for the history half of state.json. A book the engine cannot walk used
    to crash every scan, and save_state was never reached, so it could not repair
    itself either."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = env(self.tmp.name)
        self.data = engine.empty_people()
        self.data["settings"].update(history=True, historyDevices="owned")
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "\U0001f43b",
                                                  "devices": [{"mac": A}]})

    def tearDown(self):
        self.tmp.cleanup()

    def write_book(self, book):
        path = engine.state_path(self.environ)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        raw = dict(engine.empty_state(), history=book)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(raw, fh)
        return path

    def test_every_broken_shape_loads_and_then_ticks(self):
        empty = engine.empty_state()["history"]
        for book in ({"open": "nope"}, {"open": ["x"]}, {"gap": "nope"},
                     {"open": {"weird:xx": "2026-09-25T10:00:00Z"}},
                     {"open": {"person:p1": 7}}, {"prunedOn": 9}, {"cont": "nope"}):
            with self.subTest(book=book):
                self.write_book(book)
                state, existed = engine.load_state(engine.state_path(self.environ))
                self.assertTrue(existed)
                self.assertEqual(state["history"], empty)
                with tz():
                    engine.history_tick(self.environ, state, self.data,
                                        self.data["settings"], at(0))

    def test_a_good_book_survives_the_filter(self):
        self.write_book({"open": {"person:p1": "2026-09-25T10:00:00Z"},
                         "gap": {"lastSeen": "2026-09-25T09:00:00Z"},
                         "prunedOn": "2026-09-25", "cont": ["person:p1"]})
        state, _ = engine.load_state(engine.state_path(self.environ))
        self.assertEqual(state["history"]["open"], {"person:p1": "2026-09-25T10:00:00Z"})
        self.assertEqual(state["history"]["gap"], {"lastSeen": "2026-09-25T09:00:00Z"})
        self.assertEqual(state["history"]["prunedOn"], "2026-09-25")
        self.assertEqual(state["history"]["cont"], ["person:p1"])


class FreshInstallTest(unittest.TestCase):
    """state.json is a cache the first scan rebuilds silently -- that silence is what
    keeps a rebuild from announcing everyone as arriving. No people command may create
    it behind the scan's back."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = env(self.tmp.name)
        data = engine.empty_people()
        engine.save_person(data, {"name": "Ana", "emoji": "\U0001f43b",
                                  "devices": [{"mac": A}]})
        engine.save_people(engine.people_path(self.environ), data)

    def tearDown(self):
        self.tmp.cleanup()

    def run_command(self, argv, payload=None):
        engine.main(argv, environ=self.environ, now=lambda: at(0),
                    stdin=io.StringIO(json.dumps(payload)) if payload is not None else None,
                    stdout=io.StringIO())

    def test_saving_settings_leaves_no_state_file_behind(self):
        self.run_command(["set-settings"], {"history": True})
        self.assertFalse(os.path.exists(engine.state_path(self.environ)))

    def test_deleting_the_history_leaves_no_state_file_behind(self):
        self.run_command(["delete-history"])
        self.assertFalse(os.path.exists(engine.state_path(self.environ)))

    def test_deleting_a_person_leaves_no_state_file_behind(self):
        data = engine.load_people(engine.people_path(self.environ))
        self.run_command(["delete-person", data["people"][0]["id"]])
        self.assertFalse(os.path.exists(engine.state_path(self.environ)))


GATEWAY_IP, GATEWAY_MAC = "192.168.200.1", "02:00:00:00:00:01"


class ScanIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.environ = env(self.tmp.name)
        self.data = engine.empty_people()
        # A scan more than scanInterval + SCAN_ALLOWANCE (90 s) after the previous one is
        # read as a measuring gap -- that is what keeps the PC's nap from looking like
        # everyone leaving. With the default 20 s interval that ceiling is 110 s, far
        # under the >gracePeriod wait a departure needs, so these scans would all look
        # like gaps. A long interval and a short grace give a window wide enough to
        # watch a real arrival and departure without tripping it.
        self.data["settings"].update(history=True, historyDevices="owned",
                                     scanInterval=300, gracePeriod=60,
                                     subnet="192.168.200.0/24")
        self.ana = engine.save_person(self.data, {"name": "Ana", "emoji": "\U0001f43b",
                                                  "devices": [{"mac": A}]})
        engine.save_people(engine.people_path(self.environ), self.data)

    def tearDown(self):
        self.tmp.cleanup()

    def scan(self, seconds, ips):
        run = lan(nmap=nmap_out([GATEWAY_IP] + list(ips)),
                  neighbours=neigh([(GATEWAY_IP, GATEWAY_MAC, "REACHABLE")]
                                   + [(ip, A, "REACHABLE") for ip in ips]))
        return engine.scan(self.environ, run, at(seconds), force=True,
                           oui_loader=lambda: {}, spawn=lambda *a: None)

    def state(self):
        state, _ = engine.load_state(engine.state_path(self.environ))
        return state

    def test_a_stay_is_written_when_it_ends(self):
        with tz():
            self.scan(0, ["192.168.200.9"])
            self.scan(60, ["192.168.200.9"])
            self.scan(400, [])
            spans = engine.load_month(self.environ, "2026-09")["days"]["2026-09-17"]["spans"]
            self.assertEqual(sorted(s["state"] for s in spans), ["home", "on"])
            self.assertTrue(all(s["to"] == "2026-09-17T21:01:00Z" for s in spans))

    def test_a_long_pause_becomes_a_gap_and_is_bridged(self):
        with tz():
            self.scan(0, ["192.168.200.9"])
            self.scan(60, ["192.168.200.9"])
            self.assertIsNone(self.state()["history"]["gap"])
            self.scan(40000, ["192.168.200.9"])          # the PC was off all night
            self.assertEqual(self.state()["history"]["gap"]["lastSeen"],
                             "2026-09-17T21:01:00Z")
            self.scan(40100, ["192.168.200.9"])          # past the grace: trustworthy
            self.assertIsNone(self.state()["history"]["gap"])
            self.assertFalse(os.path.exists(engine.history_dir(self.environ)))

    def test_a_history_that_cannot_be_written_does_not_take_the_scan_down(self):
        with tz():
            self.scan(0, ["192.168.200.9"])
            data_home = os.path.join(self.environ["XDG_DATA_HOME"], "recognition")
            os.makedirs(data_home, exist_ok=True)
            os.chmod(data_home, 0o500)
            try:
                status = self.scan(380, [])
            finally:
                os.chmod(data_home, 0o700)
            # The presence answer still comes back and the state was still saved: a
            # history that cannot be written loses the history, not the scanner.
            self.assertEqual([person["present"] for person in status["people"]], [False])
            self.assertEqual(self.state()["lastScan"], engine.iso(at(380)))

    def test_the_prune_runs_from_the_scan(self):
        with tz():
            self.scan(0, ["192.168.200.9"])
            self.assertEqual(self.state()["history"]["prunedOn"], "2026-09-17")
