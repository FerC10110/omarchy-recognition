import QtQuick
import qs.Commons
import qs.Ui

// The right-click menu of a row. Like ConfirmDialog it fills the panel and dims
// nothing; unlike it, the card sits where the click was, clipped to the panel's
// edges. It knows nothing about what its items do: it shows them and says which one
// was picked.
//
// An item is { text, enabled, kind, payload }. kind is "copy", "run", "separator"
// (a rule, never selectable) or "none" (a dimmed line like "No manual commands").
Item {
  id: root

  property bool opened: false
  property string title: ""
  property var items: []
  property point origin: Qt.point(0, 0)      // where the click was, in scene coordinates
  property int selectedIndex: -1
  property color background: Color.popups.background
  property color foreground: Color.foreground
  property color dim: Qt.darker(foreground, 1.55)
  property color accent: Color.accent
  property string fontFamily: Style.font.family

  signal activated(var item)

  readonly property point localOrigin: root.mapFromItem(null, origin.x, origin.y)

  function open(scenePos, title, items) {
    root.title = String(title || "")
    root.items = items || []
    root.origin = scenePos
    root.selectedIndex = root.nextSelectable(-1, 1)
    root.opened = true
  }

  function close() {
    root.opened = false
    root.items = []
    root.selectedIndex = -1
  }

  // The next item that can be picked, wrapping around; -1 when none can.
  function nextSelectable(from, step) {
    for (var i = 1; i <= root.items.length; i++) {
      var at = (from + step * i + root.items.length * i) % root.items.length
      if (root.items[at] && root.items[at].enabled === true) return at
    }
    return -1
  }

  function step(dy) {
    if (root.items.length === 0) return
    root.selectedIndex = root.nextSelectable(root.selectedIndex, dy > 0 ? 1 : -1)
  }

  function activateSelected() {
    var item = root.selectedIndex >= 0 ? root.items[root.selectedIndex] : null
    if (!item || item.enabled !== true) return
    root.close()
    root.activated(item)
  }

  visible: opened

  // Catches the click that dismisses the menu, including a second right-click.
  MouseArea {
    anchors.fill: parent
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    onClicked: root.close()
  }

  BorderSurface {
    id: card
    width: Math.min(Style.space(280), root.width - Style.space(16))
    height: Math.min(card.contentTopInset + card.contentBottomInset + menu.implicitHeight,
                     root.height - Style.space(16))
    x: Math.max(Style.space(8), Math.min(root.localOrigin.x, root.width - width - Style.space(8)))
    y: Math.max(Style.space(8), Math.min(root.localOrigin.y, root.height - height - Style.space(8)))
    color: root.background
    borderSpec: Border.flat(root.accent, Style.normalBorderWidth)
    padding: Style.space(8)
    radius: Style.cornerRadius

    // Swallows the clicks that land on the card so they don't dismiss it.
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton; onClicked: {} }

    // The card is capped to the panel, so a long list of manual commands scrolls
    // instead of drawing past the bottom edge where the mouse cannot reach it.
    // Wheel and drag scroll; the keyboard selection does not follow the viewport,
    // which only matters past ~20 commands.
    Flickable {
      id: menuFlick
      anchors.fill: parent
      anchors.topMargin: card.contentTopInset
      anchors.rightMargin: card.contentRightInset
      anchors.bottomMargin: card.contentBottomInset
      anchors.leftMargin: card.contentLeftInset
      clip: true
      contentWidth: width
      contentHeight: menu.implicitHeight
      boundsBehavior: Flickable.StopAtBounds
      interactive: contentHeight > height

      Column {
        id: menu
        width: menuFlick.width
        spacing: Style.space(2)

        Text {
          width: menu.width
          visible: root.title !== ""
          text: root.title
          textFormat: Text.PlainText
          elide: Text.ElideRight
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }

        Repeater {
          model: root.items

          delegate: Item {
            id: entry
            required property int index
            required property var modelData

            width: menu.width
            height: modelData.kind === "separator" ? Style.space(9) : Style.space(26)

            Rectangle {
              anchors.fill: parent
              visible: entry.modelData.kind !== "separator"
              color: root.selectedIndex === entry.index && entry.modelData.enabled === true
                     ? Util.alpha(root.foreground, 0.08) : "transparent"
              radius: Style.cornerRadius
            }

            Rectangle {
              visible: entry.modelData.kind === "separator"
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              height: 1
              color: Util.alpha(root.foreground, 0.2)
            }

            Text {
              visible: entry.modelData.kind !== "separator"
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.leftMargin: Style.space(6)
              anchors.rightMargin: Style.space(6)
              anchors.verticalCenter: parent.verticalCenter
              text: entry.modelData.text || ""
              textFormat: Text.PlainText
              elide: Text.ElideRight
              color: entry.modelData.enabled === true
                     ? (root.selectedIndex === entry.index ? root.accent : root.foreground)
                     : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            MouseArea {
              anchors.fill: parent
              enabled: entry.modelData.enabled === true
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onEntered: root.selectedIndex = entry.index
              onClicked: {
                root.selectedIndex = entry.index
                root.activateSelected()
              }
            }
          }
        }
      }
    }
  }
}
