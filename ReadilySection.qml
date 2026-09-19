import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "SyllabusModel.js" as Model

// What Readily holds under this course's or roadmap's tag: copy it, open it, or
// import it here as a link or snippet.
Column {
  id: root

  property var app
  property var owner: null
  property var items: []
  property string tag: ""
  property string warning: ""
  property bool loading: false
  property string loadedFor: ""
  property int request: 0

  readonly property string ownerKey: owner ? owner.kind + ":" + owner.id : ""

  spacing: Style.spacing.xs

  // Only the newest request's answer is shown: switching courses while one is
  // on its way drops the old answer. If this section itself is torn down
  // (the CourseView/RoadmapView Loader deactivates when the course or
  // roadmap goes null) while the call is in flight, `root` resolves to null
  // and the reply is a silent no-op.
  function reload() {
    if (!owner || !visible) return
    var key = ownerKey
    var ref = owner
    var mine = ++request
    loading = true
    app.call(["readily-items", ref.kind, ref.id], undefined, function(payload) {
      if (!root || mine !== root.request) return
      root.loading = false
      root.loadedFor = key
      if (payload.error !== undefined) {
        root.items = []
        root.warning = payload.error
        return
      }
      root.items = payload.items
      root.tag = payload.tag
      root.warning = payload.warning
    })
  }

  onOwnerKeyChanged: {
    request++
    loading = false
    loadedFor = ""
    items = []
    tag = ""
    warning = ""
    reload()
  }

  // Read again every time it shows, so items tagged in Readily meanwhile appear.
  onVisibleChanged: if (visible) reload()

  RowLayout {
    width: root.width
    spacing: Style.spacing.md

    Text {
      text: "In Readily"
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.subtitle
      font.bold: true
    }

    Text {
      text: root.tag !== "" ? "#" + root.tag : ""
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }

    Item { Layout.fillWidth: true }

    Button {
      iconText: Model.icon("refresh")
      iconSpinning: root.loading
      tooltipText: "Refresh"
      onClicked: root.reload()
    }
  }

  Text {
    visible: root.warning !== ""
    width: root.width
    wrapMode: Text.Wrap
    text: root.warning
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }

  Text {
    visible: !root.loading && root.warning === "" && root.items.length === 0 && root.loadedFor === root.ownerKey
    width: root.width
    wrapMode: Text.Wrap
    text: "Nothing in Readily with this tag yet. Save a link above, or tag an item #" + root.tag + " in Readily."
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }

  Repeater {
    model: root.items

    RowLayout {
      width: root.width
      spacing: Style.spacing.md

      Text {
        text: Model.icon(modelData.isUrl ? "link" : "note")
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.title
      }

      Text {
        Layout.fillWidth: true
        text: modelData.title !== "" ? modelData.title : Model.preview(modelData.text, 90)
        elide: Text.ElideRight
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }

      Text {
        text: modelData.section
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      Button {
        visible: modelData.isUrl
        iconText: Model.icon("open")
        tooltipText: "Open"
        onClicked: root.app.openExternal(modelData.text.trim())
      }

      Button {
        iconText: Model.icon("copy")
        tooltipText: "Copy"
        onClicked: {
          var section = modelData.section
          var itemIndex = modelData.index
          var hash = modelData.hash
          root.app.apply({ op: "readily.copy", section: section, index: itemIndex, hash: hash }, function() {
            if (!root) return
            root.app.showNotice("Copied", false)
          })
        }
      }

      Button {
        iconText: Model.icon("plus")
        tooltipText: "Import into this list"
        onClicked: root.app.apply({ op: "link.add", owner: root.owner, title: modelData.title,
          content: modelData.text, truncated: modelData.truncated })
      }
    }
  }
}
