import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// A labeled text setting. `committed` fires on Enter, or when the field loses
// focus with a changed value. The field always ends up tracking `text` again
// after that: a rejected value (the caller never changes `text`) is replaced
// by the still-saved one instead of being left showing as if it had saved,
// and a `text` that changes for another reason (a server-normalized value,
// another edit) is picked up without the field being touched again. The
// first keystroke breaks the plain `text: root.text` binding (any imperative
// write does, and TextInput writes on every keystroke), so it is restored
// with Qt.binding() once editing is done, after the typed value has already
// been read for the commit.
ColumnLayout {
  id: root

  property string label: ""
  property string description: ""
  property string text: ""
  property string placeholder: ""

  signal committed(string text)

  spacing: Style.spacing.labelGap

  Text {
    text: root.label
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  Text {
    Layout.fillWidth: true
    visible: root.description !== ""
    text: root.description
    wrapMode: Text.Wrap
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }

  TextField {
    id: field
    Layout.fillWidth: true
    Layout.maximumWidth: 440
    text: root.text
    placeholderText: root.placeholder
    onEditingFinished: {
      var typed = field.text
      if (typed !== root.text) root.committed(typed)
      field.text = Qt.binding(function() { return root.text })
    }
  }
}
