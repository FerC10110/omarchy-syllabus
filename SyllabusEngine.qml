import QtQuick
import Quickshell.Io

// Runs bin/syllabus one call at a time (a queue), as runbook's engine does.
// Every call ends in onDone(payload): the JSON the command printed, or
// {error, code} when it could not run, printed no JSON, or outlived timeoutMs.
Item {
  id: engine

  property string program: ""
  property int timeoutMs: 20000
  readonly property bool busy: current !== null

  property var queue: []
  property var current: null
  property string _out: ""
  property string _err: ""
  property bool _exited: false
  property bool _outDone: false
  property bool _errDone: false
  property bool _timedOut: false
  property bool _started: false

  // Identifies which call the settle/watchdog timers were last armed for, so a
  // timer queued for a call that has already finished can never reach into the
  // next one (a fresh call can start within the same tick that ends the last).
  property int _callId: 0
  property int _settleFor: -1
  property int _watchFor: -1

  function call(args, stdinObj, onDone) {
    queue.push({ args: args, stdin: stdinObj, onDone: onDone })
    _pump()
  }

  function _pump() {
    if (current !== null || queue.length === 0) return
    current = queue.shift()
    _callId++
    _out = ""
    _err = ""
    _exited = false
    _outDone = false
    _errDone = false
    _timedOut = false
    _started = false
    settle.stop()
    proc.command = [program].concat(current.args)
    proc.running = true
    _watchFor = _callId
    watchdog.restart()
  }

  function _lastLine(text) {
    var lines = String(text || "").trim().split("\n")
    return lines[lines.length - 1].replace(/^syllabus: /, "")
  }

  function _finish() {
    if (current === null) return
    var call = current
    current = null
    watchdog.stop()
    settle.stop()
    var payload = null
    if (_timedOut) {
      payload = { error: "Syllabus took too long and was stopped", code: 1 }
    } else if (!_started) {
      payload = { error: "Couldn't run bin/syllabus", code: 1 }
    } else {
      try { payload = JSON.parse(_out) } catch (e) { payload = null }
      if (payload === null || typeof payload !== "object")
        payload = { error: _lastLine(_err) || "Syllabus gave no answer", code: 1 }
    }
    if (call.onDone) {
      try { call.onDone(payload) } catch (e) { console.warn("syllabus: " + e) }
    }
    Qt.callLater(_pump)
  }

  function _maybeFinish() {
    if (_exited && _outDone && _errDone) _finish()
  }

  Process {
    id: proc
    stdinEnabled: true

    onStarted: {
      engine._started = true
      // The CLI reads one line, and only for `apply`.
      if (engine.current && engine.current.stdin !== undefined) write(JSON.stringify(engine.current.stdin) + "\n")
    }

    // A program that never starts gives no onStarted and no onExited.
    onRunningChanged: {
      if (!running && !engine._started && engine.current !== null) engine._finish()
    }

    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        engine._out = String(text || "")
        engine._outDone = true
        engine._maybeFinish()
      }
    }

    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        engine._err = String(text || "")
        engine._errDone = true
        engine._maybeFinish()
      }
    }

    onExited: function(exitCode) {
      engine._exited = true
      engine._maybeFinish()
      // The streams close with the process; this only covers one that never says
      // so. _maybeFinish() above already finishes the call once every stream is
      // in (the common case), nulling `current` — arming this backup timer
      // afterwards would blindly finish whatever call runs next, so only arm it
      // while this exit's call is still the one waiting to finish.
      if (engine.current !== null) {
        engine._settleFor = engine._callId
        settle.restart()
      }
    }
  }

  Timer {
    id: settle
    interval: 250
    onTriggered: {
      if (engine._settleFor !== engine._callId) return
      engine._finish()
    }
  }

  Timer {
    id: watchdog
    interval: engine.timeoutMs
    onTriggered: {
      if (engine._watchFor !== engine._callId) return
      engine._timedOut = true
      proc.running = false
      engine._settleFor = engine._callId
      settle.restart()
    }
  }
}
