import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Format.js" as Format

// Assign one unknown device: pick a person, or make a new one with it.
Item {
  id: view
  property var host: null
  property string query: ""
  readonly property bool typing: search.activeFocus
  readonly property var device: host ? host.assignDevice : null
  readonly property var candidates: host ? host.people.concat(host.neighbors).concat(host.guests).filter(function(p) { return Format.matches(p.name, view.query) }) : []
  readonly property color foreground: host ? host.foreground : Color.foreground
  readonly property string fontFamily: host ? host.fontFamily : Style.font.family

  implicitHeight: column.implicitHeight

  Component.onCompleted: Qt.callLater(function() { search.forceActiveFocus() })

  Flickable {
    id: flick
    anchors.fill: parent
    clip: true
    contentWidth: width
    contentHeight: column.implicitHeight
    boundsBehavior: Flickable.StopAtBounds
    interactive: contentHeight > height

    Column {
      id: column
      width: flick.width
      spacing: Style.space(6)

      RowLayout {
        width: column.width
        PanelActionButton {
          iconText: "\u{F004D}"   // nf-md-arrow_left
          tooltipText: "Back"
          foreground: view.foreground
          hoverColor: view.host ? view.host.accent : Color.accent
          onClicked: view.host.back()
        }
        PanelSectionHeader {
          Layout.fillWidth: true
          text: "Assign device"
          foreground: view.foreground
          fontFamily: view.fontFamily
        }
      }

      DeviceRow {
        width: column.width
        visible: view.device !== null
        device: view.device || ({})
        host: view.host
        actions: []
      }

      Button {
        width: column.width
        text: "New person with this device"
        bordered: true
        foreground: view.foreground
        fontFamily: view.fontFamily
        onClicked: view.host.startNewPerson(view.device)
      }

      TextField {
        id: search
        width: column.width
        placeholderText: "Search people"
        foreground: view.foreground
        font.family: view.fontFamily
        onTextChanged: view.query = text
        Keys.onEscapePressed: function(event) {
          if (search.text !== "") search.text = ""
          else view.host.back()
          event.accepted = true
        }
        // Enter with exactly one match assigns it: the quickest path for a known friend.
        Keys.onReturnPressed: function(event) {
          if (view.candidates.length === 1) view.host.assignTo(view.candidates[0].id)
          event.accepted = true
        }
      }

      Text {
        visible: view.host !== null && view.candidates.length === 0 && view.query === ""
        width: column.width
        text: "No people yet: use \"New person with this device\"."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: view.host ? view.host.dim : view.foreground
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Repeater {
        model: view.candidates
        delegate: PersonRow {
          width: column.width
          person: modelData
          host: view.host
          onActivated: view.host.assignTo(modelData.id)
        }
      }
    }
  }
}
