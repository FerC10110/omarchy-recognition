import QtQuick
import QtQuick.Layouts
import qs.Commons
import "Format.js" as Format

// The grid both history screens draw with: a 24-hour axis, one row per lane, and every
// span placed by its local time. One component so the day view and the week view can
// never disagree about where nine in the morning is.
Item {
  id: strip

  property var rows: []
  property real leftWidth: 0
  property real labelWidth: 96
  property real totalWidth: 62
  property color foreground: Color.foreground
  property color accent: Color.accent
  property string fontFamily: Style.font.family
  property bool showAxis: true

  signal rowClicked(int index)

  readonly property color trackColor: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.10)
  readonly property color unknownColor: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.30)
  readonly property real barLeft: leftWidth + labelWidth
  readonly property real barWidth: Math.max(1, width - barLeft - totalWidth)

  implicitHeight: column.implicitHeight

  ColumnLayout {
    id: column
    width: parent.width
    spacing: 0

    // 0 · 6 · 12 · 18 · 24, with a dot on the hours between.
    Item {
      Layout.fillWidth: true
      visible: strip.showAxis
      implicitHeight: strip.showAxis ? Style.space(16) : 0
      Repeater {
        model: 9
        delegate: Text {
          required property int index
          readonly property real at: strip.barLeft + strip.barWidth * (index * 3 / 24)
          x: index === 0 ? at : (index === 8 ? at - implicitWidth : at - implicitWidth / 2)
          text: index % 2 === 0 ? String(index * 3) : "·"
          textFormat: Text.PlainText
          color: Qt.rgba(strip.foreground.r, strip.foreground.g, strip.foreground.b, 0.5)
          font.family: strip.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
      }
    }

    Repeater {
      model: strip.rows
      delegate: Item {
        id: row
        required property var modelData
        required property int index
        readonly property real barHeight: modelData.thick ? Style.space(11) : Style.space(5)
        // The row's own height is at the bottom; `gap` is empty space above it, which is
        // how a person's block is told apart from the next one's.
        // The floor is the label, not the bar: a thin device row is five pixels of bar
        // and eleven of text, and without it two devices in a row overlap.
        readonly property real contentHeight: modelData.header ? Style.space(14)
                                                               : Math.max(barHeight + Style.space(6),
                                                                          Style.space(16))
        readonly property real gap: modelData.gap === undefined ? 0 : modelData.gap
        readonly property real middle: height - contentHeight / 2
        Layout.fillWidth: true
        implicitHeight: contentHeight + gap

        MouseArea {
          anchors.fill: parent
          enabled: !row.modelData.header
          cursorShape: Qt.PointingHandCursor
          onClicked: strip.rowClicked(row.index)
        }

        Text {
          x: 0
          y: row.middle - implicitHeight / 2
          width: strip.leftWidth
          visible: strip.leftWidth > 0
          text: row.modelData.left || ""
          textFormat: Text.PlainText
          elide: Text.ElideRight
          color: strip.foreground
          font.family: strip.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        Text {
          x: strip.leftWidth + (row.modelData.indent ? Style.space(12) : 0)
          y: row.middle - implicitHeight / 2
          width: strip.labelWidth - (row.modelData.indent ? Style.space(12) : 0) - Style.space(6)
          text: row.modelData.label || ""
          textFormat: Text.PlainText
          elide: Text.ElideRight
          color: row.modelData.header || row.modelData.dim
                   ? Qt.rgba(strip.foreground.r, strip.foreground.g, strip.foreground.b, 0.55)
                   : strip.foreground
          font.family: strip.fontFamily
          font.pixelSize: row.modelData.thick ? Style.font.body : Style.font.bodySmall
        }

        Rectangle {
          id: track
          visible: !row.modelData.header
          x: strip.barLeft
          y: row.middle - height / 2
          width: strip.barWidth
          height: row.barHeight
          radius: height / 2
          color: strip.trackColor
          opacity: row.modelData.dim ? 0.5 : 1

          Repeater {
            model: row.modelData.spans || []
            delegate: Rectangle {
              required property var modelData
              readonly property var box: Format.spanBox(modelData, row.modelData.day)
              x: track.width * box.x
              width: Math.max(box.w > 0 ? 1.5 : 0, track.width * box.w)
              height: track.height
              radius: height / 2
              color: modelData.state === "unknown" ? strip.unknownColor
                   : row.modelData.thick ? strip.accent
                                         : Qt.rgba(strip.accent.r, strip.accent.g,
                                                   strip.accent.b, 0.7)
            }
          }
        }

        Text {
          x: strip.width - strip.totalWidth
          y: row.middle - implicitHeight / 2
          width: strip.totalWidth
          horizontalAlignment: Text.AlignRight
          visible: !row.modelData.header && row.modelData.total >= 0
          text: Format.duration(row.modelData.total)
          textFormat: Text.PlainText
          color: row.modelData.dim
                   ? Qt.rgba(strip.foreground.r, strip.foreground.g, strip.foreground.b, 0.5)
                   : strip.foreground
          font.family: strip.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
      }
    }
  }
}
