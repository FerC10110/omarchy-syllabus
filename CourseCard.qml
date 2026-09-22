import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// One course in the library: cover, title, progress, and continue.
Rectangle {
  id: card

  property var app
  property var course

  implicitHeight: col.implicitHeight + 2 * Style.spacing.lg
  radius: Style.cornerRadius
  color: mouse.containsMouse ? Style.hoverFill : Style.normalFill
  border.width: Style.normalBorderWidth
  border.color: Style.normalBorderColor

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: card.app.go("course", card.course.id)
  }

  ColumnLayout {
    id: col
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.margins: Style.spacing.lg
    spacing: Style.spacing.md

    CoverImage {
      Layout.fillWidth: true
      Layout.preferredHeight: Math.round(width * 9 / 16)
      source: card.course.cover
      title: card.course.title
    }

    Text {
      visible: card.course.web !== null && card.course.web !== undefined
      text: Model.icon("web")
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    Text {
      Layout.fillWidth: true
      text: card.course.title
      wrapMode: Text.Wrap
      maximumLineCount: 2
      elide: Text.ElideRight
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.subtitle
      font.bold: true
    }

    Text {
      Layout.fillWidth: true
      text: card.course.seenCount + "/" + card.course.lessonCount + " videos · " + Model.fmtDuration(card.course.duration)
      elide: Text.ElideRight
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    ProgressLine {
      Layout.fillWidth: true
      value: card.course.percent / 100
    }

    RowLayout {
      Layout.fillWidth: true
      spacing: Style.spacing.md

      Text {
        Layout.fillWidth: true
        text: Model.progressLabel(card.course)
        elide: Text.ElideRight
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      Button {
        visible: card.course.lessonCount > 0 && card.course.remaining > 0
        iconText: Model.icon("play")
        tooltipText: card.course.online ? "Continue" : "The disk is not mounted"
        onClicked: card.app.resume(card.course.id)
      }
    }
  }
}
