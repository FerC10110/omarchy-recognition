// Pure text helpers for the Recognition panel and bar. No QML in here, so
// node can test it (tests/test_format.js); QML ignores the module.exports
// block at the end, the same trick as Omarchy's emojis/EmojiSearch.js.

function parseIso(text) {
  if (!text) return null
  var ms = Date.parse(String(text))
  return isNaN(ms) ? null : new Date(ms)
}

function pad(n) { return n < 10 ? "0" + n : String(n) }

function clock(date) { return pad(date.getHours()) + ":" + pad(date.getMinutes()) }

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
var MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
                   "August", "September", "October", "November", "December"]
var DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

// A YYYY-MM-DD from the engine, as a local Date. Not `new Date(text)`: that reads the
// string as UTC midnight, which in Buenos Aires is the evening before, and the weekday
// would come out one day early.
function ymd(text) {
  var parts = String(text || "").split("-")
  if (parts.length !== 3) return null
  var date = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
  return isNaN(date.getTime()) ? null : date
}

function isoDay(date) {
  return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate())
}

// How long something lasted, for a dashboard row. Seconds are noise at this scale: the
// scan interval is twenty of them, so nothing here is accurate to one.
function duration(seconds) {
  var total = Math.max(0, Math.round(Number(seconds) || 0))
  var hours = Math.floor(total / 3600)
  var minutes = Math.round((total - hours * 3600) / 60)
  if (minutes === 60) { hours += 1; minutes = 0 }
  if (hours === 0) return minutes + "m"
  if (minutes === 0) return hours + "h"
  return hours + "h " + minutes + "m"
}

// How far into `day` an instant falls, 0..1. A day the engine already cut at local
// midnight can only produce instants inside it, at its start, or at the midnight that
// closes it -- and that last one is the end of this day, not the start of the next.
//
// The divisor is a flat 86400: on the two days a year a timezone changes offset the local
// day is 23 or 25 hours long, and the last hour of the axis comes out short or clipped.
// Known and left alone, the same call the history made when it cut days at local midnight.
function dayFraction(date, day) {
  var key = isoDay(date)
  if (key < day) return 0
  if (key > day) return 1
  return (date.getHours() * 3600 + date.getMinutes() * 60 + date.getSeconds()) / 86400
}

// {x, w} as fractions of the day's width, for one span of one lane.
function spanBox(span, day) {
  var from = span ? parseIso(span.from) : null
  var to = span ? parseIso(span.to) : null
  if (!from || !to) return { x: 0, w: 0 }
  var x = dayFraction(from, day)
  var end = dayFraction(to, day)
  if (end < x) end = x
  return { x: x, w: end - x }
}

// A total with the part of it nobody measured kept separate. The engine goes to some
// trouble to never claim a stretch it did not see; hiding it here would throw that away.
// A total that covers a whole period, where hours stop reading: a month of being home
// is "18d 4h", not "438h". Under a day it is duration untouched, because a day is where
// hours still say something. The threshold is counted in minutes so that a day short by
// a second reads as "1d" and not "24h" -- one second apart, the same quantity should not
// change notation.
function longDuration(seconds) {
  var total = Math.max(0, Math.round(Number(seconds) || 0))
  var minutes = Math.round(total / 60)
  if (minutes < 1440) return duration(total)
  var hours = Math.round(minutes / 60)
  var days = Math.floor(hours / 24), rest = hours - days * 24
  return rest === 0 ? days + "d" : days + "d " + rest + "h"
}

function homeTotal(home, unknown) {
  var text = longDuration(home)
  if (Number(unknown) > 0) text += " \u00b7 " + longDuration(unknown) + " not measured"
  return text
}

// "Mon 21" -- the narrow left column of the week and month grids. Short on purpose: it
// repeats once per row, and the hours to its right are what the eye is there for.
function dayShort(text) {
  var date = ymd(text)
  if (!date) return ""
  return DAY_NAMES[date.getDay()].slice(0, 3) + " " + date.getDate()
}

// The title over the dashboard: which day, week or month is on screen. `today` comes
// from the panel, so "Today" and "Yesterday" need no second clock in here.
function periodLabel(period, from, to, today) {
  var start = ymd(from)
  if (!start) return ""
  if (period === "day") {
    if (from === today) return "Today"
    var before = ymd(today)
    if (before) {
      before.setDate(before.getDate() - 1)
      if (isoDay(before) === from) return "Yesterday"
    }
    return DAY_NAMES[start.getDay()] + ", " + MONTHS[start.getMonth()] + " " + start.getDate()
  }
  if (period === "week") {
    var end = ymd(to)
    if (!end) return ""
    if (start.getMonth() === end.getMonth() && start.getFullYear() === end.getFullYear())
      return MONTHS[start.getMonth()] + " " + start.getDate() + " \u2013 " + end.getDate()
    return MONTHS[start.getMonth()] + " " + start.getDate() + " \u2013 "
         + MONTHS[end.getMonth()] + " " + end.getDate()
  }
  return MONTH_NAMES[start.getMonth()] + " " + start.getFullYear()
}

// The cells of a month, in rows of seven counted from Monday -- the day history_period
// starts a week on, so the grid and the engine agree on where a week begins. A cell
// outside the month is "", which keeps the shape without the caller doing arithmetic.
// Only the weeks the month touches come back: a month that fits in five rows does not
// get an empty sixth one under it.
function monthGrid(text) {
  var date = ymd(text)
  if (!date) return []
  var first = new Date(date.getFullYear(), date.getMonth(), 1)
  var offset = (first.getDay() + 6) % 7
  var days = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate()
  var cells = Math.ceil((offset + days) / 7) * 7
  var out = []
  for (var i = 0; i < cells; i++) {
    var day = i - offset + 1
    out.push(day >= 1 && day <= days
             ? isoDay(new Date(first.getFullYear(), first.getMonth(), day)) : "")
  }
  return out
}

// The first of the month `delta` months away, which is also how a date is reduced to the
// month it belongs to (delta 0). The day of the month is dropped on purpose: it is what
// the month arrows move over, and January 31st stepping back a month has no answer worth
// guessing at.
function shiftMonth(text, delta) {
  var date = ymd(text)
  if (!date) return ""
  return isoDay(new Date(date.getFullYear(), date.getMonth() + Number(delta || 0), 1))
}

// "12 s ago", "3 min ago", "2 h ago", "4 d ago"; "never" when missing.
function ago(text, nowMs) {
  var date = parseIso(text)
  if (!date) return "never"
  var s = Math.max(0, Math.floor((nowMs - date.getTime()) / 1000))
  if (s < 60) return s + " s ago"
  if (s < 3600) return Math.floor(s / 60) + " min ago"
  if (s < 86400) return Math.floor(s / 3600) + " h ago"
  return Math.floor(s / 86400) + " d ago"
}

// Local time: "18:32" today, "yesterday 23:10", "Sep 12 08:05" before; "never" when missing.
function when(text, nowMs) {
  var date = parseIso(text)
  if (!date) return "never"
  var now = new Date(nowMs)
  if (sameDay(date, now)) return clock(date)
  var yesterday = new Date(nowMs)
  yesterday.setDate(yesterday.getDate() - 1)
  if (sameDay(date, yesterday)) return "yesterday " + clock(date)
  return MONTHS[date.getMonth()] + " " + pad(date.getDate()) + " " + clock(date)
}

function deviceTitle(d) {
  return d.hostname || d.vendor || (d.randomMac ? "Random MAC" : "Device")
}

function deviceDetail(d, nowMs) {
  var parts = []
  if (d.hostname && d.vendor) parts.push(d.vendor)
  if (d.randomMac && !d.vendor) parts.push("probably a phone")
  if (d.ip) parts.push(d.ip)
  parts.push(d.mac)
  if (d.present === false) parts.push("seen " + when(d.lastSeen, nowMs))
  return parts.join(" · ")
}

function personDetail(p, nowMs) {
  var devices = p.devices || []
  var counting = countingDevices(devices)
  if (p.present) {
    var here = 0
    for (var i = 0; i < devices.length; i++) if (devices[i].counts !== false && devices[i].present) here++
    var text = "since " + when(p.since, nowMs)
    if (counting > 1) text += " · " + here + " of " + counting + " devices"
    return text
  }
  if (devices.length === 0) return "no devices"
  // Every device they have is ignored for presence: "never seen" would be a lie.
  if (counting === 0) return "no device counts for presence"
  return p.lastSeen ? "seen " + when(p.lastSeen, nowMs) : "never seen"
}

// One line per device: label, MAC, last known IP, and when it was last seen if
// it is not here now. The IP shows whether or not the device is connected: it is
// the last one it had, which is what tells two devices apart.
function deviceTooltipLine(d, nowMs) {
  var parts = []
  if (d.label) parts.push(d.label)
  parts.push(d.mac)
  if (d.ip) parts.push(d.ip)
  if (!d.present) parts.push(d.lastSeen ? "seen " + ago(d.lastSeen, nowMs) : "never seen")
  if (d.counts === false) parts.push("doesn't count")
  return parts.join(" · ")
}

// The line under a device's label in the person editor: what tells two devices apart
// (its MAC and its last known IP), when it was last seen if it is not here, and whether
// it is ignored for presence. `counts` comes in apart from the device because the editor
// owns the live flag while you are editing.
function deviceEditorLine(d, counts, nowMs) {
  var parts = [d.mac]
  if (d.ip) parts.push(d.ip)
  if (d.present === false) parts.push(d.lastSeen ? "seen " + ago(d.lastSeen, nowMs) : "never seen")
  if (counts === false) parts.push("doesn't count")
  return parts.join(" · ")
}

// One row of the menu that picks which of a person's devices a command runs on: the
// name they gave it, and then what tells two of them apart right now. What follows the
// name is decided by `present`, not by whether there is an IP: a device that is gone can
// still carry the IP it had, and "seen 3 h ago" is what you want to read there.
function deviceMenuLine(d, nowMs) {
  var parts = [d.label || d.mac]
  if (d.present) { if (d.ip) parts.push(d.ip) }
  else if (d.lastSeen) parts.push("seen " + ago(d.lastSeen, nowMs))
  return parts.join(" · ")
}

// How many of a person's devices say anything about where they are.
function countingDevices(devices) {
  var n = 0
  for (var i = 0; i < devices.length; i++) if (devices[i].counts !== false) n++
  return n
}

// What hovering a person shows: every device they own, in their own order.
function personTooltip(p, nowMs) {
  var devices = (p && p.devices) || []
  if (!devices.length) return "No devices yet"
  var lines = []
  for (var i = 0; i < devices.length; i++) lines.push(deviceTooltipLine(devices[i], nowMs))
  return lines.join("\n")
}

// "House (8 · 6 online)"
function houseHeader(house) {
  var online = 0
  for (var i = 0; i < house.length; i++) if (house[i].present) online++
  return "House (" + house.length + " · " + online + " online)"
}

// "Neighbors (3 · 1 online)"
function neighborsHeader(neighbors) {
  var online = 0
  for (var i = 0; i < neighbors.length; i++) if (neighbors[i].present) online++
  return "Neighbors (" + neighbors.length + " · " + online + " online)"
}

// "Guests (2 · 1 online)"
function guestsHeader(guests) {
  var online = 0
  for (var i = 0; i < guests.length; i++) if (guests[i].present) online++
  return "Guests (" + guests.length + " · " + online + " online)"
}

// The IP while online; "seen <when>" or "never seen" otherwise.
function houseDetail(d, nowMs) {
  if (d.present) return d.ip || "online"
  return d.lastSeen ? "seen " + when(d.lastSeen, nowMs) : "never seen"
}

function matches(name, query) {
  var q = String(query || "").trim().toLowerCase()
  return q === "" || String(name || "").toLowerCase().indexOf(q) >= 0
}

// How many characters (code points) a string holds, and where `count` of them
// reach back to from `at`. A TextField's own maximumLength counts UTF-16
// units, so a name of emojis stopped at half of the characters the engine
// takes — the engine counts code points, like Python's len.
function countPoints(s) {
  var points = 0
  for (var i = 0; i < s.length; i++) {
    var unit = s.charCodeAt(i)
    if (unit >= 0xD800 && unit <= 0xDBFF && i + 1 < s.length) i += 1
    points += 1
  }
  return points
}

function backFrom(s, at, count) {
  var i = at
  while (i > 0 && count > 0) {
    var unit = s.charCodeAt(i - 1)
    i -= (unit >= 0xDC00 && unit <= 0xDFFF && i >= 2) ? 2 : 1
    count -= 1
  }
  return i
}

// An edit that pushes a field past `max` characters, with the overflow taken
// out of the run that ends at the cursor — never out of what was already
// there, which is how maximumLength behaves: it trims the text being inserted
// and leaves the rest alone. Returns the text to keep and where the cursor
// goes. (A field seeded over the limit by hand can only give back what sits
// before the cursor; the engine refuses the rest on save.)
function limitEdit(text, max, at) {
  var s = (text === null || text === undefined) ? "" : String(text)
  var over = countPoints(s) - max
  if (over <= 0) return { text: s, at: at }
  var cursor = Math.min(at, s.length)
  var start = backFrom(s, cursor, over)
  return { text: s.slice(0, start) + s.slice(cursor), at: start }
}

function alertText(a) {
  var d = a.data || {}
  if (a.kind === "gateway-mac")
    return "Router " + d.ip + " changed its MAC: expected " + d.expectedMac + ", answered " + d.seenMac
  if (a.kind === "ip-conflict")
    return "IP address conflict: " + d.ip + " moved from " + d.previousMac + " to " + d.mac
  return "Network alert"
}

var GUEST_GLYPH = "👤"

// "󰀦 🐻🦊 👤×2 +2"; the home glyph when there is nothing to show.
function barText(here, unknownHere, warn, guestsHere) {
  var parts = []
  if (warn) parts.push("\u{F0026}")
  var emojis = ""
  for (var i = 0; i < here.length; i++) emojis += here[i].emoji
  if (emojis !== "") parts.push(emojis)
  var guests = (guestsHere || []).length
  if (guests > 0) parts.push(guests > 1 ? GUEST_GLYPH + "×" + guests : GUEST_GLYPH)
  if (unknownHere > 0) parts.push("+" + unknownHere)
  return parts.length ? parts.join(" ") : "\u{F02DC}"
}

function barTooltip(here, unknownHere, alertCount, error, lastScan, nowMs, guestsHere) {
  if (error) return "Recognition · " + error
  var names = []
  for (var i = 0; i < here.length; i++) names.push(here[i].name)
  var text = names.length ? "Home: " + names.join(", ") : "Nobody home"
  var guests = []
  for (var j = 0; j < (guestsHere || []).length; j++) guests.push(guestsHere[j].name)
  if (guests.length) text += " · Guests: " + guests.join(", ")
  if (unknownHere > 0) text += " · " + unknownHere + " unassigned"
  if (alertCount > 0) text += " · " + alertCount + (alertCount === 1 ? " alert" : " alerts")
  return text + " · scanned " + ago(lastScan, nowMs)
}

var EVENT_LABELS = { "arrive": "arrive", "leave": "leave",
                     "neighbor-arrive": "neighbor arrive", "neighbor-leave": "neighbor leave",
                     "guest-arrive": "guest arrive", "guest-leave": "guest leave",
                     "home-occupied": "home occupied", "home-empty": "home empty",
                     "unknown": "unknown", "alert": "alert", "manual": "manual" }

// "arrive · home occupied · alert"
function commandEvents(events) {
  var labels = []
  for (var i = 0; i < (events || []).length; i++) labels.push(EVENT_LABELS[events[i]] || String(events[i]))
  return labels.join(" · ")
}

// A command's people filter is per group: an arrival only ever fires for
// someone in that group, so "arrive" with only guests picked never runs. One
// note per group whose events are marked and whose people are missing. Nobody
// picked at all gets no note: the list already says so under it.
var GROUP_GAPS = [{ group: "home", events: ["arrive", "leave"], who: "Nobody picked lives here" },
                  { group: "neighbor", events: ["neighbor-arrive", "neighbor-leave"],
                    who: "Nobody picked is a neighbor" },
                  { group: "guest", events: ["guest-arrive", "guest-leave"], who: "Nobody picked is a guest" }]

function deadEventNotes(events, picked) {
  var marked = events || [], people = picked || [], notes = []
  if (!people.length) return notes
  for (var i = 0; i < GROUP_GAPS.length; i++) {
    var gap = GROUP_GAPS[i], dead = []
    for (var j = 0; j < gap.events.length; j++)
      if (marked.indexOf(gap.events[j]) >= 0) dead.push(EVENT_LABELS[gap.events[j]])
    if (!dead.length) continue
    var served = false
    for (var k = 0; k < people.length; k++)
      if ((people[k].group || "home") === gap.group) { served = true; break }
    if (served) continue
    notes.push(gap.who + ", so " + dead.join(" and ") + (dead.length > 1 ? " never run." : " never runs."))
  }
  return notes
}

// A command's last run: "never ran", "ran 18:32 · ok", "failed 18:32 · exit 3",
// "timed out 18:32", or "failed 18:32" when it could not start.
function commandLast(last, nowMs) {
  if (!last) return "never ran"
  var at = when(last.at, nowMs)
  if (last.ok) return "ran " + at + " · ok"
  if (last.exit !== null && last.exit !== undefined) return "failed " + at + " · exit " + last.exit
  if (String(last.message || "").indexOf("timed out") === 0) return "timed out " + at
  return "failed " + at
}

// The editor's Test line: "ok · 0.4 s", "exit 3 · <last stderr line>", or the message alone.
function testResult(test) {
  if (!test) return ""
  if (test.ok) return "ok · " + test.seconds + " s"
  if (test.exit !== null && test.exit !== undefined) return "exit " + test.exit + (test.message ? " · " + test.message : "")
  return String(test.message || "failed")
}

// The commands the right-click menu offers: the ones marked manual, and — on a
// person — only those whose people filter includes them (null is everyone). On a
// device (empty personId) the filter means nothing, so every manual command shows.
function manualCommands(commands, personId) {
  var out = []
  for (var i = 0; i < (commands || []).length; i++) {
    var c = commands[i]
    if (!c.events || c.events.indexOf("manual") < 0) continue
    if (personId && c.people && c.people.indexOf(personId) < 0) continue
    out.push(c)
  }
  return out
}

// The marker Runbook already uses for what comes from Readily, so the two plugins
// agree on what a ◆ means.
var READILY_MARK = "◆ "

// True for a command that lives in an Obsidian note instead of people.json.
function isReadily(c) { return !!c && c.source === "readily" }

// A command on one line: a Readily one comes from a fenced code block and may span
// several, and a row that elides reads better than one three lines tall.
function commandOneLine(text) {
  if (text === undefined || text === null) return ""
  return String(text).replace(/\s+/g, " ").trim()
}

// What a command applies to. "manual" is an event like any other in the record, but in
// a list it reads as the absence of one, so it is said apart instead of mixed into the
// run: "Manual only", "On arrive, leave", "On arrive · also manual".
function commandTrigger(events) {
  var marked = events || [], on = []
  for (var i = 0; i < marked.length; i++)
    if (marked[i] !== "manual") on.push(EVENT_LABELS[marked[i]] || String(marked[i]))
  var byHand = marked.indexOf("manual") >= 0
  if (!on.length) return byHand ? "Manual only" : "No events"
  return "On " + on.join(", ") + (byHand ? " · also manual" : "")
}

// Where a command was written: a note in Obsidian, or this plugin's own editor.
function commandOrigin(c) { return isReadily(c) ? "Obsidian" : "Plugin" }

function bySource(commands, readily) {
  var out = []
  for (var i = 0; i < (commands || []).length; i++)
    if (isReadily(commands[i]) === readily) out.push(commands[i])
  return out
}

// The two halves of the settings list. The engine hands over one flat list with the
// native commands first, and filtering keeps that order inside each half.
function pluginCommands(commands) { return bySource(commands, false) }
function readilyCommands(commands) { return bySource(commands, true) }

// A command row's second line: where it comes from, the note it lives in when that is
// Obsidian, what it applies to, and how its last run went. No ◆ here — the word says
// it better, and the row has space for a word.
function commandMeta(c, nowMs) {
  var note = isReadily(c) && c.note ? c.note + " · " : ""
  return commandOrigin(c) + " · " + note + commandTrigger(c ? c.events : [])
       + " — " + commandLast(c ? c.last : null, nowMs)
}

// The right-click menu's label: a Readily command goes by its note heading, which reads
// better than its text; a native one has nothing but its text.
function commandMenuLabel(c) {
  if (!c) return ""
  return isReadily(c) ? READILY_MARK + (c.title || commandOneLine(c.command)) : c.command
}

// The read-only editor's "Note: …" line: the note by itself when the item has no
// title, "note · title" when it does, and "" when there is no command at all.
function readilyNote(c) {
  if (!c) return ""
  var note = c.note || ""
  return c.title ? note + " · " + c.title : note
}

// The line under the Readily switch in Settings: what the last read found, or why it
// found nothing. Empty with the switch off, and the line is hidden then.
function readilyStatus(r) {
  if (!r || !r.enabled) return ""
  if (!r.ok) return String(r.warning || "")
  if (!r.count) return "No #recognition items in your notes"
  var text = r.count === 1 ? "1 command from Obsidian" : r.count + " commands from Obsidian"
  return r.skipped ? text + ", " + r.skipped + " skipped" : text
}

// The result view's status line: "exit 0 · 1.2 s", "failed · exit 1 · 0.3 s", or the
// message alone ("timed out after 30 s") when there is no exit code at all.
function runSummary(run) {
  if (!run) return ""
  if (run.exit === null || run.exit === undefined) return String(run.message || "failed")
  return (run.ok ? "exit " + run.exit : "failed · exit " + run.exit) + " · " + run.seconds + " s"
}

if (typeof module !== "undefined") {
  module.exports = { ago: ago, when: when, duration: duration, longDuration: longDuration, homeTotal: homeTotal, periodLabel: periodLabel, monthGrid: monthGrid, shiftMonth: shiftMonth, dayFraction: dayFraction, spanBox: spanBox, dayShort: dayShort, deviceTitle: deviceTitle, deviceDetail: deviceDetail,
                     deviceEditorLine: deviceEditorLine, deviceMenuLine: deviceMenuLine,
                     countingDevices: countingDevices,
                     personDetail: personDetail, personTooltip: personTooltip,
                     houseHeader: houseHeader, houseDetail: houseDetail,
                     neighborsHeader: neighborsHeader,
                     guestsHeader: guestsHeader,
                     matches: matches, alertText: alertText, barText: barText, barTooltip: barTooltip,
                     commandEvents: commandEvents, commandLast: commandLast, testResult: testResult,
                     manualCommands: manualCommands, runSummary: runSummary,
                     limitEdit: limitEdit, deadEventNotes: deadEventNotes,
                     isReadily: isReadily, commandOneLine: commandOneLine, commandMeta: commandMeta,
                     commandTrigger: commandTrigger, commandOrigin: commandOrigin,
                     pluginCommands: pluginCommands, readilyCommands: readilyCommands,
                     commandMenuLabel: commandMenuLabel, readilyNote: readilyNote,
                     readilyStatus: readilyStatus }
}
