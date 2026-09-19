import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// The documents in the course's folder (PDFs, text, slides…), opened with the
// desktop's default app. Read again each time the tab opens.
Item {
  id: root

  property var app
  property var course
  property bool active: false
  property var files: []
  property string base: ""
  property bool online: true
  property bool loading: false
  property string loadedFor: ""

  function load() {
    if (!course || !active) return
    var id = course.id
    loading = true
    app.call(["files", id], undefined, function(payload) {
      // This tab may be gone by the time the reply comes back (the course
      // went null and the CourseView Loader tore it down): a silent no-op.
      if (!root) return
      root.loading = false
      if (!root.course || root.course.id !== id) return
      if (payload.error !== undefined) { root.app.showNotice(payload.error, true); return }
      root.files = payload.files
      root.base = payload.root
      root.online = payload.online
      root.loadedFor = id
    })
  }

  onActiveChanged: if (active) load()
  onCourseChanged: {
    if (course && course.id !== loadedFor) {
      files = []
      load()
    }
  }

  ColumnLayout {
    anchors.fill: parent
    spacing: Style.spacing.lg

    RowLayout {
      Layout.fillWidth: true
      spacing: Style.spacing.controlGap

      Text {
        Layout.fillWidth: true
        text: root.files.length === 1 ? "1 file" : root.files.length + " files"
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }

      Button {
        visible: root.online && root.base !== "" && root.course !== null
        iconText: Model.icon("open")
        text: "Open folder"
        onClicked: root.app.openExternal(root.base + "/" + root.course.relpath)
      }
    }

    Text {
      Layout.fillWidth: true
      visible: !root.online
      wrapMode: Text.Wrap
      text: "The course disk is not mounted: the files can't be opened."
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    Text {
      Layout.fillWidth: true
      visible: root.online && !root.loading && root.files.length === 0 && root.course !== null && root.loadedFor === root.course.id
      text: "No documents in this course's folder."
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.body
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

        Repeater {
          model: root.files

          Rectangle {
            width: list.width
            implicitHeight: fileRow.implicitHeight + 2 * Style.spacing.md
            radius: Style.cornerRadius
            color: fileMouse.containsMouse ? Style.hoverFill : "transparent"

            MouseArea {
              id: fileMouse
              anchors.fill: parent
              hoverEnabled: true
              enabled: root.online
              cursorShape: Qt.PointingHandCursor
              onClicked: root.app.openExternal(modelData.path)
            }

            RowLayout {
              id: fileRow
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              anchors.leftMargin: Style.spacing.lg
              anchors.rightMargin: Style.spacing.lg
              spacing: Style.spacing.lg

              Text {
                text: Model.icon("file")
                color: Color.accent
                font.family: Style.font.family
                font.pixelSize: Style.font.title
              }

              Text {
                Layout.fillWidth: true
                text: modelData.name
                elide: Text.ElideMiddle
                color: Color.foreground
                font.family: Style.font.family
                font.pixelSize: Style.font.body
              }

              Text {
                text: (modelData.ext !== "" ? modelData.ext.toUpperCase() + " · " : "") + Model.fmtBytes(modelData.size)
                color: Color.muted
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
              }
            }
          }
        }
      }
    }
  }
}
