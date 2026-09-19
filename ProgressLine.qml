import QtQuick
import qs.Commons

// A thin bar: what was watched, in the accent color, over a faint track.
Item {
  id: line

  property real value: 0
  property int thickness: 3
  property color fill: Color.accent

  implicitHeight: thickness

  Rectangle {
    anchors.fill: parent
    radius: height / 2
    color: Util.alpha(Color.foreground, 0.12)
  }

  Rectangle {
    width: parent.width * Math.max(0, Math.min(1, line.value))
    height: parent.height
    radius: height / 2
    color: line.fill
    visible: line.value > 0
  }
}
