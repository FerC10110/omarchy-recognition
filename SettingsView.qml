import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Format.js" as Format

// Scan interval, grace period, subnet and notification switches. Below Save,
// the commands, which save on their own from the command editor.
Item {
  id: view
  property var host: null
  property int interval: 20
  property int graceMinutes: 5
  property bool guestsOccupy: true
  property bool readilyEnabled: false
  property bool historyEnabled: false
  property string historyDevices: "none"
  property int historyDays: 30
  property var notify: ({ arrive: true, leave: true, neighbor: true, guest: true, unknown: true, security: true, home: false })
  // Set the first time the user actually changes something, so a settings
  // reply that lands after the view has already opened (e.g. the panel
  // opened and the cog was clicked before refreshStatus() answered) can
  // still re-seed the form — but never clobbers an edit in progress.
  property bool touched: false
  readonly property bool typing: subnetField.activeFocus || intervalField.field.activeFocus
                                || graceField.field.activeFocus || daysField.field.activeFocus
  readonly property color foreground: host ? host.foreground : Color.foreground
  readonly property string fontFamily: host ? host.fontFamily : Style.font.family
  // The engine hands over one flat list: the plugin's own commands first, the ones read
  // from Obsidian appended. Here they are two sections, so the origin is not something
  // the reader has to work out from a row.
  readonly property var myCommands: Format.pluginCommands(host ? host.commands : [])
  readonly property var noteCommands: Format.readilyCommands(host ? host.commands : [])

  readonly property var switches: [
    { key: "arrive", label: "Arrivals", description: "Notify when someone arrives home" },
    { key: "leave", label: "Departures", description: "Notify when someone leaves" },
    { key: "neighbor", label: "Neighbors", description: "Notify when a neighbor joins or leaves the Wi-Fi" },
    { key: "guest", label: "Guests", description: "Notify when a guest arrives or leaves" },
    { key: "unknown", label: "New devices", description: "Notify when something unassigned connects" },
    { key: "security", label: "Network alerts", description: "Notify if the router changes its MAC or there's an IP conflict" },
    { key: "home", label: "Home", description: "Notify when the first person arrives or the last one leaves" }
  ]

  implicitHeight: column.implicitHeight

  function seedFromHost() {
    if (!host) return
    var s = host.engineSettings
    interval = s.scanInterval || 20
    graceMinutes = Math.max(1, Math.round((s.gracePeriod || 300) / 60))
    guestsOccupy = s.guestsOccupyHome !== false
    readilyEnabled = s.readily === true
    historyEnabled = s.history === true
    // The boolean branch is for the panel still running against an older people.json
    // between updating the plugin and restarting the shell.
    historyDevices = typeof s.historyDevices === "string" ? s.historyDevices
                   : (s.historyDevices === true ? "owned" : "none")
    historyDays = s.historyDays || 30
    notify = Object.assign({}, s.notify || {})
    subnetField.text = s.subnet || ""
  }

  onHostChanged: seedFromHost()

  // Panel starts with its own placeholder settings and fills in the real
  // ones asynchronously; if this view opened before that reply landed, its
  // first seed was the placeholder. Re-seed whenever the real settings
  // change underneath it, as long as the user hasn't started editing.
  Connections {
    target: view.host
    function onEngineSettingsChanged() {
      if (!view.touched) view.seedFromHost()
    }
  }

  function save() {
    // NumberField/SpinBox only commits typed-but-not-yet-submitted text on
    // Enter or focus loss, and the kit Button is `focusable: false` so
    // clicking "Save" does not itself take focus away. Move focus away
    // first so a pending edit commits (synchronously, via the field's own
    // focus-loss handling) and `interval`/`graceMinutes` are already
    // up to date by the time they're read below.
    if (host) host.focusKeys()
    host.saveSettings({ scanInterval: interval, gracePeriod: graceMinutes * 60,
                        subnet: subnetField.text.trim(), guestsOccupyHome: guestsOccupy,
                        readily: readilyEnabled,
                        history: historyEnabled, historyDays: historyDays,
                        historyDevices: historyDevices,
                        notify: notify })
  }

  Flickable {
    id: flick
    anchors.fill: parent
    clip: true
    contentWidth: width
    contentHeight: column.implicitHeight
    boundsBehavior: Flickable.StopAtBounds
    interactive: contentHeight > height

    Column {
      id: column
      width: flick.width
      spacing: Style.space(8)

      RowLayout {
        width: column.width
        PanelActionButton {
          iconText: "\u{F004D}"   // nf-md-arrow_left
          tooltipText: "Back without saving"
          foreground: view.foreground
          hoverColor: view.host ? view.host.accent : Color.accent
          onClicked: view.host.back()
        }
        PanelSectionHeader {
          Layout.fillWidth: true
          text: "Settings"
          foreground: view.foreground
          fontFamily: view.fontFamily
        }
      }

      NumberField {
        id: intervalField
        label: "Scan every (seconds)"
        value: view.interval
        from: 10
        to: 300
        stepSize: 5
        foreground: view.foreground
        fontFamily: view.fontFamily
        onModified: function(value) { view.interval = value; view.touched = true }
        Keys.onEscapePressed: function(event) { view.host.back(); event.accepted = true }
      }

      NumberField {
        id: graceField
        label: "Consider gone after (minutes unseen)"
        value: view.graceMinutes
        from: 1
        to: 60
        foreground: view.foreground
        fontFamily: view.fontFamily
        onModified: function(value) { view.graceMinutes = value; view.touched = true }
        Keys.onEscapePressed: function(event) { view.host.back(); event.accepted = true }
      }

      Text {
        text: "Subnet"
        textFormat: Text.PlainText
        color: view.foreground
        font.family: view.fontFamily
        font.pixelSize: Style.font.body
      }
      TextField {
        id: subnetField
        width: column.width
        placeholderText: "automatic" + (view.host && view.host.status.subnet ? " (" + view.host.status.subnet + ")" : "")
        foreground: view.foreground
        font.family: view.fontFamily
        onTextEdited: view.touched = true
        Keys.onEscapePressed: function(event) { view.host.back(); event.accepted = true }
        Keys.onReturnPressed: function(event) { view.save(); event.accepted = true }
      }

      Toggle {
        width: column.width
        label: "Guests keep the house occupied"
        description: "A guest on the Wi-Fi counts as someone in the house: no home-empty while they're connected"
        checked: view.guestsOccupy
        foreground: view.foreground
        accent: view.host ? view.host.accent : Color.accent
        fontFamily: view.fontFamily
        onClicked: {
          view.guestsOccupy = !view.guestsOccupy
          view.touched = true
        }
      }

      Toggle {
        width: column.width
        label: "Read commands from Readily"
        description: "Run the commands you tag #recognition in your Obsidian notes"
        checked: view.readilyEnabled
        foreground: view.foreground
        accent: view.host ? view.host.accent : Color.accent
        fontFamily: view.fontFamily
        onClicked: {
          view.readilyEnabled = !view.readilyEnabled
          view.touched = true
        }
      }

      // What the last read found, or why it found nothing. Empty (and hidden) with the
      // switch off, so turning it on and saving is what makes this line appear.
      Text {
        width: column.width
        visible: text !== ""
        text: Format.readilyStatus(view.host ? view.host.readilyState : null)
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: !view.host ? view.foreground
             : (view.host.readilyState.ok ? view.host.dim : view.host.urgent)
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      PanelSectionHeader {
        text: "History"
        foreground: view.foreground
        fontFamily: view.fontFamily
      }

      Toggle {
        width: column.width
        label: "Keep a history"
        description: "Record how long each person is home, and show it in a dashboard"
        checked: view.historyEnabled
        foreground: view.foreground
        accent: view.host ? view.host.accent : Color.accent
        fontFamily: view.fontFamily
        onClicked: {
          view.historyEnabled = !view.historyEnabled
          view.touched = true
        }
      }

      NumberField {
        id: daysField
        // The engine prunes on its own, switch or no switch: the retention is a promise
        // about what is on disk, not about what is being recorded.
        enabled: view.historyEnabled
        opacity: view.historyEnabled ? 1 : 0.5
        label: "Keep details for (days)"
        value: view.historyDays
        from: 1
        to: 365
        stepSize: 1
        foreground: view.foreground
        fontFamily: view.fontFamily
        onModified: function(value) { view.historyDays = value; view.touched = true }
        Keys.onEscapePressed: function(event) { view.host.back(); event.accepted = true }
      }

      Dropdown {
        width: column.width
        enabled: view.historyEnabled
        opacity: view.historyEnabled ? 1 : 0.5
        label: "Track devices"
        foreground: view.foreground
        accent: view.host ? view.host.accent : Color.accent
        fontFamily: view.fontFamily
        options: [{ value: "none", label: "No" },
                  { value: "owned", label: "The ones I've assigned" },
                  { value: "all", label: "Everything on the network" }]
        value: view.historyDevices
        onChanged: function(value) { view.historyDevices = value; view.touched = true }
      }

      Text {
        width: column.width
        text: "\"Everything\" also records the devices nobody has claimed, so a day can "
              + "show what was on the network at a given hour. It writes more."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Qt.rgba(view.foreground.r, view.foreground.g, view.foreground.b, 0.6)
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Button {
        text: "Delete all history"
        bordered: true
        foreground: view.host ? view.host.urgent : Color.urgent
        fontFamily: view.fontFamily
        onClicked: view.host.requestDeleteHistory()
      }

      PanelSectionHeader {
        text: "Notifications"
        foreground: view.foreground
        fontFamily: view.fontFamily
      }
      Repeater {
        model: view.switches
        delegate: Toggle {
          required property var modelData
          width: column.width
          label: modelData.label
          description: modelData.description
          checked: view.notify[modelData.key] !== false
          foreground: view.foreground
          accent: view.host ? view.host.accent : Color.accent
          fontFamily: view.fontFamily
          onClicked: {
            var next = Object.assign({}, view.notify)
            next[modelData.key] = !checked
            view.notify = next
            view.touched = true
          }
        }
      }

      Text {
        visible: view.host !== null && view.host.settingsError !== ""
        width: column.width
        text: view.host ? view.host.settingsError : ""
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: view.host ? view.host.urgent : Color.urgent
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      RowLayout {
        width: column.width
        spacing: Style.space(6)
        Button {
          text: "Reset panel"
          tooltipText: "Back to the panel's original size and position"
          bordered: true
          foreground: view.foreground
          fontFamily: view.fontFamily
          onClicked: view.host.resetPanelGeometry()
        }
        Item { Layout.fillWidth: true }
        Button {
          text: "Cancel"
          bordered: true
          foreground: view.foreground
          fontFamily: view.fontFamily
          onClicked: view.host.back()
        }
        Button {
          text: "Save"
          bordered: true
          foreground: view.host ? view.host.accent : Color.accent
          fontFamily: view.fontFamily
          onClicked: view.save()
        }
      }

      RowLayout {
        width: column.width
        PanelSectionHeader {
          Layout.fillWidth: true
          text: "Commands (" + view.myCommands.length + ")"
          foreground: view.foreground
          fontFamily: view.fontFamily
        }
        Button {
          text: "Add"
          tooltipText: "Run a command when something happens"
          bordered: true
          foreground: view.host ? view.host.accent : Color.accent
          fontFamily: view.fontFamily
          onClicked: view.host.newCommand()
        }
      }

      Text {
        visible: view.host !== null && view.myCommands.length === 0
        width: column.width
        text: "No commands yet."
        textFormat: Text.PlainText
        color: view.host ? view.host.dim : view.foreground
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Repeater {
        model: view.myCommands
        delegate: CommandRow {
          required property var modelData
          width: column.width
          command: modelData
          host: view.host
          onActivated: view.host.openCommand(modelData)
        }
      }

      // Only when there is something to list. With the switch off, a failed read or a
      // vault with no #recognition items, the line under the Readily switch already
      // says so, and an empty section here would say it again and worse.
      PanelSectionHeader {
        visible: view.noteCommands.length > 0
        text: "From Obsidian (" + view.noteCommands.length + ")"
        foreground: view.foreground
        fontFamily: view.fontFamily
      }

      Repeater {
        model: view.noteCommands
        delegate: CommandRow {
          required property var modelData
          width: column.width
          command: modelData
          host: view.host
          onActivated: view.host.openCommand(modelData)
        }
      }
    }
  }
}
