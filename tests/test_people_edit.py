import unittest

from _load import load

engine = load()
A = "00:00:5e:00:53:09"
B = "c2:00:00:00:01:12"


def data_with(*people, house=()):
    data = engine.empty_people()
    for person in people:
        engine.save_person(data, person)
    for mac in house:
        engine.house(data, mac, "")
    return data


class SavePersonTest(unittest.TestCase):
    def test_creates_with_new_id(self):
        data = engine.empty_people()
        person = engine.save_person(data, {"name": "Ana", "emoji": "🐻", "devices": [{"mac": A, "label": "Pixel"}]})
        self.assertRegex(person["id"], r"^[0-9a-f]{32}$")
        self.assertEqual(data["people"], [person])

    def test_replaces_existing_and_keeps_unknown_keys(self):
        data = data_with({"name": "Ana", "emoji": "🐻"})
        person = data["people"][0]
        person["zone"] = "trabajo"
        engine.save_person(data, {"id": person["id"], "name": "Ana B", "emoji": "🦊", "devices": []})
        self.assertEqual(len(data["people"]), 1)
        self.assertEqual(data["people"][0]["name"], "Ana B")
        self.assertEqual(data["people"][0]["zone"], "trabajo")

    def test_unknown_id_is_an_error(self):
        with self.assertRaises(engine.RecognitionError) as ctx:
            engine.save_person(engine.empty_people(), {"id": "f" * 32, "name": "X", "emoji": "x"})
        self.assertEqual(str(ctx.exception), "That person no longer exists")

    def test_moves_a_mac_owned_elsewhere(self):
        data = data_with({"name": "Ana", "emoji": "🐻", "devices": [{"mac": A}]}, house=[B])
        engine.save_person(data, {"name": "Juan", "emoji": "🦊", "devices": [{"mac": A}, {"mac": B}]})
        self.assertEqual(data["people"][0]["devices"], [])
        self.assertEqual(data["house"], [])
        self.assertEqual([d["mac"] for d in data["people"][1]["devices"]], [A, B])

    def test_saving_a_person_keeps_a_device_that_does_not_count(self):
        data = engine.empty_people()
        person = engine.save_person(data, {"name": "Ana", "emoji": "🐻",
                                           "devices": [{"mac": A, "label": "Printer", "counts": False}]})
        self.assertIs(person["devices"][0]["counts"], False)


class OwnershipTest(unittest.TestCase):
    def test_owner_of(self):
        data = data_with({"name": "Ana", "emoji": "🐻", "devices": [{"mac": A}]}, house=[B])
        self.assertEqual(engine.owner_of(data, A)["name"], "Ana")
        self.assertEqual(engine.owner_of(data, B), "house")
        self.assertIsNone(engine.owner_of(data, "00:11:22:33:44:55"))

    def test_delete_person_frees_its_macs(self):
        data = data_with({"name": "Ana", "emoji": "🐻", "devices": [{"mac": A}]})
        engine.delete_person(data, data["people"][0]["id"])
        self.assertEqual(data["people"], [])
        self.assertIsNone(engine.owner_of(data, A))
        with self.assertRaises(engine.RecognitionError):
            engine.delete_person(data, "f" * 32)

    def test_assign_moves_from_house_and_other_person(self):
        data = data_with({"name": "Ana", "emoji": "🐻", "devices": [{"mac": A}]},
                         {"name": "Juan", "emoji": "🦊"}, house=[B])
        juan = data["people"][1]["id"]
        engine.assign(data, A.upper(), juan, "Pixel")
        engine.assign(data, B, juan, "")
        self.assertEqual(data["people"][0]["devices"], [])
        self.assertEqual(data["people"][1]["devices"], [{"mac": A, "label": "Pixel", "counts": True},
                                                        {"mac": B, "label": "", "counts": True}])
        self.assertEqual(data["house"], [])

    def test_an_assigned_device_counts_by_default(self):
        data = data_with({"name": "Ana", "emoji": "🐻"})
        engine.assign(data, A, data["people"][0]["id"], "Pixel")
        self.assertEqual(data["people"][0]["devices"], [{"mac": A, "label": "Pixel", "counts": True}])

    def test_assign_to_missing_person_changes_nothing(self):
        data = data_with(house=[B])
        with self.assertRaises(engine.RecognitionError):
            engine.assign(data, B, "f" * 32, "")
        self.assertEqual(data["house"], [{"mac": B, "label": ""}])

    def test_unassign(self):
        data = data_with({"name": "Ana", "emoji": "🐻", "devices": [{"mac": A}]})
        engine.unassign(data, A)
        self.assertEqual(data["people"][0]["devices"], [])
        with self.assertRaises(engine.RecognitionError) as ctx:
            engine.unassign(data, A)
        self.assertEqual(str(ctx.exception), "That device isn't assigned to anyone")

    def test_house_and_unhouse(self):
        data = data_with({"name": "Ana", "emoji": "🐻", "devices": [{"mac": A}]})
        engine.house(data, A, "Router")
        self.assertEqual(data["people"][0]["devices"], [])
        self.assertEqual(data["house"], [{"mac": A, "label": "Router"}])
        engine.unhouse(data, A)
        self.assertEqual(data["house"], [])
        with self.assertRaises(engine.RecognitionError) as ctx:
            engine.unhouse(data, A)
        self.assertEqual(str(ctx.exception), "That device isn't in House")

    def test_house_again_renames(self):
        data = data_with(house=[B])
        engine.house(data, B.upper(), "Living TV")
        self.assertEqual(data["house"], [{"mac": B, "label": "Living TV"}])


class AutoLabelTest(unittest.TestCase):
    def test_prefers_hostname_then_vendor(self):
        self.assertEqual(engine.auto_label({"hostname": "Android_4f1c", "vendor": "Pearcorp"}), "Android_4f1c")
        self.assertEqual(engine.auto_label({"hostname": "", "vendor": "Pearcorp"}), "Pearcorp")
        self.assertEqual(engine.auto_label({"hostname": "", "vendor": "", "randomMac": True}), "Random MAC")
        self.assertEqual(engine.auto_label(None), "Device")
        self.assertEqual(len(engine.auto_label({"hostname": "x" * 90})), 64)


class CommandsTest(unittest.TestCase):
    def setUp(self):
        self.data = data_with({"name": "Ana", "emoji": "🐻"}, {"name": "Juan", "emoji": "🦊"})
        self.ana, self.juan = (person["id"] for person in self.data["people"])

    def save(self, **fields):
        return engine.save_command(self.data, dict({"command": "true", "events": ["arrive"]}, **fields))

    def error(self, function, *args):
        with self.assertRaises(engine.RecognitionError) as ctx:
            function(self.data, *args)
        return str(ctx.exception)

    def test_creates_at_the_end_with_a_new_id(self):
        first = self.save(command=" true ", events=["leave", "arrive"], people=None)
        second = self.save(command="false", events=["alert"], people=[self.juan, self.juan])
        self.assertRegex(first["id"], r"^[0-9a-f]{32}$")
        self.assertEqual(self.data["commands"], [first, second])
        self.assertEqual(first, {"id": first["id"], "command": "true", "events": ["arrive", "leave"], "people": None})
        self.assertEqual(second["people"], [self.juan])

    def test_replaces_by_id_and_keeps_unknown_keys(self):
        command = self.save()
        command["note"] = "kept"
        self.save(id=command["id"], command="echo hi", events=["unknown"], people=[self.ana])
        self.assertEqual(self.data["commands"], [{"id": command["id"], "command": "echo hi", "events": ["unknown"],
                                                  "people": [self.ana], "note": "kept"}])

    def test_unknown_ids_and_bad_fields_are_errors(self):
        self.assertEqual(self.error(engine.save_command, {"id": "f" * 32, "command": "true", "events": ["arrive"]}),
                         "That command no longer exists")
        self.assertEqual(self.error(engine.save_command, {"command": "true", "events": ["arrive"],
                                                          "people": ["f" * 32]}),
                         "That person no longer exists")
        self.assertEqual(self.error(engine.save_command, {"command": "true", "events": []}),
                         "Events: pick at least one")
        self.assertEqual(self.data["commands"], [])

    def test_at_most_fifty_but_editing_still_works(self):
        for _ in range(engine.COMMANDS_MAX):
            last = self.save()
        self.assertEqual(self.error(engine.save_command, {"command": "true", "events": ["arrive"]}),
                         "You can have at most 50 of your own commands")
        self.save(id=last["id"], command="false", events=["leave"])
        self.assertEqual(len(self.data["commands"]), 50)
        self.assertEqual(self.data["commands"][-1]["command"], "false")

    def test_delete_command(self):
        command = self.save()
        engine.delete_command(self.data, command["id"])
        self.assertEqual(self.data["commands"], [])
        self.assertEqual(self.error(engine.delete_command, command["id"]), "That command no longer exists")

    def test_deleting_a_person_takes_them_out_of_every_command(self):
        only_ana = self.save(people=[self.ana])
        both = self.save(people=[self.ana, self.juan])
        everyone = self.save(people=None)
        engine.delete_person(self.data, self.ana)
        self.assertEqual((only_ana["people"], both["people"], everyone["people"]), ([], [self.juan], None))


if __name__ == "__main__":
    unittest.main()
