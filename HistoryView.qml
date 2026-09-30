import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Format.js" as Format

// How long each person was home over a day, a week or a month. The engine answers
// numbers; the names and emojis come from the status the panel already has.
Item {
  id: view
  property var host: null
  readonly property bool typing: false
  readonly property color foreground: host ? host.foreground : Color.foreground
  readonly property string fontFamily: host ? host.fontFamily : Style.font.family
  readonly property color accent: host ? host.accent : Color.accent
  readonly property var report: host ? host.historyReport : null
  readonly property var rows: report && report.people ? report.people : []
  readonly property real most: {
    var top = 0
    for (var i = 0; i < rows.length; i++)
      top = Math.max(top, (rows[i].home || 0) + (rows[i].unknown || 0))
    return top
  }

  implicitHeight: column.implicitHeight

  function personOf(id) {
    var people = host && host.status && host.status.people ? host.status.people : []
    for (var i = 0; i < people.length; i++) if (people[i].id === id) return people[i]
    return null
  }

  // The panel gives a view the height that is left after the hero, and a day with every
  // lane ticked — or a week comparing several people — is taller than that. Without this
  // the rows simply paint past the panel's edge, the same scroller MainView and
  // SettingsView have always had.
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
        Repeater {
          model: ["day", "week", "month"]
          delegate: Button {
            required property string modelData
            text: modelData.charAt(0).toUpperCase() + modelData.slice(1)
            bordered: true
            foreground: view.host && view.host.historyPeriod === modelData ? view.accent
                                                                           : view.foreground
            fontFamily: view.fontFamily
            onClicked: view.host.setHistoryPeriod(modelData)
          }
        }
        Item { Layout.fillWidth: true }
      }

      RowLayout {
        Layout.fillWidth: true
        spacing: Style.space(6)
        Text {
          Layout.fillWidth: true
          text: view.report ? Format.periodLabel(view.report.period, view.report.from,
                                                 view.report.to, view.host.todayIso()) : ""
          textFormat: Text.PlainText
          elide: Text.ElideRight
          color: view.foreground
          font.family: view.fontFamily
          font.pixelSize: Style.font.body
        }
        PanelActionButton {
          iconText: "\u{F00ED}"   // nf-md-calendar
          tooltipText: "Pick a day"
          // Without a report there is no floor to stop dimming at, and the grid would
          // claim nothing was ever recorded while the first one is still on its way.
          enabled: !!view.report
          opacity: enabled ? 1 : 0.4
          foreground: view.foreground
          hoverColor: view.accent
          onClicked: view.host.openCalendar()
        }
        PanelActionButton {
          iconText: "\u{F004D}"   // nf-md-arrow_left
          tooltipText: "Earlier"
          enabled: !!(view.report && view.report.prev) && !!view.host && !view.host.historyLoading
          opacity: enabled ? 1 : 0.4
          foreground: view.foreground
          hoverColor: view.accent
          onClicked: view.host.stepHistory(view.report.prev)
        }
        PanelActionButton {
          iconText: "\u{F0054}"   // nf-md-arrow_right
          tooltipText: "Later"
          enabled: !!(view.report && view.report.next) && !!view.host && !view.host.historyLoading
          opacity: enabled ? 1 : 0.4
          foreground: view.foreground
          hoverColor: view.accent
          onClicked: view.host.stepHistory(view.report.next)
        }
      }

      // The switch is off: say what this would do instead of showing an empty list, which
      // would read as "nobody was ever home".
      Text {
        Layout.fillWidth: true
        visible: !!view.report && view.report.enabled === false
        text: "The history is off. Turn \"Keep a history\" on in Settings and this fills in from there — nothing before that was recorded."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: view.foreground
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Text {
        Layout.fillWidth: true
        visible: !!view.host && view.host.historyError !== ""
        text: view.host ? view.host.historyError : ""
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: view.host ? view.host.urgent : Color.urgent
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Repeater {
        model: view.rows
        delegate: Item {
          id: personRow
          required property var modelData
          readonly property var person: view.personOf(modelData.id)
          Layout.fillWidth: true
          implicitHeight: line.implicitHeight + Style.space(8)

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: view.host.openHistoryPerson(personRow.modelData.id)
          }

          RowLayout {
            id: line
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(6)

            Text {
              Layout.preferredWidth: Math.round(personRow.width * 0.34)
              text: personRow.person ? personRow.person.emoji + " " + personRow.person.name
                                     : "Someone"
              textFormat: Text.PlainText
              elide: Text.ElideRight
              color: view.foreground
              font.family: view.fontFamily
              font.pixelSize: Style.font.body
            }
            Rectangle {
              id: track
              Layout.fillWidth: true
              implicitHeight: Style.space(6)
              radius: height / 2
              color: Qt.rgba(view.foreground.r, view.foreground.g, view.foreground.b, 0.15)
              // Two segments: what was measured at home, and -- paler, right after it --
              // the stretch nobody was watching. Folding the second into the first would
              // claim she was home; leaving it out would claim she was not.
              Row {
                height: parent.height
                Rectangle {
                  height: parent.height
                  radius: parent.height / 2
                  width: view.most > 0 ? track.width * (personRow.modelData.home / view.most) : 0
                  color: view.accent
                }
                Rectangle {
                  height: parent.height
                  radius: parent.height / 2
                  width: view.most > 0
                           ? track.width * ((personRow.modelData.unknown || 0) / view.most) : 0
                  color: Qt.rgba(view.accent.r, view.accent.g, view.accent.b, 0.35)
                }
              }
            }
            Text {
              text: Format.longDuration(personRow.modelData.home)
              textFormat: Text.PlainText
              color: view.foreground
              font.family: view.fontFamily
              font.pixelSize: Style.font.bodySmall
            }
          }
        }
      }

      Text {
        Layout.fillWidth: true
        visible: view.rows.length > 0
        text: "Tap a person for details"
        textFormat: Text.PlainText
        color: Qt.rgba(view.foreground.r, view.foreground.g, view.foreground.b, 0.6)
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }
    }
  }
}
