import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Format.js" as Format

// What one manual command printed: the command, what it ran on, how it ended, and
// its output, selectable and copyable. Nothing here is stored — leaving forgets it.
Item {
  id: view
  property var host: null
  // No text field here, so the panel's key catcher never has to step aside.
  readonly property bool typing: false
  readonly property var run: host ? host.runResult : null
  readonly property string output: run && run.output ? String(run.output) : ""
  readonly property string status: host && host.runError !== "" ? host.runError
                                 : (run ? Format.runSummary(run) : "running…")
  readonly property color foreground: host ? host.foreground : Color.foreground
  readonly property color dim: host ? host.dim : Color.foreground
  readonly property color urgent: host ? host.urgent : Color.urgent
  readonly property string fontFamily: host ? host.fontFamily : Style.font.family

  implicitHeight: column.implicitHeight

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
      spacing: Style.space(8)

      RowLayout {
        width: column.width
        PanelActionButton {
          iconText: "\u{F004D}"   // nf-md-arrow_left
          tooltipText: "Close"
          foreground: view.foreground
          hoverColor: view.host ? view.host.accent : Color.accent
          onClicked: view.host.closeResult()
        }
        PanelSectionHeader {
          Layout.fillWidth: true
          text: "Command"
          foreground: view.foreground
          fontFamily: view.fontFamily
        }
      }

      Text {
        width: column.width
        text: view.host ? Format.commandOneLine(view.host.runCommand) : ""
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        maximumLineCount: 3
        elide: Text.ElideRight
        color: view.foreground
        font.family: view.fontFamily
        font.pixelSize: Style.font.body
      }

      Text {
        width: column.width
        visible: view.host !== null && view.host.runTarget !== ""
        text: "on " + (view.host ? view.host.runTarget : "")
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: view.dim
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Text {
        width: column.width
        text: view.status
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: view.host && view.host.runError !== "" ? view.urgent
             : (view.run && !view.run.ok ? view.urgent : view.dim)
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Rectangle {
        width: column.width
        height: Math.max(Style.space(90), Math.min(Style.space(260), outputText.implicitHeight + Style.space(16)))
        color: Util.alpha(view.foreground, 0.06)
        radius: Style.cornerRadius

        Flickable {
          id: outFlick
          anchors.fill: parent
          anchors.margins: Style.space(8)
          clip: true
          contentWidth: width
          contentHeight: outputText.implicitHeight
          boundsBehavior: Flickable.StopAtBounds
          interactive: contentHeight > height

          TextEdit {
            id: outputText
            width: outFlick.width
            readOnly: true
            selectByMouse: true
            textFormat: TextEdit.PlainText
            wrapMode: TextEdit.WrapAtWordBoundaryOrAnywhere
            // Style.fontFamily is already monospace in this shell, so the output
            // lines up without asking for another font.
            text: view.output !== "" ? view.output : (view.run ? "(no output)" : "")
            color: view.output !== "" ? view.foreground : view.dim
            font.family: view.fontFamily
            font.pixelSize: Style.font.bodySmall
          }
        }
      }

      Text {
        width: column.width
        visible: view.run !== null && view.run.truncated === true
        text: "output cut at 8 kB"
        textFormat: Text.PlainText
        color: view.dim
        font.family: view.fontFamily
        font.pixelSize: Style.font.caption
      }

      RowLayout {
        width: column.width
        spacing: Style.space(8)
        Item { Layout.fillWidth: true }
        Button {
          text: "Copy"
          bordered: true
          enabled: view.run !== null || (view.host !== null && view.host.runError !== "")
          foreground: enabled ? view.foreground : view.dim
          fontFamily: view.fontFamily
          fontSize: Style.font.bodySmall
          // With no output there is still something worth copying: the status line
          // is where a failure says what went wrong.
          onClicked: view.host.copyText(view.output !== "" ? view.output : view.status, "the output")
        }
        Button {
          text: "Close"
          bordered: true
          foreground: view.foreground
          fontFamily: view.fontFamily
          fontSize: Style.font.bodySmall
          onClicked: view.host.closeResult()
        }
      }
    }
  }
}
