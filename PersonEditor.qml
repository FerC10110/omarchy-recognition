import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Format.js" as Format

// Add or edit a person: name, emoji, and the devices that mean "home".
// Validation lives in the engine; its message shows under the form.
Item {
  id: view
  property var host: null
  property var devices: []            // local copy, see the plan note
  property bool labelFocus: false
  readonly property var draft: host && host.draft ? host.draft : ({ id: "", name: "", emoji: "", group: "home", notify: true, devices: [] })
  readonly property bool typing: nameField.activeFocus || labelFocus
  readonly property color foreground: host ? host.foreground : Color.foreground
  readonly property string fontFamily: host ? host.fontFamily : Style.font.family

  implicitHeight: column.implicitHeight

  // Panel assigns `host` in Loader.onLoaded, which runs after this Item's
  // own Component.onCompleted — so seeding the form there always saw the
  // fallback draft (empty name, no devices). Seed here instead, once `host`
  // is actually set. Read `host.draft` directly rather than the `draft`
  // property above: that binding depends on `host`, but its own dependency
  // on `host.draft` is only established the first time it is *read* with a
  // non-null host, so inside this very handler it can still answer with the
  // stale fallback it returned while `host` was null.
  onHostChanged: {
    if (!host) return
    var d = host.draft || { id: "", name: "", emoji: "", devices: [] }
    nameField.text = d.name
    devices = d.devices.map(function(dv) {
      return { mac: dv.mac, label: dv.label, counts: dv.counts !== false,
               ip: dv.ip, present: dv.present, lastSeen: dv.lastSeen }
    })
    // Panel's emojiPicked() returns here without calling focusKeys(), so
    // coming back from the picker with a non-empty name would otherwise
    // leave focus nowhere. Always (re)focus the name field, not just when
    // it's empty.
    Qt.callLater(function() { nameField.forceActiveFocus() })
  }

  // The flag is mutated in place, exactly like the label field does it: replacing
  // `devices` destroys the delegates, and with them the focus of the label field you
  // may be editing — leaving `labelFocus` stuck true and the panel's keyboard dead.
  // That is the trap removeDevice has to work around with forceActiveFocus; this
  // one avoids it by never replacing the array.
  function setCounts(index, value) {
    devices[index].counts = value
    host.updateDraft({ devices: devices })
  }

  function removeDevice(index) {
    // The ✕ button itself is not focusable, so if the device's own label
    // field currently has focus, move focus to the name field *before* the
    // model is replaced below — replacing `devices` destroys that field's
    // delegate, which would otherwise drop keyboard focus entirely (with
    // `labelFocus` stuck true) instead of raising its activeFocusChanged.
    nameField.forceActiveFocus()
    labelFocus = false
    var next = devices.slice()
    next.splice(index, 1)
    devices = next
    host.updateDraft({ devices: next })
  }

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
          tooltipText: "Back without saving"
          foreground: view.foreground
          hoverColor: view.host ? view.host.accent : Color.accent
          onClicked: view.host.back()
        }
        PanelSectionHeader {
          Layout.fillWidth: true
          text: view.draft.id ? "Edit person" : "New person"
          foreground: view.foreground
          fontFamily: view.fontFamily
        }
      }

      RowLayout {
        width: column.width
        spacing: Style.space(10)

        Button {
          text: view.draft.emoji !== "" ? view.draft.emoji : "Emoji"
          tooltipText: "Choose emoji"
          bordered: true
          fontSize: view.draft.emoji !== "" ? Style.font.display : Style.font.body
          foreground: view.foreground
          fontFamily: view.fontFamily
          onClicked: view.host.pickEmoji()
        }

        TextField {
          id: nameField
          Layout.fillWidth: true
          placeholderText: "Name"
          foreground: view.foreground
          font.family: view.fontFamily
          // Not maximumLength: it counts UTF-16 units, so a name of emojis
          // would stop at half of the 64 characters the engine takes.
          onTextEdited: {
            var fix = Format.limitEdit(text, 64, cursorPosition)
            if (fix.text !== text) { text = fix.text; cursorPosition = fix.at }
          }
          onTextChanged: if (view.host && view.host.draft) view.host.updateDraft({ name: text })
          Keys.onEscapePressed: function(event) { view.host.back(); event.accepted = true }
          Keys.onReturnPressed: function(event) { view.host.saveDraft(); event.accepted = true }
        }
      }

      RowLayout {
        width: column.width
        spacing: Style.space(10)

        Button {
          text: "Lives here"
          bordered: true
          foreground: view.draft.group === "home" || !view.draft.group ? (view.host ? view.host.accent : Color.accent) : view.foreground
          fontFamily: view.fontFamily
          fontSize: Style.font.bodySmall
          onClicked: view.host.updateDraft({ group: "home" })
        }
        Button {
          text: "Neighbor"
          bordered: true
          foreground: view.draft.group === "neighbor" ? (view.host ? view.host.accent : Color.accent) : view.foreground
          fontFamily: view.fontFamily
          fontSize: Style.font.bodySmall
          onClicked: view.host.updateDraft({ group: "neighbor" })
        }
        Button {
          text: "Guest"
          bordered: true
          foreground: view.draft.group === "guest" ? (view.host ? view.host.accent : Color.accent) : view.foreground
          fontFamily: view.fontFamily
          fontSize: Style.font.bodySmall
          onClicked: view.host.updateDraft({ group: "guest" })
        }
        Text {
          Layout.fillWidth: true
          text: view.draft.group === "guest" ? "A visitor in your house."
                : (view.draft.group === "neighbor" ? "Doesn't count as home." : "Counts as home.")
          textFormat: Text.PlainText
          wrapMode: Text.Wrap
          color: view.host ? view.host.dim : view.foreground
          font.family: view.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
      }

      RowLayout {
        width: column.width
        spacing: Style.space(10)

        Button {
          text: "Notify me"
          bordered: true
          foreground: view.draft.notify !== false ? (view.host ? view.host.accent : Color.accent) : view.foreground
          fontFamily: view.fontFamily
          fontSize: Style.font.bodySmall
          onClicked: view.host.updateDraft({ notify: true })
        }
        Button {
          text: "Silent"
          bordered: true
          foreground: view.draft.notify === false ? (view.host ? view.host.accent : Color.accent) : view.foreground
          fontFamily: view.fontFamily
          fontSize: Style.font.bodySmall
          onClicked: view.host.updateDraft({ notify: false })
        }
        Text {
          Layout.fillWidth: true
          text: view.draft.notify === false ? "No arrival or departure notifications."
                                            : "Notifies on arrival and departure."
          textFormat: Text.PlainText
          wrapMode: Text.Wrap
          color: view.host ? view.host.dim : view.foreground
          font.family: view.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
      }

      PanelSectionHeader {
        text: "Devices (" + view.devices.length + ")"
        foreground: view.foreground
        fontFamily: view.fontFamily
      }

      Text {
        visible: view.devices.length === 0
        width: column.width
        text: "No devices: assign one from \"Unassigned\"."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: view.host ? view.host.dim : view.foreground
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Repeater {
        model: view.devices
        delegate: RowLayout {
          id: deviceRow
          required property var modelData
          required property int index
          // The live flag. The model is mutated in place rather than replaced (see Task 5),
          // so this is what the icon and the line below read.
          property bool counts: modelData.counts !== false
          width: column.width
          spacing: Style.space(6)

          ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            TextField {
              Layout.fillWidth: true
              // Seeded, not bound, for the reason DeviceRow's rename field is:
              // the limit below assigns `text`, and that would drop a binding.
              Component.onCompleted: text = modelData.label
              placeholderText: "Label (e.g. phone)"
              foreground: view.foreground
              font.family: view.fontFamily
              onActiveFocusChanged: view.labelFocus = activeFocus
              onTextEdited: {
                var fix = Format.limitEdit(text, 64, cursorPosition)
                if (fix.text !== text) { text = fix.text; cursorPosition = fix.at }
                view.devices[index].label = text
                view.host.updateDraft({ devices: view.devices })
              }
              Keys.onEscapePressed: function(event) { view.host.back(); event.accepted = true }
            }
            Text {
              Layout.fillWidth: true
              text: Format.deviceEditorLine(deviceRow.modelData, deviceRow.counts,
                                            view.host ? view.host.nowMs : Date.now())
              textFormat: Text.PlainText
              elide: Text.ElideRight
              color: view.host ? view.host.dim : view.foreground
              font.family: view.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          PanelActionButton {
            iconText: deviceRow.counts ? "\u{F02DC}" : "\u{F1A46}"   // nf-md-home / nf-md-home_off
            tooltipText: deviceRow.counts ? "Counts for presence" : "Doesn't count for presence"
            foreground: deviceRow.counts ? view.foreground : (view.host ? view.host.dim : view.foreground)
            hoverColor: view.foreground
            onClicked: {
              deviceRow.counts = !deviceRow.counts
              view.setCounts(deviceRow.index, deviceRow.counts)
            }
          }

          PanelActionButton {
            iconText: "\u{F0156}"   // nf-md-close
            tooltipText: "Remove this device"
            foreground: view.foreground
            hoverColor: view.host ? view.host.urgent : Color.urgent
            onClicked: view.removeDevice(index)
          }
        }
      }

      Text {
        visible: view.host !== null && view.host.editorError !== ""
        width: column.width
        text: view.host ? view.host.editorError : ""
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: view.host ? view.host.urgent : Color.urgent
        font.family: view.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      RowLayout {
        width: column.width
        spacing: Style.space(6)
        Button {
          visible: view.draft.id !== ""
          text: "Delete person"
          bordered: true
          foreground: view.host ? view.host.urgent : Color.urgent
          fontFamily: view.fontFamily
          onClicked: view.host.requestDelete()
        }
        Item { Layout.fillWidth: true }
        Button {
          text: "Cancel"
          bordered: true
          foreground: view.foreground
          fontFamily: view.fontFamily
          onClicked: view.host.back()
        }
        Button {
          text: "Save"
          bordered: true
          foreground: view.host ? view.host.accent : Color.accent
          fontFamily: view.fontFamily
          onClicked: view.host.saveDraft()
        }
      }
    }
  }
}
