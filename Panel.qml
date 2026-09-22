import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// The Syllabus panel. BarWidget.qml loads it and hands it the bar and the icon;
// it opens under the icon like the shell's own panels, and the shortcut
// `omarchy-shell shell toggle io.github.ferc10110.syllabus` reaches it through
// that icon. A click outside closes it unless it is pinned: pinned, clicks
// outside go to the windows below (mpv, say) and the panel stays.
// bin/syllabus makes every decision: this file keeps the last view it printed,
// refreshes it when the files it writes change, and sends every action back.
Panel {
  id: syllabus
  moduleName: "io.github.ferc10110.syllabus"
  // The shell routes the shortcut to the icon on the focused monitor; a fixed
  // IPC target would only ever reach one of the per-monitor copies.
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  // Shown and holding the keyboard: turns false while another window (an
  // editor opened from Notes, say) has the focus, and true again on return.
  readonly property bool focused: opened && keys.Window.active

  // ---- the panel's size and pin, kept in state.json (window.set)
  property bool pinned: false
  property int pinPending: 0
  property int viewWidth: 1100
  property int viewHeight: 720
  property bool resizing: false

  // ---- what bin/syllabus last said
  property var view: null
  property string viewText: ""
  property var courseMap: ({})
  property var roadmapMap: ({})
  readonly property var courses: view ? view.courses : []
  readonly property var roadmaps: view ? view.roadmaps : []
  readonly property var config: view ? view.config : null
  readonly property bool readilyOn: config !== null && config.readily.enabled === true

  // ---- navigation
  property string page: "library"      // library | course | roadmap | settings
  property string selectedId: ""
  property var trail: []
  property string topicFilter: ""      // "" every course, "__none__" courses without topic
  property string query: ""
  readonly property var selectedCourse: page === "course" ? (courseMap[selectedId] || null) : null
  readonly property var selectedRoadmap: page === "roadmap" ? (roadmapMap[selectedId] || null) : null

  property string notice: ""
  property bool noticeUrgent: false
  property bool scanning: false
  property bool autoScanDue: false
  property var pendingConfirm: null

  // Ops whose result can carry "rescan" or "webIds" (see ops.py): applying one can
  // trigger a real read of the web courses, which is what scanEngine's longer budget is
  // for and engine's 20 s is not — a Vimeo removal alone can fan out to several rounds
  // of yt-dlp. Keep this in sync with ops.py; tests/test_panel.py checks that it is.
  readonly property var rescanOps: ["folder.layout", "web.remove", "web.removeVideo"]

  function pluginPath(relative) {
    var url = String(Qt.resolvedUrl(relative))
    return url.indexOf("file://") === 0 ? decodeURIComponent(url.substring(7)) : url
  }

  onOpenedChanged: {
    if (!opened) return
    autoScanDue = true
    refresh()
  }

  function focusKeys() {
    Qt.callLater(function() { keys.forceActiveFocus() })
  }

  // ---- bin/syllabus
  function call(args, stdinObj, onDone) {
    engine.call(args, stdinObj, onDone)
  }

  function refresh() {
    engine.call(["view"], undefined, function(payload) {
      if (payload.error !== undefined) { syllabus.showNotice(payload.error, true); return }
      syllabus.setView(payload)
      syllabus.maybeScan()
    })
  }

  // Skipped when nothing changed, so lists are not rebuilt every poll.
  function setView(payload) {
    var text = JSON.stringify(payload)
    if (text === viewText) return
    viewText = text
    var courseIndex = {}
    var roadmapIndex = {}
    payload.courses.forEach(function(c) { courseIndex[c.id] = c })
    payload.roadmaps.forEach(function(r) { roadmapIndex[r.id] = r })
    courseMap = courseIndex
    roadmapMap = roadmapIndex
    view = payload
    if (pinPending === 0) pinned = payload.window.pinned === true
    if (!resizing) {
      viewWidth = payload.window.width
      viewHeight = payload.window.height
    }
    if ((page === "course" && !courseIndex[selectedId]) || (page === "roadmap" && !roadmapIndex[selectedId])) {
      page = "library"
      selectedId = ""
    }
  }

  // One change: the reply carries the new view, and `result` goes to onDone.
  // On error the notice shows the CLI's message, then onError (optional) gets
  // the error payload ({error, code, reason?}); onDone never runs then.
  function apply(op, onDone, onError) {
    var target = rescanOps.indexOf(op.op) >= 0 ? scanEngine : engine
    target.call(["apply"], op, function(payload) {
      if (payload.error !== undefined) {
        syllabus.showNotice(payload.error, true)
        if (onError) onError(payload)
        return
      }
      syllabus.setView(payload.view)
      if (payload.result && payload.result.scan) syllabus.showScanResult(payload.result.scan)
      if (onDone) onDone(payload.result || {})
    })
  }

  // Once mpv has the video the panel steps aside, unless it is pinned. On an
  // error it stays open to show why.
  function play(lessonId, at) {
    var args = ["play", lessonId]
    if (at !== undefined && at !== null) args = args.concat(["--at", String(at)])
    engine.call(args, undefined, syllabus.afterPlay)
  }

  function resume(courseId) {
    engine.call(courseId ? ["resume", courseId] : ["resume"], undefined, syllabus.afterPlay)
  }

  function afterPlay(payload) {
    if (payload.error !== undefined) syllabus.showNotice(payload.error, true)
    else if (!syllabus.pinned) syllabus.close()
  }

  // Shown at once; the reply (or its error) settles it.
  function togglePin() {
    var next = !pinned
    pinned = next
    pinPending++
    apply({ op: "window.set", pinned: next },
      function() { syllabus.pinPending-- },
      function() { syllabus.pinPending--; syllabus.pinned = !next })
  }

  function setViewSize(width, height) {
    viewWidth = Math.max(760, Math.round(width))
    viewHeight = Math.max(480, Math.round(height))
  }

  function commitView() {
    apply({ op: "window.set", width: viewWidth, height: viewHeight },
      function() { syllabus.resizing = false },
      function() { syllabus.resizing = false })
  }

  function resumeRoadmap(roadmap) {
    var id = Model.nextCourse(roadmap, courseMap)
    if (id === "") showNotice("Every course in this roadmap is done", false)
    else resume(id)
  }

  function scan(force) {
    if (scanning) return
    scanning = true
    autoScanDue = false
    scanEngine.call(force ? ["scan", "--force"] : ["scan"], undefined, function(payload) {
      syllabus.scanning = false
      if (payload.error !== undefined) { syllabus.showNotice(payload.error, true); return }
      syllabus.showScanResult(payload)
      syllabus.refresh()
    })
  }

  function showScanResult(result) {
    var text = result.courses + " courses · " + result.lessons + " videos · " + Math.round(result.hours) + " h"
    if (result.moved > 0) text += " · " + result.moved + " moved"
    if (result.errors.length > 0) text += " · " + result.errors.length + " unreadable"
    showNotice(text, false)
  }

  // At most one automatic scan per open(), once the disk is mounted and the last
  // scan is over an hour old: new videos show up without pressing Rescan. Checked
  // on every refresh while the window is open, so a disk plugged in after opening
  // still gets its scan; the chance is spent only when a scan starts (this or
  // any other), never by a check that found nothing to do.
  function maybeScan() {
    if (!autoScanDue || scanning || !view) return
    var stale = view.roots.some(function(r) {
      return r.online && (!r.scannedAt || Date.now() - Date.parse(r.scannedAt) > 3600 * 1000)
    })
    if (stale) scan(false)
  }

  // ---- navigation
  function go(nextPage, id) {
    var nextId = id || ""
    if (nextPage === page && nextId === selectedId) return
    trail = trail.concat([{ page: page, id: selectedId }]).slice(-20)
    page = nextPage
    selectedId = nextId
  }

  function openLibrary(topic) {
    topicFilter = topic || ""
    go("library", "")
  }

  function back() {
    while (trail.length > 0) {
      var last = trail[trail.length - 1]
      trail = trail.slice(0, trail.length - 1)
      if ((last.page === "course" && !courseMap[last.id]) || (last.page === "roadmap" && !roadmapMap[last.id])) continue
      page = last.page
      selectedId = last.id
      return
    }
    if (page === "library") close()
    else {
      page = "library"
      selectedId = ""
    }
  }

  // ---- dialogs and small helpers
  function ask(message, confirmText, action) {
    pendingConfirm = action
    confirm.message = message
    confirm.confirmText = confirmText
    confirm.selectedIndex = 1
    confirm.opened = true
  }

  function prompt(title, fields, confirmText, action) {
    promptDialog.show(title, fields, confirmText, action)
  }

  function editCourse(course) {
    courseEdit.show(course)
  }

  // Adding needs the network, so it is a command and not an apply: the CLI reads the
  // link first and only then writes.
  function webAdd(values, onDone) {
    var args = ["web-add", values.url]
    if (values.course) args = args.concat(["--course", values.course])
    if (values.title) args = args.concat(["--title", values.title])
    if (values.topic) args = args.concat(["--topic", values.topic])
    if (values.password) args = args.concat(["--password", values.password])
    scanEngine.call(args, undefined, function(payload) {
      if (payload.error === undefined) {
        if (payload.scan) syllabus.showScanResult(payload.scan)
        syllabus.refresh()
      }
      if (onDone) onDone(payload)
    })
  }

  function openWebAdd(courseId) { webAddDialog.show(courseId || "") }

  function webRefresh(courseId) {
    scanEngine.call(["web-refresh", courseId], undefined, function(payload) {
      if (payload.error !== undefined) { syllabus.showNotice(payload.error, true); return }
      syllabus.showScanResult(payload)
      syllabus.refresh()
    })
  }

  // The download runs detached: the panel only starts or stops it and watches
  // state.json, which every finished video updates.
  function download(courseId, stop) {
    engine.call(stop ? ["download", courseId, "--stop"] : ["download", courseId], undefined, function(payload) {
      if (payload.error !== undefined) { syllabus.showNotice(payload.error, true); return }
      syllabus.showNotice(stop ? (payload.stopped ? "Download stopped" : "That download was not running")
                                : "Downloading " + payload.pending + " videos", false)
      syllabus.refresh()
    })
  }

  function deleteDownloads(courseId) {
    engine.call(["downloads-delete", courseId], undefined, function(payload) {
      if (payload.error !== undefined) { syllabus.showNotice(payload.error, true); return }
      syllabus.showNotice(payload.removed + " files deleted", false)
      syllabus.refresh()
    })
  }

  // Clipboard via wl-copy with the text as its argument: no shell, no quoting.
  function copyText(text) {
    Quickshell.execDetached(["wl-copy", "--", String(text)])
    showNotice("Copied", false)
  }

  function openExternal(target) {
    Util.execArgv(["xdg-open", String(target)])
  }

  function showNotice(text, urgent) {
    notice = String(text || "")
    noticeUrgent = urgent === true
    noticeTimer.restart()
  }

  SyllabusEngine {
    id: engine
    program: syllabus.pluginPath("bin/syllabus")
    timeoutMs: 20000
  }

  // Scans get their own queue: a first scan can take a minute, and edits must not wait for it.
  SyllabusEngine {
    id: scanEngine
    program: syllabus.pluginPath("bin/syllabus")
    timeoutMs: 600000
  }

  // mpv's reports and every other writer change these files; the window follows.
  FileView {
    path: syllabus.view ? syllabus.view.paths.state : ""
    watchChanges: true
    printErrors: false
    onFileChanged: refreshDebounce.restart()
  }

  FileView {
    path: syllabus.view ? syllabus.view.paths.library : ""
    watchChanges: true
    printErrors: false
    onFileChanged: refreshDebounce.restart()
  }

  Timer {
    id: refreshDebounce
    interval: 400
    onTriggered: if (syllabus.opened) syllabus.refresh()
  }

  // Backup for a missed file event.
  Timer {
    interval: 15000
    repeat: true
    running: syllabus.opened
    onTriggered: syllabus.refresh()
  }

  Timer {
    id: noticeTimer
    interval: 5000
    onTriggered: syllabus.notice = ""
  }

  // What the panel calls when a click lands outside it, and what the bar calls
  // when another icon opens its panel: both are ignored while pinned. Esc, the
  // icon and the shortcut call close() directly and always close.
  QtObject {
    id: dismissOwner
    readonly property bool popoutSwitchClosing: syllabus.popoutSwitchClosing
    function close() { if (!syllabus.pinned) syllabus.close() }
    function closeForPopoutSwitch() { if (!syllabus.pinned) syllabus.closeForPopoutSwitch() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: syllabus.anchorItem
    owner: dismissOwner
    bar: syllabus.bar
    open: syllabus.opened
    focusTarget: keys
    contentWidth: panel.fittedContentWidth(syllabus.viewWidth)
    contentHeight: panel.cappedContentHeight(syllabus.viewHeight)
    // Pinned, only the card takes the pointer: clicks anywhere else reach the
    // windows below instead of closing the panel.
    mask: Region {
      x: syllabus.pinned ? panel.cardOrigin.x : 0
      y: syllabus.pinned ? panel.cardOrigin.y : 0
      width: syllabus.pinned ? panel.contentWidth : panel.screenW
      height: syllabus.pinned ? panel.contentHeight : panel.screenH
    }

    FocusScope {
      id: keys
      anchors.fill: parent
      focus: true

      Keys.onPressed: function(event) {
        if (confirm.opened) {
          if (confirm.handleKey(event)) event.accepted = true
          return
        }
        if (event.key !== Qt.Key_Escape) return
        event.accepted = true
        if (promptDialog.opened) promptDialog.cancel()
        else if (courseEdit.opened) courseEdit.cancel()
        else if (webAddDialog.opened) { webAddDialog.cancel(); return }
        else syllabus.back()
      }

      RowLayout {
        anchors.fill: parent
        spacing: 0

        Sidebar {
          Layout.fillHeight: true
          Layout.preferredWidth: 270
          app: syllabus
        }

        Rectangle {
          Layout.fillHeight: true
          Layout.preferredWidth: 1
          color: Util.alpha(Color.foreground, 0.12)
        }

        StackLayout {
          Layout.fillWidth: true
          Layout.fillHeight: true
          currentIndex: ["library", "course", "roadmap", "settings"].indexOf(syllabus.page)

          LibraryView { app: syllabus }
          CourseView {
            app: syllabus
            course: syllabus.selectedCourse
          }
          RoadmapView {
            app: syllabus
            roadmap: syllabus.selectedRoadmap
          }
          SettingsView { app: syllabus }
        }
      }

      Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Style.spacing.huge
        z: 40
        visible: syllabus.notice !== ""
        width: Math.min(noticeText.implicitWidth + 2 * Style.spacing.xxl, parent.width - 64)
        height: noticeText.contentHeight + 2 * Style.spacing.lg
        radius: Style.cornerRadius
        color: Color.popups.background
        border.width: Style.normalBorderWidth
        border.color: syllabus.noticeUrgent ? Color.urgent : Color.accent

        Text {
          id: noticeText
          anchors.fill: parent
          anchors.leftMargin: Style.spacing.xxl
          anchors.rightMargin: Style.spacing.xxl
          verticalAlignment: Text.AlignVCenter
          horizontalAlignment: Text.AlignHCenter
          wrapMode: Text.Wrap
          text: syllabus.notice
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }

        MouseArea {
          anchors.fill: parent
          onClicked: syllabus.notice = ""
        }
      }

      PromptDialog {
        id: promptDialog
        anchors.fill: parent
        z: 20
        onClosed: syllabus.focusKeys()
      }

      CourseEditDialog {
        id: courseEdit
        anchors.fill: parent
        z: 20
        app: syllabus
        onClosed: syllabus.focusKeys()
      }

      WebAddDialog {
        id: webAddDialog
        anchors.fill: parent
        z: 20
        app: syllabus
        onClosed: syllabus.focusKeys()
      }

      ConfirmDialog {
        id: confirm
        anchors.fill: parent
        z: 30
        background: Color.popups.background
        onConfirmed: {
          var action = syllabus.pendingConfirm
          syllabus.pendingConfirm = null
          opened = false
          syllabus.focusKeys()
          if (action) action()
        }
        onCanceled: {
          syllabus.pendingConfirm = null
          opened = false
          syllabus.focusKeys()
        }
      }

      // Drag the corner to resize, as in Runbook; the size is kept on release.
      MouseArea {
        id: grip
        width: panel.padding + Style.space(4)
        height: panel.padding + Style.space(4)
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: -(panel.padding + 2)
        anchors.bottomMargin: -(panel.padding + 2)
        z: 50
        hoverEnabled: true
        preventStealing: true
        cursorShape: Qt.SizeFDiagCursor
        acceptedButtons: Qt.LeftButton
        property point dragStart
        property int startWidth: 0
        property int startHeight: 0
        onPressed: function(mouse) {
          dragStart = mapToItem(null, mouse.x, mouse.y)
          startWidth = syllabus.viewWidth
          startHeight = syllabus.viewHeight
          syllabus.resizing = true
        }
        onPositionChanged: function(mouse) {
          if (!pressed) return
          var point = mapToItem(null, mouse.x, mouse.y)
          syllabus.setViewSize(startWidth + (point.x - dragStart.x), startHeight + (point.y - dragStart.y))
        }
        onReleased: syllabus.commitView()

        Text {
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          text: "\u25E2"
          color: grip.containsMouse || grip.pressed ? Color.accent : Color.muted
          font.pixelSize: Style.font.caption
        }
      }
    }
  }
}
