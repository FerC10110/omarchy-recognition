import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Format.js" as Format

// Add or edit a command: the line sh -c runs, the events it runs on and, for
// arrivals and departures, whose. Validation lives in the engine; its message
// shows under the form. Test runs the line now with example data.
Item {
  id: view
  property var host: null
  property var events: []            // marked events; the engine stores them in its own order
  property bool everyone: true       // people === null
  property var people: []            // picked person ids when not everyone
  readonly property var editing: host ? host.editingCommand : null
  // A Readily command is read-only here: it lives in a note, and Obsidian is where it
  // gets edited. Everything this mode changes hangs off this one property.
  readonly property bool readOnly: Format.isReadily(editing)
  readonly property bool typing: commandField.activeFocus
  // The six events that happen on their own and can be filtered by person.
  readonly property bool picksAutomatic: events.indexOf("arrive") >= 0 || events.indexOf("leave") >= 0
                                      || events.indexOf("neighbor-arrive") >= 0
                                      || events.indexOf("neighbor-leave") >= 0
                                      || events.indexOf("guest-arrive") >= 0
                                      || events.indexOf("guest-leave") >= 0
  // A manual command is filtered by person too: it only shows in the menu of the
  // people it is for.
  readonly property bool picksPeople: !readOnly && (picksAutomatic || events.indexOf("manual") >= 0)
  // The people picked, in the order the list shows them. Format reads each
  // one's group to tell which marked events they can never set off.
  readonly property var pickedPeople: host && !everyone
                                      ? host.people.concat(host.neighbors).concat(host.guests)
                                            .filter(function(p) { return view.people.indexOf(p.id) >= 0 })
                                      : []
  readonly property color foreground: host ? host.foreground : Color.foreground
  readonly property color dim: host ? host.dim : Color.foreground
  readonly property color urgent: host ? host.urgent : Color.urgent
  readonly property string fontFamily: host ? host.fontFamily : Style.font.family

  readonly property var eventSwitches: [
    { key: "arrive", label: "Arrive", description: "Someone arrives home" },
    { key: "leave", label: "Leave", description: "Someone leaves" },
    { key: "neighbor-arrive", label: "Neighbor arrives", description: "Someone from Neighbors joins the Wi-Fi" },
    { key: "neighbor-leave", label: "Neighbor leaves", description: "Someone from Neighbors leaves the Wi-Fi" },
    { key: "guest-arrive", label: "Guest arrives", description: "Someone from Guests connects" },
    { key: "guest-leave", label: "Guest leaves", description: "Someone from Guests disconnects" },
    { key: "home-occupied", label: "Home occupied", description: "The first person arrives" },
    { key: "home-empty", label: "Home empty", description: "The last person leaves" },
    { key: "unknown", label: "Unknown device", description: "An unassigned device joins" },
    { key: "alert", label: "Alert", description: "Router MAC change or IP conflict" },
    { key: "manual", label: "Manual", description: "Run it yourself from the right-click menu" }
  ]

  implicitHeight: column.implicitHeight

  // Seed here, not in Component.onCompleted: Panel sets `host` in
  // Loader.onLoaded, after this Item is complete (see PersonEditor.qml).
  onHostChanged: {
    if (!host) return
    var c = host.editingCommand
    commandField.text = c ? c.command : ""
    events = c ? c.events.slice() : []
    everyone = !c || c.people === null
    people = c && c.people !== null ? c.people.slice() : []
    if (!readOnly) Qt.callLater(function() { commandField.forceActiveFocus() })
  }

  function toggled(list, value) {
    var next = list.slice()
    var at = next.indexOf(value)
    if (at >= 0) next.splice(at, 1)
    else next.push(value)
    return next
  }

  // The first marked event in list order, or arrive when none is marked.
  function firstEvent() {
    for (var i = 0; i < eventSwitches.length; i++)
      if (events.indexOf(eventSwitches[i].key) >= 0) return eventSwitches[i].key
    return "arrive"
  }

  function save() {
    if (readOnly) return
    var fields = { command: commandField.text, events: events, people: everyone ? null : people }
    if (editing) fields.id = editing.id
    host.saveCommand(fields)
  }

  function runTest() {
    // A Readily command is named by its id: the engine resolves the text from the note,
    // so Test always runs what the note says now.
    if (readOnly) { host.testCommand({ readilyId: editing.id }); return }
    host.testCommand({ command: commandField.text, event: firstEvent(), people: everyone ? null : people })
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
          text: view.readOnly ? "Command from Readily"
                              : (view.editing ? "Edit command" : "New command")
          foreground: view.foreground
          fontFamily: view.fontFamily
        }
      }

      Text {
        text: "Command"
        textFormat: Text.PlainText
        color: view.foreground
        font.family: view.fontFamily
        font.pixelSize: Style.font.body
      }
      TextField {
        id: commandField
        visible: !view.readOnly
        width: column.width
        placeholderText: "curl -s -d \"$RECOGNITION_MESSAGE\" ntfy.sh/your-topic"
        foreground: view.foreground
        font.family: view.fontFamily
        // Not maximumLength: it counts UTF-16 units, the engine counts characters.
        onTextEdited: {
          var fix = Format.limitEdit(text, 1000, cursorPosition)
          if (fix.text !== text) { text = fix.text; cursorPosition = fix.at }
        }
        Keys.onEscapePressed: function(event) { view.host.back(); event.accepted = true }
        Keys.onReturnPressed: function(event) { view.save(); event.accepted = true }
      }
      Rectangle {
        visible: view.readOnly
        width: column.width
        height: Math.max(Style.space(60), Math.min(Style.space(200),
                                                   readilyText.implicitHeight + Style.space(16)))
        color: Util.alpha(view.foreground, 0.06)
        radius: Style.cornerRadius

        Flickable {
          id: readilyFlick
          anchors.fill: parent
          anchors.margins: Style.space(8)
          clip: true
          contentWidth: width
          contentHeight: readilyText.implicitHeight
          boundsBehavior: Flickable.StopAtBounds
          interactive: contentHeight > height

          TextEdit {
            id: readilyText
            width: readilyFlick.width
            readOnly: true
            selectByMouse: true
            textFormat: TextEdit.PlainText
            wrapMode: TextEdit.WrapAtWordBoundaryOrAnywhere
            text: view.editing ? String(view.editing.command || "") : ""
            color: view.foreground
            font.family: view.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
        }
      }
      Text {
        width: column.width
        text: "Runs with sh -c. Variables: $RECOGNITION_MESSAGE, $RECOGNITION_PERSON_NAME, $RECOGNITION_HOME … (see README)."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: view.dim
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      PanelSectionHeader {
        text: "Events"
        foreground: view.foreground
        fontFamily: view.fontFamily
      }
      Repeater {
        model: view.readOnly ? [] : view.eventSwitches
        delegate: Toggle {
          required property var modelData
          width: column.width
          label: modelData.label
          description: modelData.description
          checked: view.events.indexOf(modelData.key) >= 0
          foreground: view.foreground
          accent: view.host ? view.host.accent : Color.accent
          fontFamily: view.fontFamily
          onClicked: view.events = view.toggled(view.events, modelData.key)
        }
      }
      Text {
        visible: view.readOnly
        width: column.width
        text: "Note: " + Format.readilyNote(view.editing)
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: view.foreground
        font.family: view.fontFamily
        font.pixelSize: Style.font.body
      }
      Text {
        visible: view.readOnly
        width: column.width
        text: "Events: " + Format.commandEvents(view.events)
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: view.foreground
        font.family: view.fontFamily
        font.pixelSize: Style.font.body
      }
      Text {
        visible: view.readOnly
        width: column.width
        text: "Set by the #recognition tags in Obsidian. Runs for everyone."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: view.dim
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      PanelSectionHeader {
        visible: view.picksPeople
        text: "People"
        foreground: view.foreground
        fontFamily: view.fontFamily
      }
      Toggle {
        visible: view.picksPeople
        width: column.width
        label: "Everyone"
        description: "Anyone at home, nearby, or visiting"
        checked: view.everyone
        foreground: view.foreground
        accent: view.host ? view.host.accent : Color.accent
        fontFamily: view.fontFamily
        onClicked: {
          view.everyone = !view.everyone
          if (!view.everyone) view.people = []
        }
      }
      Repeater {
        model: view.picksPeople && !view.everyone && view.host ? view.host.people.concat(view.host.neighbors).concat(view.host.guests) : []
        delegate: Toggle {
          required property var modelData
          width: column.width
          label: modelData.emoji + " " + modelData.name
          checked: view.people.indexOf(modelData.id) >= 0
          foreground: view.foreground
          accent: view.host ? view.host.accent : Color.accent
          fontFamily: view.fontFamily
          onClicked: view.people = view.toggled(view.people, modelData.id)
        }
      }
      Text {
        visible: view.picksPeople && !view.everyone && view.people.length === 0
        width: column.width
        text: view.picksAutomatic ? "Runs for no one on arrival or departure."
                                  : "Runs for no one in the right-click menu."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: view.urgent
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }
      Repeater {
        model: view.picksPeople && !view.everyone ? Format.deadEventNotes(view.events, view.pickedPeople) : []
        delegate: Text {
          required property var modelData
          width: column.width
          text: modelData
          textFormat: Text.PlainText
          wrapMode: Text.Wrap
          color: view.urgent
          font.family: view.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
      }

      RowLayout {
        width: column.width
        spacing: Style.space(8)
        Button {
          text: "Test"
          tooltipText: "Run it now with example data"
          bordered: true
          enabled: view.host !== null && !view.host.commandTesting
          foreground: view.foreground
          fontFamily: view.fontFamily
          onClicked: view.runTest()
        }
        Text {
          Layout.fillWidth: true
          text: !view.host ? ""
                : view.host.commandTesting ? "running…"
                : Format.testResult(view.host.commandTestResult)
          textFormat: Text.PlainText
          wrapMode: Text.Wrap
          color: view.host && !view.host.commandTesting && view.host.commandTestResult
                 && !view.host.commandTestResult.ok ? view.urgent : view.dim
          font.family: view.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
      }

      Text {
        visible: view.host !== null && view.host.commandError !== ""
        width: column.width
        text: view.host ? view.host.commandError : ""
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: view.urgent
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      RowLayout {
        width: column.width
        spacing: Style.space(6)
        Button {
          visible: view.editing !== null && !view.readOnly
          text: "Delete"
          bordered: true
          foreground: view.urgent
          fontFamily: view.fontFamily
          onClicked: view.host.requestDeleteCommand()
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
          visible: !view.readOnly
          text: "Save"
          bordered: true
          foreground: view.host ? view.host.accent : Color.accent
          fontFamily: view.fontFamily
          onClicked: view.save()
        }
        Button {
          visible: view.readOnly
          text: "Open in Obsidian"
          bordered: true
          foreground: view.host ? view.host.accent : Color.accent
          fontFamily: view.fontFamily
          onClicked: view.host.openReadilyNote(view.editing ? view.editing.note : "")
        }
      }
    }
  }
}
