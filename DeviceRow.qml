import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Format.js" as Format

// One device: a presence dot, a title (a text field while `editing`), a detail
// line, and one button per name in `actions` ("suggest", "assign", "house",
// "forget", "rename", "remove"). The owner keeps the edited text in `editText`, so a
// status refresh that recreates this row doesn't lose it.
Item {
  id: row
  property var device: ({})
  property var host: null
  property var actions: []
  // The suggestion button's text depends on the person, so it cannot live in the fixed
  // map below; `labels` reads it from here.
  property string suggestionLabel: ""
  property string title: Format.deviceTitle(device)
  property string detail: Format.deviceDetail(device, host ? host.nowMs : Date.now())
  property bool editing: false
  property string editText: ""
  signal action(string name)
  signal editEdited(string text)
  signal editAccepted()
  signal editCanceled()
  signal contextRequested(point scenePos)

  readonly property var labels: ({ assign: "Assign", house: "House", forget: "Forget", rename: "Rename",
                                   remove: "Remove", suggest: row.suggestionLabel })
  readonly property color foreground: host ? host.foreground : Color.foreground

  implicitHeight: Math.max(Style.space(40), texts.implicitHeight + Style.space(8))

  function focusEditor() { if (row.editing) editField.forceActiveFocus() }
  // The field is seeded, not bound to editText: the character limit below has
  // to assign `text`, and an assignment drops a binding for good.
  // Both seeds are load-bearing, do not drop either: onEditingChanged is the
  // one that fires when a rename starts on a live row, and Component.onCompleted
  // is the one that covers a row the scan recreates mid-rename (there `editing`
  // can go true while `editText` is still empty, because the owner's bindings
  // are evaluated in declaration order).
  function seedEditor() { editField.text = row.editText }
  onEditingChanged: if (editing) { row.seedEditor(); Qt.callLater(row.focusEditor) }
  Component.onCompleted: if (editing) { row.seedEditor(); Qt.callLater(row.focusEditor) }

  // Right-click anywhere on the row opens the panel's context menu. Declared before
  // the layout so it sits underneath it, and right-button only so it never gets in
  // the way of the buttons or of the rename field.
  MouseArea {
    anchors.fill: parent
    acceptedButtons: Qt.RightButton
    onClicked: function(mouse) { row.contextRequested(mapToItem(null, mouse.x, mouse.y)) }
  }

  RowLayout {
    anchors.fill: parent
    anchors.leftMargin: Style.space(6)
    anchors.rightMargin: Style.space(4)
    spacing: Style.space(8)

    Text {
      text: "●"
      color: row.device.present ? (row.host ? row.host.accent : Color.accent) : Util.alpha(row.foreground, 0.25)
      font.pixelSize: Style.font.caption
    }

    ColumnLayout {
      id: texts
      Layout.fillWidth: true
      spacing: 0
      Text {
        visible: !row.editing
        Layout.fillWidth: true
        text: row.title
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: row.foreground
        font.family: row.host ? row.host.fontFamily : Style.font.family
        font.pixelSize: Style.font.body
      }
      TextField {
        id: editField
        visible: row.editing
        Layout.fillWidth: true
        foreground: row.foreground
        font.family: row.host ? row.host.fontFamily : Style.font.family
        // Match the kit's own row-embedded inline field (network Panel's
        // passphrase prompt): drop verticalPadding from the default
        // inputPaddingY to controlPaddingY so editing doesn't grow the row.
        verticalPadding: Style.spacing.controlPaddingY
        onTextEdited: {
          var fix = Format.limitEdit(text, 64, cursorPosition)
          if (fix.text !== text) { text = fix.text; cursorPosition = fix.at }
          row.editEdited(text)
        }
        Keys.onReturnPressed: function(event) { row.editAccepted(); event.accepted = true }
        Keys.onEnterPressed: function(event) { row.editAccepted(); event.accepted = true }
        Keys.onEscapePressed: function(event) { row.editCanceled(); event.accepted = true }
      }
      Text {
        Layout.fillWidth: true
        text: row.detail
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: row.host ? row.host.dim : row.foreground
        font.family: row.host ? row.host.fontFamily : Style.font.family
        font.pixelSize: Style.font.caption
      }
    }

    Repeater {
      model: row.editing ? [] : row.actions
      delegate: Button {
        text: row.labels[modelData] || modelData
        bordered: true
        foreground: modelData === "forget" && row.host ? row.host.urgent : row.foreground
        fontFamily: row.host ? row.host.fontFamily : Style.font.family
        fontSize: Style.font.bodySmall
        onClicked: row.action(modelData)
        onRightClicked: row.contextRequested(mapToItem(null, width / 2, height / 2))
      }
    }

    // While renaming, Enter and Esc are not the only way out: the mouse needs
    // its own, and these take the place of the row's usual buttons.
    Button {
      visible: row.editing
      text: "Save"
      bordered: true
      foreground: row.foreground
      fontFamily: row.host ? row.host.fontFamily : Style.font.family
      fontSize: Style.font.bodySmall
      onClicked: row.editAccepted()
      onRightClicked: row.contextRequested(mapToItem(null, width / 2, height / 2))
    }
    Button {
      visible: row.editing
      text: "Cancel"
      bordered: true
      foreground: row.foreground
      fontFamily: row.host ? row.host.fontFamily : Style.font.family
      fontSize: Style.font.bodySmall
      onClicked: row.editCanceled()
      onRightClicked: row.contextRequested(mapToItem(null, width / 2, height / 2))
    }
  }
}
