import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Io

PanelWindow {
    id: island

    anchors.top: true
    color: "transparent"
    exclusiveZone: 0
    visible: true

    mask: Region {
        item: shell
    }

    focusable: island.isHovered || island.panelOpen

    // ================= music state =================
    property bool isPlaying: statusText === "playing"
    property bool isIdleStatus: statusText === "not playing"
    property bool isHovered: false
    property bool hasSession: nowPlaying.length > 0
    property string statusText: "not playing"
    property string nowPlaying: ""
    property string duration: ""
    property string thumbnailSource: ""
    property bool isLastPlayed: false
    property string homeDir: ""

    // ================= interaction state =================
    property bool panelOpen: false
    property string uiMode: panelOpen ? "panel"
        : (island.isHovered ? "hover" : "idle")

    // ================= sizing =================
    property int hitPad: 15
    property int tinyW: 100
    property int tinyH: 10
    property int idleH: 30
    property int hoverW: 300
    property int hoverH: 60
    property int panelW: 400
    property int panelH: 600

    property int idleMusicWidth: Math.max(150, Math.min(titleText.implicitWidth + 24 + (island.thumbnailSource.length > 0 ? 32 : 0), 380))

    function contentWidth() {
        if (island.uiMode === "panel") return island.panelW;
        if (island.uiMode === "hover") return island.hoverW;
        return (island.hasSession && !island.isIdleStatus) ? island.idleMusicWidth : island.tinyW;
    }
    function contentHeight() {
        if (island.uiMode === "panel") return island.panelH;
        if (island.uiMode === "hover") return island.hoverH;
        return (island.hasSession && !island.isIdleStatus) ? island.idleH : island.tinyH;
    }

    readonly property int maxContentW: Math.max(panelW, 380) + hitPad * 5
    readonly property int maxContentH: panelH + hitPad * 2

    implicitWidth: maxContentW
    implicitHeight: maxContentH

    // ================= flow processes =================
    Process {
        id: statusProc
        command: ["flow", "--status"]
        running: false
        stdout: StdioCollector { onStreamFinished: island.parseStatus(this.text) }
    }
    Process {
        id: homeProc
        command: ["sh", "-c", "echo $HOME"]
        running: false
        stdout: StdioCollector { onStreamFinished: island.homeDir = this.text.trim() }
    }
    Process { id: prevProc; command: ["flow", "--previous"]; running: false }
    Process { id: toggleProc; command: ["flow", "--stop"]; running: false }
    Process { id: nextProc; command: ["flow", "--next"]; running: false }

    Process {
        id: radioProc
        property string query: ""
        command: ["flow", "radio"].concat(radioProc.query.trim().length > 0 ? radioProc.query.trim().split(/\s+/) : [])
        running: false
    }
    Process { id: stopAll; command: ["flow", "--stop-all"]; running: false }
    function runRadio(q) {
        if (q.trim().length === 0) return;
        stopAll.running = true;
        radioProc.running = false;
        radioProc.query = q;
        stopAll.running = false;
        radioProc.running = true;
    }

    Timer {
        interval: 1500
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: {
            statusProc.running = true;
            if (island.homeDir === "") homeProc.running = true;
        }
    }

    function stripAnsi(text) { return text.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, ""); }
    function resolveThumbnail(raw) {
        const t = raw.trim();
        if (/^https?:\/\//i.test(t)) return t;
        let p = t.startsWith("~") ? island.homeDir + t.substring(1) : t;
        if (p.startsWith("/downloads/") || p.startsWith("/cache/") || p.startsWith("/.cache/")) {
            p = island.homeDir + "/.flow" + p;
        }
        return p;
    }
    function parseStatus(rawText) {
        const text = island.stripAnsi(rawText);
        const statusMatch = text.match(/status\s*:\s*(.+)/i);
        const nowMatch = text.match(/currently playing\s*:\s*(.+)/i);
        const lastMatch = text.match(/last played\s*:\s*(.+)/i);
        const durMatch = text.match(/total duration\s*:\s*(.+)/i);
        const thumbMatch = text.match(/thumbnail\s*:\s*(.+)/i);

        island.statusText = statusMatch ? statusMatch[1].trim() : "not playing";
        island.thumbnailSource = thumbMatch ? island.resolveThumbnail(thumbMatch[1].trim()) : "";

        if (nowMatch) { island.nowPlaying = nowMatch[1].trim(); island.isLastPlayed = false; }
        else if (lastMatch) { island.nowPlaying = lastMatch[1].trim(); island.isLastPlayed = true; }
        else { island.nowPlaying = ""; island.isLastPlayed = false; }

        island.duration = durMatch ? durMatch[1].trim() : "";
    }

    // MouseArea is bound to `shell`, not the full (now-fixed-size) window,
    // so hover/click detection only fires over the visually-visible pill/panel.
    MouseArea {
        anchors.fill: shell
        hoverEnabled: true
        onEntered: island.isHovered = true
        onExited: island.isHovered = false
        onClicked: island.panelOpen = !island.panelOpen // click toggles panel open/closed
    }

    Item {
        anchors.fill: parent
        focus: island.isHovered || island.panelOpen
        Keys.onEscapePressed: if (island.panelOpen) island.panelOpen = false
    }

    // ================= shell =================
    Rectangle {
        id: shell
        width: contentWidth()
        height: contentHeight()
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        radius: {
            if (island.uiMode === "panel") return 10;
            if (island.uiMode === "idle") return 5;
            return height / 8;
        }
        color: "#000"
        border.color: "#242424"
        border.width: (island.uiMode === "idle" && !(island.hasSession && !island.isIdleStatus)) ? 0 : 1
        clip: true

        Behavior on width { NumberAnimation { duration: 600; easing.type: Easing.OutExpo } }
        Behavior on height { NumberAnimation { duration: 600; easing.type: Easing.OutExpo } }
        Behavior on radius { NumberAnimation { duration: 200; easing.type: Easing.OutExpo } }

        // ---- idle: mini music pill ----
        Row {
            anchors.centerIn: parent
            spacing: 10
            visible: island.uiMode === "idle" && island.hasSession && !island.isIdleStatus

            Rectangle {
                width: 20; height: 20; radius: 10
                color: "transparent"; clip: true
                anchors.verticalCenter: parent.verticalCenter
                visible: island.thumbnailSource.length > 0
                Image {
                    anchors.fill: parent
                    source: island.thumbnailSource
                    sourceSize: Qt.size(60, 60)
                    fillMode: Image.PreserveAspectCrop
                    mipmap: true; asynchronous: true
                }
            }
            Text {
                id: titleText
                text: island.nowPlaying
                color: "#f5f5f5"; font.pixelSize: 12; font.bold: true
                elide: Text.ElideRight
                width: island.idleMusicWidth - 24 - (island.thumbnailSource.length > 0 ? 28 : 0)
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        // ---- hover: quick music controls ----
        Row {
            anchors.centerIn: parent
            spacing: 10
            visible: island.uiMode === "hover"

            Rectangle {
                width: 44; height: 44; radius: 20
                color: "transparent"; clip: true
                anchors.verticalCenter: parent.verticalCenter
                visible: island.thumbnailSource.length > 0
                Image {
                    anchors.fill: parent
                    source: island.thumbnailSource
                    sourceSize: Qt.size(94, 94)
                    fillMode: Image.PreserveAspectCrop
                    mipmap: true; asynchronous: true
                }
            }
            Column {
                spacing: 2
                anchors.verticalCenter: parent.verticalCenter
                Text {
                    text: island.nowPlaying.length > 0 ? island.nowPlaying : "Nothing playing"
                    color: "#f5f5f5"; font.pixelSize: 12; font.bold: true
                    elide: Text.ElideRight
                    width: shell.width - 24 - 44 - ctrlRow.implicitWidth - 16
                }
                Text { text: island.duration; color: "#999999"; font.pixelSize: 11 }
            }
            Row {
                id: ctrlRow
                spacing: 6
                anchors.verticalCenter: parent.verticalCenter
                Text {
                    id: prevBtn; text: "󰼨"
                    color: prevBtn.hovered ? "#f5f5f5" : "#999999"; font.pixelSize: 20
                    property bool hovered: false
                    MouseArea { anchors.fill: parent; hoverEnabled: true; onEntered: prevBtn.hovered = true; onExited: prevBtn.hovered = false; onClicked: prevProc.running = true }
                }
                Text {
                    id: toggleBtn; text: island.isPlaying ? "󰏤" : "󰐊"
                    color: toggleBtn.hovered ? "#f5f5f5" : "#999999"; font.pixelSize: 20
                    property bool hovered: false
                    MouseArea { anchors.fill: parent; hoverEnabled: true; onEntered: toggleBtn.hovered = true; onExited: toggleBtn.hovered = false; onClicked: toggleProc.running = true }
                }
                Text {
                    id: nextBtn; text: "󰼧"
                    color: nextBtn.hovered ? "#f5f5f5" : "#999999"; font.pixelSize: 20
                    property bool hovered: false
                    MouseArea { anchors.fill: parent; hoverEnabled: true; onEntered: nextBtn.hovered = true; onExited: nextBtn.hovered = false; onClicked: nextProc.running = true }
                }
            }
        }

        // ---- panel: full 400x600 music detail view ----
        Column {
            anchors.centerIn: parent
            spacing: 16
            visible: island.uiMode === "panel"

            Rectangle {
                width: 260; height: 260; radius: 10
                color: "#1a1a1c"; clip: true
                anchors.horizontalCenter: parent.horizontalCenter
                visible: island.thumbnailSource.length > 0
                Image {
                    anchors.fill: parent
                    source: island.thumbnailSource
                    sourceSize: Qt.size(320, 320)
                    fillMode: Image.PreserveAspectCrop
                    mipmap: true; asynchronous: true
                }
            }
            Text {
                text: island.nowPlaying.length > 0 ? island.nowPlaying : "Nothing playing"
                color: "#f5f5f5"; font.pixelSize: 16; font.bold: true
                width: 320; horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                anchors.horizontalCenter: parent.horizontalCenter
            }
            Text {
                text: island.isLastPlayed ? "Last played · " + island.duration : island.duration
                color: "#999999"; font.pixelSize: 12
                anchors.horizontalCenter: parent.horizontalCenter
                visible: island.duration.length > 0
            }
            Row {
                spacing: 16
                anchors.horizontalCenter: parent.horizontalCenter
                Text {
                    id: pPrevBtn; text: "󰼨"
                    color: pPrevBtn.hovered ? "#f5f5f5" : "#999999"; font.pixelSize: 30
                    property bool hovered: false
                    MouseArea { anchors.fill: parent; anchors.margins: -8; hoverEnabled: true; onEntered: pPrevBtn.hovered = true; onExited: pPrevBtn.hovered = false; onClicked: prevProc.running = true }
                }
                Text {
                    id: pToggleBtn; text: island.isPlaying ? "󰏤" : "󰐊"
                    color: pToggleBtn.hovered ? "#f5f5f5" : "#999999"; font.pixelSize: 30
                    property bool hovered: false
                    MouseArea { anchors.fill: parent; anchors.margins: -8; hoverEnabled: true; onEntered: pToggleBtn.hovered = true; onExited: pToggleBtn.hovered = false; onClicked: toggleProc.running = true }
                }
                Text {
                    id: pNextBtn; text: "󰼧"
                    color: pNextBtn.hovered ? "#f5f5f5" : "#999999"; font.pixelSize: 30
                    property bool hovered: false
                    MouseArea { anchors.fill: parent; anchors.margins: -8; hoverEnabled: true; onEntered: pNextBtn.hovered = true; onExited: pNextBtn.hovered = false; onClicked: nextProc.running = true }
                }
            }
            Rectangle { width: 320; height: 1; color: "#242424"; anchors.horizontalCenter: parent.horizontalCenter }

            Rectangle {
                width: 320; height: 34; radius: 10
                color: "#141416"
                border.color: radioInput.activeFocus ? "#3a3a3f" : "#242424"
                border.width: 1
                anchors.horizontalCenter: parent.horizontalCenter

                Row {
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 6

                    Item {
                        width: parent.width - 24
                        height: parent.height
                        anchors.verticalCenter: parent.verticalCenter

                        Text {
                            text: "Start a radio for..."
                            color: "#5c5c5c"; font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                            visible: radioInput.text.length === 0
                        }
                        TextInput {
                            id: radioInput
                            anchors.fill: parent
                            verticalAlignment: TextInput.AlignVCenter
                            color: "#f5f5f5"
                            font.pixelSize: 12
                            clip: true
                            selectByMouse: true
                            Keys.onReturnPressed: { island.runRadio(radioInput.text); radioInput.text = ""; }
                        }
                    }
                    Text {
                        text: "󰍉"
                        color: "#999999"; font.pixelSize: 14
                        anchors.verticalCenter: parent.verticalCenter
                        MouseArea {
                            anchors.fill: parent; anchors.margins: -6
                            onClicked: { island.runRadio(radioInput.text); radioInput.text = ""; }
                        }
                    }
                }
            }
        }
    }
}
