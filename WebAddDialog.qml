import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// Add a course from the web: a link, and what to call it. A link that turns out to be
// a single video can join a web course that already exists instead of making its own.
Item {
  id: root

  property var app
  property bool opened: false
  property bool working: false
  property string error: ""
  property string link: ""
  property string title: ""
  property string topic: ""
  property string password: ""
  property string courseId: ""            // "" = a new course

  readonly property var webCourses: (app && app.courses ? app.courses : []).filter(function(c) { return c.web })

  // As PromptDialog and CourseEditDialog do: the panel returns keyboard focus
  // to itself once this modal is gone.
  signal closed()

  function show(intoCourseId) {
    link = ""; title = ""; topic = ""; password = ""; error = ""; working = false
    courseId = intoCourseId || ""
    coursePicker.value = courseId
    // A TextField's `text: root.x` binding is destroyed the moment the user types
    // into it (QML drops a property's binding on the first imperative write, and
    // typing is one), so a later show() resetting `root.x` alone would leave the
    // previous text on screen. Clear the fields themselves too.
    linkField.text = ""
    titleField.text = ""
    topicField.text = ""
    passwordField.text = ""
    opened = true
    Qt.callLater(function() { linkField.forceActiveFocus() })
  }

  function cancel() {
    if (working) return
    opened = false
    closed()
  }

  function accept() {
    if (working || link.trim() === "") return
    working = true
    error = ""
    app.webAdd({ url: link.trim(), course: courseId, title: title.trim(), topic: topic.trim(),
                 password: password.trim() }, function(payload) {
      root.working = false
      if (payload.error !== undefined) { root.error = payload.error; return }
      root.opened = false
      root.closed()
      app.go("course", payload.courseId)
    })
  }

  visible: opened

  Rectangle {
    anchors.fill: parent
    color: Util.alpha(Color.background, 0.7)

    MouseArea {
      anchors.fill: parent
      onClicked: root.cancel()
    }

    BorderSurface {
      anchors.centerIn: parent
      width: Math.min(parent.width - 2 * Style.spacing.panelPadding, 560)
      height: column.implicitHeight + 2 * Style.spacing.panelPadding
      color: Color.popups.background
      borderSpec: Border.flat(Color.popups.border, Style.normalBorderWidth)
      radius: Style.cornerRadius

      MouseArea { anchors.fill: parent }        // clicks inside must not close it

      ColumnLayout {
        id: column
        anchors.fill: parent
        anchors.margins: Style.spacing.panelPadding
        spacing: Style.spacing.md

        Text {
          text: "Add from the web"
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.heading
          font.bold: true
        }

        Text {
          Layout.fillWidth: true
          wrapMode: Text.Wrap
          text: "Paste a YouTube playlist, a Vimeo showcase, or a single video. Public or unlisted only."
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        TextField {
          id: linkField
          Layout.fillWidth: true
          placeholderText: "https://…"
          text: root.link
          onTextChanged: root.link = text
          onAccepted: root.accept()
        }

        TextField {
          id: titleField
          Layout.fillWidth: true
          placeholderText: "Title (optional)"
          text: root.title
          onTextChanged: root.title = text
        }

        TextField {
          id: topicField
          Layout.fillWidth: true
          placeholderText: "Topic (optional)"
          text: root.topic
          onTextChanged: root.topic = text
        }

        TextField {
          id: passwordField
          Layout.fillWidth: true
          placeholderText: "Video password (only if the site asks for one)"
          password: true
          text: root.password
          onTextChanged: root.password = text
        }

        Dropdown {
          id: coursePicker
          Layout.fillWidth: true
          visible: root.webCourses.length > 0
          label: "Add to"
          options: [{ value: "", label: "New course" }].concat(root.webCourses.map(function(c) {
            return { value: c.id, label: c.title }
          }))
          // Dropdown writes its own `value` on pick, which would break a plain binding.
          onChanged: function(value) { root.courseId = value }
        }

        Text {
          Layout.fillWidth: true
          visible: root.error !== ""
          wrapMode: Text.Wrap
          text: root.error
          color: Color.urgent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        RowLayout {
          Layout.alignment: Qt.AlignRight
          spacing: Style.spacing.sm

          Text {
            visible: root.working
            text: "Reading the playlist…"
            color: Color.muted
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }

          Button {
            text: "Cancel"
            enabled: !root.working
            onClicked: root.cancel()
          }

          Button {
            text: "Add"
            selected: true
            enabled: !root.working && root.link.trim() !== ""
            onClicked: root.accept()
          }
        }
      }
    }
  }
}
