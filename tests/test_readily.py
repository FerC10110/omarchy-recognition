"""Reading commands from Readily (spec §3)."""
import os
import subprocess
import tempfile
import unittest
import unittest.mock

from _load import load
from fakes import FakeRun, fake_readily, readily_item, readily_listing

engine = load()
WOL = "wol 00:00:5e:00:53:09"


def listing_run(tmpdir, notes):
    path, run = fake_readily(tmpdir, (0, readily_listing(notes), ""))
    return {"RECOGNITION_READILY_BIN": path}, run


class ReadilyTest(unittest.TestCase):
    """Base for everything that looks for the binary. PLUGIN_DIR is pinned to a temp
    folder because the installed plugin really does have Readily as a sibling: without
    this, "no binary anywhere" would pass in a worktree and fail once merged."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = unittest.mock.patch.object(engine, "PLUGIN_DIR",
                                           os.path.join(self.tmp.name, "plugins", "recognition"))
        patch.start()
        self.addCleanup(patch.stop)


class BinaryTest(ReadilyTest):
    def test_the_override_wins(self):
        path, _ = fake_readily(self.tmp.name)
        self.assertEqual(engine.readily_bin({"RECOGNITION_READILY_BIN": path, "PATH": ""}), path)

    def test_an_override_that_is_not_a_file_is_ignored(self):
        missing = self.tmp.name + "/nope"
        self.assertIsNone(engine.readily_bin({"RECOGNITION_READILY_BIN": missing, "PATH": ""}))

    def test_the_sibling_plugin_comes_next(self):
        folder = os.path.join(self.tmp.name, "plugins", "io.github.ferc10110.readily", "bin")
        os.makedirs(folder)
        path = os.path.join(folder, "readily")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n")
        self.assertEqual(engine.readily_bin({"PATH": ""}), path)

    def test_the_path_is_the_last_resort(self):
        path, _ = fake_readily(self.tmp.name)
        self.assertEqual(engine.readily_bin({"PATH": self.tmp.name}), path)

    def test_nothing_anywhere_is_none(self):
        self.assertIsNone(engine.readily_bin({"PATH": self.tmp.name}))


class EventsTest(unittest.TestCase):
    def test_sub_tags_become_events_in_engine_order(self):
        self.assertEqual(engine.readily_events(["recognition/manual", "recognition/arrive"]),
                         ["arrive", "manual"])

    def test_a_bare_tag_is_manual(self):
        self.assertEqual(engine.readily_events(["recognition"]), ["manual"])

    def test_an_unknown_sub_tag_never_makes_it_run_on_its_own(self):
        self.assertEqual(engine.readily_events(["recognition/arive"]), ["manual"])

    def test_other_tags_are_ignored(self):
        self.assertEqual(engine.readily_events(["work", "recognition/leave"]), ["leave"])

    def test_a_repeated_event_appears_once(self):
        self.assertEqual(engine.readily_events(["recognition/leave", "recognition/leave"]), ["leave"])


class CommandTextTest(unittest.TestCase):
    def test_a_command_may_span_lines(self):
        self.assertEqual(engine.readily_command("cd /tmp\nls -la"), "cd /tmp\nls -la")

    def test_surrounding_blank_space_goes(self):
        self.assertEqual(engine.readily_command("\n  true  \n"), "true")

    def test_empty_is_not_a_command(self):
        self.assertEqual(engine.readily_command("   \n "), "")

    def test_over_the_limit_is_not_a_command(self):
        self.assertEqual(engine.readily_command("x" * (engine.COMMAND_MAX + 1)), "")
        self.assertEqual(engine.readily_command("x" * engine.COMMAND_MAX), "x" * engine.COMMAND_MAX)

    def test_a_control_character_is_not_a_command(self):
        self.assertEqual(engine.readily_command("true\x07"), "")

    def test_a_tab_is_fine(self):
        self.assertEqual(engine.readily_command("if true; then\n\techo hi\nfi"),
                         "if true; then\n\techo hi\nfi")

    def test_something_that_is_not_text_is_not_a_command(self):
        self.assertEqual(engine.readily_command(None), "")


class IdTest(unittest.TestCase):
    def test_the_id_is_32_hex_characters(self):
        value = engine.readily_id("commands", "Wake the desktop")
        self.assertEqual(len(value), 32)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in value))

    def test_the_id_survives_editing_the_command(self):
        self.assertEqual(engine.readily_id("commands", "Wake"), engine.readily_id("commands", "Wake"))

    def test_the_id_changes_with_the_note_and_with_the_title(self):
        base = engine.readily_id("commands", "Wake")
        self.assertNotEqual(base, engine.readily_id("home", "Wake"))
        self.assertNotEqual(base, engine.readily_id("commands", "Wake up"))


class ReadTest(ReadilyTest):
    def test_a_listing_becomes_commands(self):
        environ, run = listing_run(self.tmp.name, {
            "commands": [readily_item("Wake the desktop", WOL, tags=["recognition/arrive", "recognition/manual"])]})
        result = engine.read_readily(environ, run)
        self.assertTrue(result["ok"])
        self.assertEqual(result["warning"], "")
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["commands"], [
            {"id": engine.readily_id("commands", "Wake the desktop"), "command": WOL,
             "events": ["arrive", "manual"], "people": None, "source": "readily",
             "note": "commands", "title": "Wake the desktop"}])
        self.assertEqual(run.calls, [[environ["RECOGNITION_READILY_BIN"],
                                      "list", "--tag", "recognition", "--json"]])

    def test_a_tag_inherited_from_the_note_counts(self):
        environ, run = listing_run(self.tmp.name, {
            "home": [readily_item("Lock", "loginctl lock-sessions", inherited=["recognition/home-empty"])]})
        self.assertEqual(engine.read_readily(environ, run)["commands"][0]["events"], ["home-empty"])

    def test_finding_nothing_is_a_genuine_read(self):
        environ, run = listing_run(self.tmp.name, {"commands": []})
        result = engine.read_readily(environ, run)
        self.assertTrue(result["ok"])
        self.assertEqual(result["commands"], [])

    def test_a_missing_binary_is_not_a_genuine_read(self):
        result = engine.read_readily({"PATH": self.tmp.name}, FakeRun())
        self.assertEqual(result, {"commands": [], "ok": False, "warning": "Readily not found", "skipped": 0})

    def test_no_folder_says_so(self):
        path, run = fake_readily(self.tmp.name, (4, "", "readily: No folder chosen yet"))
        result = engine.read_readily({"RECOGNITION_READILY_BIN": path}, run)
        self.assertEqual(result["warning"], "Readily has no folder set")
        self.assertFalse(result["ok"])

    def test_any_other_failure_is_unavailable(self):
        path, run = fake_readily(self.tmp.name, (1, "", "boom"))
        self.assertEqual(engine.read_readily({"RECOGNITION_READILY_BIN": path}, run)["warning"],
                         "Readily isn't available")

    def test_an_answer_that_is_not_json_degrades(self):
        path, run = fake_readily(self.tmp.name, (0, "not json", ""))
        self.assertFalse(engine.read_readily({"RECOGNITION_READILY_BIN": path}, run)["ok"])

    def test_an_answer_that_is_not_an_object_degrades(self):
        path, run = fake_readily(self.tmp.name, (0, "[]", ""))
        self.assertFalse(engine.read_readily({"RECOGNITION_READILY_BIN": path}, run)["ok"])

    def test_a_run_that_raises_degrades(self):
        path, run = fake_readily(self.tmp.name, OSError("no such process"))
        self.assertFalse(engine.read_readily({"RECOGNITION_READILY_BIN": path}, run)["ok"])

    def test_a_timeout_degrades_like_any_other_failure(self):
        path, run = fake_readily(self.tmp.name, subprocess.TimeoutExpired(["readily", "list"],
                                                                          engine.READILY_TIMEOUT))
        result = engine.read_readily({"RECOGNITION_READILY_BIN": path}, run)
        self.assertFalse(result["ok"])
        self.assertEqual(result["warning"], "Readily isn't available")

    def test_reading_the_vault_is_bounded(self):
        # Readily runs inside the panel's own calls, so it gets a deadline and no stdin
        # to wait on: without both, a vault that stops answering freezes the panel.
        environ, run = listing_run(self.tmp.name, {"commands": []})
        engine.read_readily(environ, run)
        self.assertEqual(run.kwargs[0]["timeout"], engine.READILY_TIMEOUT)
        self.assertIs(run.kwargs[0]["stdin"], subprocess.DEVNULL)

    def test_what_cannot_be_a_command_is_skipped_and_counted(self):
        environ, run = listing_run(self.tmp.name, {"commands": [
            readily_item("A picture", "", kind="image", tags=["recognition"]),
            readily_item("", WOL, tags=["recognition"]),
            readily_item("Too long", "x" * 1001, tags=["recognition"]),
            "not even an item",
            readily_item("Good", "true", tags=["recognition"])]})
        result = engine.read_readily(environ, run)
        self.assertEqual([c["title"] for c in result["commands"]], ["Good"])
        self.assertEqual(result["skipped"], 4)
        self.assertTrue(result["ok"])

    def test_a_section_that_is_not_one_is_ignored(self):
        payload = '{"sections": ["nope", {"name": "", "items": []}, {"name": "x", "items": "no"}]}'
        path, run = fake_readily(self.tmp.name, (0, payload, ""))
        result = engine.read_readily({"RECOGNITION_READILY_BIN": path}, run)
        self.assertEqual(result["commands"], [])
        self.assertEqual(result["skipped"], 0)
        self.assertTrue(result["ok"])

    def test_the_cap_stops_at_fifty_and_counts_the_rest(self):
        items = [readily_item("Item %d" % n, "true", tags=["recognition"]) for n in range(55)]
        environ, run = listing_run(self.tmp.name, {"commands": items})
        result = engine.read_readily(environ, run)
        self.assertEqual(len(result["commands"]), engine.READILY_MAX)
        self.assertEqual(result["skipped"], 5)


class GateTest(ReadilyTest):
    def test_the_setting_off_means_no_call_at_all(self):
        environ, run = listing_run(self.tmp.name, {"commands": [readily_item("Good", "true", tags=["recognition"])]})
        data = engine.empty_people()
        self.assertIsNone(engine.readily_for(environ, run, data))
        self.assertEqual(run.calls, [])

    def test_the_setting_on_reads(self):
        environ, run = listing_run(self.tmp.name, {"commands": [readily_item("Good", "true", tags=["recognition"])]})
        data = engine.empty_people()
        data["settings"]["readily"] = True
        self.assertEqual(len(engine.readily_for(environ, run, data)["commands"]), 1)

    def test_find_readily_matches_by_id(self):
        commands = [{"id": "a" * 32, "command": "true"}]
        self.assertEqual(engine.find_readily(commands, "a" * 32)["command"], "true")
        self.assertIsNone(engine.find_readily(commands, "b" * 32))
        self.assertIsNone(engine.find_readily((), "a" * 32))
