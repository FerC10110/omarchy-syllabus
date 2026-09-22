import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// Every course, grouped by topic, with search and the topic chosen in the sidebar.
Item {
  id: root

  property var app

  readonly property var filtered: Model.filterCourses(app.courses, app.query, app.topicFilter)
  readonly property var groups: Model.groupByTopic(filtered)
  readonly property var offline: app.view ? app.view.roots.filter(function(r) { return !r.online }) : []
  readonly property int gap: Style.spacing.xxl
  readonly property int columns: Math.max(1, Math.floor((flick.width + gap) / (250 + gap)))
  readonly property real cardWidth: Math.floor((flick.width - (columns - 1) * gap) / columns)
  readonly property string heading: app.topicFilter === "" ? "Library"
    : (app.topicFilter === "__none__" ? "Courses without topic" : app.topicFilter)

  ColumnLayout {
    anchors.fill: parent
    anchors.margins: Style.spacing.panelPadding
    spacing: Style.spacing.panelGap

    RowLayout {
      Layout.fillWidth: true
      spacing: Style.spacing.controlGap

      Text {
        text: root.heading
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.heading
        font.bold: true
      }

      Button {
        visible: root.app.topicFilter !== ""
        iconText: Model.icon("close")
        tooltipText: "Show every course"
        onClicked: root.app.topicFilter = ""
      }

      Item { Layout.fillWidth: true }

      TextField {
        Layout.preferredWidth: 260
        placeholderText: "Search courses"
        text: root.app.query
        onTextChanged: root.app.query = text
      }

      Button {
        iconText: Model.icon("web")
        text: "Add from the web"
        tooltipText: "A YouTube playlist, a Vimeo showcase or a single video"
        onClicked: root.app.openWebAdd()
      }

      Button {
        iconText: Model.icon("refresh")
        iconSpinning: root.app.scanning
        text: root.app.scanning ? "Scanning…" : "Rescan"
        tooltipText: "Look for new videos on the disk"
        onClicked: root.app.scan(false)
      }
    }

    Rectangle {
      Layout.fillWidth: true
      visible: root.offline.length > 0
      implicitHeight: offlineText.implicitHeight + 2 * Style.spacing.lg
      radius: Style.cornerRadius
      color: Util.alpha(Color.urgent, 0.15)

      Text {
        id: offlineText
        anchors.fill: parent
        anchors.margins: Style.spacing.lg
        wrapMode: Text.Wrap
        text: "The course disk is not mounted. You can browse and edit everything; playing needs the disk."
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }
    }

    Text {
      Layout.fillWidth: true
      visible: root.app.courses.length === 0
      wrapMode: Text.Wrap
      text: root.app.scanning
        ? "Scanning the disk… The first scan reads the length of every video and can take a minute."
        : "No courses yet. Mount the disk and press Rescan."
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    Flickable {
      id: flick
      Layout.fillWidth: true
      Layout.fillHeight: true
      clip: true
      contentWidth: width
      contentHeight: groupsColumn.implicitHeight
      boundsBehavior: Flickable.StopAtBounds
      QQC.ScrollBar.vertical: QQC.ScrollBar {}

      Column {
        id: groupsColumn
        width: flick.width
        spacing: Style.spacing.huge

        Repeater {
          model: root.groups

          Column {
            width: groupsColumn.width
            spacing: Style.spacing.lg

            Text {
              visible: root.app.topicFilter === ""
              text: modelData.topic !== "" ? modelData.topic : "No topic"
              color: Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.subtitle
              font.bold: true
            }

            Flow {
              width: parent.width
              spacing: root.gap

              Repeater {
                model: modelData.courses

                CourseCard {
                  width: root.cardWidth
                  app: root.app
                  course: modelData
                }
              }
            }
          }
        }
      }
    }
  }
}
