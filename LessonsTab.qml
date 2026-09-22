import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// The course's videos in order. "Edit" shows the curation buttons; hidden videos
// (including the ones too short to be real) can be shown here to bring them back.
Item {
  id: root

  property var app
  property var course
  property bool showHidden: false
  property bool editing: false
  property var expanded: ({})

  readonly property var lessons: course ? Model.visibleLessons(course.lessons, showHidden) : []
  readonly property int hidden: course ? Model.hiddenCount(course.lessons) : 0

  function toggleExpanded(id) {
    var next = Object.assign({}, expanded)
    if (next[id]) delete next[id]
    else next[id] = true
    expanded = next
  }

  ColumnLayout {
    anchors.fill: parent
    spacing: Style.spacing.lg

    RowLayout {
      Layout.fillWidth: true
      spacing: Style.spacing.controlGap

      Button {
        iconText: Model.icon("pencil")
        text: root.editing ? "Done" : "Edit order and names"
        selected: root.editing
        onClicked: root.editing = !root.editing
      }

      Button {
        visible: root.hidden > 0
        iconText: Model.icon(root.showHidden ? "eye" : "eyeOff")
        text: (root.showHidden ? "Hide " : "Show ") + root.hidden + " hidden"
        onClicked: root.showHidden = !root.showHidden
      }

      Button {
        visible: root.editing && root.course && root.course.web !== null
        iconText: Model.icon("plus")
        text: "Add a video"
        tooltipText: "Paste another link into this course"
        onClicked: root.app.openWebAdd(root.course.id)
      }

      Item { Layout.fillWidth: true }
    }

    Flickable {
      id: flick
      Layout.fillWidth: true
      Layout.fillHeight: true
      clip: true
      contentWidth: width
      contentHeight: list.implicitHeight
      boundsBehavior: Flickable.StopAtBounds
      QQC.ScrollBar.vertical: QQC.ScrollBar {}

      Column {
        id: list
        width: flick.width
        spacing: Style.spacing.xxs

        // A count, not the lessons array: a refresh comes about every 30 s while
        // mpv plays, and an array model would rebuild every row (hover and
        // tooltips reset) whenever any video's progress changed. Each row
        // follows the lesson now at its position; rows are rebuilt only when
        // the number of visible videos changes.
        Repeater {
          model: root.lessons.length

          Column {
            id: entry

            readonly property var lesson: root.lessons[index]

            width: list.width

            Text {
              visible: Model.showGroup(root.lessons, index)
              topPadding: Style.spacing.lg
              bottomPadding: Style.spacing.xs
              text: entry.lesson.group
              color: Color.accent
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              font.bold: true
            }

            LessonRow {
              width: list.width
              app: root.app
              course: root.course
              lesson: entry.lesson
              position: index
              count: root.lessons.length
              editing: root.editing
              expanded: root.expanded[entry.lesson.id] === true
              onToggleBookmarks: root.toggleExpanded(entry.lesson.id)
            }
          }
        }
      }
    }
  }
}
