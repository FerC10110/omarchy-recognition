import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Format.js" as Format

// Jumping to an older day instead of walking there one arrow-click at a time.
//
// Unlike the desktop's own calendar this grid is a picker, not a read-out, and it hands
// its date back without touching the period: the 12th picked from the week ranking lands
// on the week of the 12th, because the engine snaps a date to whichever period it was
// asked about. So one day picker serves the day, the week and the month alike.
//
// Weeks start on Monday and that is not a preference: it is where `history_period` cuts
// them, and a grid that disagreed with the engine would put a week's days under the
// wrong heading.
Item {
  id: view
  property var host: null
  readonly property bool typing: false
  readonly property color foreground: host ? host.foreground : Color.foreground
  readonly property string fontFamily: host ? host.fontFamily : Style.font.family
  readonly property color accent: host ? host.accent : Color.accent

  readonly property string today: host ? host.todayIso() : ""
  readonly property string picked: host ? host.calendarAnchor : ""
  readonly property bool empty: !host || host.calendarEarliest === ""
  // With nothing recorded the floor is today: a grid where every other cell is out of
  // reach says "the history starts here" more plainly than an empty screen would.
  readonly property string earliest: view.empty ? view.today : host.calendarEarliest

  // The month on screen, seeded from the day being viewed. The arrows assign it, which
  // drops this binding for good -- fine, the view is rebuilt on every open.
  property string month: Format.shiftMonth(view.picked || view.today, 0)

  readonly property var cells: Format.monthGrid(view.month)
  readonly property bool earlierMonth: view.month > Format.shiftMonth(view.earliest, 0)
  readonly property bool laterMonth: view.month < Format.shiftMonth(view.today, 0)

  // Outside this the history has nothing to say, so the cell is shown but not offered.
  function reachable(day) {
    return day !== "" && day >= view.earliest && day <= view.today
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

    ColumnLayout {
      id: column
      width: flick.width
      spacing: Style.space(8)

      RowLayout {
        Layout.fillWidth: true
        spacing: Style.space(6)
        PanelActionButton {
          iconText: "\u{F004D}"   // nf-md-arrow_left
          tooltipText: "Earlier month"
          enabled: view.earlierMonth
          opacity: enabled ? 1 : 0.4
          foreground: view.foreground
          hoverColor: view.accent
          onClicked: view.month = Format.shiftMonth(view.month, -1)
        }
        Text {
          Layout.fillWidth: true
          horizontalAlignment: Text.AlignHCenter
          text: Format.periodLabel("month", view.month, view.month, view.today)
          textFormat: Text.PlainText
          elide: Text.ElideRight
          color: view.foreground
          font.family: view.fontFamily
          font.pixelSize: Style.font.body
        }
        PanelActionButton {
          iconText: "\u{F0054}"   // nf-md-arrow_right
          tooltipText: "Later month"
          enabled: view.laterMonth
          opacity: enabled ? 1 : 0.4
          foreground: view.foreground
          hoverColor: view.accent
          onClicked: view.month = Format.shiftMonth(view.month, 1)
        }
      }

      Text {
        Layout.fillWidth: true
        visible: view.empty
        text: "No history recorded yet. Today is the only day there is."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: view.foreground
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      // One grid for the initials and the days, so the two can never fall out of
      // alignment: a row of a Grid takes its own height, and the columns are shared.
      Grid {
        id: grid
        Layout.fillWidth: true
        columns: 7
        spacing: Style.space(2)
        readonly property real cell: Math.floor((width - grid.spacing * 6) / 7)

        Repeater {
          model: ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
          delegate: Text {
            required property string modelData
            width: grid.cell
            height: Style.space(16)
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            text: modelData
            textFormat: Text.PlainText
            color: view.foreground
            opacity: 0.6
            font.family: view.fontFamily
            font.pixelSize: Style.font.caption
            font.letterSpacing: 1
            font.bold: true
          }
        }

        Repeater {
          model: view.cells
          delegate: Rectangle {
            id: cellBox
            required property string modelData
            readonly property bool open: view.reachable(modelData)
            readonly property bool chosen: modelData !== "" && modelData === view.picked
            readonly property bool now: modelData !== "" && modelData === view.today

            width: grid.cell
            height: Style.space(34)
            radius: Style.cornerRadius
            // The day on screen is filled; today is only outlined, so the two marks read
            // as different things when they land on different days.
            color: cellBox.chosen ? Qt.rgba(view.accent.r, view.accent.g, view.accent.b, 0.22)
                 : dayMouse.containsMouse ? Qt.rgba(view.foreground.r, view.foreground.g,
                                                    view.foreground.b, 0.10)
                 : "transparent"
            border.width: cellBox.now && !cellBox.chosen ? 1 : 0
            border.color: Qt.rgba(view.foreground.r, view.foreground.g, view.foreground.b, 0.35)

            Text {
              anchors.centerIn: parent
              visible: cellBox.modelData !== ""
              text: cellBox.modelData === "" ? "" : String(parseInt(cellBox.modelData.slice(8), 10))
              textFormat: Text.PlainText
              // A day the history cannot answer is left legible but plainly out of reach.
              opacity: cellBox.open ? 1 : 0.3
              color: cellBox.chosen ? view.accent : view.foreground
              font.family: view.fontFamily
              font.pixelSize: Style.font.body
              font.bold: cellBox.chosen
            }

            MouseArea {
              id: dayMouse
              anchors.fill: parent
              enabled: cellBox.open
              hoverEnabled: enabled
              cursorShape: Qt.PointingHandCursor
              onClicked: view.host.pickDay(cellBox.modelData)
            }
          }
        }
      }
    }
  }
}
