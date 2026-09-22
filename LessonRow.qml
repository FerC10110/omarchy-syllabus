import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// One video: watched box, title, time and progress, play from where it was
// left, and its bookmarks. In edit mode: move, rename, hide.
Column {
  id: row

  property var app
  property var course
  property var lesson
  property int position: 0
  property int count: 0
  property bool editing: false
  property bool expanded: false

  signal toggleBookmarks()

  readonly property string status: Model.lessonStatus(lesson)

  function editBookmark(mark) {
    var app = row.app
    var lessonId = row.lesson.id
    var bookmarkId = mark.id
    app.prompt("Edit bookmark", [
      { key: "at", label: "Time (1:23:40)", text: Model.fmtClock(mark.at) },
      { key: "text", label: "Text", text: mark.text }
    ], "Save", function(values) {
      var at = Model.parseTimestamp(values.at)
      if (at < 0) { app.showNotice("Write the time as 1:23:40, 23:40 or 95", true); return }
      app.apply({ op: "bookmark.set", lessonId: lessonId, bookmarkId: bookmarkId, at: at, text: values.text })
    })
  }

  function addBookmark() {
    var app = row.app
    var lessonId = row.lesson.id
    app.prompt("New bookmark in " + row.lesson.title, [
      { key: "at", label: "Time (1:23:40)", text: Model.fmtClock(row.lesson.pos) },
      { key: "text", label: "Text", text: "", placeholder: "What happens here" }
    ], "Add", function(values) {
      var at = Model.parseTimestamp(values.at)
      if (at < 0) { app.showNotice("Write the time as 1:23:40, 23:40 or 95", true); return }
      app.apply({ op: "bookmark.add", lessonId: lessonId, at: at, text: values.text })
    })
  }

  Rectangle {
    width: row.width
    implicitHeight: line.implicitHeight + 2 * Style.spacing.md
    radius: Style.cornerRadius
    color: row.expanded ? Style.selectedFill : "transparent"
    opacity: row.lesson.hidden || row.lesson.available === false ? 0.55 : 1

    RowLayout {
      id: line
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.spacing.sm
      anchors.rightMargin: Style.spacing.sm
      spacing: Style.spacing.md

      Button {
        iconText: Model.icon(row.lesson.seen ? "boxChecked" : "boxEmpty")
        foreground: row.lesson.seen ? Color.accent : Color.foreground
        tooltipText: row.lesson.seen ? "Mark as not watched (starts over)" : "Mark as watched"
        onClicked: row.app.apply({ op: "seen.set", lessonId: row.lesson.id, seen: !row.lesson.seen })
      }

      Text {
        Layout.preferredWidth: Style.font.body * 2.5
        horizontalAlignment: Text.AlignRight
        text: (row.lesson.number !== null ? row.lesson.number : row.position + 1) + "."
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }

      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.xs

        Text {
          Layout.fillWidth: true
          text: row.lesson.title + (row.lesson.suspect ? "  · short or unreadable" : "")
          elide: Text.ElideRight
          color: row.status === "seen" ? Color.muted : Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.spacing.md

          ProgressLine {
            Layout.preferredWidth: 220
            visible: row.status !== "new"
            value: row.lesson.seen ? 1 : Model.fraction(row.lesson.pos, row.lesson.duration)
          }

          Text {
            text: row.status === "started"
              ? Model.fmtClock(row.lesson.pos) + " / " + Model.fmtClock(row.lesson.duration)
              : Model.fmtClock(row.lesson.duration)
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          Item { Layout.fillWidth: true }
        }
      }

      Button {
        iconText: Model.icon("bookmark")
        text: row.lesson.bookmarks.length > 0 ? String(row.lesson.bookmarks.length) : ""
        selected: row.expanded
        tooltipText: "Bookmarks"
        onClicked: row.toggleBookmarks()
      }

      Text {
        visible: row.lesson.downloaded === true
        text: Model.icon("download")
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        // A tooltip is enough: the file is an implementation detail, not an action.
      }

      Text {
        visible: row.lesson.available === false
        text: "Not available"
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      Button {
        // A gone-but-downloaded video still plays from its own file: only a video with
        // neither a file nor a link left has no Play button.
        visible: !row.editing && (row.lesson.available !== false || row.lesson.downloaded === true)
        iconText: Model.icon("play")
        text: row.status === "started" ? "Resume" : (row.status === "seen" ? "Again" : "Play")
        // "Again" means from the start: a video left at 92 % would otherwise
        // resume near its end.
        onClicked: row.app.play(row.lesson.id, row.status === "seen" ? 0 : undefined)
      }

      Button {
        visible: row.editing && !row.lesson.hidden && row.position > 0
        iconText: Model.icon("up")
        tooltipText: "Move up"
        onClicked: row.app.apply({ op: "lesson.move", courseId: row.course.id, lessonId: row.lesson.id, delta: -1 })
      }

      Button {
        visible: row.editing && !row.lesson.hidden && row.position < row.count - 1
        iconText: Model.icon("down")
        tooltipText: "Move down"
        onClicked: row.app.apply({ op: "lesson.move", courseId: row.course.id, lessonId: row.lesson.id, delta: 1 })
      }

      Button {
        visible: row.editing
        iconText: Model.icon("pencil")
        tooltipText: "Rename"
        onClicked: {
          var app = row.app
          var lessonId = row.lesson.id
          var defaultTitle = row.lesson.defaultTitle
          var currentTitle = row.lesson.title
          app.prompt("Rename video", [{
            key: "title", label: "Title (empty: " + defaultTitle + ")",
            text: currentTitle === defaultTitle ? "" : currentTitle,
            placeholder: defaultTitle
          }], "Save", function(values) {
            app.apply({ op: "lesson.set", lessonId: lessonId, title: values.title })
          })
        }
      }

      Button {
        visible: row.editing
        iconText: Model.icon(row.lesson.hidden ? "eye" : "eyeOff")
        tooltipText: row.lesson.hidden ? "Show in the course" : "Hide from the course"
        onClicked: row.app.apply({ op: "lesson.set", lessonId: row.lesson.id, hidden: !row.lesson.hidden })
      }

      Button {
        visible: row.editing && row.lesson.source === "video"
        iconText: Model.icon("trash")
        tooltipText: "Remove this video from the course"
        onClicked: row.app.ask("Remove \"" + row.lesson.title + "\" from the course?", "Remove", function() {
          row.app.apply({ op: "web.removeVideo", courseId: row.course.id, lessonId: row.lesson.id })
        })
      }
    }
  }

  Column {
    visible: row.expanded
    width: row.width
    leftPadding: Style.spacing.huge * 4
    bottomPadding: Style.spacing.md
    spacing: Style.spacing.xs

    Repeater {
      model: row.expanded ? row.lesson.bookmarks : []

      RowLayout {
        width: row.width - Style.spacing.huge * 4
        spacing: Style.spacing.md

        Button {
          iconText: Model.icon("play")
          text: Model.fmtClock(modelData.at)
          tooltipText: "Play from here"
          onClicked: row.app.play(row.lesson.id, modelData.at)
        }

        Text {
          Layout.fillWidth: true
          text: modelData.text !== "" ? modelData.text : "(no text)"
          elide: Text.ElideRight
          color: modelData.text !== "" ? Color.foreground : Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }

        Button {
          iconText: Model.icon("pencil")
          tooltipText: "Edit"
          onClicked: row.editBookmark(modelData)
        }

        Button {
          iconText: Model.icon("trash")
          tooltipText: "Delete"
          onClicked: {
            var app = row.app
            var lessonId = row.lesson.id
            var markId = modelData.id
            app.ask("Delete the bookmark at " + Model.fmtClock(modelData.at) + "?", "Delete", function() {
              app.apply({ op: "bookmark.remove", lessonId: lessonId, bookmarkId: markId })
            })
          }
        }
      }
    }

    Button {
      iconText: Model.icon("plus")
      text: "Add bookmark"
      tooltipText: "Or press b in mpv while it plays"
      onClicked: row.addBookmark()
    }
  }
}
