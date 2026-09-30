import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Format.js" as Format

// One command: its text, and the events it runs on with how its last run went.
CursorSurface {
  id: row
  property var command: ({ command: "", events: [], last: null })
  property var host: null
  readonly property bool failed: !!(row.command.last && row.command.last.ok === false)
  signal activated()

  foreground: host ? host.foreground : Color.foreground
  accent: host ? host.accent : Color.accent
  implicitHeight: Style.space(40)
  hasCursor: mouse.containsMouse

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: row.activated()
  }

  RowLayout {
    anchors.fill: parent
    anchors.leftMargin: Style.space(6)
    anchors.rightMargin: Style.space(8)

    ColumnLayout {
      Layout.fillWidth: true
      spacing: 0
      Text {
        Layout.fillWidth: true
        text: Format.commandOneLine(row.command.command)
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: row.foreground
        font.family: row.host ? row.host.fontFamily : Style.font.family
        font.pixelSize: Style.font.body
      }
      Text {
        Layout.fillWidth: true
        text: Format.commandMeta(row.command, row.host ? row.host.nowMs : Date.now())
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: row.failed ? (row.host ? row.host.urgent : Color.urgent) : (row.host ? row.host.dim : Color.foreground)
        font.family: row.host ? row.host.fontFamily : Style.font.family
        font.pixelSize: Style.font.bodySmall
      }
    }
  }
}
