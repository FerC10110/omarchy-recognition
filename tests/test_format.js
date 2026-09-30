// Run with: TZ=UTC node --test tests/test_format.js
const test = require("node:test")
const assert = require("node:assert/strict")
const F = require("../Format.js")

const NOW = Date.parse("2026-09-17T21:00:00Z")
const ana = { name: "Ana", emoji: "🐻", present: true, since: "2026-09-17T18:32:00Z", lastSeen: "2026-09-17T20:59:40Z",
              devices: [{ present: true }, { present: false }, { present: false }] }
const juan = { name: "Juan", emoji: "🦊", present: false, since: null, lastSeen: "2026-09-16T23:10:00Z",
               devices: [{ present: false }] }

test("ago", () => {
  assert.equal(F.ago("2026-09-17T20:59:48Z", NOW), "12 s ago")
  assert.equal(F.ago("2026-09-17T20:57:00Z", NOW), "3 min ago")
  assert.equal(F.ago("2026-09-17T19:00:00Z", NOW), "2 h ago")
  assert.equal(F.ago("2026-09-13T21:00:00Z", NOW), "4 d ago")
  assert.equal(F.ago(null, NOW), "never")
})

test("when", () => {
  assert.equal(F.when("2026-09-17T18:32:00Z", NOW), "18:32")
  assert.equal(F.when("2026-09-16T23:10:00Z", NOW), "yesterday 23:10")
  assert.equal(F.when("2026-09-12T08:05:00Z", NOW), "Sep 12 08:05")
  assert.equal(F.when("", NOW), "never")
})

test("device title and detail", () => {
  const named = { mac: "00:00:5e:00:53:09", ip: "192.168.200.9", hostname: "Android_4f1c", vendor: "Pearcorp",
                  randomMac: false, present: true }
  assert.equal(F.deviceTitle(named), "Android_4f1c")
  assert.equal(F.deviceDetail(named, NOW), "Pearcorp · 192.168.200.9 · 00:00:5e:00:53:09")
  const random = { mac: "c2:00:00:00:01:12", ip: "192.168.200.112", hostname: "", vendor: "", randomMac: true,
                   present: false, lastSeen: "2026-09-17T20:40:00Z" }
  assert.equal(F.deviceTitle(random), "Random MAC")
  assert.equal(F.deviceDetail(random, NOW),
               "probably a phone · 192.168.200.112 · c2:00:00:00:01:12 · seen 20:40")
  assert.equal(F.deviceTitle({ mac: "x", hostname: "", vendor: "", randomMac: false }), "Device")
})

test("person detail", () => {
  assert.equal(F.personDetail(ana, NOW), "since 18:32 · 1 of 3 devices")
  assert.equal(F.personDetail(juan, NOW), "seen yesterday 23:10")
  assert.equal(F.personDetail({ present: false, lastSeen: null, devices: [] }, NOW), "no devices")
  assert.equal(F.personDetail({ present: false, lastSeen: null, devices: [{}] }, NOW), "never seen")
})

test("person tooltip", () => {
  const here = { label: "Pixel", mac: "00:00:5e:00:53:01", ip: "192.168.200.14",
                 present: true, lastSeen: "2026-09-17T20:59:40Z" }
  const away = { label: "Laptop", mac: "00:00:5e:00:53:02", ip: "192.168.200.22",
                 present: false, lastSeen: "2026-09-17T18:00:00Z" }
  const never = { label: "Tablet", mac: "00:00:5e:00:53:03", ip: "", present: false, lastSeen: null }
  const plain = { label: "", mac: "00:00:5e:00:53:04", ip: "192.168.200.31",
                  present: false, lastSeen: "2026-09-17T18:00:00Z" }
  assert.equal(F.personTooltip({ devices: [here] }, NOW), "Pixel · 00:00:5e:00:53:01 · 192.168.200.14")
  assert.equal(F.personTooltip({ devices: [away] }, NOW),
               "Laptop · 00:00:5e:00:53:02 · 192.168.200.22 · seen 3 h ago")
  assert.equal(F.personTooltip({ devices: [never] }, NOW), "Tablet · 00:00:5e:00:53:03 · never seen")
  assert.equal(F.personTooltip({ devices: [plain] }, NOW),
               "00:00:5e:00:53:04 · 192.168.200.31 · seen 3 h ago")
  assert.equal(F.personTooltip({ devices: [here, away, never] }, NOW),
               "Pixel · 00:00:5e:00:53:01 · 192.168.200.14\n"
               + "Laptop · 00:00:5e:00:53:02 · 192.168.200.22 · seen 3 h ago\n"
               + "Tablet · 00:00:5e:00:53:03 · never seen")
  assert.equal(F.personTooltip({ devices: [] }, NOW), "No devices yet")
  assert.equal(F.personTooltip({}, NOW), "No devices yet")
})

test("device editor line", () => {
  const here = { mac: "00:00:5e:00:53:01", ip: "192.168.200.14", present: true,
                 lastSeen: "2026-09-17T20:59:40Z" }
  const away = { mac: "00:00:5e:00:53:02", ip: "192.168.200.22", present: false,
                 lastSeen: "2026-09-17T18:00:00Z" }
  const fresh = { mac: "00:00:5e:00:53:03" }
  const never = { mac: "00:00:5e:00:53:04", ip: "", present: false, lastSeen: null }
  assert.equal(F.deviceEditorLine(here, true, NOW), "00:00:5e:00:53:01 · 192.168.200.14")
  assert.equal(F.deviceEditorLine(away, true, NOW), "00:00:5e:00:53:02 · 192.168.200.22 · seen 3 h ago")
  assert.equal(F.deviceEditorLine(fresh, true, NOW), "00:00:5e:00:53:03")
  assert.equal(F.deviceEditorLine(never, true, NOW), "00:00:5e:00:53:04 · never seen")
  assert.equal(F.deviceEditorLine(here, false, NOW), "00:00:5e:00:53:01 · 192.168.200.14 · doesn't count")
})

test("device menu line", () => {
  const here = { mac: "00:00:5e:00:53:01", label: "Pixel", ip: "192.168.200.14", present: true,
                 lastSeen: "2026-09-17T20:59:40Z" }
  const noIp = { mac: "00:00:5e:00:53:02", label: "Pixel", ip: "", present: true, lastSeen: "2026-09-17T20:59:40Z" }
  const away = { mac: "00:00:5e:00:53:03", label: "Desktop", ip: "192.168.200.22", present: false,
                 lastSeen: "2026-09-17T18:00:00Z" }
  const never = { mac: "00:00:5e:00:53:04", label: "Printer", ip: "", present: false, lastSeen: null }
  const bare = { mac: "00:00:5e:00:53:05", label: "", ip: "192.168.200.31", present: true, lastSeen: null }
  assert.equal(F.deviceMenuLine(here, NOW), "Pixel · 192.168.200.14")
  assert.equal(F.deviceMenuLine(noIp, NOW), "Pixel")
  // The IP it had while it was up says nothing about where it is now: what you want to
  // read on a device that is gone is when it was last seen.
  assert.equal(F.deviceMenuLine(away, NOW), "Desktop · seen 3 h ago")
  assert.equal(F.deviceMenuLine(never, NOW), "Printer")
  assert.equal(F.deviceMenuLine(bare, NOW), "00:00:5e:00:53:05 · 192.168.200.31")
})

test("a device that does not count says so in the tooltip", () => {
  const printer = { label: "Printer", mac: "00:00:5e:00:53:05", ip: "192.168.200.44",
                    present: true, lastSeen: "2026-09-17T20:59:40Z", counts: false }
  assert.equal(F.personTooltip({ devices: [printer] }, NOW),
               "Printer · 00:00:5e:00:53:05 · 192.168.200.44 · doesn't count")
})

test("person detail counts only the devices that count", () => {
  const withPrinter = { present: true, since: "2026-09-17T18:32:00Z",
                        devices: [{ present: true }, { present: true, counts: false },
                                  { present: false, counts: false }] }
  // One counting device: the counter stays hidden, as it already does for a single device.
  assert.equal(F.personDetail(withPrinter, NOW), "since 18:32")
  const two = { present: true, since: "2026-09-17T18:32:00Z",
                devices: [{ present: true }, { present: false }, { present: true, counts: false }] }
  assert.equal(F.personDetail(two, NOW), "since 18:32 · 1 of 2 devices")
  const onlyPrinters = { present: false, lastSeen: null,
                         devices: [{ present: true, counts: false }] }
  assert.equal(F.personDetail(onlyPrinters, NOW), "no device counts for presence")
})

test("matches", () => {
  assert.equal(F.matches("Ana María", "  maR "), true)
  assert.equal(F.matches("Juan", "ana"), false)
  assert.equal(F.matches("Juan", ""), true)
})

test("alert text", () => {
  assert.equal(F.alertText({ kind: "gateway-mac", data: { ip: "192.168.200.1", expectedMac: "02:00:00:00:00:01",
                                                          seenMac: "aa:bb:cc:dd:ee:ff" } }),
               "Router 192.168.200.1 changed its MAC: expected 02:00:00:00:00:01, answered aa:bb:cc:dd:ee:ff")
  assert.equal(F.alertText({ kind: "ip-conflict", data: { ip: "192.168.200.9", previousMac: "a", mac: "b" } }),
               "IP address conflict: 192.168.200.9 moved from a to b")
})

test("bar text and tooltip", () => {
  assert.equal(F.barText([], 0, false), "\u{F02DC}")
  assert.equal(F.barText([ana, juan], 2, false), "🐻🦊 +2")
  assert.equal(F.barText([ana], 0, true), "\u{F0026} 🐻")
  assert.equal(F.barTooltip([ana], 2, 1, "", "2026-09-17T20:59:48Z", NOW),
               "Home: Ana · 2 unassigned · 1 alert · scanned 12 s ago")
  assert.equal(F.barTooltip([], 0, 0, "", null, NOW), "Nobody home · scanned never")
  assert.equal(F.barTooltip([], 0, 0, "nmap isn't installed", null, NOW), "Recognition · nmap isn't installed")
})

test("barText marks the guests without their emoji", () => {
  const ana = { emoji: "🐻", name: "Ana" }
  const sam = { emoji: "🦊", name: "Sam" }
  assert.equal(F.barText([ana], 0, false, [sam]), "🐻 👤")
  assert.equal(F.barText([ana], 2, false, [sam, sam]), "🐻 👤×2 +2")
  assert.equal(F.barText([], 0, false, [sam]), "👤")
  assert.equal(F.barText([ana], 0, false, []), "🐻")
})

test("barTooltip names the guests in their own stretch", () => {
  const ana = { emoji: "🐻", name: "Ana" }
  const sam = { emoji: "🦊", name: "Sam" }
  assert.equal(F.barTooltip([ana], 2, 1, "", null, 0, [sam]),
               "Home: Ana · Guests: Sam · 2 unassigned · 1 alert · scanned never")
  assert.equal(F.barTooltip([], 0, 0, "", null, 0, [sam]), "Nobody home · Guests: Sam · scanned never")
  assert.equal(F.barTooltip([ana], 0, 0, "", null, 0, []), "Home: Ana · scanned never")
})

test("house header and detail", () => {
  assert.equal(F.houseHeader([{ present: true }, { present: false }, { present: true }]), "House (3 · 2 online)")
  assert.equal(F.houseHeader([]), "House (0 · 0 online)")
  assert.equal(F.houseDetail({ present: true, ip: "192.168.200.20" }, NOW), "192.168.200.20")
  assert.equal(F.houseDetail({ present: true, ip: "" }, NOW), "online")
  assert.equal(F.houseDetail({ present: false, ip: "192.168.200.20", lastSeen: "2026-09-16T23:10:00Z" }, NOW),
               "seen yesterday 23:10")
  assert.equal(F.houseDetail({ present: false, ip: "", lastSeen: null }, NOW), "never seen")
})

test("command events, last run and test result", () => {
  assert.equal(F.commandEvents(["arrive", "home-occupied", "alert"]), "arrive · home occupied · alert")
  assert.equal(F.commandEvents(["home-empty", "unknown", "leave"]), "home empty · unknown · leave")
  assert.equal(F.commandEvents([]), "")
  assert.equal(F.commandLast(null, NOW), "never ran")
  assert.equal(F.commandLast({ at: "2026-09-17T18:32:00Z", ok: true, exit: 0, message: "" }, NOW), "ran 18:32 · ok")
  assert.equal(F.commandLast({ at: "2026-09-16T23:10:00Z", ok: false, exit: 3, message: "x" }, NOW),
               "failed yesterday 23:10 · exit 3")
  assert.equal(F.commandLast({ at: "2026-09-17T18:32:00Z", ok: false, exit: null, message: "timed out after 30 s" },
                             NOW), "timed out 18:32")
  assert.equal(F.commandLast({ at: "2026-09-17T18:32:00Z", ok: false, exit: null, message: "No such file" }, NOW),
               "failed 18:32")
  assert.equal(F.testResult({ ok: true, exit: 0, message: "", seconds: 0.4 }), "ok · 0.4 s")
  assert.equal(F.testResult({ ok: false, exit: 3, message: "curl: (6) no host", seconds: 0.1 }),
               "exit 3 · curl: (6) no host")
  assert.equal(F.testResult({ ok: false, exit: 3, message: "", seconds: 0.1 }), "exit 3")
  assert.equal(F.testResult({ ok: false, exit: null, message: "timed out after 30 s", seconds: 30 }),
               "timed out after 30 s")
})

test("commandEvents names the neighbor events", () => {
  assert.equal(F.commandEvents(["neighbor-arrive"]), "neighbor arrive")
  assert.equal(F.commandEvents(["arrive", "neighbor-leave"]), "arrive · neighbor leave")
})

test("commandEvents names the guest events", () => {
  assert.equal(F.commandEvents(["guest-arrive", "guest-leave"]), "guest arrive · guest leave")
})

test("neighborsHeader counts how many are online", () => {
  assert.equal(F.neighborsHeader([]), "Neighbors (0 · 0 online)")
  assert.equal(F.neighborsHeader([{ present: true }, { present: false }]), "Neighbors (2 · 1 online)")
})

test("guestsHeader counts the guests online", () => {
  assert.equal(F.guestsHeader([{ present: true }, { present: false }]), "Guests (2 · 1 online)")
  assert.equal(F.guestsHeader([]), "Guests (0 · 0 online)")
})

test("limitEdit takes the overflow out of what was just typed", () => {
  const full = "a".repeat(64)
  // Typing at the end of a full field: the new character goes, the old text stays.
  assert.deepEqual(F.limitEdit(full + "b", 64, 65), { text: full, at: 64 })
  // Typing in the MIDDLE of a full field: the character just typed is what
  // goes. Cutting the tail here would eat a character the user already had.
  assert.deepEqual(F.limitEdit("a".repeat(32) + "X" + "a".repeat(32), 64, 33), { text: full, at: 32 })
  // A paste that half fits keeps the half that fits, like maximumLength.
  assert.deepEqual(F.limitEdit("012ABCDE3456789", 12, 8), { text: "012AB3456789", at: 5 })
  // A paste into an already full field keeps none of it.
  assert.deepEqual(F.limitEdit("012ABCDE3456789", 10, 8), { text: "0123456789", at: 3 })
  // Under the limit nothing moves.
  assert.deepEqual(F.limitEdit("Ana", 64, 3), { text: "Ana", at: 3 })
  assert.deepEqual(F.limitEdit("", 64, 0), { text: "", at: 0 })
  assert.deepEqual(F.limitEdit(null, 64, 0), { text: "", at: 0 })
})

test("limitEdit counts characters the way the engine counts them", () => {
  // Four foxes are eight UTF-16 units but four characters: a maximumLength of
  // 3 would have cut the field at one and a half foxes.
  assert.deepEqual(F.limitEdit("🦊🦊🦊", 3, 6), { text: "🦊🦊🦊", at: 6 })
  assert.deepEqual(F.limitEdit("🦊🦊🦊🦊", 3, 8), { text: "🦊🦊🦊", at: 6 })
  // The cut never lands inside a fox: two units go, not one.
  assert.equal(F.limitEdit("🦊🦊🦊🦊", 3, 8).text.length, 6)
  // An emoji typed into the middle of a full field is the one that goes.
  assert.deepEqual(F.limitEdit("🦊🦊🦊🦊", 3, 4), { text: "🦊🦊🦊", at: 2 })
})

test("deadEventNotes names the events nobody picked can set off", () => {
  const ana = { id: "1", name: "Ana", group: "home" }
  const kim = { id: "2", name: "Kim", group: "neighbor" }
  const sam = { id: "3", name: "Sam", group: "guest" }
  assert.deepEqual(F.deadEventNotes(["arrive", "leave"], [sam]),
                   ["Nobody picked lives here, so arrive and leave never run."])
  assert.deepEqual(F.deadEventNotes(["guest-arrive"], [ana]),
                   ["Nobody picked is a guest, so guest arrive never runs."])
  assert.deepEqual(F.deadEventNotes(["neighbor-arrive", "neighbor-leave"], [ana, sam]),
                   ["Nobody picked is a neighbor, so neighbor arrive and neighbor leave never run."])
  // One note per group, in the order the switches are listed.
  assert.deepEqual(F.deadEventNotes(["arrive", "guest-leave"], [kim]),
                   ["Nobody picked lives here, so arrive never runs.",
                    "Nobody picked is a guest, so guest leave never runs."])
})

test("deadEventNotes stays quiet when there is nothing to warn about", () => {
  const ana = { id: "1", name: "Ana", group: "home" }
  const sam = { id: "3", name: "Sam", group: "guest" }
  assert.deepEqual(F.deadEventNotes(["arrive", "guest-arrive"], [ana, sam]), [])
  assert.deepEqual(F.deadEventNotes(["unknown", "alert", "home-empty"], [ana]), [])
  // Nobody picked at all already has its own message under the list.
  assert.deepEqual(F.deadEventNotes(["arrive"], []), [])
  // A person from before groups existed lives here.
  assert.deepEqual(F.deadEventNotes(["arrive"], [{ id: "4", name: "Old" }]), [])
})

const CMDS = [
  { id: "1", command: "ping it", events: ["manual"], people: null },
  { id: "2", command: "on arrival", events: ["arrive"], people: null },
  { id: "3", command: "wake hers", events: ["manual", "arrive"], people: ["ana"] },
  { id: "4", command: "no events", events: [], people: null }
]

test("manualCommands", () => {
  assert.deepEqual(F.manualCommands(CMDS, "").map(c => c.id), ["1", "3"])
  assert.deepEqual(F.manualCommands(CMDS, "ana").map(c => c.id), ["1", "3"])
  assert.deepEqual(F.manualCommands(CMDS, "bo").map(c => c.id), ["1"])
  assert.deepEqual(F.manualCommands([], "ana"), [])
  assert.deepEqual(F.manualCommands(null, ""), [])
})

test("commandOneLine collapses a command that spans lines", () => {
  assert.equal(F.commandOneLine("cd /tmp\nls -la"), "cd /tmp ls -la")
  assert.equal(F.commandOneLine("  true  "), "true")
  assert.equal(F.commandOneLine(null), "")
})

test("commandTrigger says whether a command runs on an event or only by hand", () => {
  assert.equal(F.commandTrigger(["manual"]), "Manual only")
  assert.equal(F.commandTrigger(["arrive", "leave"]), "On arrive, leave")
  assert.equal(F.commandTrigger(["arrive", "leave", "manual"]), "On arrive, leave · also manual")
  assert.equal(F.commandTrigger(["home-empty"]), "On home empty")
  // Neither validate_events nor readily_events can hand back an empty list. The branch
  // is here so a hand-edited people.json cannot make a command read as "Manual only".
  assert.equal(F.commandTrigger([]), "No events")
  assert.equal(F.commandTrigger(null), "No events")
})

test("commandOrigin names where a command was written", () => {
  assert.equal(F.commandOrigin({ source: "readily", note: "Home" }), "Obsidian")
  assert.equal(F.commandOrigin({ command: "true" }), "Plugin")
  assert.equal(F.commandOrigin(null), "Plugin")
})

test("commandMeta leads with the origin and what the command applies to", () => {
  const readily = { source: "readily", note: "commands", title: "Wake", events: ["arrive"], last: null }
  assert.equal(F.commandMeta(readily, NOW), "Obsidian · commands · On arrive — never ran")
  assert.equal(F.commandMeta({ events: ["leave"], last: null }, NOW), "Plugin · On leave — never ran")
  assert.equal(F.commandMeta({ events: ["manual"], last: null }, NOW), "Plugin · Manual only — never ran")
  assert.equal(F.commandMeta({ events: ["arrive", "manual"], last: null }, NOW),
               "Plugin · On arrive · also manual — never ran")
  assert.equal(F.isReadily(readily), true)
  assert.equal(F.isReadily({ command: "true" }), false)
  // A Readily command that already ran once still gets the full second line.
  const ran = { source: "readily", note: "commands", title: "Wake", events: ["arrive"],
               last: { at: "2026-09-17T18:32:00Z", ok: true } }
  assert.equal(F.commandMeta(ran, NOW), "Obsidian · commands · On arrive — ran 18:32 · ok")
  // _command_view defaults a missing note to "", and an empty one must not leave a
  // dangling separator hanging off the origin.
  assert.equal(F.commandMeta({ source: "readily", note: "", events: ["manual"], last: null }, NOW),
               "Obsidian · Manual only — never ran")
})

test("the command list splits by where each command comes from", () => {
  const mine = { id: "a", command: "true", events: ["manual"] }
  const other = { id: "b", command: "false", events: ["arrive"] }
  const note = { id: "c", source: "readily", note: "Home", events: ["manual"] }
  assert.deepEqual(F.pluginCommands([mine, note, other]), [mine, other])
  assert.deepEqual(F.readilyCommands([mine, note, other]), [note])
  assert.deepEqual(F.pluginCommands([note]), [])
  assert.deepEqual(F.readilyCommands([mine]), [])
  assert.deepEqual(F.pluginCommands(null), [])
  assert.deepEqual(F.readilyCommands(null), [])
})

test("commandMenuLabel names a Readily command by its title", () => {
  assert.equal(F.commandMenuLabel({ source: "readily", title: "Wake", command: "wol x" }), "◆ Wake")
  assert.equal(F.commandMenuLabel({ command: "true" }), "true")
  assert.equal(F.commandMenuLabel(null), "")
  // No title: falls back to the command text, collapsed to one line.
  assert.equal(F.commandMenuLabel({ source: "readily", title: "", command: "cd /tmp\nls -la" }),
               "◆ cd /tmp ls -la")
})

test("readilyNote joins the note and title, or falls back to just the note", () => {
  assert.equal(F.readilyNote({ source: "readily", note: "cosas.md", title: "Wake" }), "cosas.md · Wake")
  assert.equal(F.readilyNote({ source: "readily", note: "cosas.md", title: "" }), "cosas.md")
  assert.equal(F.readilyNote(null), "")
})

test("readilyStatus", () => {
  const on = { enabled: true, ok: true, warning: "", count: 0, skipped: 0 }
  assert.equal(F.readilyStatus(null), "")
  assert.equal(F.readilyStatus({ enabled: false, ok: true, warning: "", count: 3, skipped: 0 }), "")
  assert.equal(F.readilyStatus({ enabled: true, ok: false, warning: "Readily not found", count: 0, skipped: 0 }),
               "Readily not found")
  assert.equal(F.readilyStatus(on), "No #recognition items in your notes")
  assert.equal(F.readilyStatus(Object.assign({}, on, { count: 1 })), "1 command from Obsidian")
  assert.equal(F.readilyStatus(Object.assign({}, on, { count: 3 })), "3 commands from Obsidian")
  assert.equal(F.readilyStatus(Object.assign({}, on, { count: 3, skipped: 2 })),
               "3 commands from Obsidian, 2 skipped")
})

test("runSummary", () => {
  assert.equal(F.runSummary(null), "")
  assert.equal(F.runSummary({ ok: true, exit: 0, message: "", seconds: 1.2 }), "exit 0 · 1.2 s")
  assert.equal(F.runSummary({ ok: false, exit: 1, message: "", seconds: 0.3 }), "failed · exit 1 · 0.3 s")
  assert.equal(F.runSummary({ ok: false, exit: null, message: "timed out after 30 s", seconds: 30 }),
               "timed out after 30 s")
  assert.equal(F.runSummary({ ok: false, exit: null, message: "", seconds: 0 }), "failed")
})

test("manual has a label", () => {
  assert.equal(F.commandEvents(["arrive", "manual"]), "arrive · manual")
})

test("duration reads as hours and minutes", () => {
  assert.equal(F.duration(0), "0m")
  assert.equal(F.duration(59), "1m")
  assert.equal(F.duration(60), "1m")
  assert.equal(F.duration(2700), "45m")
  assert.equal(F.duration(3600), "1h")
  assert.equal(F.duration(22800), "6h 20m")
  assert.equal(F.duration(64800), "18h")
  assert.equal(F.duration(3599), "1h")        // rounds up into the hour
  assert.equal(F.duration(-5), "0m")
  assert.equal(F.duration(null), "0m")
})

test("longDuration leaves a day alone and rolls anything longer into days", () => {
  // Under a day it is duration, unchanged.
  assert.equal(F.longDuration(0), "0m");
  assert.equal(F.longDuration(2700), "45m");
  assert.equal(F.longDuration(22800), "6h 20m");
  assert.equal(F.longDuration(84600), "23h 30m");
  // The threshold is counted in minutes, so a day short by a second is a day and not
  // "24h" -- the same quantity written two ways on either side of one second.
  assert.equal(F.longDuration(86399), "1d");
  assert.equal(F.longDuration(86400), "1d");
  // Days and hours, minutes dropped: at this scale they are noise.
  assert.equal(F.longDuration(90000), "1d 1h");
  assert.equal(F.longDuration(1569600), "18d 4h");
  assert.equal(F.longDuration(172800), "2d");
  assert.equal(F.longDuration(2595600), "30d 1h");   // a full month, the largest total
  assert.equal(F.longDuration(-5), "0m");
  assert.equal(F.longDuration(null), "0m");
});

test("homeTotal keeps the unmeasured part separate", () => {
  assert.equal(F.homeTotal(210000, 0), "2d 10h");
  assert.equal(F.homeTotal(210000, 3600), "2d 10h \u00b7 1h not measured");
  assert.equal(F.homeTotal(22800, 0), "6h 20m");
  assert.equal(F.homeTotal(0, 0), "0m");
});

test("spanBox places a span inside its day", () => {
  const box = F.spanBox({ from: "2026-09-24T09:00:00Z", to: "2026-09-24T12:00:00Z" },
                        "2026-09-24");
  assert.equal(box.x, 9 / 24);
  assert.equal(box.w, 3 / 24);
});

test("spanBox starts at zero at local midnight", () => {
  const box = F.spanBox({ from: "2026-09-24T00:00:00Z", to: "2026-09-24T06:00:00Z" },
                        "2026-09-24");
  assert.equal(box.x, 0);
  assert.equal(box.w, 0.25);
});

test("spanBox reads the next midnight as the end of this day, not the start of none", () => {
  const box = F.spanBox({ from: "2026-09-24T18:00:00Z", to: "2026-09-25T00:00:00Z" },
                        "2026-09-24");
  assert.equal(box.x, 18 / 24);
  assert.equal(box.w, 6 / 24);
});

test("spanBox gives a zero-length span no width", () => {
  const box = F.spanBox({ from: "2026-09-24T09:00:00Z", to: "2026-09-24T09:00:00Z" },
                        "2026-09-24");
  assert.equal(box.w, 0);
});

test("spanBox survives a span it cannot read", () => {
  assert.deepEqual(F.spanBox({ from: "nope", to: "nope" }, "2026-09-24"), { x: 0, w: 0 });
  assert.deepEqual(F.spanBox({}, "2026-09-24"), { x: 0, w: 0 });
});

test("dayShort labels the narrow column of the week grid", () => {
  assert.equal(F.dayShort("2026-09-21"), "Mon 21");
  assert.equal(F.dayShort("2026-09-27"), "Sun 27");
  assert.equal(F.dayShort("nope"), "");
});

test("periodLabel names the day", () => {
  assert.equal(F.periodLabel("day", "2026-09-26", "2026-09-26", "2026-09-26"), "Today")
  assert.equal(F.periodLabel("day", "2026-09-25", "2026-09-25", "2026-09-26"), "Yesterday")
  assert.equal(F.periodLabel("day", "2026-09-18", "2026-09-18", "2026-09-26"), "Friday, Sep 18")
  assert.equal(F.periodLabel("day", "2026-03-01", "2026-03-01", "2026-03-02"), "Yesterday")
})

test("periodLabel names the week and the month", () => {
  assert.equal(F.periodLabel("week", "2026-09-21", "2026-09-27", "2026-09-26"), "Sep 21 – 27")
  assert.equal(F.periodLabel("week", "2026-09-28", "2026-10-04", "2026-10-01"), "Sep 28 – Oct 4")
  assert.equal(F.periodLabel("month", "2026-09-01", "2026-09-30", "2026-09-26"), "September 2026")
  assert.equal(F.periodLabel("month", "2025-12-01", "2025-12-31", "2026-09-26"), "December 2025")
})

test("periodLabel survives a date it cannot read", () => {
  assert.equal(F.periodLabel("month", "", "", "2026-09-26"), "")
  assert.equal(F.periodLabel("week", "2026-09-21", "nope", "2026-09-26"), "")
})

test("monthGrid lays a month out in whole weeks from Monday", () => {
  // September 2026 starts on a Tuesday and has 30 days: one blank, then 30, and five
  // rows is enough -- a sixth would be an empty strip under the grid.
  const sep = F.monthGrid("2026-09-14")
  assert.equal(sep.length, 35)
  assert.equal(sep[0], "")
  assert.equal(sep[1], "2026-09-01")
  assert.equal(sep[30], "2026-09-30")
  assert.equal(sep[31], "")
})

test("monthGrid takes a sixth row when the month needs one", () => {
  // March 2026 starts on a Sunday: six cells go to February before the 1st even lands,
  // and 31 days then push past the fifth row.
  const mar = F.monthGrid("2026-03-31")
  assert.equal(mar.length, 42)
  assert.equal(mar[5], "")
  assert.equal(mar[6], "2026-03-01")
  assert.equal(mar[36], "2026-03-31")
  assert.equal(mar[41], "")
})

test("monthGrid counts a leap February to the 29th", () => {
  const feb = F.monthGrid("2024-02-01")
  assert.equal(feb.length, 35)
  assert.equal(feb[3], "2024-02-01")
  assert.equal(feb[31], "2024-02-29")
  assert.equal(feb[32], "")
})

test("monthGrid survives a date it cannot read", () => {
  assert.deepEqual(F.monthGrid("nope"), [])
  assert.deepEqual(F.monthGrid(""), [])
})

test("shiftMonth lands on the first of the month, across the year's edge", () => {
  assert.equal(F.shiftMonth("2026-09-14", 0), "2026-09-01")
  assert.equal(F.shiftMonth("2026-09-14", 1), "2026-10-01")
  assert.equal(F.shiftMonth("2026-09-14", -1), "2026-08-01")
  assert.equal(F.shiftMonth("2026-12-31", 1), "2027-01-01")
  assert.equal(F.shiftMonth("2026-01-05", -1), "2025-12-01")
  assert.equal(F.shiftMonth("nope", 1), "")
})
