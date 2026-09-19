import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// A checklist of a course, a roadmap or a stage: tick, reorder, rename, delete,
// and a field to add more. `owner` is the op owner ({kind, id[, roadmapId]}).
// With `editing` off only the ticks are left.
Column {
  id: root

  property var app
  property var owner: null
  property var tasks: []
  property string title: "Tasks"
  property bool editing: true

  readonly property int done: tasks.filter(function(t) { return t.done }).length
  // A draft belongs to its owner: when this editor starts showing another one
  // (the next course, or another stage after a stage moved) it is not carried over.
  readonly property string ownerKey: owner ? JSON.stringify(owner) : ""

  onOwnerKeyChanged: field.text = ""

  spacing: Style.spacing.xs

  function add() {
    var text = field.text.trim()
    if (text === "" || !root.owner) return
    // The component may be gone by the time the reply comes back (e.g. it sits
    // inside a StageCard, and every StageCard is rebuilt when a stage is added
    // or removed). "field" turns null once its item is destroyed, so this is a
    // silent no-op instead of a logged exception. Cleared only if it still
    // holds what was added and this editor still shows the same owner.
    var key = root.ownerKey
    root.app.apply({ op: "task.add", owner: root.owner, text: text }, function() {
      if (field && root.ownerKey === key && field.text.trim() === text) field.text = ""
    })
  }

  RowLayout {
    width: root.width
    spacing: Style.spacing.md

    Text {
      text: root.title
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.subtitle
      font.bold: true
    }

    Text {
      visible: root.tasks.length > 0
      text: root.done + "/" + root.tasks.length
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    Item { Layout.fillWidth: true }
  }

  Repeater {
    model: root.tasks

    RowLayout {
      width: root.width
      spacing: Style.spacing.md

      Button {
        iconText: Model.icon(modelData.done ? "boxChecked" : "boxEmpty")
        foreground: modelData.done ? Color.accent : Color.foreground
        tooltipText: modelData.done ? "Not done" : "Done"
        onClicked: root.app.apply({ op: "task.set", owner: root.owner, taskId: modelData.id, done: !modelData.done })
      }

      Text {
        Layout.fillWidth: true
        text: modelData.text
        wrapMode: Text.Wrap
        font.strikeout: modelData.done
        color: modelData.done ? Color.muted : Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }

      Button {
        visible: root.editing && index > 0
        iconText: Model.icon("up")
        tooltipText: "Move up"
        onClicked: root.app.apply({ op: "task.move", owner: root.owner, taskId: modelData.id, delta: -1 })
      }

      Button {
        visible: root.editing && index < root.tasks.length - 1
        iconText: Model.icon("down")
        tooltipText: "Move down"
        onClicked: root.app.apply({ op: "task.move", owner: root.owner, taskId: modelData.id, delta: 1 })
      }

      Button {
        visible: root.editing
        iconText: Model.icon("pencil")
        tooltipText: "Edit"
        onClicked: {
          // Captured before the dialog opens: this delegate (and root itself,
          // when nested in a StageCard) may be destroyed by a refresh that
          // lands while the dialog is open.
          var app = root.app
          var owner = root.owner
          var taskId = modelData.id
          app.prompt("Edit task", [{ key: "text", label: "Task", text: modelData.text }], "Save", function(values) {
            app.apply({ op: "task.set", owner: owner, taskId: taskId, text: values.text })
          })
        }
      }

      Button {
        visible: root.editing
        iconText: Model.icon("trash")
        tooltipText: "Delete"
        onClicked: {
          var app = root.app
          var owner = root.owner
          var taskId = modelData.id
          app.ask("Delete the task \"" + Model.preview(modelData.text, 60) + "\"?", "Delete", function() {
            app.apply({ op: "task.remove", owner: owner, taskId: taskId })
          })
        }
      }
    }
  }

  TextField {
    id: field
    visible: root.editing
    width: root.width
    placeholderText: "Add a task and press Enter"
    onAccepted: root.add()
  }
}
