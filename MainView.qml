import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Format.js" as Format

// Main view: alerts, who is home, unassigned devices, everyone, House.
Item {
  id: view
  property var host: null
  property string query: ""
  // Rename in the House section: at most one row at a time, by MAC. The text
  // lives here because a status refresh recreates the rows.
  property string renamingMac: ""
  property string renameText: ""
  readonly property bool renaming: renamingMac !== "" && host !== null && host.houseOpen
                                   && host.house.some(function(d) { return d.mac === view.renamingMac })
  readonly property bool typing: search.activeFocus || renaming
  readonly property var everyone: host ? host.people.filter(function(p) { return Format.matches(p.name, view.query) }) : []
  readonly property color foreground: host ? host.foreground : Color.foreground
  readonly property string fontFamily: host ? host.fontFamily : Style.font.family

  function startRename(device) { renameText = device.label; renamingMac = device.mac }
  function cancelRename() {
    renamingMac = ""
    renameText = ""
    if (host) host.focusKeys()
  }
  function commitRename() {
    var mac = renamingMac, label = renameText
    cancelRename()
    if (mac !== "" && host) host.houseDevice({ mac: mac }, label)
  }

  // Opening the context menu cancels an inline rename, the same way clicking the
  // search field or a section header does. The rename field loses the keyboard
  // either way, and leaving renamingMac set keeps `typing` — and with it the
  // panel's whole key catcher — blocked long after the menu is gone.
  function menuForPerson(person, scenePos) {
    if (view.renamingMac !== "") view.cancelRename()
    view.host.openPersonMenu(person, scenePos)
  }

  function menuForDevice(device, scenePos) {
    if (view.renamingMac !== "") view.cancelRename()
    view.host.openDeviceMenu(device, scenePos)
  }

  // A device removed from House from outside this panel (another instance,
  // a hand edit) drops `renaming` without touching renamingMac/renameText;
  // clear the stale edit so the MAC doesn't reopen in edit mode with old
  // text if it re-enters House.
  onRenamingChanged: if (!renaming && renamingMac !== "") cancelRename()

  // Closing the panel drops a rename in progress.
  Connections {
    target: view.host
    function onOpenedChanged() { if (view.host && !view.host.opened) { view.renamingMac = ""; view.renameText = "" } }
  }

  implicitHeight: column.implicitHeight

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
      spacing: Style.space(6)

      PanelSectionHeader {
        visible: view.host !== null && view.host.alerts.length > 0
        text: "Alerts"
        foreground: view.host ? view.host.urgent : Color.urgent
        fontFamily: view.fontFamily
      }
      Repeater {
        model: view.host ? view.host.alerts : []
        delegate: AlertRow { width: column.width; alert: modelData; host: view.host }
      }

      PanelSectionHeader {
        text: "Home (" + (view.host ? view.host.here.length : 0) + ")"
        foreground: view.foreground
        fontFamily: view.fontFamily
      }
      Text {
        visible: view.host !== null && view.host.here.length === 0
        text: "Nobody home"
        textFormat: Text.PlainText
        color: view.host ? view.host.dim : view.foreground
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }
      Repeater {
        model: view.host ? view.host.here : []
        delegate: PersonRow {
          width: column.width
          person: modelData
          host: view.host
          onActivated: view.host.startEdit(modelData)
          onContextRequested: function(scenePos) { view.menuForPerson(modelData, scenePos) }
        }
      }

      PanelSectionHeader {
        text: "Unassigned (" + (view.host ? view.host.unknown.length : 0) + ")"
        foreground: view.foreground
        fontFamily: view.fontFamily
      }
      Text {
        visible: view.host !== null && view.host.unknown.length === 0
        text: "Nothing unassigned in the last 24 h"
        textFormat: Text.PlainText
        color: view.host ? view.host.dim : view.foreground
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }
      Repeater {
        model: view.host ? view.host.unknown : []
        delegate: DeviceRow {
          width: column.width
          device: modelData
          host: view.host
          suggestionLabel: modelData.suggestion ? modelData.suggestion.emoji + " " + modelData.suggestion.name + "?" : ""
          actions: (modelData.suggestion ? ["suggest"] : []).concat(
                     modelData.present ? ["assign", "house"] : ["assign", "house", "forget"])
          onAction: function(name) {
            if (name === "suggest") view.host.acceptSuggestion(modelData)
            else if (name === "assign") view.host.startAssign(modelData)
            else if (name === "house") view.host.houseDevice(modelData)
            else if (name === "forget") view.host.forgetDevice(modelData)
          }
          onContextRequested: function(scenePos) { view.menuForDevice(modelData, scenePos) }
        }
      }

      RowLayout {
        width: column.width
        PanelSectionHeader {
          Layout.fillWidth: true
          text: "People (" + (view.host ? view.host.people.length : 0) + ")"
          foreground: view.foreground
          fontFamily: view.fontFamily
        }
        Button {
          text: "New person"
          bordered: true
          foreground: view.foreground
          fontFamily: view.fontFamily
          fontSize: Style.font.bodySmall
          onClicked: view.host.startNewPerson(null)
        }
      }
      TextField {
        id: search
        width: column.width
        visible: view.host !== null && view.host.people.length > 8
        placeholderText: "Search people"
        foreground: view.foreground
        font.family: view.fontFamily
        onTextChanged: view.query = text
        onActiveFocusChanged: if (activeFocus && view.renamingMac !== "") { view.renamingMac = ""; view.renameText = "" }
        Keys.onEscapePressed: function(event) {
          if (search.text !== "") search.text = ""
          else view.host.focusKeys()
          event.accepted = true
        }
      }
      Text {
        visible: view.host !== null && view.host.people.length === 0 && view.host.neighbors.length === 0
                 && view.host.guests.length === 0
        width: column.width
        text: "No people yet. Assign a device from \"Unassigned\" or create one."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: view.host ? view.host.dim : view.foreground
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }
      Repeater {
        model: view.everyone
        delegate: PersonRow {
          width: column.width
          person: modelData
          host: view.host
          onActivated: view.host.startEdit(modelData)
          onContextRequested: function(scenePos) { view.menuForPerson(modelData, scenePos) }
        }
      }

      CollapsibleSection {
        visible: view.host !== null && view.host.neighbors.length > 0
        width: column.width
        open: view.host ? view.host.neighborsOpen : false
        title: Format.neighborsHeader(view.host ? view.host.neighbors : [])
        foreground: view.foreground
        accent: view.host ? view.host.accent : Color.accent
        fontFamily: view.fontFamily
        onToggled: {
          if (view.renamingMac !== "") view.cancelRename()
          view.host.neighborsOpen = !view.host.neighborsOpen
        }
      }
      Repeater {
        model: view.host && view.host.neighborsOpen ? view.host.neighbors : []
        delegate: PersonRow {
          width: column.width
          person: modelData
          host: view.host
          onActivated: view.host.startEdit(modelData)
          onContextRequested: function(scenePos) { view.menuForPerson(modelData, scenePos) }
        }
      }

      CollapsibleSection {
        visible: view.host !== null && view.host.guests.length > 0
        width: column.width
        open: view.host ? view.host.guestsOpen : false
        title: Format.guestsHeader(view.host ? view.host.guests : [])
        foreground: view.foreground
        accent: view.host ? view.host.accent : Color.accent
        fontFamily: view.fontFamily
        onToggled: {
          if (view.renamingMac !== "") view.cancelRename()
          view.host.guestsOpen = !view.host.guestsOpen
        }
      }
      Repeater {
        model: view.host && view.host.guestsOpen ? view.host.guests : []
        delegate: PersonRow {
          width: column.width
          person: modelData
          host: view.host
          onActivated: view.host.startEdit(modelData)
          onContextRequested: function(scenePos) { view.menuForPerson(modelData, scenePos) }
        }
      }

      CollapsibleSection {
        visible: view.host !== null && view.host.house.length > 0
        width: column.width
        open: view.host ? view.host.houseOpen : false
        title: Format.houseHeader(view.host ? view.host.house : [])
        foreground: view.foreground
        accent: view.host ? view.host.accent : Color.accent
        fontFamily: view.fontFamily
        onToggled: {
          if (view.renamingMac !== "") view.cancelRename()
          view.host.houseOpen = !view.host.houseOpen
        }
      }
      Repeater {
        model: view.host && view.host.houseOpen ? view.host.house : []
        delegate: DeviceRow {
          width: column.width
          device: modelData
          host: view.host
          title: modelData.label || "Device"
          detail: Format.houseDetail(modelData, view.host ? view.host.nowMs : Date.now())
          actions: ["rename", "remove"]
          editing: modelData.mac === view.renamingMac
          editText: view.renameText
          onAction: function(name) {
            if (name === "rename") view.startRename(modelData)
            else if (name === "remove") view.host.unhouseDevice(modelData.mac)
          }
          onEditEdited: function(text) { view.renameText = text }
          onEditAccepted: view.commitRename()
          onEditCanceled: view.cancelRename()
          onContextRequested: function(scenePos) { view.menuForDevice(modelData, scenePos) }
        }
      }
    }
  }
}
