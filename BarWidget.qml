import QtQuick
import qs.Commons
import qs.Ui

// Bar entry point for Recognition: the emojis of whoever is home. The panel is
// always loaded because it owns the scan timer; it is injected with the bar
// context like Runbook's. Left click opens/closes the panel; right click scans now.
BarWidget {
  id: root
  moduleName: "io.github.ferc10110.recognition"

  readonly property var panel: panelLoader.item
  readonly property bool opened: panel ? panel.opened === true : false
  readonly property bool popoutSwitchClosing: panel ? panel.popoutSwitchClosing === true : false

  function open() { if (panel) panel.open() }
  function close() { if (panel) panel.close() }
  function togglePanel() { if (panel) panel.toggle() }
  function closeForPopoutSwitch() { if (panel) panel.closeForPopoutSwitch() }

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = anchorProxy
    if ("hostWidget" in target) target.hostWidget = root
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  // Omarchy 4.5 normalises BarIconButton's text as a single icon: the whole
  // string is scaled into Style.bar.iconSize, so a face of several emoji
  // ("🦊🐱 +2") shrinks to a few pixels however wide the slot is. Render the
  // face as a text label instead — WidgetButton leaves label text at its own
  // size and only normalises a single icon glyph, which the fallback face
  // still is. horizontalMargin 4 keeps the old 8px of breathing room around
  // the label, and fixedWidth keeps the old status slot as the minimum.
  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.panel ? root.panel.barText : "\u{F02DC}"
    labelVisible: true
    fontSize: Style.bar.iconFont
    horizontalMargin: 4
    fixedWidth: vertical ? -1
                           : Math.max(Style.bar.statusSlot, labelWidth + Style.space(8))
    fixedHeight: vertical ? Style.bar.statusSlot : -1
    dimmed: root.panel ? root.panel.barDimmed : true
    active: root.panel ? root.panel.barActive : false
    activeColor: root.panel ? root.panel.barActiveColor : Color.urgent
    tooltipText: root.panel ? root.panel.barTooltip : "Recognition"
    onPressed: function(b) {
      if (!root.panel) return
      if (b === Qt.RightButton) root.panel.scanNow()
      else root.togglePanel()
    }

    // The panel hangs from this item instead of from the button itself, so
    // moving it moves the panel along the bar. An Item with no children paints
    // nothing, and the KeyboardPanel's TransformWatcher makes the move reactive.
    Item {
      id: anchorProxy
      width: button.width
      height: button.height
      x: root.panel ? root.panel.anchorOffsetX : 0
      y: root.panel ? root.panel.anchorOffsetY : 0
    }
  }
}
