import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar icon for Syllabus. It loads the panel and hands it the bar and itself, so
// the panel opens under the icon (same as Runbook). Click: open or close the
// panel. Right click: continue the last video (or the next one of its roadmap).
// The tooltip is read from `syllabus summary` each time the pointer rests on
// the icon: no timers, since there is one widget per monitor.
BarWidget {
  id: root
  moduleName: "io.github.ferc10110.syllabus"

  // What the shell's `shell toggle` reads and calls on the icon of the focused monitor.
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function toggle() { if (panelLoader.item) panelLoader.item.toggle() }

  readonly property string bin: {
    var url = String(Qt.resolvedUrl("bin/syllabus"))
    return url.indexOf("file://") === 0 ? decodeURIComponent(url.substring(7)) : url
  }
  property string summary: "Syllabus"

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    target.bar = root.bar
    target.settings = root.settings
    target.anchorItem = button
    target.hostWidget = root
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: String.fromCodePoint(0xF0474)
    tooltipText: root.summary
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.RightButton) Util.execArgv([root.bin, "resume", "--notify"])
      else root.toggle()
    }
    onTooltipHoveredChanged: {
      if (tooltipHovered && !summaryProc.running) summaryProc.running = true
    }
  }

  Process {
    id: summaryProc
    command: [root.bin, "summary"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var data = JSON.parse(String(text || ""))
          if (data.text) root.summary = "Syllabus\n" + data.text
        } catch (e) {}
      }
    }
  }
}
