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

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.panel ? root.panel.barText : "\u{F02DC}"
    // BarIconButton fixes its slot to `slotSize` along the bar's long axis —
    // width when horizontal, height when vertical (its own fixedWidth/
    // fixedHeight). Our face can be more than one glyph ("🦊🐱 +2"), which
    // overflows the single-icon default, so widen the slot to the text's own
    // painted width (glyphPaintedWidth, from the same OpticalGlyph the button
    // already renders). Only in the horizontal case: in a vertical bar the
    // slot's *width* still comes from the bar's fixed thickness regardless of
    // slotSize, so growing slotSize there only changes height, which the
    // painted (horizontal) text width has nothing to do with — leave it at
    // the default so we don't waste vertical space for no benefit.
    slotSize: vertical ? Style.bar.statusSlot
                        : Math.max(Style.bar.statusSlot, glyphPaintedWidth + Style.space(8))
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
