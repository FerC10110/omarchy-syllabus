import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// The course's Markdown note. Saved a second after the last keystroke, when
// the tab or the course changes, when the window hides or loses the focus, and
// when the course page closes (this item is destroyed then, so the text lives
// in `draft`). Every save says which text it started from (`base`), and
// bin/syllabus refuses it when the file changed outside the window since: the
// tab then keeps what was typed and offers to reload the file or overwrite it.
// While nothing typed here is unsaved, the tab picks up edits made elsewhere
// (e.g. in the editor "Open in editor" starts) when it, or the window, comes back.
Item {
  id: root

  property var app
  property var course
  property bool active: false
  property string loadedFor: ""
  property string path: ""
  property string draft: ""
  property string savedText: ""
  property bool loading: false
  property bool reloading: false
  // The last save was refused: the file changed outside the window.
  property bool conflict: false
  // The newest note.set still waiting for its reply ({serial, id, text}), or null.
  property var inFlight: null
  property int serial: 0

  readonly property bool dirty: loadedFor !== "" && draft !== savedText

  function load() {
    if (!course || !active || course.id === loadedFor || loading) return
    flush()
    var id = course.id
    loading = true
    app.call(["note-get", id], undefined, function(payload) {
      // This tab may be gone by the time the reply comes back (the course
      // went null and the CourseView Loader tore it down): a silent no-op.
      if (!root) return
      root.loading = false
      if (payload.error !== undefined) { root.app.showNotice(payload.error, true); return }
      if (!root.course || root.course.id !== id) { root.load(); return }
      root.path = payload.path
      root.loadedFor = id
      root.conflict = false
      root.show(payload.text)
    })
  }

  // The text on disk becomes both what the tab shows and what it is based on.
  function show(text) {
    savedText = text
    draft = text
    var cursor = area.cursorPosition
    area.text = text
    area.cursorPosition = Math.min(cursor, area.length)
  }

  // Picks up edits made outside the window, unless something typed here is
  // not saved yet (that draft is never replaced without asking).
  function reloadIfClean() {
    if (!course || !active || loadedFor === "" || course.id !== loadedFor || loading || reloading || dirty) return
    var id = loadedFor
    var seen = draft
    reloading = true
    app.call(["note-get", id], undefined, function(payload) {
      if (!root) return
      root.reloading = false
      if (payload.error !== undefined) return
      // Typed meanwhile, or another course loaded: leave it as it is.
      if (root.loadedFor !== id || root.draft !== seen || root.dirty) return
      root.conflict = false
      if (payload.text !== root.savedText) root.show(payload.text)
    })
  }

  // Only marked saved once app.apply's onDone confirms it: Panel.apply never
  // calls onDone on error (it shows a notice, then calls onError), so a failed
  // save must leave `dirty` true, or the status would claim "Saved" for text
  // that never reached disk, and a later reload (leaving and returning to the
  // course) would silently bring back the old text. Captured before the call
  // (this tab may be destroyed, or loaded for a different course, by the time
  // the reply comes back): `id` is always `loadedFor`, never the course that
  // might be showing when the save lands. `savedText` is set to `sent` (what
  // was actually sent), not the current `draft`, so text typed while this
  // save was in flight stays dirty and the debounce timer saves it next. On
  // failure only onError runs here, so dirty stays true and the next thing
  // that calls flush() (a keystroke, a tab switch, the window hiding, a course
  // switch) retries; a refusal because the file changed outside the window
  // sets `conflict`, which stops the automatic retries until the user picks
  // "Reload from file" or "Overwrite file".
  function flush(done) {
    saveTimer.stop()
    if (loadedFor === "" || draft === savedText) {
      if (done) done()
      return
    }
    var id = loadedFor
    var sent = draft
    // A save sent while an earlier one is still on its way starts from that
    // one's text: once it lands, that is what the file holds.
    var base = inFlight !== null && inFlight.id === id ? inFlight.text : savedText
    var mine = ++serial
    inFlight = { serial: mine, id: id, text: sent }
    var app = root.app
    function settled() {
      if (root && root.inFlight !== null && root.inFlight.serial === mine) root.inFlight = null
    }
    app.apply({ op: "note.set", courseId: id, text: sent, base: base }, function() {
      settled()
      if (root && root.loadedFor === id) {
        root.savedText = sent
        root.conflict = false
      }
      if (done) done()
    }, function(payload) {
      settled()
      if (root && root.loadedFor === id && payload.reason === "noteChanged") root.conflict = true
    })
  }

  // Automatic saves (the debounce timer, the window losing the focus) wait
  // while there is a conflict; leaving (tab, course or window) still tries,
  // so a refusal there shows its notice instead of dropping the text quietly.
  function autoFlush() {
    if (!conflict) flush()
  }

  function reloadFromFile() {
    var app = root.app
    var id = root.loadedFor
    app.ask("Replace the text here with the note file as it is now? What you typed here since the last save is lost.",
      "Reload", function() {
        app.call(["note-get", id], undefined, function(payload) {
          if (payload.error !== undefined) { app.showNotice(payload.error, true); return }
          if (!root || root.loadedFor !== id) return
          root.conflict = false
          root.show(payload.text)
        })
      })
  }

  function overwriteFile() {
    var app = root.app
    var id = root.loadedFor
    app.ask("Overwrite the note file with the text here? The changes made to it outside the window are lost.",
      "Overwrite", function() {
        app.call(["note-get", id], undefined, function(payload) {
          if (payload.error !== undefined) { app.showNotice(payload.error, true); return }
          if (!root || root.loadedFor !== id) return
          // The file as it is now becomes the base, so this save replaces it on purpose.
          root.savedText = payload.text
          root.conflict = false
          root.flush()
        })
      })
  }

  onCourseChanged: load()
  onActiveChanged: {
    if (active) {
      load()
      reloadIfClean()
    } else {
      flush()
    }
  }

  Component.onDestruction: flush()

  Connections {
    target: root.app
    function onOpenedChanged() {
      if (root.app.opened) root.reloadIfClean()
      else root.flush()
    }
    function onFocusedChanged() {
      if (root.app.focused) root.reloadIfClean()
      else root.autoFlush()
    }
  }

  Timer {
    id: saveTimer
    interval: 1000
    onTriggered: root.autoFlush()
  }

  ColumnLayout {
    anchors.fill: parent
    spacing: Style.spacing.lg

    RowLayout {
      Layout.fillWidth: true
      spacing: Style.spacing.controlGap

      Text {
        Layout.fillWidth: true
        text: root.conflict ? "Not saved"
          : (root.loading ? "Loading…" : (root.dirty ? "Saving…" : (root.loadedFor !== "" ? "Saved" : "")))
        color: root.conflict ? Color.urgent : Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      Button {
        iconText: Model.icon("open")
        text: "Open in editor"
        tooltipText: "Edits made there show here when you come back to this window"
        onClicked: {
          if (root.draft.trim() === "") { root.app.showNotice("Write something first", false); return }
          root.flush(function() {
            // Same destroyed-component guard as load(): the course may have
            // gone null while the save was in flight.
            if (!root) return
            root.app.openExternal(root.path)
          })
        }
      }
    }

    Rectangle {
      Layout.fillWidth: true
      visible: root.conflict
      implicitHeight: conflictRow.implicitHeight + 2 * Style.spacing.lg
      radius: Style.cornerRadius
      color: Util.alpha(Color.urgent, 0.15)

      RowLayout {
        id: conflictRow
        anchors.fill: parent
        anchors.margins: Style.spacing.lg
        spacing: Style.spacing.controlGap

        Text {
          Layout.fillWidth: true
          wrapMode: Text.Wrap
          text: "The note file changed outside this window, so what you typed here is not saved. "
            + "Reload the file (your text here is lost) or overwrite it with your text."
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }

        Button {
          iconText: Model.icon("refresh")
          text: "Reload from file"
          bordered: true
          onClicked: root.reloadFromFile()
        }

        Button {
          iconText: Model.icon("save")
          text: "Overwrite file"
          onClicked: root.overwriteFile()
        }
      }
    }

    QQC.ScrollView {
      Layout.fillWidth: true
      Layout.fillHeight: true

      QQC.TextArea {
        id: area
        readOnly: root.loading
        placeholderText: "Notes for this course (Markdown)"
        wrapMode: TextEdit.Wrap
        selectByMouse: true
        color: Color.foreground
        placeholderTextColor: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        background: Rectangle {
          radius: Style.cornerRadius
          color: Util.alpha(Color.foreground, 0.03)
          border.width: Style.normalBorderWidth
          border.color: area.activeFocus ? Color.accent : Style.normalBorderColor
        }
        onTextChanged: {
          if (root.loadedFor === "" || root.loading || text === root.draft) return
          root.draft = text
          saveTimer.restart()
        }
      }
    }
  }
}
