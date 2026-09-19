import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// One stage of a roadmap: its courses in order with their progress and the
// stage's own checklist. With `editing` on it also moves, renames and deletes
// the stage, reorders and removes its courses and has a picker to add more.
Rectangle {
  id: card

  property var app
  property var roadmap
  property var stage
  property int position: 0
  property int count: 0
  property bool editing: false
  property bool showTasks: stage.taskCount > 0

  readonly property var owner: ({ kind: "stage", roadmapId: roadmap.id, id: stage.id })
  readonly property string stageId: stage ? stage.id : ""

  // RoadmapView keeps its cards through refreshes, so after a stage moves this
  // card shows another stage: start from that stage's default, not from the
  // one that was here before (the checklist clears its own draft the same way).
  onStageIdChanged: showTasks = Qt.binding(function() { return card.stage.taskCount > 0 })

  implicitHeight: col.implicitHeight + 2 * Style.spacing.xl
  radius: Style.cornerRadius
  color: Style.normalFill
  border.width: Style.normalBorderWidth
  border.color: Style.normalBorderColor

  // Used only by handlers that run synchronously (the click itself, not a
  // dialog callback), so `card` is still the live delegate and shows this stage.
  function stageOp(op, extra) {
    var payload = { op: op, roadmapId: card.roadmap.id, stageId: card.stage.id }
    for (var key in extra) payload[key] = extra[key]
    card.app.apply(payload)
  }

  Column {
    id: col
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.margins: Style.spacing.xl
    spacing: Style.spacing.md

    RowLayout {
      width: col.width
      spacing: Style.spacing.md

      Text {
        text: "STAGE " + (card.position + 1)
        color: Color.accent
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      Text {
        Layout.fillWidth: true
        text: card.stage.title
        elide: Text.ElideRight
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.title
        font.bold: true
      }

      Text {
        text: Model.progressLabel(card.stage)
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      Button {
        visible: card.editing && card.position > 0
        iconText: Model.icon("up")
        tooltipText: "Move stage up"
        onClicked: card.stageOp("stage.move", { delta: -1 })
      }

      Button {
        visible: card.editing && card.position < card.count - 1
        iconText: Model.icon("down")
        tooltipText: "Move stage down"
        onClicked: card.stageOp("stage.move", { delta: 1 })
      }

      Button {
        visible: card.editing
        iconText: Model.icon("pencil")
        tooltipText: "Rename stage"
        onClicked: {
          // `card` is a Repeater delegate: by the time this dialog's callback
          // runs it may be gone (a stage was added or removed, which rebuilds
          // every card) or show another stage (one moved). Capture what it
          // needs now.
          var app = card.app
          var roadmapId = card.roadmap.id
          var stageId = card.stage.id
          app.prompt("Rename stage", [{ key: "title", label: "Title", text: card.stage.title }], "Save",
            function(values) { app.apply({ op: "stage.set", roadmapId: roadmapId, stageId: stageId, title: values.title }) })
        }
      }

      Button {
        visible: card.editing
        iconText: Model.icon("trash")
        tooltipText: "Delete stage"
        onClicked: {
          var app = card.app
          var roadmapId = card.roadmap.id
          var stageId = card.stage.id
          var title = card.stage.title
          app.ask("Delete the stage \"" + title + "\"? Its tasks go with it; the courses stay in the library.",
            "Delete", function() { app.apply({ op: "stage.remove", roadmapId: roadmapId, stageId: stageId }) })
        }
      }
    }

    ProgressLine {
      width: col.width
      value: card.stage.percent / 100
    }

    Text {
      visible: card.stage.missing > 0
      text: card.stage.missing === 1 ? "1 course is no longer in the library" : card.stage.missing + " courses are no longer in the library"
      color: Color.urgent
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    Text {
      visible: !card.editing && card.stage.courseIds.length === 0
      text: "No courses yet."
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    Repeater {
      model: card.stage.courseIds

      Rectangle {
        id: courseItem

        readonly property var course: card.app.courseMap[modelData]

        width: col.width
        visible: course !== undefined
        implicitHeight: courseRow.implicitHeight + 2 * Style.spacing.sm
        radius: Style.cornerRadius
        color: courseMouse.containsMouse ? Style.hoverFill : "transparent"

        MouseArea {
          id: courseMouse
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: card.app.go("course", modelData)
        }

        RowLayout {
          id: courseRow
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.spacing.sm
          anchors.rightMargin: Style.spacing.sm
          spacing: Style.spacing.lg

          CoverImage {
            Layout.preferredWidth: 72
            Layout.preferredHeight: 40
            source: courseItem.course ? courseItem.course.cover : ""
            title: courseItem.course ? courseItem.course.title : ""
          }

          ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.spacing.xs

            Text {
              Layout.fillWidth: true
              text: courseItem.course ? courseItem.course.title : ""
              elide: Text.ElideRight
              color: Color.foreground
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }

            ProgressLine {
              Layout.fillWidth: true
              value: courseItem.course ? courseItem.course.percent / 100 : 0
            }

            Text {
              text: courseItem.course
                ? courseItem.course.seenCount + "/" + courseItem.course.lessonCount + " videos · " + Model.progressLabel(courseItem.course)
                : ""
              color: Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
            }
          }

          Button {
            visible: courseItem.course !== undefined && courseItem.course.remaining > 0
            iconText: Model.icon("play")
            tooltipText: "Continue this course"
            onClicked: card.app.resume(modelData)
          }

          Button {
            visible: card.editing && index > 0
            iconText: Model.icon("up")
            tooltipText: "Move up"
            onClicked: card.stageOp("stage.moveCourse", { courseId: modelData, delta: -1 })
          }

          Button {
            visible: card.editing && index < card.stage.courseIds.length - 1
            iconText: Model.icon("down")
            tooltipText: "Move down"
            onClicked: card.stageOp("stage.moveCourse", { courseId: modelData, delta: 1 })
          }

          Button {
            visible: card.editing
            iconText: Model.icon("close")
            tooltipText: "Remove from this stage"
            onClicked: card.stageOp("stage.removeCourse", { courseId: modelData })
          }
        }
      }
    }

    RowLayout {
      visible: card.editing
      width: col.width
      spacing: Style.spacing.controlGap

      SearchableDropdown {
        id: picker
        Layout.preferredWidth: Math.min(col.width, 380)
        showLabel: false
        triggerLabel: "Add a course…"
        placeholderText: "Search courses"
        options: Model.courseOptions(card.app.courses, card.stage.courseIds)
        onChanged: function(value) {
          picker.value = ""
          if (value !== "") card.stageOp("stage.addCourse", { courseId: value })
        }
      }

      Item { Layout.fillWidth: true }

      Button {
        iconText: Model.icon("check")
        text: card.showTasks ? "Hide tasks" : "Tasks" + (card.stage.taskCount > 0 ? " " + card.stage.taskDone + "/" + card.stage.taskCount : "")
        onClicked: card.showTasks = !card.showTasks
      }
    }

    // Outside editing the tasks show whenever there are any; ticking them is
    // using the roadmap, not configuring it.
    ChecklistEditor {
      visible: card.editing ? card.showTasks : card.stage.taskCount > 0
      width: col.width
      app: card.app
      owner: card.owner
      tasks: card.stage.tasks
      title: "Stage tasks"
      editing: card.editing
    }
  }
}
