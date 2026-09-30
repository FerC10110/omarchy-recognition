import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Format.js" as Format

// One person: emoji, name, and when they arrived or were last seen.
CursorSurface {
  id: row
  property var person: ({ devices: [] })
  property var host: null
  signal activated()
  signal contextRequested(point scenePos)

  foreground: host ? host.foreground : Color.foreground
  accent: host ? host.accent : Color.accent
  implicitHeight: Style.space(40)
  hasCursor: mouse.containsMouse

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    // Scene coordinates: the menu is a layer over the whole panel and the row it
    // was opened from may scroll out from under it.
    onClicked: function(mouse) {
      if (mouse.button === Qt.RightButton) row.contextRequested(mapToItem(null, mouse.x, mouse.y))
      else row.activated()
    }
  }

  RowLayout {
    anchors.fill: parent
    anchors.leftMargin: Style.space(6)
    anchors.rightMargin: Style.space(8)
    spacing: Style.space(10)

    Text {
      text: row.person.emoji || ""
      textFormat: Text.PlainText
      font.pixelSize: Style.font.heading
    }

    ColumnLayout {
      Layout.fillWidth: true
      spacing: 0
      Text {
        Layout.fillWidth: true
        text: row.person.name || ""
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: row.foreground
        font.family: row.host ? row.host.fontFamily : Style.font.family
        font.pixelSize: Style.font.body
      }
      Text {
        Layout.fillWidth: true
        text: Format.personDetail(row.person, row.host ? row.host.nowMs : Date.now())
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: row.host ? row.host.dim : Color.foreground
        font.family: row.host ? row.host.fontFamily : Style.font.family
        font.pixelSize: Style.font.bodySmall
      }
    }

    Text {
      visible: row.person.present === true
      text: "●"
      color: row.accent
      font.pixelSize: Style.font.caption
    }
  }

  PanelToolTip {
    visible: mouse.containsMouse
    text: Format.personTooltip(row.person, row.host ? row.host.nowMs : Date.now())
    fontFamily: row.host ? row.host.fontFamily : Style.font.family
  }
}
