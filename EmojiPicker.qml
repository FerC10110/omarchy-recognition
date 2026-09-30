import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Emoji grid with a search box, over the same list and keyword search as
// Omarchy's emoji overlay (which cannot hand its choice to another plugin).
Item {
  id: view
  property var host: null
  property var emojis: []
  property string query: ""
  // Distinguishes "still loading" from "loaded and actually empty/broken",
  // since emojis.json's load is async — without this the FileView's
  // one-frame gap between creation and onLoaded/onLoadFailed reads as an
  // empty list and flashes the "not found" message on every open.
  property bool loadFailed: false
  readonly property bool typing: search.activeFocus
  readonly property var shown: filterEmojis(emojis, query)
  readonly property color foreground: host ? host.foreground : Color.foreground
  readonly property string fontFamily: host ? host.fontFamily : Style.font.family

  implicitHeight: Style.space(420)

  // Every match, not a page of them: the grid below is a GridView, which builds
  // only the cells it shows, so the whole list costs one pass of string compares.
  function filterEmojis(list, text) {
    var needle = String(text || "").trim().toLowerCase()
    var out = []
    for (var i = 0; i < list.length; i++) {
      var item = list[i]
      if (item && item.e && (needle === "" || String(item.k || "").toLowerCase().indexOf(needle) >= 0)) out.push(item.e)
    }
    return out
  }

  FileView {
    path: Quickshell.env("OMARCHY_PATH") + "/shell/plugins/emojis/emojis.json"
    printErrors: false
    onLoaded: {
      try {
        var data = JSON.parse(text())
        view.emojis = Array.isArray(data) ? data : []
        view.loadFailed = view.emojis.length === 0
      } catch (e) {
        view.emojis = []
        view.loadFailed = true
      }
    }
    onLoadFailed: view.loadFailed = true
  }

  Component.onCompleted: Qt.callLater(function() { search.forceActiveFocus() })

  ColumnLayout {
    anchors.fill: parent
    spacing: Style.space(6)

    RowLayout {
      Layout.fillWidth: true
      PanelActionButton {
        iconText: "\u{F004D}"   // nf-md-arrow_left
        tooltipText: "Back"
        foreground: view.foreground
        hoverColor: view.host ? view.host.accent : Color.accent
        onClicked: view.host.back()
      }
      PanelSectionHeader {
        Layout.fillWidth: true
        text: "Choose emoji"
        foreground: view.foreground
        fontFamily: view.fontFamily
      }
    }

    TextField {
      id: search
      Layout.fillWidth: true
      placeholderText: "Search (e.g. fox, bear, cat…)"
      foreground: view.foreground
      font.family: view.fontFamily
      onTextChanged: view.query = text
      Keys.onEscapePressed: function(event) {
        if (search.text !== "") search.text = ""
        else view.host.back()
        event.accepted = true
      }
      Keys.onReturnPressed: function(event) {
        if (view.shown.length > 0) view.host.emojiPicked(view.shown[0])
        event.accepted = true
      }
    }

    Text {
      visible: view.loadFailed
      Layout.fillWidth: true
      text: "Couldn't find Omarchy's emoji list."
      textFormat: Text.PlainText
      color: view.host ? view.host.urgent : Color.urgent
      font.family: view.fontFamily
      font.pixelSize: Style.font.bodySmall
    }

    GridView {
      id: grid
      Layout.fillWidth: true
      Layout.fillHeight: true
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      cellWidth: Math.max(Style.space(44), Style.font.display + Style.spacing.md)
      cellHeight: cellWidth
      model: view.shown
      delegate: CursorSurface {
        required property var modelData
        width: grid.cellWidth - Style.space(4)
        height: grid.cellHeight - Style.space(4)
        foreground: view.foreground
        hasCursor: cell.containsMouse
        Text {
          anchors.centerIn: parent
          text: modelData
          textFormat: Text.PlainText
          font.pixelSize: Style.font.display
        }
        MouseArea {
          id: cell
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: view.host.emojiPicked(modelData)
        }
      }
    }
  }
}
