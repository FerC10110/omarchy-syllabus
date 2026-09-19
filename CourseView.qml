import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// One course: header with progress and actions, and tabs for its videos,
// tasks, links, note and files.
Item {
  id: root

  property var app
  property var course: null
  property string tab: "videos"

  readonly property var owner: course ? { kind: "course", id: course.id } : null
  readonly property var tabs: course ? [
    { key: "videos", label: "Videos" },
    { key: "tasks", label: "Tasks" + (course.taskCount > 0 ? " " + course.taskDone + "/" + course.taskCount : "") },
    { key: "links", label: "Links" + (course.links.length > 0 ? " " + course.links.length : "") },
    { key: "notes", label: "Notes" + (course.hasNote ? " •" : "") },
    { key: "files", label: "Files" + (course.docCount > 0 ? " " + course.docCount : "") }
  ] : []

  Loader {
    anchors.fill: parent
    anchors.margins: Style.spacing.panelPadding
    active: root.course !== null
    sourceComponent: content
  }

  Component {
    id: content

    ColumnLayout {
      spacing: Style.spacing.panelGap

      RowLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.xxl

        Button {
          Layout.alignment: Qt.AlignTop
          iconText: Model.icon("chevronLeft")
          tooltipText: "Back"
          onClicked: root.app.back()
        }

        CoverImage {
          Layout.preferredWidth: 176
          Layout.preferredHeight: 99
          source: root.course.cover
          title: root.course.title
        }

        ColumnLayout {
          Layout.fillWidth: true
          spacing: Style.spacing.sm

          Text {
            text: root.course.topic !== "" ? root.course.topic : "No topic"
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          Text {
            Layout.fillWidth: true
            text: root.course.title
            wrapMode: Text.Wrap
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.heading
            font.bold: true
          }

          Text {
            Layout.fillWidth: true
            text: root.course.seenCount + "/" + root.course.lessonCount + " videos · "
              + Model.fmtDuration(root.course.duration) + " · " + Model.progressLabel(root.course)
              + (root.course.online ? "" : " · disk not mounted")
            elide: Text.ElideRight
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }

          ProgressLine {
            Layout.fillWidth: true
            value: root.course.percent / 100
          }
        }

        ColumnLayout {
          Layout.alignment: Qt.AlignTop
          spacing: Style.spacing.sm

          Button {
            iconText: Model.icon("play")
            text: "Continue"
            bordered: true
            onClicked: root.app.resume(root.course.id)
          }

          Button {
            iconText: Model.icon("cog")
            text: "Edit course"
            onClicked: root.app.editCourse(root.course)
          }
        }
      }

      RowLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.sm

        Repeater {
          model: root.tabs

          Button {
            text: modelData.label
            selected: root.tab === modelData.key
            onClicked: root.tab = modelData.key
          }
        }
      }

      StackLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        currentIndex: ["videos", "tasks", "links", "notes", "files"].indexOf(root.tab)

        LessonsTab {
          app: root.app
          course: root.course
        }

        Flickable {
          id: tasksFlick
          clip: true
          contentWidth: width
          contentHeight: courseTasks.implicitHeight
          boundsBehavior: Flickable.StopAtBounds
          QQC.ScrollBar.vertical: QQC.ScrollBar {}

          ChecklistEditor {
            id: courseTasks
            width: tasksFlick.width
            app: root.app
            owner: root.owner
            tasks: root.course.tasks
            title: "Course tasks"
          }
        }
        Flickable {
          id: linksFlick
          clip: true
          contentWidth: width
          contentHeight: courseLinks.implicitHeight
          boundsBehavior: Flickable.StopAtBounds
          QQC.ScrollBar.vertical: QQC.ScrollBar {}

          LinksTab {
            id: courseLinks
            width: linksFlick.width
            app: root.app
            owner: root.owner
            links: root.course.links
          }
        }

        NotesTab {
          app: root.app
          course: root.course
          active: root.tab === "notes"
        }

        FilesTab {
          app: root.app
          course: root.course
          active: root.tab === "files"
        }
      }
    }
  }
}
