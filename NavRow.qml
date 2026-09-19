import QtQuick
import QtQuick.Layouts
import qs.Commons

// A clickable row for the sidebar: icon, label, a detail on the right, and an
// optional thin progress line along the bottom.
Rectangle {
  id: row

  property string icon: ""
  property string label: ""
  property string detail: ""
  property bool selected: false
  property real progress: -1

  signal clicked()

  implicitHeight: Math.round(Style.font.body * 2.5)
  radius: Style.cornerRadius
  color: selected ? Style.selectedFill : (mouse.containsMouse ? Style.hoverFill : "transparent")

  RowLayout {
    anchors.fill: parent
    anchors.leftMargin: Style.spacing.lg
    anchors.rightMargin: Style.spacing.lg
    spacing: Style.spacing.lg

    Text {
      visible: row.icon !== ""
      text: row.icon
      color: row.selected ? Color.accent : Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.title
    }

    Text {
      Layout.fillWidth: true
      text: row.label
      elide: Text.ElideRight
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    Text {
      visible: row.detail !== ""
      text: row.detail
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }
  }

  ProgressLine {
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    anchors.leftMargin: Style.spacing.lg
    anchors.rightMargin: Style.spacing.lg
    visible: row.progress >= 0
    value: Math.max(0, row.progress)
    thickness: 2
  }

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: row.clicked()
  }
}
