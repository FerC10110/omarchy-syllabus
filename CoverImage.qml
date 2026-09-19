import QtQuick
import qs.Commons
import "SyllabusModel.js" as Model

// A course cover, or the course's initials on a tinted tile when it has none.
Rectangle {
  id: cover

  property string source: ""
  property string title: ""

  radius: Style.cornerRadius
  color: Util.alpha(Color.accent, 0.14)
  clip: true

  Text {
    anchors.centerIn: parent
    visible: image.status !== Image.Ready
    text: Model.initials(cover.title)
    color: Color.accent
    font.family: Style.font.family
    font.pixelSize: Math.max(Style.font.body, Math.round(cover.height * 0.32))
    font.bold: true
  }

  Image {
    id: image
    anchors.fill: parent
    source: cover.source !== "" ? Util.fileUrl(cover.source) : ""
    fillMode: Image.PreserveAspectCrop
    asynchronous: true
    sourceSize.width: 480
    visible: status === Image.Ready
  }
}
