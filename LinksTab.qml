import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC
import Quickshell.Io
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// Links and text snippets of a course or roadmap: paste or type one, give it a
// title, open, copy, reorder, edit, and save it to Readily. Readily's items with
// the same tag are listed underneath. With `editing` off only the saved ones are
// shown, to open or copy.
Column {
  id: root

  property var app
  property var owner: null
  property var links: []
  property bool editing: true

  spacing: Style.spacing.lg

  function add() {
    var content = input.text
    if (content.trim() === "" || !root.owner) return
    // The whole tab (and its fields) may be gone by the time the reply comes
    // back (the owning course/roadmap went null and the Loader tore it down).
    // "input"/"titleField" turn null once their item is destroyed, so this is
    // a silent no-op instead of a logged exception.
    root.app.apply({ op: "link.add", owner: root.owner, title: titleField.text, content: content }, function() {
      if (input) input.text = ""
      if (titleField) titleField.text = ""
    })
  }

  // Captured before the dialog opens: `root` may be destroyed (its owner went
  // null) while the user is still answering the prompt.
  function edit(link) {
    var app = root.app
    var owner = root.owner
    var linkId = link.id
    app.prompt("Edit", [
      { key: "title", label: "Title", text: link.title },
      { key: "content", label: "Link or text", text: Model.linkText(link), multiline: true }
    ], "Save", function(values) {
      app.apply({ op: "link.set", owner: owner, linkId: linkId, title: values.title, content: values.content })
    })
  }

  Text {
    text: "Links and snippets"
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.subtitle
    font.bold: true
  }

  Rectangle {
    visible: root.editing
    width: root.width
    implicitHeight: inputColumn.implicitHeight + 2 * Style.spacing.lg
    radius: Style.cornerRadius
    color: Style.normalFill
    border.width: Style.normalBorderWidth
    border.color: Style.normalBorderColor

    ColumnLayout {
      id: inputColumn
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.margins: Style.spacing.lg
      spacing: Style.spacing.md

      QQC.TextArea {
        id: input
        Layout.fillWidth: true
        Layout.preferredHeight: Math.max(64, Math.min(220, contentHeight + topPadding + bottomPadding))
        placeholderText: "Paste a link or a piece of text (a command, a prompt, an answer…)"
        wrapMode: TextEdit.Wrap
        selectByMouse: true
        color: Color.foreground
        placeholderTextColor: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        background: Rectangle {
          radius: Style.cornerRadius
          color: Util.alpha(Color.foreground, 0.04)
          border.width: Style.normalBorderWidth
          border.color: input.activeFocus ? Color.accent : Style.normalBorderColor
        }
        Keys.onPressed: function(event) {
          if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (event.modifiers & Qt.ControlModifier)) {
            event.accepted = true
            root.add()
          }
        }
      }

      RowLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.controlGap

        TextField {
          id: titleField
          Layout.fillWidth: true
          placeholderText: "Title (optional)"
          onAccepted: root.add()
        }

        Button {
          text: "Paste"
          tooltipText: "Paste the clipboard here"
          onClicked: {
            pasteProc.running = false
            pasteProc.running = true
          }
        }

        Button {
          iconText: Model.icon("plus")
          text: "Add"
          bordered: true
          tooltipText: "Add (Ctrl+Enter)"
          onClicked: root.add()
        }
      }
    }
  }

  Process {
    id: pasteProc
    command: ["wl-paste", "--no-newline", "--type", "text"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var pasted = String(text || "")
        if (pasted.length > 0) input.text = pasted
      }
    }
  }

  Text {
    visible: root.editing && root.links.length === 0
    text: "Nothing saved yet."
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }

  Repeater {
    model: root.links

    RowLayout {
      width: root.width
      spacing: Style.spacing.md

      Text {
        Layout.alignment: Qt.AlignTop
        text: Model.icon(modelData.kind === "link" ? "link" : "note")
        color: Color.accent
        font.family: Style.font.family
        font.pixelSize: Style.font.title
      }

      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.xxs

        Text {
          Layout.fillWidth: true
          text: modelData.title !== "" ? modelData.title : Model.preview(Model.linkText(modelData), 100)
          elide: Text.ElideRight
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          font.bold: modelData.title !== ""
        }

        Text {
          Layout.fillWidth: true
          visible: modelData.title !== ""
          text: Model.preview(Model.linkText(modelData), 140)
          elide: Text.ElideRight
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Text {
          visible: modelData.truncated === true
          text: "Imported from Readily, cut at 4096 characters"
          color: Color.urgent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
      }

      Button {
        visible: modelData.kind === "link"
        iconText: Model.icon("open")
        tooltipText: "Open"
        onClicked: root.app.openExternal(modelData.url)
      }

      Button {
        iconText: Model.icon("copy")
        tooltipText: "Copy"
        onClicked: root.app.copyText(Model.linkText(modelData))
      }

      Button {
        visible: root.editing && root.app.readilyOn
        iconText: Model.icon(modelData.readilySavedAt ? "check" : "save")
        tooltipText: modelData.readilySavedAt ? "Saved to Readily (save again)" : "Save to Readily"
        onClicked: {
          var owner = root.owner
          var linkId = modelData.id
          root.app.apply({ op: "readily.save", owner: owner, linkId: linkId }, function() {
            // `root` (this whole tab) may be gone by now, same reason as add().
            if (!root) return
            root.app.showNotice("Saved to Readily", false)
            readilySection.reload()
          })
        }
      }

      Button {
        visible: root.editing && index > 0
        iconText: Model.icon("up")
        tooltipText: "Move up"
        onClicked: root.app.apply({ op: "link.move", owner: root.owner, linkId: modelData.id, delta: -1 })
      }

      Button {
        visible: root.editing && index < root.links.length - 1
        iconText: Model.icon("down")
        tooltipText: "Move down"
        onClicked: root.app.apply({ op: "link.move", owner: root.owner, linkId: modelData.id, delta: 1 })
      }

      Button {
        visible: root.editing
        iconText: Model.icon("pencil")
        tooltipText: "Edit"
        onClicked: root.edit(modelData)
      }

      Button {
        visible: root.editing
        iconText: Model.icon("trash")
        tooltipText: "Delete"
        onClicked: {
          // Captured before the dialog opens: this delegate (and root itself)
          // may be destroyed by a refresh, or by the owner going null, while
          // the confirmation is open.
          var app = root.app
          var owner = root.owner
          var linkId = modelData.id
          var label = modelData.title || Model.preview(Model.linkText(modelData), 60)
          app.ask("Delete \"" + label + "\"? A copy saved in Readily stays there.",
            "Delete", function() { app.apply({ op: "link.remove", owner: owner, linkId: linkId }) })
        }
      }
    }
  }

  Item {
    visible: readilySection.visible
    width: 1
    height: Style.spacing.lg
  }

  ReadilySection {
    id: readilySection
    width: root.width
    visible: root.editing && root.app.readilyOn
    app: root.app
    owner: root.owner
  }
}
