import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// Left column: what to play next, the roadmaps, the library by topic, and
// today's study time with the streak.
Rectangle {
  id: root

  property var app

  readonly property var cont: app.view ? app.view["continue"] : null
  readonly property var today: app.view ? app.view.today : null
  readonly property var topics: Model.topicCounts(app.courses)
  // Same data as the library's banner: roots whose folder is not there.
  readonly property int offline: app.view ? app.view.roots.filter(function(r) { return !r.online }).length : 0

  color: Util.alpha(Color.foreground, 0.03)

  function newRoadmap() {
    root.app.prompt("New roadmap", [{ key: "title", label: "Title", text: "", placeholder: "AI Engineering" }], "Create",
      function(values) {
        root.app.apply({ op: "roadmap.add", title: values.title }, function(result) { root.app.go("roadmap", result.id) })
      })
  }

  ColumnLayout {
    anchors.fill: parent
    anchors.margins: Style.spacing.xxl
    spacing: Style.spacing.xl

    Rectangle {
      id: continueCard
      Layout.fillWidth: true
      visible: root.cont !== null
      implicitHeight: continueColumn.implicitHeight + 2 * Style.spacing.xl
      radius: Style.cornerRadius
      color: continueMouse.containsMouse ? Util.alpha(Color.accent, 0.16) : Util.alpha(Color.accent, 0.10)

      MouseArea {
        id: continueMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.app.go("course", root.cont.courseId)
      }

      ColumnLayout {
        id: continueColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Style.spacing.xl
        spacing: Style.spacing.sm

        Text {
          text: "CONTINUE"
          color: Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        Text {
          Layout.fillWidth: true
          text: root.cont ? root.cont.courseTitle : ""
          wrapMode: Text.Wrap
          maximumLineCount: 2
          elide: Text.ElideRight
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          font.bold: true
        }

        Text {
          Layout.fillWidth: true
          text: root.cont ? root.cont.title : ""
          elide: Text.ElideRight
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        ProgressLine {
          Layout.fillWidth: true
          value: root.cont ? Model.fraction(root.cont.pos, root.cont.duration) : 0
        }

        RowLayout {
          Layout.fillWidth: true

          Text {
            Layout.fillWidth: true
            text: !root.cont ? "" : (root.cont.online
              ? Model.fmtClock(root.cont.pos) + " / " + Model.fmtClock(root.cont.duration)
              : "Disk not mounted")
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          Button {
            visible: root.cont !== null && root.cont.online
            iconText: Model.icon("play")
            text: "Play"
            bordered: true
            onClicked: root.app.play(root.cont.lessonId)
          }
        }
      }
    }

    Flickable {
      id: flick
      Layout.fillWidth: true
      Layout.fillHeight: true
      clip: true
      contentWidth: width
      contentHeight: lists.implicitHeight
      boundsBehavior: Flickable.StopAtBounds
      QQC.ScrollBar.vertical: QQC.ScrollBar {}

      Column {
        id: lists
        width: flick.width
        spacing: Style.spacing.xs

        RowLayout {
          width: lists.width

          Text {
            Layout.fillWidth: true
            text: "ROADMAPS"
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            font.bold: true
          }

          Button {
            iconText: Model.icon("plus")
            tooltipText: "New roadmap"
            onClicked: root.newRoadmap()
          }
        }

        Repeater {
          model: root.app.roadmaps

          NavRow {
            width: lists.width
            icon: Model.icon("roadmap")
            label: modelData.title
            detail: Math.round(modelData.percent) + "%"
            progress: modelData.percent / 100
            selected: root.app.page === "roadmap" && root.app.selectedId === modelData.id
            onClicked: root.app.go("roadmap", modelData.id)
          }
        }

        Text {
          visible: root.app.roadmaps.length === 0
          leftPadding: Style.spacing.lg
          text: "No roadmaps yet"
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Item { width: 1; height: Style.spacing.xl }

        Text {
          text: "LIBRARY"
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        NavRow {
          width: lists.width
          icon: Model.icon("library")
          label: "All courses"
          detail: String(root.app.courses.length)
          selected: root.app.page === "library" && root.app.topicFilter === ""
          onClicked: root.app.openLibrary("")
        }

        Repeater {
          model: root.topics

          NavRow {
            width: lists.width
            label: modelData.topic !== "" ? modelData.topic : "No topic"
            detail: String(modelData.count)
            selected: root.app.page === "library"
              && root.app.topicFilter === (modelData.topic !== "" ? modelData.topic : "__none__")
            onClicked: root.app.openLibrary(modelData.topic !== "" ? modelData.topic : "__none__")
          }
        }
      }
    }

    ColumnLayout {
      Layout.fillWidth: true
      spacing: Style.spacing.xs

      Text {
        Layout.fillWidth: true
        visible: root.offline > 0
        text: Model.icon("disk") + " " + (root.offline === 1 ? "Disk offline" : root.offline + " disks offline")
        elide: Text.ElideRight
        color: Color.urgent
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      RowLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.md

        Text {
          Layout.fillWidth: true
          text: root.today
            ? Model.icon("fire") + " " + Model.fmtStudy(root.today.seconds) + " today · " + Model.daysLabel(root.today.streak)
            : ""
          elide: Text.ElideRight
          color: root.today && root.today.streak > 0 ? Color.foreground : Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Button {
          iconText: Model.icon(root.app.pinned ? "pin" : "pinOff")
          tooltipText: root.app.pinned ? "Pinned: stays open when you click outside" : "Pin: stay open when you click outside"
          selected: root.app.pinned
          onClicked: root.app.togglePin()
        }

        Button {
          iconText: Model.icon("cog")
          tooltipText: "Settings"
          selected: root.app.page === "settings"
          onClicked: root.app.go("settings", "")
        }
      }
    }
  }
}
