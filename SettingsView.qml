import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// Settings: the library disk, playback, the streak, Readily, and where the files are.
Item {
  id: root

  property var app

  readonly property var config: app.config
  readonly property var roots: app.view ? app.view.roots : []
  readonly property var paths: app.view ? app.view.paths : null

  function set(key, value) {
    app.apply({ op: "config.set", key: key, value: value })
  }

  function setNumber(key, text, divisor) {
    var n = Number(String(text).trim().replace(",", "."))
    if (String(text).trim() === "" || !isFinite(n)) { app.showNotice("Write a number", true); return }
    set(key, divisor ? n / divisor : n)
  }

  Loader {
    anchors.fill: parent
    anchors.margins: Style.spacing.panelPadding
    active: root.config !== null
    sourceComponent: content
  }

  Component {
    id: content

    Flickable {
      id: flick
      clip: true
      contentWidth: width
      contentHeight: col.implicitHeight
      boundsBehavior: Flickable.StopAtBounds
      QQC.ScrollBar.vertical: QQC.ScrollBar {}

      ColumnLayout {
        id: col
        width: flick.width
        spacing: Style.spacing.xl

        Text {
          text: "Settings"
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.heading
          font.bold: true
        }

        Text {
          text: "LIBRARY"
          color: Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        Repeater {
          model: root.roots

          ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.spacing.xs

            Text {
              Layout.fillWidth: true
              text: Model.icon("disk") + "  " + modelData.path
              elide: Text.ElideMiddle
              color: Color.foreground
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }

            Text {
              text: (modelData.online ? "Mounted" : "Not mounted") + " · " + modelData.courseCount + " courses · scanned "
                + Model.fmtWhen(modelData.scannedAt)
              color: modelData.online ? Color.muted : Color.urgent
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
            }
          }
        }

        RowLayout {
          spacing: Style.spacing.controlGap

          Button {
            iconText: Model.icon("refresh")
            iconSpinning: root.app.scanning
            text: "Rescan"
            tooltipText: "New and changed videos"
            onClicked: root.app.scan(false)
          }

          Button {
            text: "Read every duration again"
            tooltipText: "Slow: runs ffprobe on every video"
            onClicked: root.app.scan(true)
          }
        }

        Text {
          Layout.fillWidth: true
          wrapMode: Text.Wrap
          text: "Another disk or folder can be added by hand to \"roots\" in " + (root.paths ? root.paths.config : "config.json") + "."
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Text {
          text: "PLAYBACK"
          color: Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        SettingField {
          Layout.fillWidth: true
          label: "Player"
          description: "mpv, or a command that takes mpv's options."
          text: root.config.player.command
          onCommitted: function(text) { root.set("player.command", text) }
        }

        SettingField {
          Layout.fillWidth: true
          label: "Extra player options"
          description: "Added to every launch, separated by spaces, e.g. --fs --volume=70"
          text: root.config.player.args.join(" ")
          onCommitted: function(text) { root.set("player.args", Model.splitArgs(text)) }
        }

        SettingField {
          Layout.fillWidth: true
          label: "Rewind when resuming (seconds)"
          text: String(root.config.resumeRewind)
          onCommitted: function(text) { root.setNumber("resumeRewind", text) }
        }

        SettingField {
          Layout.fillWidth: true
          label: "Watched from (%)"
          description: "A video counts as watched once playback passes this point."
          text: String(Math.round(root.config.seenThreshold * 100))
          onCommitted: function(text) { root.setNumber("seenThreshold", text, 100) }
        }

        SettingField {
          Layout.fillWidth: true
          label: "Save the position every (seconds)"
          description: "Applies from the next time mpv starts."
          text: String(root.config.reportSeconds)
          onCommitted: function(text) { root.setNumber("reportSeconds", text) }
        }

        Text {
          text: "STUDY"
          color: Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        SettingField {
          Layout.fillWidth: true
          label: "Minutes that make a streak day"
          text: String(root.config.streakMinutes)
          onCommitted: function(text) { root.setNumber("streakMinutes", text) }
        }

        Text {
          text: "READILY"
          color: Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        Toggle {
          Layout.fillWidth: true
          Layout.maximumWidth: 520
          label: "Integrate with Readily"
          description: "Save links to Readily and list its items that carry the course's tag."
          checked: root.config.readily.enabled
          onClicked: root.set("readily.enabled", !root.config.readily.enabled)
        }

        SettingField {
          Layout.fillWidth: true
          visible: root.config.readily.enabled
          label: "Readily section"
          description: "Where saved links go. Created if it does not exist."
          text: root.config.readily.section
          onCommitted: function(text) { root.set("readily.section", text) }
        }

        Text {
          text: "FILES"
          color: Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        Text {
          Layout.fillWidth: true
          wrapMode: Text.Wrap
          text: root.paths ? "Library: " + root.paths.library + "\nProgress: " + root.paths.state + "\nSettings: " + root.paths.config : ""
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Button {
          iconText: Model.icon("open")
          text: "Open the settings folder"
          onClicked: root.app.openExternal(root.paths.configDir)
        }
      }
    }
  }
}
