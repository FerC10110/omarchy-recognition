import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Format.js" as Format

// One person's history as a grid: a row per day of the period, and inside each row a
// lane per person you asked to compare. The hours line up vertically from one day to the
// next, which is the only thing that makes a week worth looking at.
Item {
  id: view
  property var host: null
  readonly property bool typing: false
  readonly property color foreground: host ? host.foreground : Color.foreground
  readonly property string fontFamily: host ? host.fontFamily : Style.font.family
  readonly property color accent: host ? host.accent : Color.accent
  readonly property var report: host ? host.historyReport : null
  readonly property var grid: host ? host.timelineReport : null
  readonly property var devices: report && report.devices ? report.devices : []
  readonly property var person: view.personOf(host ? host.historyPersonId : "")

  implicitHeight: column.implicitHeight

  function personOf(id) {
    var people = host && host.status && host.status.people ? host.status.people : []
    for (var i = 0; i < people.length; i++)
      if (people[i].id === id) return people[i]
    return null
  }

  function personLabel(id) {
    var found = view.personOf(id)
    return found ? found.emoji + " " + found.name : "Someone"
  }

  function deviceLabel(mac) {
    var owned = view.person && view.person.devices ? view.person.devices : []
    for (var i = 0; i < owned.length; i++)
      if (owned[i].mac === mac) return owned[i].label || mac
    return mac
  }

  // The person you opened, first, then whoever is ticked in Compare -- in the engine's
  // order, so the lanes inside a day never reshuffle between one load and the next.
  // A ticked key naming someone who has since been deleted matches no lane and simply
  // drops out; the rest still draw.
  readonly property var lanes: {
    var out = []
    var picked = view.host ? view.host.timelineCompare : []
    var all = view.grid && view.grid.lanes ? view.grid.lanes : []
    var mine = null
    for (var i = 0; i < all.length; i++) {
      if (all[i].kind !== "person") continue
      if (view.host && all[i].id === view.host.historyPersonId) mine = all[i]
      else if (Array.prototype.indexOf.call(picked, all[i].key) >= 0) out.push(all[i])
    }
    return mine ? [mine].concat(out) : out
  }

  readonly property var rows: {
    var out = []
    var days = view.grid && view.grid.days ? view.grid.days : []
    var lanes = view.lanes
    for (var d = 0; d < days.length; d++) {
      for (var l = 0; l < lanes.length; l++) {
        var slot = lanes[l].days[d] || {}
        out.push({ left: l === 0 ? Format.dayShort(days[d].day) : "",
                   label: view.personLabel(lanes[l].id),
                   indent: 0, thick: true, header: false, dim: !days[d].detail,
                   gap: (l === 0 && d > 0) ? Style.space(6) : 0,
                   total: days[d].detail ? (slot.total || 0) : -1,
                   day: days[d].day, spans: slot.spans || [] })
      }
    }
    return out
  }

  // Every day of the period lost its detail to the retention. An empty grid would read
  // as "nobody was home"; say what actually happened, and where to change it.
  readonly property bool allSealed: {
    var days = view.grid && view.grid.days ? view.grid.days : []
    if (days.length === 0) return false
    for (var i = 0; i < days.length; i++)
      if (days[i].detail) return false
    return true
  }

  readonly property var compareOptions: {
    var out = []
    var people = view.host && view.host.status && view.host.status.people
                   ? view.host.status.people : []
    for (var i = 0; i < people.length; i++) {
      if (view.host && people[i].id === view.host.historyPersonId) continue
      out.push({ value: "person:" + people[i].id,
                 label: people[i].emoji + " " + people[i].name })
    }
    return out
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
        PanelActionButton {
          iconText: "\u{F004D}"   // nf-md-arrow_left
          tooltipText: "Back"
          foreground: view.foreground
          hoverColor: view.accent
          onClicked: view.host.back()
        }
        Text {
          Layout.fillWidth: true
          text: view.person ? view.person.emoji + " " + view.person.name : "Someone"
          textFormat: Text.PlainText
          elide: Text.ElideRight
          color: view.foreground
          font.family: view.fontFamily
          font.pixelSize: Style.font.body
        }
        Text {
          text: view.report && view.report.person
                  ? Format.homeTotal(view.report.person.home, view.report.person.unknown) : ""
          textFormat: Text.PlainText
          color: view.foreground
          font.family: view.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
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
          font.pixelSize: Style.font.bodySmall
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

      // Ticking a name redraws right away; the engine only hears about it when the popup
      // closes, because set-settings prunes and a tick is not a reason to walk the months.
      MultiSelect {
        id: compare
        Layout.fillWidth: true
        showLabel: false
        triggerLabel: "Compare"
        noSelectionText: "Compare"
        emptyText: "Nobody else"
        values: view.host ? view.host.timelineCompare : []
        options: view.compareOptions
        foreground: view.foreground
        accent: view.accent
        fontFamily: view.fontFamily
        visible: view.compareOptions.length > 0
        onChanged: function(values) { view.host.pickCompare(values, false) }
        onPopupOpenChanged: if (!compare.popupOpen && view.host)
                              view.host.pickCompare(view.host.timelineCompare, true)
      }

      Text {
        Layout.fillWidth: true
        visible: view.allSealed
        text: "Details are only kept for the last "
              + (view.grid ? view.grid.keepDays : 0)
              + " days. Settings can keep them longer."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Qt.rgba(view.foreground.r, view.foreground.g, view.foreground.b, 0.6)
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      DayStrip {
        Layout.fillWidth: true
        visible: !view.allSealed && view.rows.length > 0
        rows: view.rows
        leftWidth: Style.space(52)
        labelWidth: Style.space(84)
        totalWidth: Style.space(54)
        foreground: view.foreground
        accent: view.accent
        fontFamily: view.fontFamily
        onRowClicked: function(index) {
          var row = view.rows[index]
          if (row && row.day) view.host.openTimelineDay(row.day)
        }
      }

      PanelSeparator { Layout.fillWidth: true; visible: view.devices.length > 0 }

      Repeater {
        model: view.devices
        delegate: RowLayout {
          required property var modelData
          Layout.fillWidth: true
          spacing: Style.space(6)
          Text {
            Layout.fillWidth: true
            text: view.deviceLabel(modelData.mac)
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: view.foreground
            font.family: view.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
          Text {
            text: "answered " + Format.longDuration(modelData.on)
            textFormat: Text.PlainText
            color: Qt.rgba(view.foreground.r, view.foreground.g, view.foreground.b, 0.7)
            font.family: view.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
        }
      }
    }
  }
}
