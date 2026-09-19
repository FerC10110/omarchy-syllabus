import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// A roadmap: its stages in order, each with its courses, then the roadmap's own
// tasks and links. It opens to a plain view (progress, Continue, ticking tasks,
// opening links); "Edit" shows everything that changes it.
Item {
  id: root

  property var app
  property var roadmap: null
  property bool editing: false

  readonly property string roadmapId: roadmap ? roadmap.id : ""

  // Each roadmap opens in the plain view, except an empty one (just created):
  // there is nothing to see until it has stages.
  onRoadmapIdChanged: editing = roadmap !== null && roadmap.stages.length === 0

  readonly property var owner: roadmap ? { kind: "roadmap", id: roadmap.id } : null
  readonly property int position: {
    if (!roadmap) return -1
    for (var i = 0; i < app.roadmaps.length; i++) if (app.roadmaps[i].id === roadmap.id) return i
    return -1
  }

  function addStage() {
    // Captured now: root.roadmap can go null (roadmap deleted, or navigation
    // elsewhere) while this dialog is waiting on the user.
    var app = root.app
    var roadmapId = root.roadmap.id
    app.prompt("New stage", [{ key: "title", label: "Title", text: "", placeholder: "Foundations" }], "Add",
      function(values) { app.apply({ op: "stage.add", roadmapId: roadmapId, title: values.title }) })
  }

  function edit() {
    var app = root.app
    var id = root.roadmap.id
    app.prompt("Edit roadmap", [
      { key: "title", label: "Title", text: root.roadmap.title },
      { key: "readilyTag", label: "Readily tag (empty: automatic)", text: root.roadmap.readilyTag, placeholder: "cursos/roadmap-…" }
    ], "Save", function(values) {
      app.apply({ op: "roadmap.set", roadmapId: id, title: values.title, readilyTag: values.readilyTag })
    })
  }

  function remove() {
    var app = root.app
    var id = root.roadmap.id
    var title = root.roadmap.title
    app.ask("Delete the roadmap \"" + title + "\"? Its stages, tasks and links go with it; the courses stay.",
      "Delete", function() { app.apply({ op: "roadmap.remove", roadmapId: id }) })
  }

  Loader {
    anchors.fill: parent
    anchors.margins: Style.spacing.panelPadding
    active: root.roadmap !== null
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

        ColumnLayout {
          Layout.fillWidth: true
          spacing: Style.spacing.sm

          Text {
            text: "ROADMAP"
            color: Color.accent
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            font.bold: true
          }

          Text {
            Layout.fillWidth: true
            text: root.roadmap.title
            wrapMode: Text.Wrap
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.heading
            font.bold: true
          }

          Text {
            Layout.fillWidth: true
            text: root.roadmap.stages.length + (root.roadmap.stages.length === 1 ? " stage · " : " stages · ")
              + root.roadmap.courseCount + (root.roadmap.courseCount === 1 ? " course · " : " courses · ")
              + Model.fmtDuration(root.roadmap.duration) + " · " + Model.progressLabel(root.roadmap)
            elide: Text.ElideRight
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }

          ProgressLine {
            Layout.fillWidth: true
            value: root.roadmap.percent / 100
          }
        }

        ColumnLayout {
          Layout.alignment: Qt.AlignTop
          spacing: Style.spacing.sm

          RowLayout {
            Layout.alignment: Qt.AlignRight
            spacing: Style.spacing.controlGap

            Button {
              iconText: Model.icon("play")
              text: "Continue"
              bordered: true
              onClicked: root.app.resumeRoadmap(root.roadmap)
            }

            Button {
              iconText: Model.icon(root.editing ? "check" : "pencil")
              text: root.editing ? "Done" : "Edit"
              selected: root.editing
              onClicked: root.editing = !root.editing
            }
          }

          RowLayout {
            Layout.alignment: Qt.AlignRight
            visible: root.editing
            spacing: Style.spacing.xs

            Button {
              iconText: Model.icon("pencil")
              tooltipText: "Rename"
              onClicked: root.edit()
            }

            Button {
              visible: root.position > 0
              iconText: Model.icon("up")
              tooltipText: "Move up in the sidebar"
              onClicked: root.app.apply({ op: "roadmap.move", roadmapId: root.roadmap.id, delta: -1 })
            }

            Button {
              visible: root.position >= 0 && root.position < root.app.roadmaps.length - 1
              iconText: Model.icon("down")
              tooltipText: "Move down in the sidebar"
              onClicked: root.app.apply({ op: "roadmap.move", roadmapId: root.roadmap.id, delta: 1 })
            }

            Button {
              iconText: Model.icon("trash")
              tooltipText: "Delete roadmap"
              onClicked: root.remove()
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
        contentHeight: body.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        QQC.ScrollBar.vertical: QQC.ScrollBar {}

        Column {
          id: body
          width: flick.width
          spacing: Style.spacing.huge

          Text {
            visible: root.roadmap.stages.length === 0
            width: body.width
            wrapMode: Text.Wrap
            text: root.editing
              ? "This roadmap has no stages yet. Add one, then add courses to it."
              : "This roadmap has no stages yet. Use Edit to add them."
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }

          // A count, not the stages array: every refresh (about every 30 s while
          // mpv plays) brings a new roadmap, and an array model would rebuild
          // every StageCard whenever anything in it changed, losing a half-typed
          // task, an open course picker and the shown tasks. With a count the
          // cards stay, and each one follows the stage now at its position; they
          // are rebuilt only when a stage is added or removed.
          Repeater {
            model: root.roadmap ? root.roadmap.stages.length : 0

            StageCard {
              width: body.width
              app: root.app
              roadmap: root.roadmap
              stage: root.roadmap.stages[index]
              position: index
              count: root.roadmap.stages.length
              editing: root.editing
            }
          }

          Button {
            visible: root.editing
            iconText: Model.icon("plus")
            text: "Add stage"
            bordered: true
            onClicked: root.addStage()
          }

          ChecklistEditor {
            visible: root.editing || root.roadmap.tasks.length > 0
            width: body.width
            app: root.app
            owner: root.owner
            tasks: root.roadmap.tasks
            title: "Roadmap tasks"
            editing: root.editing
          }

          LinksTab {
            visible: root.editing || root.roadmap.links.length > 0
            width: body.width
            app: root.app
            owner: root.owner
            links: root.roadmap.links
            editing: root.editing
          }
        }
      }
    }
  }
}
