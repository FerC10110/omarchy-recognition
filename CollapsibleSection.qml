import QtQuick
import qs.Commons
import qs.Ui

// The header of a collapsible section: the arrow, the title, and one click
// that toggles it. The caller owns the open flag and the rows below, so the
// three sections that use this (Neighbors, Guests, House) keep their own
// models and their own memory of being open.
CursorSurface {
  id: section
  property bool open: false
  property string title: ""
  property string fontFamily: Style.font.family
  signal toggled()

  implicitHeight: label.implicitHeight + Style.space(12)
  hasCursor: mouse.containsMouse

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: section.toggled()
  }
  PanelSectionHeader {
    id: label
    anchors.left: parent.left
    anchors.leftMargin: Style.space(6)
    anchors.verticalCenter: parent.verticalCenter
    text: (section.open ? "▾ " : "▸ ") + section.title
    foreground: section.foreground
    fontFamily: section.fontFamily
  }
}
