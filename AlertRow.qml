import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Format.js" as Format

// One network alert: what happened and what can be done about it.
Item {
  id: row
  property var alert: ({})
  property var host: null

  implicitHeight: column.implicitHeight + Style.space(8)

  ColumnLayout {
    id: column
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    anchors.leftMargin: Style.space(6)
    spacing: Style.space(4)

    Text {
      Layout.fillWidth: true
      text: Format.alertText(row.alert)
      textFormat: Text.PlainText
      wrapMode: Text.Wrap
      color: row.host ? row.host.urgent : Color.urgent
      font.family: row.host ? row.host.fontFamily : Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    RowLayout {
      spacing: Style.space(6)
      Button {
        visible: row.alert.kind === "gateway-mac"
        text: "It's my new router"
        tooltipText: "Accept the new MAC as the router's"
        bordered: true
        foreground: row.host ? row.host.foreground : Color.foreground
        fontFamily: row.host ? row.host.fontFamily : Style.font.family
        fontSize: Style.font.bodySmall
        onClicked: row.host.acceptGateway()
      }
      Button {
        text: "Dismiss"
        bordered: true
        foreground: row.host ? row.host.foreground : Color.foreground
        fontFamily: row.host ? row.host.fontFamily : Style.font.family
        fontSize: Style.font.bodySmall
        onClicked: row.host.dismissAlert(row.alert)
      }
      Item { Layout.fillWidth: true }
    }
  }
}
