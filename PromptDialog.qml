import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC
import qs.Commons
import qs.Ui

// A small form over the window: a title, one or more fields, OK and Cancel.
// show(title, fields, confirmText, action): fields are
// [{ key, label, text, placeholder, multiline }]; action({ key: text }) runs on OK.
// Enter in a one-line field confirms; Ctrl+Enter confirms from a text area.
Item {
  id: root

  property bool opened: false
  property string title: ""
  property string confirmText: "OK"
  property var fields: []
  property var pendingAction: null
  property var values: ({})

  signal closed()

  visible: opened

  function show(dialogTitle, dialogFields, confirmLabel, action) {
    title = dialogTitle
    confirmText = confirmLabel || "OK"
    pendingAction = action
    var start = {}
    dialogFields.forEach(function(f) { start[f.key] = f.text || "" })
    values = start
    fields = dialogFields
    opened = true
    Qt.callLater(function() {
      var first = repeater.itemAt(0)
      if (first) first.focusField()
    })
  }

  function accept() {
    var action = pendingAction
    var result = values
    pendingAction = null
    opened = false
    closed()
    if (action) action(result)
  }

  function cancel() {
    pendingAction = null
    opened = false
    closed()
  }

  Rectangle {
    anchors.fill: parent
    color: Util.alpha(Color.background, 0.7)

    MouseArea {
      anchors.fill: parent
      onClicked: root.cancel()
    }

    Rectangle {
      id: card
      anchors.centerIn: parent
      width: Math.min(parent.width - 64, 520)
      height: form.implicitHeight + 2 * Style.spacing.huge
      radius: Style.cornerRadius
      color: Color.popups.background
      border.width: Style.normalBorderWidth
      border.color: Color.popups.border

      // Clicks on the card must not reach the scrim behind it.
      MouseArea { anchors.fill: parent }

      ColumnLayout {
        id: form
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Style.spacing.huge
        spacing: Style.spacing.lg

        Text {
          Layout.fillWidth: true
          text: root.title
          wrapMode: Text.Wrap
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.title
          font.bold: true
        }

        Repeater {
          id: repeater
          model: root.fields

          ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.spacing.labelGap

            function focusField() {
              if (modelData.multiline === true) area.forceActiveFocus()
              else line.forceActiveFocus()
            }

            Text {
              visible: (modelData.label || "") !== ""
              text: modelData.label || ""
              color: Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
            }

            TextField {
              id: line
              visible: modelData.multiline !== true
              Layout.fillWidth: true
              text: modelData.text || ""
              placeholderText: modelData.placeholder || ""
              onTextChanged: if (modelData.multiline !== true) root.values[modelData.key] = text
              onAccepted: root.accept()
            }

            QQC.TextArea {
              id: area
              visible: modelData.multiline === true
              Layout.fillWidth: true
              Layout.preferredHeight: 160
              text: modelData.text || ""
              placeholderText: modelData.placeholder || ""
              wrapMode: TextEdit.Wrap
              selectByMouse: true
              color: Color.foreground
              placeholderTextColor: Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.body
              background: Rectangle {
                radius: Style.cornerRadius
                color: Util.alpha(Color.foreground, 0.04)
                border.width: Style.normalBorderWidth
                border.color: area.activeFocus ? Color.accent : Style.normalBorderColor
              }
              onTextChanged: if (modelData.multiline === true) root.values[modelData.key] = text
              Keys.onPressed: function(event) {
                if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (event.modifiers & Qt.ControlModifier)) {
                  event.accepted = true
                  root.accept()
                }
              }
            }
          }
        }

        RowLayout {
          Layout.fillWidth: true
          Layout.topMargin: Style.spacing.md
          spacing: Style.spacing.controlGap

          Item { Layout.fillWidth: true }

          Button {
            text: "Cancel"
            onClicked: root.cancel()
          }

          Button {
            text: root.confirmText
            bordered: true
            selected: true
            onClicked: root.accept()
          }
        }
      }
    }
  }
}
