import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Format.js" as Format

// Recognition panel: a thin face over bin/recognition. It owns the scan timer,
// watches both data files, keeps the last status the engine answered, and holds
// the editor draft so views can come and go. Views are separate files loaded one
// at a time; each gets `host` (this panel) and reads everything from it.
Panel {
  id: recognition   // not `root`: views reach the panel through `host`
  moduleName: "io.github.ferc10110.recognition"
  ipcTarget: "io.github.ferc10110.recognition"
  // Base Panel's own IpcHandler (open/close/show/hide/toggle on `ipcTarget`)
  // is a separate channel from `omarchy-shell shell summon`, which routes
  // through shell.bar.summonBarWidget(id) instead. With one Quickshell
  // instance per monitor sharing this same target string, leaving the base
  // handler enabled lets each monitor's Recognition panel react to every
  // other monitor's IPC call too. Disable it; summon/hide keep working
  // through the bar-widget path (Ruling R16).
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null

  // ---- what the engine last said
  property var status: ({ lastScan: null, subnet: "", error: null, people: [], unknown: [], house: [], neighbors: [], guests: [], alerts: [],
                          commands: [],
                          settings: { scanInterval: 20, gracePeriod: 300, subnet: "",
                                      guestsOccupyHome: true,
                                      notify: { arrive: true, leave: true, neighbor: true, guest: true, unknown: true, security: true, home: false } } })
  property string callError: ""        // a status/scan call that failed (e.g. people.json broken)
  property string notice: ""           // the last failed action, shown for a few seconds
  property bool noticeOk: false        // an ok notice (a copy) is not painted red
  property real nowMs: Date.now()
  // Where the last context menu was opened, in scene coordinates: the device menu
  // reopens the card in the same place, and the handler that reopens it has no click
  // of its own to go by.
  property point menuOrigin: Qt.point(0, 0)
  property real lastScanReply: 0
  // `scan` reads people.json at its own start and answers from that copy, with
  // no lock against a concurrent edit. If an edit's status lands while a scan
  // is still running, the scan's later (now stale) reply would overwrite it.
  // Set whenever that can happen; scanProc's own finish handler clears it and
  // asks for the status again once the stale reply has already been applied.
  property bool refreshAfterScan: false

  // ---- view state
  property string view: "main"         // main | assign | editor | emoji | settings | command
                                       // | result | history | historyPerson | timeline
  property var assignDevice: null      // the unknown device being assigned
  property var draft: null             // editor draft { id, name, emoji, group, notify, devices: [{mac, label}] }
  property string editorError: ""
  property string settingsError: ""
  // House section expanded or not. Lives here, not in MainView, so it
  // survives closing and reopening the panel (not a shell restart).
  property bool houseOpen: false
  // Neighbors section expanded or not. Lives here, not in MainView, for the same
  // reason as houseOpen: it survives closing and reopening the panel.
  property bool neighborsOpen: false
  // Guests section expanded or not. Same reason as houseOpen/neighborsOpen.
  property bool guestsOpen: false
  // ---- history view state. The engine answers a report; the panel keeps only
  // which slice of time is on screen.
  property string historyPeriod: "month"     // day | week | month
  property string historyAnchor: ""          // YYYY-MM-DD inside the period on screen
  property string historyPersonId: ""
  property var historyReport: null
  property bool historyLoading: false
  property string historyError: ""
  property int historyGeneration: 0
  property bool historyPending: false
  // ---- the grid. Its own report, its own process: `timeline` answers no `people`
  // array, so engineCall would take it for a status and blank the panel.
  property string timelinePeriod: "day"     // what the grid on screen covers
  property string timelineAnchor: ""        // YYYY-MM-DD inside it
  property var timelineReport: null
  property bool timelineLoading: false
  property int timelineGeneration: 0
  property bool timelinePending: false
  // The two pickers live here, not in the views: a view is destroyed every time you
  // leave it, and stepping to another day must not forget who you were looking at.
  //
  // `null` means "not touched this time round", and then what the engine saved is what
  // shows. Copying the saved list up front would lose it whenever the clock is opened
  // before the first status reply lands -- the copy would be empty, and closing the
  // picker would write that emptiness over a real selection.
  property var timelinePicked: null
  property var timelineComparePicked: null
  // ---- the calendar. Which screen opened it, so a pick knows where to go back to; ""
  // while it is closed. The day it opens on and the floor it stops dimming at are
  // whichever screen's they are -- the day grid keeps an anchor of its own.
  property string calendarFrom: ""
  readonly property string calendarAnchor: calendarFrom === "timeline" ? timelineAnchor : historyAnchor
  readonly property string calendarEarliest: {
    var report = calendarFrom === "timeline" ? timelineReport : historyReport
    return report && report.earliest ? String(report.earliest) : ""
  }
  readonly property var savedLanes: status && status.settings && status.settings.timelineLanes
                                      ? status.settings.timelineLanes : []
  readonly property var savedCompare: status && status.settings && status.settings.timelineCompare
                                        ? status.settings.timelineCompare : []
  readonly property var timelineLanes: timelinePicked !== null ? timelinePicked : savedLanes
  readonly property var timelineCompare: timelineComparePicked !== null ? timelineComparePicked
                                                                        : savedCompare
  // ---- panel geometry. Pixels, 0 = automatic (the size the panel had before it
  // could be resized). Plain properties, not bindings: the grip assigns to them,
  // and an assignment would destroy a binding for good.
  property int cardWidth: 0
  property int cardHeight: 0
  // Screen-axis offsets in pixels from where the panel would fall on its own,
  // 0 = automatic. Same reason as cardWidth/cardHeight for not being bindings.
  property int panelX: 0
  property int panelY: 0

  readonly property string barPos: bar && bar.position ? bar.position : "top"
  readonly property bool barIsHorizontal: barPos === "top" || barPos === "bottom"
  // The bar-parallel offset travels through the anchor item (BarWidget's
  // anchorProxy): cardOrigin only reads the anchor's position for that axis.
  readonly property int anchorOffsetX: barIsHorizontal ? panelX : 0
  readonly property int anchorOffsetY: barIsHorizontal ? 0 : panelY
  // The perpendicular offset travels through `gap`, the bar-to-card distance,
  // which is all cardOrigin uses on that axis. It only ever grows: the panel
  // moves away from the bar, never under it.
  readonly property int panelGap: Style.gapsOut
                                  + (barPos === "top" ? Math.max(0, panelY)
                                   : barPos === "bottom" ? Math.max(0, -panelY)
                                   : barPos === "left" ? Math.max(0, panelX)
                                   : Math.max(0, -panelX))
  // True while a drag is in flight. A status landing mid-drag (a scan finishes
  // every few seconds) would otherwise snap the panel back to the stored size.
  property bool adjustingPanel: false
  // Command editor. editingCommand is the status entry being edited, or null
  // for a new one. commandGeneration grows every time the editor closes, so a
  // test-command reply that arrives afterwards is dropped.
  property var editingCommand: null
  property string commandError: ""
  property var commandTestResult: null
  property int commandGeneration: 0
  // Guards saveCommand against a double click sending two save-command calls
  // and creating two commands.
  property bool commandSaving: false
  // What the delete dialog deletes: "person" (the editor draft) or "command".
  property string confirmTarget: "person"

  // ---- manual runs (the right-click menu). None of this is stored: closing the
  // panel forgets the result, which is what the user asked for.
  property var runResult: null         // {ok, exit, message, seconds, output, truncated}, or null while it runs
  property string runCommand: ""       // the command's text, shown at the top of the result view
  property string runTarget: ""        // what it ran on: "Ana · Pixel" or "Switch · 00:00:5e:00:53:05"
  property string runError: ""         // the engine's own error, when the command never ran
  property int runGeneration: 0

  readonly property var people: Array.isArray(status.people) ? status.people : []
  readonly property var here: people.filter(function(p) { return p.present })
  readonly property var unknown: Array.isArray(status.unknown) ? status.unknown : []
  readonly property var unknownHere: unknown.filter(function(d) { return d.present })
  readonly property var house: Array.isArray(status.house) ? status.house : []
  readonly property var neighbors: Array.isArray(status.neighbors) ? status.neighbors : []
  readonly property var guests: Array.isArray(status.guests) ? status.guests : []
  readonly property var guestsHere: guests.filter(function(p) { return p.present })
  readonly property var alerts: Array.isArray(status.alerts) ? status.alerts : []
  readonly property var commands: Array.isArray(status.commands) ? status.commands : []
  readonly property bool commandTesting: testProc.running
  // Not `settings`: Panel already has that property (the bar widget's own settings).
  readonly property var engineSettings: status.settings || ({})
  readonly property string engineError: callError !== "" ? callError : (status.error || "")
  readonly property int scanInterval: engineSettings.scanInterval > 0 ? engineSettings.scanInterval : 20
  readonly property bool scanning: scanProc.running
  // What the engine's last status said about the Readily integration. The panel starts
  // with a placeholder status that has no `readily` key at all, so the fallback matters.
  readonly property var readilyState: status.readily
                                      || ({ enabled: false, ok: false, warning: "", count: 0, skipped: 0 })

  // ---- colours
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  // Bar.qml does not expose `accent`; guard the read so it falls back cleanly.
  readonly property color accent: (bar && bar.accent !== undefined) ? bar.accent : Color.accent
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // ---- bar face, read by BarWidget.qml
  readonly property bool warn: alerts.length > 0 || engineError !== ""
  readonly property string barText: Format.barText(here, unknownHere.length, warn, guestsHere)
  readonly property bool barDimmed: !warn && here.length === 0 && guestsHere.length === 0 && unknownHere.length === 0
  readonly property bool barActive: warn || unknownHere.length > 0
  readonly property color barActiveColor: warn ? urgent : accent
  readonly property string barTooltip: Format.barTooltip(here, unknownHere.length, alerts.length, engineError,
                                                         status.lastScan, nowMs, guestsHere)

  readonly property string viewSource: ({ main: "MainView.qml", assign: "AssignView.qml", editor: "PersonEditor.qml",
                                          emoji: "EmojiPicker.qml", settings: "SettingsView.qml",
                                          command: "CommandEditor.qml", result: "ResultView.qml",
                                          history: "HistoryView.qml",
                                          historyPerson: "HistoryPersonView.qml",
                                          timeline: "TimelineView.qml",
                                          calendar: "CalendarView.qml" })[view] || "MainView.qml"

  function pluginPath(relative) {
    var url = String(Qt.resolvedUrl(relative))
    return url.indexOf("file://") === 0 ? decodeURIComponent(url.substring(7)) : url
  }

  // A failed command answers {"error": msg} alone; a status always has `people`
  // and its own `error` is the last scan's (shown through engineError).
  function isFailure(payload) { return !payload || !Array.isArray(payload.people) }

  // ok distinguishes "it worked" (copied) from the failures every other caller
  // reports; called with one argument it keeps painting red, as it always did.
  function showNotice(text, ok) {
    notice = String(text || "")
    noticeOk = ok === true
    noticeTimer.restart()
  }

  Timer { id: noticeTimer; interval: 6000; onTriggered: recognition.notice = "" }
  Timer { interval: 5000; running: true; repeat: true; onTriggered: recognition.nowMs = Date.now() }

  // ---- scanning: its own Process so a slow nmap doesn't block most edits —
  // except forget, accept-gateway and dismiss-alert, which take the engine's
  // own state lock and so still wait behind a scan's probes.
  function runScan(force) {
    if (scanProc.running) return
    scanProc.started = false
    scanProc.command = [pluginPath("bin/recognition"), "scan"].concat(force ? ["--force"] : [])
    scanProc.running = true
  }

  function scanNow() { runScan(true) }

  function applyStatus(text) {
    var payload = null
    try { payload = JSON.parse(String(text || "")) } catch (e) { callError = "The engine didn't return JSON"; return }
    if (recognition.isFailure(payload)) {
      callError = payload && payload.error ? String(payload.error) : "The engine didn't answer"
      return
    }
    callError = ""
    status = payload
    recognition.retryMissingFileViews()
  }

  Process {
    id: scanProc
    // Set true by onStarted; still false in onRunningChanged means the OS
    // never managed to launch bin/recognition at all (finding 2).
    property bool started: false
    onStarted: started = true
    onRunningChanged: {
      if (!running && !started) recognition.callError = "Couldn't run the engine"
    }
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        recognition.lastScanReply = Date.now()
        recognition.applyStatus(text)
        // The reply we just applied was read from disk before this scan
        // started, so it may already be stale (finding 1) — catch up now
        // instead of waiting for the next 20 s tick.
        if (recognition.refreshAfterScan) {
          recognition.refreshAfterScan = false
          recognition.refreshStatus()
        }
      }
    }
    stderr: StdioCollector { waitForEnd: true }
  }

  Timer {
    interval: recognition.scanInterval * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: recognition.runScan(false)
  }

  // ---- engine calls: one in flight, the rest queued. Every successful call
  // answers the full status, so it is applied here; onDone only moves views
  // or shows errors.
  property var engineQueue: []
  property var engineCurrent: null

  function engineCall(args, stdinJson, onDone) {
    // `started` (finding 2): set by engineProc's onStarted once the OS
    // actually launches bin/recognition, so a launch failure — which
    // Quickshell reports only as onRunningChanged(false), with no onStarted
    // and no streamFinished — can still be told apart from a normal reply.
    engineQueue.push({ args: args, stdin: stdinJson, onDone: onDone, started: false })
    pumpEngine()
  }

  function pumpEngine() {
    if (engineCurrent !== null || engineQueue.length === 0) return
    engineCurrent = engineQueue.shift()
    engineProc.command = [pluginPath("bin/recognition")].concat(engineCurrent.args)
    engineProc.running = true
  }

  function finishEngine(text) {
    var call = engineCurrent
    engineCurrent = null
    var payload = null
    try { payload = JSON.parse(String(text || "")) } catch (e) { payload = { error: "The engine didn't return JSON" } }
    if (!recognition.isFailure(payload)) {
      callError = ""
      status = payload
      recognition.retryMissingFileViews()
      // This call's success may have landed while a scan (reading a copy of
      // people.json from before it) is still running; its later reply would
      // otherwise undo this one (finding 1).
      if (scanProc.running) recognition.refreshAfterScan = true
    }
    if (call && call.onDone) call.onDone(payload)
    pumpEngine()
  }

  Process {
    id: engineProc
    stdinEnabled: true
    onStarted: {
      // The engine reads exactly one line and only for the commands that take
      // input, so `undefined` means "write nothing".
      var call = recognition.engineCurrent
      if (call) call.started = true
      if (call && call.stdin !== undefined) write(JSON.stringify(call.stdin) + "\n")
    }
    onRunningChanged: {
      // See engineCall's comment on `started`. Don't key on `!running` alone:
      // in the normal path `running` goes false before streamFinished too.
      if (!running && recognition.engineCurrent !== null && !recognition.engineCurrent.started) {
        recognition.finishEngine("")
      }
    }
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: recognition.finishEngine(text)
    }
    stderr: StdioCollector { waitForEnd: true }
  }

  function refreshStatus() {
    engineCall(["status"], undefined, function(payload) {
      if (recognition.isFailure(payload)) {
        recognition.callError = payload && payload.error ? String(payload.error) : "The engine didn't answer"
      }
    })
  }

  // ---- panel geometry: dragged live, saved on release
  function seedPanelGeometry() {
    if (adjustingPanel) return
    var s = status.settings || ({})
    cardWidth = s.panelWidth > 0 ? s.panelWidth : 0
    cardHeight = s.panelHeight > 0 ? s.panelHeight : 0
    panelX = Number(s.panelX) || 0
    panelY = Number(s.panelY) || 0
  }

  // Live drag: clamp to the engine's range and to what fits on this screen.
  function setCardSize(w, h) {
    var maxW = Math.min(4000, panel.availableCardWidth > 0 ? panel.availableCardWidth : 4000)
    var maxH = Math.min(3000, panel.availableCardHeight > 0 ? panel.availableCardHeight : 3000)
    // The floors follow the theme: 280/240 are the engine's raw-pixel limits,
    // but the panel's contents are laid out in Style.space units and the views
    // clip instead of scrolling sideways, so at a larger scale the smallest
    // usable panel is bigger.
    var minW = Math.max(280, Style.space(280))
    var minH = Math.max(240, Style.space(240))
    cardWidth = Math.round(Math.max(minW, Math.min(maxW, w)))
    cardHeight = Math.round(Math.max(minH, Math.min(maxH, h)))
  }

  // Live drag. The engine's range, what fits on this screen, and the rule that
  // the axis pointing into the bar never goes past 0 — clamped here, when the
  // offset is stored, so a drag towards the bar leaves no dead slack to undo.
  function setPanelOffset(x, y) {
    // Clamped against the screen, NOT against availableCardWidth/Height: those
    // subtract `gap`, which is where the perpendicular offset travels, so
    // clamping against them lowers the ceiling on every mouse move and makes the
    // panel bounce between two positions instead of travelling. cardOrigin does
    // the real clipping against the screen anyway; this only keeps the stored
    // value from growing without bound.
    var maxX = Math.min(4000, panel.screenW > 0 ? panel.screenW : 4000)
    var maxY = Math.min(4000, panel.screenH > 0 ? panel.screenH : 4000)
    var nx = Math.round(Math.max(-maxX, Math.min(maxX, x)))
    var ny = Math.round(Math.max(-maxY, Math.min(maxY, y)))
    if (barPos === "top") ny = Math.max(0, ny)
    else if (barPos === "bottom") ny = Math.min(0, ny)
    else if (barPos === "left") nx = Math.max(0, nx)
    else nx = Math.min(0, nx)
    panelX = nx
    panelY = ny
  }

  // One drag, one write. Called on release, never while dragging. The guard
  // stays up until the engine has answered: between the release and the reply,
  // status.settings still holds the old geometry, and any status landing in
  // that gap (a scan finishing, a debounced refresh) would re-seed the panel
  // back to where it was.
  function savePanelGeometry() {
    var s = status.settings || ({})
    // Nothing is saved before the first real status: until then cardWidth and
    // cardHeight are 0 (automatic) even if people.json holds a size, and saving
    // would wipe it. The panel's placeholder status has no panel keys at all.
    if (s.panelWidth === undefined) {
      adjustingPanel = false
      return
    }
    if (s.panelWidth === cardWidth && s.panelHeight === cardHeight
        && s.panelX === panelX && s.panelY === panelY) {
      adjustingPanel = false
      return
    }
    engineCall(["set-settings"], { panelWidth: cardWidth, panelHeight: cardHeight,
                                   panelX: panelX, panelY: panelY }, function(payload) {
      // Only if nothing is being dragged right now: this reply may belong to a
      // previous drag while a new one is already in flight.
      if (!grip.pressed && !mover.pressed) recognition.adjustingPanel = false
      if (recognition.isFailure(payload)) {
        recognition.showNotice(payload && payload.error ? String(payload.error) : "The engine didn't answer")
        recognition.seedPanelGeometry()   // back to the last geometry the engine has
      }
    })
  }

  // Back to factory: the four keys to 0. The seed that follows the engine's
  // reply is what actually puts the panel back. The escape hatch for a panel
  // dragged somewhere awkward — including one whose drag never got its release
  // (the panel closed mid-drag, the compositor took the pointer), which would
  // otherwise leave the guard up and make this button do nothing on screen.
  function resetPanelGeometry() {
    adjustingPanel = false
    engineCall(["set-settings"], { panelWidth: 0, panelHeight: 0, panelX: 0, panelY: 0 }, function(payload) {
      if (recognition.isFailure(payload))
        recognition.showNotice(payload && payload.error ? String(payload.error) : "The engine didn't answer")
    })
  }

  onStatusChanged: seedPanelGeometry()

  // An action: on error show it; on success run onOk.
  function act(args, stdinJson, onOk) {
    engineCall(args, stdinJson, function(payload) {
      if (recognition.isFailure(payload)) {
        recognition.showNotice(payload && payload.error ? String(payload.error) : "The engine didn't answer")
        return
      }
      if (onOk) onOk(payload)
    })
  }

  // people.json edited by hand, or state.json written by a scan started from
  // another monitor: ask for the status. Our own scan's reply already carries
  // it, so skip the refresh right after one.
  Timer {
    id: statusDebounce
    interval: 400
    onTriggered: {
      if (scanProc.running) { recognition.refreshAfterScan = true; return }
      if (Date.now() - recognition.lastScanReply < 1500) return
      recognition.refreshStatus()
    }
  }

  // A FileView whose file didn't exist yet at load time never fires again on
  // its own once the file appears (e.g. people.json before the first save).
  // Retry any that failed after every status we successfully apply, since
  // that is already the signal "the engine just touched these files".
  function retryMissingFileViews() {
    if (peopleFile.retryPending) { peopleFile.retryPending = false; peopleFile.reload() }
    if (stateFile.retryPending) { stateFile.retryPending = false; stateFile.reload() }
    if (resultsFile.retryPending) { resultsFile.retryPending = false; resultsFile.reload() }
  }

  FileView {
    id: peopleFile
    property bool retryPending: false
    path: (Quickshell.env("XDG_CONFIG_HOME") || (Quickshell.env("HOME") + "/.config")) + "/recognition/people.json"
    watchChanges: true
    printErrors: false
    onFileChanged: statusDebounce.restart()
    onLoadFailed: retryPending = true
  }

  FileView {
    id: stateFile
    property bool retryPending: false
    path: (Quickshell.env("XDG_STATE_HOME") || (Quickshell.env("HOME") + "/.local/state")) + "/recognition/state.json"
    watchChanges: true
    printErrors: false
    onFileChanged: statusDebounce.restart()
    onLoadFailed: retryPending = true
  }

  // commands.json: the runner writes it after a scan has already answered, so
  // unlike statusDebounce this one never skips the refresh after our own scan.
  Timer {
    id: resultsDebounce
    interval: 400
    onTriggered: {
      if (scanProc.running) { recognition.refreshAfterScan = true; return }
      recognition.refreshStatus()
    }
  }

  FileView {
    id: resultsFile
    property bool retryPending: false
    path: (Quickshell.env("XDG_STATE_HOME") || (Quickshell.env("HOME") + "/.local/state")) + "/recognition/commands.json"
    watchChanges: true
    printErrors: false
    onFileChanged: resultsDebounce.restart()
    onLoadFailed: retryPending = true
  }

  // ---- navigation and actions (the `host` API)
  function focusKeys() { keyCatcher.forceActiveFocus() }

  function back() {
    confirm.opened = false
    if (view === "emoji") { view = "editor"; return }
    if (view === "command") {
      closeCommand()
      settingsError = ""
      view = "settings"
      focusKeys()
      return
    }
    if (view === "calendar") {
      view = calendarFrom || "history"
      calendarFrom = ""
      focusKeys()
      return
    }
    if (view === "timeline") {
      timelinePeriod = historyPeriod
      timelineAnchor = historyAnchor
      // Without this the person screen draws the day's report as its own grid for one
      // round trip: a single row where a week belongs, and a sealed day flashing the
      // "details are only kept for N days" line at a period that has plenty.
      timelineReport = null
      view = "historyPerson"
      loadTimeline()
      focusKeys()
      return
    }
    if (view === "historyPerson") {
      historyPersonId = ""
      timelineReport = null
      view = "history"
      loadHistory()
      focusKeys()
      return
    }
    if (view === "result") { closeResult(); return }
    view = "main"
    assignDevice = null
    draft = null
    editorError = ""
    settingsError = ""
    focusKeys()
  }

  // Unlike `back()` — which, from the emoji picker, only steps to the editor
  // one level at a time (Ruling R14; Esc keeps doing that) — closing the
  // panel must always land on `main` regardless of which view was open, or
  // it reopens next time still in the editor with the old draft kept.
  function resetToMain() {
    confirm.opened = false
    menu.close()
    closeCommand()
    runGeneration += 1
    runResult = null
    runError = ""
    runCommand = ""
    runTarget = ""
    historyPersonId = ""
    historyReport = null
    historyError = ""
    timelineReport = null
    timelinePicked = null
    timelineComparePicked = null
    calendarFrom = ""
    view = "main"
    assignDevice = null
    draft = null
    editorError = ""
    settingsError = ""
  }

  // The gear is visible in the result view too, and it is the only exit that does not
  // go through closeResult(): without this the run state survives into another view
  // with no way back to it.
  function openSettings() {
    if (view === "result") closeResult()
    closeCommand()
    settingsError = ""
    view = "settings"
  }

  function todayIso() {
    var now = new Date()
    var month = now.getMonth() + 1
    var day = now.getDate()
    return now.getFullYear() + "-" + (month < 10 ? "0" : "") + month
                            + "-" + (day < 10 ? "0" : "") + day
  }

  function openHistory() {
    if (view === "result") closeResult()
    closeCommand()
    historyPersonId = ""
    historyPeriod = "month"
    historyAnchor = todayIso()
    historyReport = null
    timelinePicked = null
    timelineComparePicked = null
    view = "history"
    loadHistory()
  }

  function openHistoryPerson(personId) {
    historyPersonId = String(personId)
    historyReport = null
    timelineReport = null
    timelinePeriod = historyPeriod
    timelineAnchor = historyAnchor
    view = "historyPerson"
    loadHistory()
    loadTimeline()
  }

  function setHistoryPeriod(period) {
    historyPeriod = String(period)
    historyAnchor = todayIso()
    timelinePeriod = historyPeriod
    timelineAnchor = historyAnchor
    loadHistory()
    if (view === "historyPerson") loadTimeline()
  }

  function stepHistory(anchor) {
    if (!anchor) return
    historyAnchor = String(anchor)
    timelineAnchor = historyAnchor
    timelinePeriod = historyPeriod
    loadHistory()
    if (view === "historyPerson") loadTimeline()
  }

  // The day screen. It keeps its own anchor so stepping through days does not drag the
  // week behind it back on the person screen.
  function openTimelineDay(day) {
    if (!day) return
    timelinePeriod = "day"
    timelineAnchor = String(day)
    timelineReport = null
    view = "timeline"
    loadTimeline()
  }

  function stepTimeline(anchor) {
    if (!anchor) return
    timelineAnchor = String(anchor)
    loadTimeline()
  }

  // ---- the calendar. A view rather than a popup, like the emoji picker: the panel is
  // small and a month of days wants all of it. It remembers which screen opened it,
  // because that is both where a pick goes and where Esc comes back to.
  function openCalendar() {
    if (view === "calendar") return
    calendarFrom = view
    view = "calendar"
    focusKeys()
  }

  // The period is left alone on purpose: the engine snaps a date to the period it is
  // asked about, so the 12th picked from the week ranking is the week of the 12th. The
  // view is restored before stepping, or stepHistory would decide whether to reload the
  // timeline while the calendar is still the screen on show.
  function pickDay(day) {
    if (!day) return
    var from = calendarFrom || "history"
    calendarFrom = ""
    view = from
    if (from === "timeline") stepTimeline(day)
    else stepHistory(day)
    focusKeys()
  }

  // history answers numbers, not a status, so it has its own Process instead of going
  // through engineCall -- which would put the report in `status` and blank the panel.
  //
  // The generation is bumped before anything else, so a reply already on its way is
  // dropped rather than landing under controls that by then describe something else --
  // tapping Week while Day is still loading, or a person's row before the ranking is
  // back. A request that finds the process busy is re-issued when it frees up, so the
  // tap is not simply lost.
  function loadHistory() {
    historyGeneration += 1
    historyLoading = true
    historyError = ""
    if (historyProc.running) { historyPending = true; return }
    historyPending = false
    historyProc.generation = historyGeneration
    historyProc.started = false
    var args = [pluginPath("bin/recognition"), "history", historyPeriod, historyAnchor]
    if (historyPersonId !== "") args.push(historyPersonId)
    historyProc.command = args
    historyProc.running = true
  }

  function finishHistory(text, generation) {
    if (generation !== historyGeneration) return
    historyLoading = false
    var payload = null
    try { payload = JSON.parse(String(text || "")) } catch (e) { payload = null }
    if (!payload) { historyError = "The engine didn't answer"; return }
    if (payload.error) { historyError = String(payload.error); return }
    historyReport = payload
  }

  function loadTimeline() {
    timelineGeneration += 1
    timelineLoading = true
    if (timelineProc.running) { timelinePending = true; return }
    timelinePending = false
    timelineProc.generation = timelineGeneration
    timelineProc.started = false
    timelineProc.command = [pluginPath("bin/recognition"), "timeline",
                            timelinePeriod, timelineAnchor]
    timelineProc.running = true
  }

  // The grid failing is not worth a red banner: the header above it already says
  // whether the engine answered, and an empty grid says the rest.
  function finishTimeline(text, generation) {
    if (generation !== timelineGeneration) return
    timelineLoading = false
    var payload = null
  try { payload = JSON.parse(String(text || "")) } catch (e) { payload = null }
    timelineReport = (payload && !payload.error) ? payload : null
  }

  // A tick redraws now; the engine hears about it when the popup closes. set-settings
  // prunes whenever a history key moves, and walking the month files once per checkbox
  // would be a scan's worth of work for a decision the user has not finished making.
  //
  // And only when it moved: opening a picker and closing it again is not an edit, and
  // set-settings rewrites people.json.
  // Closing the picker is not a pick: it must not pin the selection to whatever the
  // fallback happened to be showing, or a picker opened before the first status reply
  // would freeze an empty list in place of the saved one.
  function pickLanes(values, commit) {
    if (!commit) { timelinePicked = values; return }
    if (!sameKeys(savedLanes, timelineLanes))
      act(["set-settings"], { timelineLanes: timelineLanes })
  }

  function pickCompare(values, commit) {
    if (!commit) { timelineComparePicked = values; return }
    if (!sameKeys(savedCompare, timelineCompare))
      act(["set-settings"], { timelineCompare: timelineCompare })
  }

  function sameKeys(a, b) {
    if (!a || !b || a.length !== b.length) return false
    for (var i = 0; i < a.length; i++)
      if (a[i] !== b[i]) return false
    return true
  }

  function startAssign(device) { assignDevice = device; view = "assign" }

  function assignTo(personId) {
    if (!assignDevice) return
    act(["assign", assignDevice.mac, personId], {}, function() { recognition.back() })
  }

  // The device the engine matched to a person by its network name: assign it without
  // going through the assign view, keeping the old device's label.
  function acceptSuggestion(device) {
    if (!device || !device.suggestion) return
    act(["assign", device.mac, device.suggestion.personId], { label: device.suggestion.label })
  }

  // No label: the engine picks the automatic one; with one: put in House or rename.
  function houseDevice(device, label) { act(["house", device.mac], label === undefined ? {} : { label: label }) }
  function forgetDevice(device) { act(["forget", device.mac], undefined) }
  function unhouseDevice(mac) { act(["unhouse", mac], undefined) }
  function acceptGateway() { act(["accept-gateway"], undefined) }
  function dismissAlert(alert) { act(["dismiss-alert", alert.id], undefined) }

  function startNewPerson(device) {
    draft = { id: "", name: "", emoji: "", group: "home", notify: true,
              devices: device ? [{ mac: device.mac, label: Format.deviceTitle(device), counts: true,
                                   ip: device.ip, present: device.present,
                                   lastSeen: device.lastSeen }] : [] }
    editorError = ""
    assignDevice = null
    view = "editor"
  }

  function startEdit(person) {
    draft = { id: person.id, name: person.name, emoji: person.emoji, group: person.group || "home",
              notify: person.notify !== false,
              // `counts` has to travel: without it, opening a person and saving would clear
              // every flag. `ip`/`present`/`lastSeen` are only for the editor's grey line —
              // save_person rebuilds each device from the three keys it knows.
              devices: person.devices.map(function(d) {
                return { mac: d.mac, label: d.label, counts: d.counts !== false,
                         ip: d.ip, present: d.present, lastSeen: d.lastSeen }
              }) }
    editorError = ""
    view = "editor"
  }

  // Views change the draft through here so it survives the emoji picker.
  function updateDraft(patch) { draft = Object.assign({}, draft, patch) }

  function saveDraft() {
    if (!draft) return
    var fields = { name: draft.name, emoji: draft.emoji, group: draft.group || "home",
                   notify: draft.notify !== false, devices: draft.devices }
    if (draft.id) fields.id = draft.id
    engineCall(["save-person"], fields, function(payload) {
      if (recognition.isFailure(payload)) {
        recognition.editorError = payload && payload.error ? String(payload.error) : "The engine didn't answer"
        return
      }
      recognition.back()
    })
  }

  // Switching the history off stops the recording and keeps what is there, so
  // deleting is its own deliberate act, with its own confirmation.
  function requestDeleteHistory() {
    confirmTarget = "history"
    confirm.message = "Delete all history? Everything recorded so far is lost."
    confirm.selectedIndex = 0
    confirm.opened = true
  }

  function requestDelete() {
    confirmTarget = "person"
    if (!draft || !draft.id) return
    confirm.message = "Delete " + draft.name + "? Its devices go back to \"Unassigned\", and its history is deleted."
    confirm.selectedIndex = 0
    confirm.opened = true
    focusKeys()
  }

  function performDelete() {
    confirm.opened = false
    if (confirmTarget === "history") {
      act(["delete-history"], undefined, function() {
        recognition.showNotice("History deleted", true)
      })
      return
    }
    if (confirmTarget === "command") {
      if (!editingCommand) return
      act(["delete-command", editingCommand.id], undefined, function() { recognition.back() })
      return
    }
    if (!draft || !draft.id) return
    act(["delete-person", draft.id], undefined, function() { recognition.back() })
  }

  function pickEmoji() { view = "emoji" }

  function emojiPicked(emoji) {
    updateDraft({ emoji: emoji })
    view = "editor"
  }

  function saveSettings(newSettings) {
    engineCall(["set-settings"], newSettings, function(payload) {
      if (recognition.isFailure(payload)) {
        recognition.settingsError = payload && payload.error ? String(payload.error) : "The engine didn't answer"
        return
      }
      recognition.back()
    })
  }

  // readily-open answers {"opened": …}, not a status, so nothing applies it: the only
  // thing worth reporting is Readily failing to open the note.
  function openReadilyNote(note) {
    var name = String(note || "")
    if (name === "") return
    engineCall(["readily-open", name], undefined, function(payload) {
      if (payload && payload.opened) return
      recognition.showNotice(payload && payload.error ? String(payload.error) : "The engine didn't answer")
    })
  }

  // ---- commands. Opening the editor drops unsaved Settings edits: the Loader
  // destroys SettingsView (spec §9).
  function newCommand() { openCommand(null) }

  function openCommand(command) {
    editingCommand = command
    commandError = ""
    commandTestResult = null
    view = "command"
  }

  function closeCommand() {
    commandGeneration++
    editingCommand = null
    commandError = ""
    commandTestResult = null
    commandSaving = false
  }

  function saveCommand(fields) {
    if (commandSaving) return
    commandSaving = true
    engineCall(["save-command"], fields, function(payload) {
      recognition.commandSaving = false
      if (recognition.isFailure(payload)) {
        recognition.commandError = payload && payload.error ? String(payload.error) : "The engine didn't answer"
        return
      }
      recognition.back()
    })
  }

  function requestDeleteCommand() {
    if (!editingCommand) return
    confirmTarget = "command"
    confirm.message = "Delete this command?"
    confirm.selectedIndex = 0
    confirm.opened = true
    focusKeys()
  }

  // test-command answers {"test": …}, not a status, so it has its own Process
  // instead of going through engineCall.
  function testCommand(fields) {
    if (testProc.running) return
    commandError = ""
    commandTestResult = null
    testProc.input = fields
    testProc.generation = commandGeneration
    testProc.started = false
    testProc.command = [pluginPath("bin/recognition"), "test-command"]
    testProc.running = true
  }

  // wl-copy without a shell (Runbook's pattern): there is nothing to expand here,
  // and not having a shell is one thing fewer that can go wrong with a hostname
  // somebody else chose.
  function copyText(text, what) {
    var value = String(text || "")
    if (value === "") return
    Quickshell.execDetached(["wl-copy", "--", value])
    showNotice("Copied " + (what ? String(what) : value), true)
  }

  // run-command answers {"run": …}, not a status, so it has its own Process, like
  // test-command. One at a time: a Quickshell Process runs one command, and starting
  // a second one would mean killing the first mid-flight — exactly what we don't want
  // from something the user fired on purpose.
  function runManual(commandId, commandText, target, targetLabel) {
    if (runProc.running) { showNotice("Another command is still running"); return }
    runGeneration += 1
    runResult = null
    runError = ""
    runCommand = String(commandText || "")
    runTarget = String(targetLabel || "")
    view = "result"
    focusKeys()
    runProc.input = target
    runProc.generation = runGeneration
    runProc.started = false
    runProc.command = [pluginPath("bin/recognition"), "run-command", String(commandId)]
    runProc.running = true
  }

  function finishRun(text, generation) {
    if (generation !== runGeneration) return
    var payload = null
    try { payload = JSON.parse(String(text || "")) } catch (e) { payload = null }
    if (payload && payload.run) { runResult = payload.run; return }
    runError = payload && payload.error ? String(payload.error) : "The engine didn't answer"
  }

  // Leaving the result view. The command may still be running; bumping the
  // generation is what keeps its late reply from landing on top of whatever the
  // user is looking at by then.
  function closeResult() {
    runGeneration += 1
    runResult = null
    runError = ""
    runCommand = ""
    runTarget = ""
    view = "main"
    focusKeys()
  }

  // The menu of one device row (Unassigned and House). The people filter means
  // nothing here, so every manual command shows.
  function openDeviceMenu(device, scenePos) {
    if (!device) return
    var name = device.label || Format.deviceTitle(device)
    var items = []
    if (device.mac) items.push({ text: "Copy MAC", enabled: true, kind: "copy",
                                 payload: { text: device.mac } })
    if (device.ip) items.push({ text: "Copy IP", enabled: true, kind: "copy",
                                payload: { text: device.ip } })
    openMenu(name, scenePos, items, Format.manualCommands(commands, ""),
             { mac: device.mac }, name + " · " + device.mac)
  }

  // The menu of one person row (Home, Neighbors, Guests). With more than one device the
  // first menu picks which one the command will run on; with one -- or none -- it opens
  // the command menu directly, because there is nothing to pick.
  function openPersonMenu(person, scenePos) {
    if (!person) return
    menuOrigin = scenePos
    var devices = person.devices || []
    var name = (person.emoji || "") + " " + (person.name || "")
    if (devices.length > 1) {
      var rows = []
      for (var i = 0; i < devices.length; i++)
        rows.push({ text: Format.deviceMenuLine(devices[i], nowMs), enabled: true, kind: "device",
                    payload: { person: person, device: devices[i],
                               title: name + " · " + (devices[i].label || devices[i].mac) } })
      menu.open(scenePos, name, rows)
      focusKeys()
      return
    }
    openPersonDeviceMenu(person, devices.length === 1 ? devices[0] : null, name, scenePos)
  }

  // The command menu for one person and the device they picked (null when they have
  // none). The target carries both, so the command gets the person's variables and the
  // device the user chose instead of the one the engine would have guessed.
  function openPersonDeviceMenu(person, device, title, scenePos) {
    if (!person) return
    var items = []
    var target = { personId: person.id }
    if (device) {
      target.mac = device.mac
      items.push({ text: "Copy MAC", enabled: true, kind: "copy", payload: { text: device.mac } })
      if (device.ip) items.push({ text: "Copy IP", enabled: true, kind: "copy",
                                  payload: { text: device.ip } })
    }
    openMenu(title, scenePos, items, Format.manualCommands(commands, person.id), target,
             (person.name || "") + (device ? " · " + (device.label || device.mac) : ""))
  }

  function openMenu(title, scenePos, items, manual, target, targetLabel) {
    if (manual.length > 0 && items.length > 0) items.push({ text: "", enabled: false, kind: "separator" })
    for (var i = 0; i < manual.length; i++)
      items.push({ text: Format.commandMenuLabel(manual[i]), enabled: true, kind: "run",
                   payload: { id: manual[i].id, command: manual[i].command,
                              target: target, label: targetLabel } })
    if (manual.length === 0) items.push({ text: "No manual commands", enabled: false, kind: "none" })
    menu.open(scenePos, title, items)
    focusKeys()
  }

  function finishTest(text, generation) {
    if (generation !== commandGeneration || view !== "command") return
    var payload = null
    try { payload = JSON.parse(String(text || "")) } catch (e) { payload = null }
    if (payload && payload.test) { commandTestResult = payload.test; return }
    commandError = payload && payload.error ? String(payload.error) : "The engine didn't answer"
  }

  Process {
    id: testProc
    property var input: null
    property int generation: 0
    property bool started: false
    stdinEnabled: true
    onStarted: {
      started = true
      write(JSON.stringify(testProc.input) + "\n")
    }
    onRunningChanged: {
      if (!running && !started) recognition.finishTest("", testProc.generation)
    }
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: recognition.finishTest(text, testProc.generation)
    }
    stderr: StdioCollector { waitForEnd: true }
  }

  Process {
    id: historyProc
    property int generation: 0
    property bool started: false
    onStarted: started = true
    onRunningChanged: {
      if (running) return
      if (!started) recognition.finishHistory("", historyProc.generation)
      if (recognition.historyPending) recognition.loadHistory()
    }
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: recognition.finishHistory(text, historyProc.generation)
    }
    stderr: StdioCollector { waitForEnd: true }
  }

    Process {
      id: timelineProc
      property int generation: 0
      property bool started: false
      onStarted: started = true
      onRunningChanged: {
        if (running) return
        if (!started) recognition.finishTimeline("", timelineProc.generation)
        if (recognition.timelinePending) recognition.loadTimeline()
      }
      stdout: StdioCollector {
        waitForEnd: true
        onStreamFinished: recognition.finishTimeline(text, timelineProc.generation)
      }
      stderr: StdioCollector { waitForEnd: true }
    }

  Process {
    id: runProc
    property var input: null
    property int generation: 0
    property bool started: false
    stdinEnabled: true
    onStarted: {
      started = true
      write(JSON.stringify(runProc.input) + "\n")
    }
    onRunningChanged: {
      if (!running && !started) recognition.finishRun("", runProc.generation)
    }
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: recognition.finishRun(text, runProc.generation)
    }
    stderr: StdioCollector { waitForEnd: true }
  }

  onOpenedChanged: {
    if (opened) {
      nowMs = Date.now()
      refreshStatus()
    } else {
      resetToMain()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: recognition.anchorItem
    owner: recognition.hostWidget || recognition
    bar: recognition.bar
    open: recognition.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(recognition.cardWidth > 0 ? recognition.cardWidth
                                                                     : Style.space(400))
    // With a stored height the panel measures what the user chose, even if the
    // content is shorter (blank space below) or taller (each view scrolls). With
    // 0 it still grows with the content up to the old cap.
    contentHeight: recognition.cardHeight > 0
                   ? panel.cappedContentHeight(recognition.cardHeight)
                   : panel.fittedContentHeight(Math.max(Style.space(240), layout.implicitHeight),
                                               Style.space(560))
    gap: recognition.panelGap

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      // While a text field owns the keyboard, letters and Escape must reach it.
      blocked: !confirm.opened && !menu.opened && viewLoader.item !== null && viewLoader.item.typing === true
      onCloseRequested: {
        if (menu.opened) menu.close()
        else if (confirm.opened) confirm.opened = false
        else if (recognition.view === "main") recognition.close()
        else recognition.back()
      }
      onTabRequested: function(direction) {
        if (menu.opened) return
        if (confirm.opened) confirm.selectedIndex = confirm.selectedIndex === 0 ? 1 : 0
        else recognition.switchPanel(direction)
      }
      onMoveRequested: function(dx, dy) {
        if (menu.opened) { if (dy !== 0) menu.step(dy); return }
        if (confirm.opened && dx !== 0) confirm.selectedIndex = confirm.selectedIndex === 0 ? 1 : 0
      }
      onActivateRequested: {
        if (menu.opened) { menu.activateSelected(); return }
        // Enter only answers the delete dialog; it never triggers an action.
        if (!confirm.opened) return
        if (confirm.selectedIndex === 0) confirm.opened = false
        else recognition.performDelete()
      }

      // Drag the title strip to move the panel. Declared before the layout so it
      // sits underneath it: the header's texts don't accept mouse events and let
      // the press through, while Scan now and Settings, which do accept them and
      // are on top, keep working. Scene coordinates for the same reason as the
      // grip: the card moves while it is being dragged.
      MouseArea {
        id: mover
        width: keyCatcher.width
        height: hero.height
        hoverEnabled: true
        preventStealing: true
        cursorShape: Qt.SizeAllCursor
        acceptedButtons: Qt.LeftButton
        property point dragStart
        property int startX: 0
        property int startY: 0
        onPressed: function(mouse) {
          dragStart = mapToItem(null, mouse.x, mouse.y)
          startX = recognition.panelX
          startY = recognition.panelY
          recognition.adjustingPanel = true
        }
        onPositionChanged: function(mouse) {
          if (!pressed) return
          var point = mapToItem(null, mouse.x, mouse.y)
          recognition.setPanelOffset(startX + (point.x - dragStart.x),
                                     startY + (point.y - dragStart.y))
        }
        onReleased: recognition.savePanelGeometry()
        // Losing the grab (the panel closing mid-drag) emits canceled(), not
        // released(): without this the drag is never saved and the guard stays up.
        onCanceled: recognition.savePanelGeometry()
      }

      ColumnLayout {
        id: layout
        anchors.fill: parent
        spacing: Style.space(8)

        PanelHero {
          id: hero
          Layout.fillWidth: true
          title: "Recognition"
          meta: recognition.scanning ? "scanning…"
            : (recognition.status.lastScan ? "scanned " + Format.ago(recognition.status.lastScan, recognition.nowMs)
                                           : "not scanned yet")
            + (recognition.status.subnet ? " · " + recognition.status.subnet : "")
          foreground: recognition.foreground
          fontFamily: recognition.fontFamily

          trailingControl: Component {
            Row {
              spacing: Style.space(6)
              PanelActionButton {
                iconText: "\u{F0450}"   // nf-md-refresh
                tooltipText: "Scan now"
                enabled: !recognition.scanning
                foreground: recognition.foreground
                hoverColor: recognition.accent
                onClicked: recognition.scanNow()
              }
              PanelActionButton {
                iconText: "\u{F02DA}"   // nf-md-history
                tooltipText: "History"
                foreground: recognition.foreground
                hoverColor: recognition.accent
                onClicked: recognition.view === "history" || recognition.view === "historyPerson"
                             || recognition.view === "timeline" || recognition.view === "calendar"
                             ? recognition.back() : recognition.openHistory()
              }
              PanelActionButton {
                iconText: "\u{F0493}"   // nf-md-cog
                tooltipText: "Settings"
                foreground: recognition.foreground
                hoverColor: recognition.accent
                onClicked: recognition.view === "settings" ? recognition.back() : recognition.openSettings()
              }
            }
          }
        }

        Text {
          Layout.fillWidth: true
          visible: recognition.engineError !== ""
          text: recognition.engineError
          textFormat: Text.PlainText
          wrapMode: Text.Wrap
          color: recognition.urgent
          font.family: recognition.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        Text {
          Layout.fillWidth: true
          visible: recognition.notice !== ""
          text: recognition.notice
          textFormat: Text.PlainText
          wrapMode: Text.Wrap
          color: recognition.noticeOk ? recognition.foreground : recognition.urgent
          font.family: recognition.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        Loader {
          id: viewLoader
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.preferredHeight: item ? item.implicitHeight : 0
          source: recognition.viewSource
          onLoaded: item.host = recognition
        }
      }

      ConfirmDialog {
        id: confirm
        anchors.fill: parent
        z: 10
        cancelText: "Cancel"
        confirmText: "Delete"
        background: Color.popups.background
        foreground: recognition.foreground
        selectedText: recognition.accent
        fontFamily: recognition.fontFamily
        onCanceled: confirm.opened = false
        onConfirmed: recognition.performDelete()
      }

      // Bottom-right grip: drag to resize. It lives in the card's own padding
      // band (negative margins push it past the content edge) so it never
      // overlaps a content button, and above the confirm dialog (z) so it always
      // works. Copied from Runbook's Panel.qml, including the scene coordinates:
      // the card moves while it grows, so measuring against the grip itself
      // feeds the delta back into the next frame.
      MouseArea {
        id: grip
        width: panel.padding + Style.space(4)
        height: panel.padding + Style.space(4)
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: -(panel.padding + 2)
        anchors.bottomMargin: -(panel.padding + 2)
        z: 20
        hoverEnabled: true
        preventStealing: true
        cursorShape: Qt.SizeFDiagCursor
        acceptedButtons: Qt.LeftButton
        property point dragStart
        property int startWidth: 0
        property int startHeight: 0
        onPressed: function(mouse) {
          dragStart = mapToItem(null, mouse.x, mouse.y)
          // The panel's real size, not cardWidth/cardHeight: those are 0 until
          // someone drags for the first time, and the drag has to start from
          // what is on screen.
          startWidth = panel.contentWidth
          startHeight = panel.contentHeight
          recognition.adjustingPanel = true
        }
        onPositionChanged: function(mouse) {
          if (!pressed) return
          var point = mapToItem(null, mouse.x, mouse.y)
          recognition.setCardSize(startWidth + (point.x - dragStart.x),
                                  startHeight + (point.y - dragStart.y))
        }
        onReleased: recognition.savePanelGeometry()
        // Losing the grab (the panel closing mid-drag) emits canceled(), not
        // released(): without this the drag is never saved and the guard stays up.
        onCanceled: recognition.savePanelGeometry()

        Text {
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          text: "◢"
          color: grip.containsMouse || grip.pressed ? recognition.accent : recognition.dim
          font.pixelSize: Style.font.caption
        }
      }

      // Above the delete dialog (10) and the resize grip (20): whatever is open,
      // the menu is what the next click belongs to.
      ContextMenu {
        id: menu
        anchors.fill: parent
        z: 30
        background: Color.popups.background
        foreground: recognition.foreground
        dim: recognition.dim
        accent: recognition.accent
        fontFamily: recognition.fontFamily
        onActivated: function(item) {
          if (item.kind === "copy") recognition.copyText(item.payload.text)
          else if (item.kind === "device")
            recognition.openPersonDeviceMenu(item.payload.person, item.payload.device,
                                             item.payload.title, recognition.menuOrigin)
          else if (item.kind === "run") recognition.runManual(item.payload.id, item.payload.command,
                                                              item.payload.target, item.payload.label)
        }
      }
    }
  }
}
