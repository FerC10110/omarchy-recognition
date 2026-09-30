import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Format.js" as Format

// One day, every lane: each person thick with their own devices thin underneath, then
// House, then whatever else answered on the network that day. Who is on screen is the
// user's to choose and the choice outlives the shell -- it lives in settings.
Item {
  id: view
  property var host: null
  readonly property bool typing: false
  readonly property color foreground: host ? host.foreground : Color.foreground
  readonly property string fontFamily: host ? host.fontFamily : Style.font.family
  readonly property color accent: host ? host.accent : Color.accent
  readonly property var report: host ? host.timelineReport : null
  readonly property var allLanes: report && report.lanes ? report.lanes : []
  readonly property bool sealed: {
    var days = view.report && view.report.days ? view.report.days : []
    return days.length > 0 && !days[0].detail
  }
  readonly property bool off: !!view.report && view.report.enabled === false

  implicitHeight: column.implicitHeight

  function laneLabel(lane) {
    if (lane.kind === "person") {
      var people = view.host && view.host.status && view.host.status.people
                     ? view.host.status.people : []
      for (var i = 0; i < people.length; i++)
        if (people[i].id === lane.id) return people[i].emoji + " " + people[i].name
      return "Someone"
    }
    return lane.label || lane.vendor || lane.mac
  }

  // "house" for House, "other" for a MAC nobody claims, "mine" for a person and for the
  // devices that hang off one. The engine already hands the lanes over in that order, so
  // a section header is just the moment the group changes.
  //
  // `owner` is answered for every person, neighbours and guests included, but only the
  // home group gets a person lane -- so a neighbour's phone has an owner nobody can see.
  // The lanes on screen are the authority for what counts as somebody's: without this a
  // neighbour's hardware lands inside the House block and is ticked by default.
  function groupOf(lane) {
    if (lane.kind === "person") return "mine"
    if (lane.owner === "house") return "house"
    return lane.owner && view.isOnScreen(lane.owner) ? "mine" : "other"
  }

  function isOnScreen(personId) {
    for (var i = 0; i < view.allLanes.length; i++)
      if (view.allLanes[i].kind === "person" && view.allLanes[i].id === personId) return true
    return false
  }

  // The first time there is nothing saved: the household and House, not the strangers.
  // Unticking everything lands here too, which is the kindest thing an empty list can
  // mean -- an empty screen with no way back to a full one would just look broken.
  readonly property var picked: {
    var saved = view.host ? view.host.timelineLanes : []
    var out = []
    if (saved && saved.length > 0) {
      for (var i = 0; i < view.allLanes.length; i++)
        if (Array.prototype.indexOf.call(saved, view.allLanes[i].key) >= 0)
          out.push(view.allLanes[i])
      if (out.length > 0) return out
    }
    for (var j = 0; j < view.allLanes.length; j++)
      if (view.groupOf(view.allLanes[j]) !== "other") out.push(view.allLanes[j])
    return out
  }

  // What the grid draws, as keys. The picker binds to this and not to the saved setting:
  // on a fresh install the setting is empty while the grid shows the household, and a
  // picker that showed nothing ticked would turn the first tick into "replace all".
  readonly property var pickedKeys: view.picked.map(function (lane) { return lane.key })

  // Why the day has no device lanes, when it has none and that is a setting rather than
  // an empty night. The engine answers `scope` for exactly this.
  readonly property string scopeNote: {
    if (!view.report || view.report.scope !== "none") return ""
    return "Devices are not being recorded. Settings can follow the ones you have "
         + "assigned, or everything on the network."
  }

  // The day screen is the whole screen: unlike the period screen there is no header
  // above it still saying whether the engine answered.
  readonly property string emptyNote: {
    if (view.report || (view.host && view.host.timelineLoading)) return ""
    return "The engine didn't answer."
  }

  readonly property var rows: {
    var out = []
    var group = "mine"
    var lanes = view.picked
    for (var i = 0; i < lanes.length; i++) {
      var lane = lanes[i]
      var mine = view.groupOf(lane)
      if (mine !== group && mine !== "mine") {
        out.push({ left: "", label: mine === "house" ? "House" : "Unassigned",
                   indent: 0, thick: false, header: true, dim: false,
                   gap: out.length > 0 ? Style.space(6) : 0, total: -1, day: "", spans: [] })
      }
      group = mine
      var slot = lane.days[0] || {}
      out.push({ left: "", label: view.laneLabel(lane),
                 indent: lane.kind === "person" ? 0 : 1,
                 thick: lane.kind === "person", header: false,
                 // Hardware passing through: readable, and visibly not part of the house.
                 dim: lane.kind === "device" && !!lane.randomMac,
                 gap: lane.kind === "person" && out.length > 0 ? Style.space(4) : 0,
                 total: slot.total || 0, day: slot.day || "", spans: slot.spans || [] })
    }
    return out
  }

  readonly property var laneOptions: {
    var out = []
    for (var i = 0; i < view.allLanes.length; i++) {
      var lane = view.allLanes[i]
      out.push({ value: lane.key, label: view.laneLabel(lane),
                 description: lane.kind === "person" ? ""
                            : (lane.owner === "house" ? "House" : (lane.owner ? "" : lane.mac)) })
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
          text: view.report ? Format.periodLabel("day", view.report.from, view.report.to,
                                                 view.host.todayIso()) : ""
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
          enabled: !!(view.report && view.report.prev) && !!view.host && !view.host.timelineLoading
          opacity: enabled ? 1 : 0.4
          foreground: view.foreground
          hoverColor: view.accent
          onClicked: view.host.stepTimeline(view.report.prev)
        }
        PanelActionButton {
          iconText: "\u{F0054}"   // nf-md-arrow_right
          tooltipText: "Later"
          enabled: !!(view.report && view.report.next) && !!view.host && !view.host.timelineLoading
          opacity: enabled ? 1 : 0.4
          foreground: view.foreground
          hoverColor: view.accent
          onClicked: view.host.stepTimeline(view.report.next)
        }
      }

      MultiSelect {
        id: who
        Layout.fillWidth: true
        showLabel: false
        triggerLabel: "Who"
        noSelectionText: "Who"
        emptyText: "Nothing recorded"
        // MultiSelect assigns to `values` when a row is toggled, which drops this binding
        // for the life of the popup -- that is fine, the view is rebuilt on navigation, but
        // it does mean nothing outside can reseed the ticks while it is open.
        values: view.pickedKeys
        options: view.laneOptions
        foreground: view.foreground
        accent: view.accent
        fontFamily: view.fontFamily
        visible: !view.sealed && !view.off && view.allLanes.length > 0
        onChanged: function(values) { view.host.pickLanes(values, false) }
        onPopupOpenChanged: if (!who.popupOpen && view.host)
                              view.host.pickLanes(view.host.timelineLanes, true)
      }

      Text {
        Layout.fillWidth: true
        visible: view.emptyNote !== ""
        text: view.emptyNote
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Qt.rgba(view.foreground.r, view.foreground.g, view.foreground.b, 0.6)
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Text {
        Layout.fillWidth: true
        visible: !view.off && !view.sealed && view.scopeNote !== ""
        text: view.scopeNote
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Qt.rgba(view.foreground.r, view.foreground.g, view.foreground.b, 0.6)
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Text {
        Layout.fillWidth: true
        visible: view.off
        text: "The history is off. Settings can turn it back on."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Qt.rgba(view.foreground.r, view.foreground.g, view.foreground.b, 0.6)
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Text {
        Layout.fillWidth: true
        visible: view.sealed && !view.off
        text: "Details were not kept for this day."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Qt.rgba(view.foreground.r, view.foreground.g, view.foreground.b, 0.6)
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      DayStrip {
        Layout.fillWidth: true
        visible: !view.sealed && !view.off && view.rows.length > 0
        rows: view.rows
        leftWidth: 0
        labelWidth: Style.space(96)
        totalWidth: Style.space(54)
        foreground: view.foreground
        accent: view.accent
        fontFamily: view.fontFamily
      }
    }
  }
}
