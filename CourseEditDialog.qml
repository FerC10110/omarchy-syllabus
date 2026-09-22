import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// How a course shows: title, topic, Readily tag, cover, and how its top-level
// folder splits into courses. The files on the disk never change.
Item {
  id: root

  property var app
  property bool opened: false
  property var course: null
  property var images: []
  property bool imagesOnline: true
  property string chosenCover: ""
  property bool coverTouched: false
  property string layout: "auto"

  readonly property var folder: course && app.view ? (app.view.folders[course.folderId] || null) : null
  readonly property string folderName: course ? course.folderId.split(":").slice(1).join(":") : ""
  readonly property var layoutOptions: folder ? [
    { value: "auto", label: "Automatic (" + (folder.detected === "collection" ? "one course per subfolder" : "one course") + ")" },
    { value: "course", label: "One course" },
    { value: "collection", label: "One course per subfolder" }
  ] : []

  signal closed()

  visible: opened

  function show(c) {
    course = c
    titleField.text = c.title === c.defaultTitle ? "" : c.title
    topicField.text = c.topic
    tagField.text = c.readilyTag
    chosenCover = ""
    coverTouched = false
    layout = folder ? folder.layout : "auto"
    layoutPicker.value = layout  // Dropdown sets its own value on pick, which breaks a binding
    images = []
    imagesOnline = true
    opened = true
    titleField.forceActiveFocus()
    // Captured now: the dialog can be closed and reopened for another course
    // (or `app` could in principle change) before this reply arrives, so the
    // callback below must not depend on anything but these locals and the
    // course-identity check.
    var app = root.app
    var id = c.id
    app.call(["covers", id], undefined, function(payload) {
      if (!root.course || root.course.id !== id || payload.error !== undefined) return
      root.images = payload.images
      root.imagesOnline = payload.online
    })
  }

  function cancel() {
    opened = false
    closed()
  }

  function save() {
    var c = course
    var ops = [{ op: "course.set", courseId: c.id, title: titleField.text, topic: topicField.text, readilyTag: tagField.text }]
    if (coverTouched) ops.push({ op: "cover.set", courseId: c.id, source: chosenCover })
    if (folder && layout !== folder.layout) ops.push({ op: "folder.layout", folderId: c.folderId, layout: layout })
    var app = root.app
    opened = false
    closed()
    runOps(app, ops)
  }

  // One after the other: a failed op stops the rest (its error shows as a
  // notice). `app` is passed through rather than read back off `root`, so a
  // reopened dialog editing a different course can never make a later step
  // of this chain apply to the wrong app instance.
  function runOps(app, ops) {
    if (ops.length === 0) return
    app.apply(ops[0], function() { runOps(app, ops.slice(1)) })
  }

  Rectangle {
    anchors.fill: parent
    color: Util.alpha(Color.background, 0.7)

    MouseArea {
      anchors.fill: parent
      onClicked: root.cancel()
    }

    Rectangle {
      anchors.centerIn: parent
      width: Math.min(parent.width - 64, 660)
      height: Math.min(parent.height - 64, form.implicitHeight + 2 * Style.spacing.huge)
      radius: Style.cornerRadius
      color: Color.popups.background
      border.width: Style.normalBorderWidth
      border.color: Color.popups.border

      MouseArea { anchors.fill: parent }

      Flickable {
        id: flick
        anchors.fill: parent
        anchors.margins: Style.spacing.huge
        clip: true
        contentWidth: width
        contentHeight: form.implicitHeight
        boundsBehavior: Flickable.StopAtBounds

        ColumnLayout {
          id: form
          width: flick.width
          spacing: Style.spacing.lg

          Text {
            text: "Edit course"
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.title
            font.bold: true
          }

          Text {
            Layout.fillWidth: true
            text: root.course ? root.course.relpath : ""
            elide: Text.ElideMiddle
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          Text {
            text: "Title"
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          TextField {
            id: titleField
            Layout.fillWidth: true
            placeholderText: root.course ? root.course.defaultTitle : ""
            onAccepted: root.save()
          }

          Text {
            text: "Topic"
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          TextField {
            id: topicField
            Layout.fillWidth: true
            placeholderText: "e.g. RAG, Agents, Trading"
            onAccepted: root.save()
          }

          Flow {
            Layout.fillWidth: true
            spacing: Style.spacing.sm

            Repeater {
              model: root.app.view ? root.app.view.topics : []

              Button {
                text: modelData
                selected: topicField.text === modelData
                onClicked: topicField.text = modelData
              }
            }
          }

          Text {
            text: "Readily tag"
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          TextField {
            id: tagField
            Layout.fillWidth: true
            placeholderText: "Automatic: cursos/<title>, fixed the first time a link is saved"
            onAccepted: root.save()
          }

          Text {
            text: "Cover"
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          Text {
            visible: !root.imagesOnline
            text: "Mount the disk to choose a cover."
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }

          Flow {
            Layout.fillWidth: true
            spacing: Style.spacing.md

            Repeater {
              model: [{ path: "", name: "Automatic" }].concat(root.imagesOnline ? root.images : [])

              Column {
                spacing: Style.spacing.xs

                Rectangle {
                  width: 128
                  height: 72
                  radius: Style.cornerRadius
                  color: "transparent"
                  border.width: root.coverTouched && root.chosenCover === modelData.path ? 2 : 0
                  border.color: Color.accent

                  CoverImage {
                    anchors.fill: parent
                    anchors.margins: 3
                    source: modelData.path
                    title: root.course ? root.course.title : ""
                  }

                  MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                      root.chosenCover = modelData.path
                      root.coverTouched = true
                    }
                  }
                }

                Text {
                  width: 128
                  text: modelData.name
                  elide: Text.ElideMiddle
                  color: Color.muted
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                }
              }
            }
          }

          ColumnLayout {
            Layout.fillWidth: true
            visible: root.folder !== null && root.course && root.course.web === null
            spacing: Style.spacing.sm

            Text {
              text: "Folder \"" + root.folderName + "\""
              color: Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
            }

            Dropdown {
              id: layoutPicker
              Layout.fillWidth: true
              showLabel: false
              options: root.layoutOptions
              onChanged: function(value) { root.layout = value }
            }

            Text {
              Layout.fillWidth: true
              wrapMode: Text.Wrap
              text: "Applies to the whole folder. Regrouping keeps every video's progress and bookmarks; "
                + "course tasks, links and notes belong to the grouping they were made in and come back if you switch back."
              color: Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
            }
          }

          ColumnLayout {
            Layout.fillWidth: true
            visible: root.course && root.course.web !== null
            spacing: Style.spacing.sm

            Button {
              iconText: Model.icon("refresh")
              text: "Refresh now"
              onClicked: root.app.webRefresh(root.course.id)
            }

            Button {
              iconText: Model.icon("trash")
              text: "Delete downloads"
              visible: root.course && root.course.web && root.course.web.downloadedCount > 0
              onClicked: root.app.ask("Delete the " + root.course.web.downloadedCount
                                        + " downloaded videos of this course?", "Delete", function() {
                root.app.deleteDownloads(root.course.id)
              })
            }

            Button {
              iconText: Model.icon("trash")
              text: "Remove course"
              onClicked: root.app.ask("Remove this course, its tasks, links, notes and bookmarks, and delete "
                                        + "its downloaded videos? The videos stay on the web.", "Remove", function() {
                root.cancel()
                root.app.apply({ op: "web.remove", courseId: root.course.id }, function() { root.app.openLibrary("") })
              })
            }
          }

          RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Style.spacing.md
            spacing: Style.spacing.controlGap

            Item { Layout.fillWidth: true }

            Button {
              text: "Cancel"
              onClicked: root.cancel()
            }

            Button {
              text: "Save"
              bordered: true
              selected: true
              onClicked: root.save()
            }
          }
        }
      }
    }
  }
}
