#!/usr/bin/env python3
#
# Robot and chat, side by side, in the browser: the live world view (same
# pose feed as world_viewer.py, drawn on a canvas) next to the "#robots"
# chat channel, with a box to send messages. Serves http://localhost:8123
# with one SSE stream carrying poses, chat messages and connection status.
# (A claude.ai Artifact page can't connect to MQTT -- its sandbox blocks
# external connections -- hence this small local web app.)
#
# The page is a chat client like "aiko_chat repl": it discovers the
# ChatServer (wherever it runs, e.g aiko.hashtag.ai), subscribes to the
# channel topic and sends via ChatServer.send_message().
#
# Usage
# ~~~~~
#   source env.sh
#   ./world_viewer_web.py [--name anj_turtle_world] [--channel robots]
#                         [--username anj] [--botname @@anj_turtlebot]
#                         [--port 8123]
#   then open http://localhost:8123

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import queue
import threading
import time

import click

import aiko_services as aiko
from aiko_chat import ChatServer, get_server_service_filter
from aiko_chat.protocol import _decode_message
from virtual_world import VirtualWorld, WORLD_NAME

_CHANNEL = "robots"
_BOTNAME = "@@anj_turtlebot"
_HISTORY_LIMIT = 300
_TRAIL_LIMIT = 2000
_ACK_SUFFIX = " !!!!"           # bots' loop-prevention marker, see aiko_chat.bot

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>TurtleBot Live</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root { --bg:#f7f6f2; --surface:#ffffff; --ink:#1c2420; --muted:#5c6b62;
        --line:#d8ded9; --accent:#0b7a4b; --bot:#2456a6; --me:#eef7f1; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#101512; --surface:#182019; --ink:#e6ece7; --muted:#93a398;
          --line:#2a352c; --accent:#3ecf8e; --bot:#8fb4ff; --me:#1f2d24; }
}
* { box-sizing:border-box; }
body { background:var(--bg); color:var(--ink); margin:0; padding:0 16px 24px;
       font-family:"IBM Plex Mono",monospace; display:flex; flex-direction:column;
       align-items:center; min-height:100vh; }
h1 { font-family:"Sora",sans-serif; font-size:1.3rem; margin:24px 0 4px; }
#status { color:var(--muted); font-size:0.78rem; margin-bottom:16px; text-align:center; }
#grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:16px;
        width:min(100%,1180px); align-items:start; }
@media (max-width: 900px) { #grid { grid-template-columns:1fr; } }
.panel { background:var(--surface); border:1px solid var(--line); border-radius:6px;
         padding:12px; min-width:0; }
.panel h2 { font-family:"Sora",sans-serif; font-size:0.95rem; margin:0 0 10px; }
canvas { display:block; width:100%; height:auto; aspect-ratio:1/1; }
#bar { display:flex; gap:16px; align-items:center; margin-top:12px; flex-wrap:wrap; }
#pose { color:var(--accent); font-size:0.85rem; }
button { font-family:"IBM Plex Mono",monospace; font-size:0.78rem;
         background:var(--accent); color:var(--bg); border:none;
         border-radius:4px; padding:6px 12px; cursor:pointer; }
button:hover { opacity:0.88; }
button:focus-visible, input:focus-visible { outline:2px solid var(--muted); outline-offset:2px; }
#messages { list-style:none; margin:0; padding:0; height:min(60vh,520px); overflow-y:auto;
            border:1px solid var(--line); border-radius:4px; font-size:0.82rem; }
#messages li { padding:6px 10px; border-bottom:1px solid var(--line); word-break:break-word; }
#messages li:last-child { border-bottom:none; }
#messages .who { color:var(--muted); margin-right:8px; }
#messages .bot .who { color:var(--bot); }
#messages .me { background:var(--me); }
#messages .me .who { color:var(--accent); }
#messages .time { float:right; color:var(--muted); font-size:0.7rem; }
#empty { color:var(--muted); font-size:0.8rem; padding:10px; }
#chips { display:flex; gap:6px; flex-wrap:wrap; margin:10px 0; }
#chips button { background:var(--surface); color:var(--ink); border:1px solid var(--line); }
#chips button:hover { border-color:var(--accent); opacity:1; }
#send { display:flex; gap:8px; }
#text { flex:1; min-width:0; font-family:"IBM Plex Mono",monospace; font-size:0.85rem;
        padding:8px 10px; border:1px solid var(--line); border-radius:4px;
        background:var(--bg); color:var(--ink); }
</style></head><body>
<h1>TurtleBot Live</h1>
<div id="status">connecting…</div>
<main id="grid">
<section class="panel" id="robot">
  <h2>Robot <span id="world" style="color:var(--muted);font-weight:normal;font-size:0.78rem"></span></h2>
  <canvas id="c" width="560" height="560"></canvas>
  <div id="bar">
    <button id="clear">clear trail</button>
    <div id="pose"></div>
  </div>
</section>
<section class="panel" id="chat">
  <h2>#__CHANNEL__ <span id="chatstate" style="color:var(--muted);font-weight:normal;font-size:0.78rem"></span></h2>
  <ol id="messages"><li id="empty">no messages yet</li></ol>
  <div id="chips"></div>
  <form id="send" autocomplete="off">
    <input id="text" placeholder="__BOTNAME__ move 100" aria-label="message">
    <button type="submit">send</button>
  </form>
</section>
</main>
<script>
var ME = "__USERNAME__", BOTNAME = "__BOTNAME__";
var canvas = document.getElementById("c"), ctx = canvas.getContext("2d");
if (!ctx.roundRect) {
  ctx.roundRect = function (x, y, w, h, r) {
    this.moveTo(x + r, y); this.arcTo(x + w, y, x + w, y + h, r);
    this.arcTo(x + w, y + h, x, y + h, r); this.arcTo(x, y + h, x, y, r);
    this.arcTo(x, y, x + w, y, r);
  };
}
var trail = [], pose = null;
function colors() {
  var s = getComputedStyle(document.documentElement);
  return { line: s.getPropertyValue("--line").trim(),
           muted: s.getPropertyValue("--muted").trim(),
           accent: s.getPropertyValue("--accent").trim() };
}
function bounds() {
  var xs = trail.map(p => p[0]).concat([0]), ys = trail.map(p => p[1]).concat([0]);
  var minX = Math.min(...xs) - 60, maxX = Math.max(...xs) + 60;
  var minY = Math.min(...ys) - 60, maxY = Math.max(...ys) + 60;
  var span = Math.max(maxX - minX, maxY - minY, 300);
  var cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  return { minX: cx - span/2, minY: cy - span/2, span: span };
}
function draw() {
  var c = colors(), b = bounds(), S = 560;
  function T(p) { return [(p[0]-b.minX)/b.span*S, S-(p[1]-b.minY)/b.span*S]; }
  ctx.clearRect(0,0,S,S);
  var step = Math.pow(10, Math.floor(Math.log10(b.span/4)));
  ctx.strokeStyle = c.line; ctx.lineWidth = 1;
  for (var gx = Math.ceil(b.minX/step)*step; gx < b.minX+b.span; gx += step) {
    var a = T([gx, b.minY]), z = T([gx, b.minY+b.span]);
    ctx.beginPath(); ctx.moveTo(a[0],a[1]); ctx.lineTo(z[0],z[1]); ctx.stroke();
  }
  for (var gy = Math.ceil(b.minY/step)*step; gy < b.minY+b.span; gy += step) {
    var a2 = T([b.minX, gy]), z2 = T([b.minX+b.span, gy]);
    ctx.beginPath(); ctx.moveTo(a2[0],a2[1]); ctx.lineTo(z2[0],z2[1]); ctx.stroke();
  }
  var o = T([0,0]);
  ctx.fillStyle = c.muted;
  ctx.beginPath(); ctx.arc(o[0],o[1],3,0,7); ctx.fill();
  ctx.font = "10px 'IBM Plex Mono',monospace"; ctx.fillText("0,0", o[0]+6, o[1]-5);
  if (trail.length > 1) {
    ctx.strokeStyle = c.accent; ctx.lineWidth = 2.5; ctx.lineCap = "round";
    ctx.beginPath();
    var p0 = T(trail[0]); ctx.moveTo(p0[0],p0[1]);
    for (var i = 1; i < trail.length; i++) { var p = T(trail[i]); ctx.lineTo(p[0],p[1]); }
    ctx.stroke();
  }
  if (pose) {
    var rp = T([pose.x, pose.y]), rad = pose.heading * Math.PI/180;
    drawLoliBot(rp[0], rp[1], rad, c);
    document.getElementById("pose").textContent =
      "x=" + pose.x.toFixed(1) + "  y=" + pose.y.toFixed(1) +
      "  heading=" + pose.heading.toFixed(1);
  } else {
    ctx.fillStyle = c.muted; ctx.font = "12px 'IBM Plex Mono',monospace";
    ctx.fillText("robot not started yet \\u2014 send it a command", 20, 30);
  }
}
// Stylised top-down LoliBot (openhardwareconf.org LoliBot): blue PCB
// chassis, two yellow-hub wheels, red 18650 battery, ESP32 board, green
// underglow. Nose points along the heading.
function drawLoliBot(x, y, rad, c) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(-rad);              // canvas y is flipped vs world y
  var glow = ctx.createRadialGradient(0, 0, 4, 0, 0, 30);
  glow.addColorStop(0, "rgba(62,207,142,0.45)");
  glow.addColorStop(1, "rgba(62,207,142,0)");
  ctx.fillStyle = glow;
  ctx.beginPath(); ctx.arc(0, 0, 30, 0, 7); ctx.fill();
  function wheel(wy) {
    ctx.fillStyle = "#1c1c1e";
    ctx.beginPath(); ctx.roundRect(-2, wy - 5, 22, 10, 5); ctx.fill();
    ctx.fillStyle = "#f0b429";
    ctx.beginPath(); ctx.roundRect(4, wy - 2, 10, 4, 2); ctx.fill();
  }
  wheel(-17); wheel(17);
  ctx.fillStyle = "#2456a6";
  ctx.strokeStyle = c.line; ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(-16, -13);
  ctx.quadraticCurveTo(-21, 0, -16, 13);
  ctx.lineTo(8, 13);
  ctx.quadraticCurveTo(22, 8, 25, 0);
  ctx.quadraticCurveTo(22, -8, 8, -13);
  ctx.closePath();
  ctx.fill(); ctx.stroke();
  ctx.fillStyle = "#c03535";
  ctx.beginPath(); ctx.roundRect(-2, -10, 6, 20, 3); ctx.fill();
  ctx.fillStyle = "#e8e2d4";
  ctx.fillRect(-2, -10, 6, 2.5);
  ctx.fillStyle = "#232323";
  ctx.beginPath(); ctx.roundRect(-13, -6, 8, 12, 1.5); ctx.fill();
  ctx.fillStyle = "#ff5348";
  ctx.beginPath(); ctx.arc(18, 0, 1.8, 0, 7); ctx.fill();
  ctx.fillStyle = "#cfcfcf";
  ctx.strokeStyle = "#8a8a8a";
  ctx.beginPath(); ctx.arc(-17, 0, 2.5, 0, 7); ctx.fill(); ctx.stroke();
  ctx.restore();
}

// ---- chat pane ---------------------------------------------------------
var messages = document.getElementById("messages");
function addMessage(m) {
  var empty = document.getElementById("empty");
  if (empty) empty.remove();
  var who = m.username || "?";
  var text = (m.message || "").replace(/ !!!!$/, "");
  var li = document.createElement("li");
  li.className = who.startsWith("@@") ? "bot" : (who === ME ? "me" : "human");
  var t = document.createElement("span"); t.className = "time";
  t.textContent = new Date(m.timestamp * 1000).toLocaleTimeString();
  var w = document.createElement("span"); w.className = "who"; w.textContent = who + ":";
  var x = document.createElement("span"); x.textContent = text;
  li.append(t, w, x);
  messages.append(li);
  while (messages.children.length > 300) messages.firstChild.remove();
  messages.scrollTop = messages.scrollHeight;
}
function send(text) {
  text = text.trim();
  if (!text) return;
  fetch("/send", { method: "POST", headers: {"Content-Type": "application/json"},
                   body: JSON.stringify({ message: text }) })
    .then(function (r) {
      if (!r.ok) document.getElementById("chatstate").textContent = "send failed: chat server not connected";
    });
}
document.getElementById("send").addEventListener("submit", function (e) {
  e.preventDefault();
  var box = document.getElementById("text");
  send(box.value); box.value = "";
});
var chips = document.getElementById("chips");
["move 100", "turn 90", "look", "reset", "telemetry"].forEach(function (cmd) {
  var b = document.createElement("button"); b.type = "button";
  b.textContent = cmd;
  b.addEventListener("click", function () { send(BOTNAME + " " + cmd); });
  chips.append(b);
});
function setStatus(s) {
  document.getElementById("world").textContent = s.world ? "live" : "waiting for world";
  document.getElementById("chatstate").textContent =
    s.chat ? "connected (" + s.chat + ")" : "waiting for chat server";
}
var events = new EventSource("/events");
events.onopen = function () {
  document.getElementById("status").textContent = "live \\u2014 drive the robot from the chat on the right";
};
events.onerror = function () {
  document.getElementById("status").textContent = "reconnecting\\u2026";
};
events.onmessage = function (message) {
  var data = JSON.parse(message.data);
  if (data.kind === "chat") { addMessage(data); return; }
  if (data.kind === "status") { setStatus(data); return; }
  if (data.kind === "clear") { trail = pose ? [[pose.x, pose.y]] : []; draw(); return; }
  pose = data;
  trail.push([pose.x, pose.y]);
  if (trail.length > 2000) trail.shift();
  draw();
};
document.getElementById("clear").addEventListener("click", function () {
  fetch("/clear");
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
draw();
</script></body></html>"""


class EventHub:
    # Fan-out of poses, chat messages and status to the page's SSE clients,
    # with replay of recent history for a newly connected page
    def __init__(self):
        self.clients = set()
        self.trail = []
        self.chat = []
        self.status = {"kind": "status", "world": False, "chat": None}
        self.lock = threading.Lock()

    def _broadcast(self, event):
        with self.lock:
            clients = list(self.clients)
        for client in clients:
            client.put(event)

    def publish_pose(self, pose):
        pose = dict(pose, kind="pose")
        with self.lock:
            self.trail.append(pose)
            del self.trail[:-_TRAIL_LIMIT]
        self._broadcast(pose)

    def publish_chat(self, message):
        message = dict(message, kind="chat")
        with self.lock:
            self.chat.append(message)
            del self.chat[:-_HISTORY_LIMIT]
        self._broadcast(message)

    def set_status(self, **changes):
        with self.lock:
            self.status.update(changes)
            status = dict(self.status)
        self._broadcast(status)

    def clear(self):
        with self.lock:
            del self.trail[:-1]     # keep the current pose as the new start
        self._broadcast({"kind": "clear"})

    def subscribe(self):
        client = queue.Queue()
        with self.lock:
            replay = [dict(self.status)] + list(self.trail) + list(self.chat)
            self.clients.add(client)
        return client, replay

    def unsubscribe(self, client):
        with self.lock:
            self.clients.discard(client)


HUB = EventHub()
WATCHER = None      # the Aiko Actor, set in main()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            client, replay = HUB.subscribe()
            try:
                for event in replay:
                    self._send(event)
                while True:
                    try:
                        self._send(client.get(timeout=20))
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                HUB.unsubscribe(client)
        elif self.path == "/clear":
            HUB.clear()
            self.send_response(204)
            self.end_headers()
        else:
            body = WATCHER.page().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        if self.path != "/send":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            message = json.loads(self.rfile.read(length)).get("message", "")
        except (ValueError, AttributeError):
            message = ""
        okay = bool(message.strip()) and WATCHER.send(message.strip())
        self.send_response(204 if okay else 503)
        self.end_headers()

    def _send(self, event):
        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
        self.wfile.flush()


class Watcher(aiko.Actor):
    # Watches the VirtualWorld's pose (ECConsumer) and the chat channel
    # (ChatServer discovery + channel topic subscription, like the REPL)
    def __init__(self, context, world_name=WORLD_NAME, channel=_CHANNEL,
                 username="anj", botname=_BOTNAME):
        context.call_init(self, "Actor", context)
        self.channel = channel
        self.username = username
        self.botname = botname
        self.ec_consumer = None
        self.chat_server = None
        self.chat_topic = None
        print(f"VIEWER: waiting for world \"{world_name}\" and chat server ...",
              flush=True)
        aiko.do_discovery(
            VirtualWorld,
            aiko.ServiceFilter("*", world_name, "*", "*", "*", "*"),
            self._world_add_handler, self._world_remove_handler)
        aiko.do_discovery(
            ChatServer, get_server_service_filter(),
            self._chat_add_handler, self._chat_remove_handler)

    def page(self):
        return (_PAGE.replace("__CHANNEL__", self.channel)
                     .replace("__USERNAME__", self.username)
                     .replace("__BOTNAME__", self.botname))

    # ---- world -------------------------------------------------------- #

    def _world_add_handler(self, service_details, service):
        print(f"VIEWER: world connected: {service_details[0]}", flush=True)
        if self.ec_consumer:
            self.ec_consumer.terminate()
        self.ec_consumer = aiko.ECConsumer(
            self, 0, {}, f"{service_details[0]}/control", ["pose"])
        self.ec_consumer.add_handler(self._pose_handler)
        HUB.set_status(world=True)

    def _world_remove_handler(self, service_details):
        print("VIEWER: world disconnected", flush=True)
        if self.ec_consumer:
            self.ec_consumer.terminate()
            self.ec_consumer = None
        HUB.set_status(world=False)

    def _pose_handler(self, client_id, command, item_name, item_value):
        if item_name != "pose":
            return
        try:
            if isinstance(item_value, (list, tuple)):   # older producers
                values = [str(value) for value in item_value]
            else:
                values = str(item_value).strip("()").split()
            x, y, heading = (float(value) for value in values)
        except (ValueError, TypeError):
            return
        HUB.publish_pose({"x": x, "y": y, "heading": heading})

    # ---- chat --------------------------------------------------------- #

    def _chat_add_handler(self, service_details, service):
        print(f"VIEWER: chat server connected: {service_details[0]}",
              flush=True)
        self.chat_server = service
        if self.chat_topic:
            self.remove_message_handler(self._chat_handler, self.chat_topic)
        self.chat_topic = f"{service_details[0]}/{self.channel}"
        self.add_message_handler(self._chat_handler, self.chat_topic)
        HUB.set_status(chat=service_details[0])

    def _chat_remove_handler(self, service_details):
        print("VIEWER: chat server disconnected", flush=True)
        self.chat_server = None
        HUB.set_status(chat=None)

    def _chat_handler(self, _aiko, topic, payload_in):
        fields = _decode_message(payload_in)
        if not fields:
            return
        try:
            timestamp = float(fields.get("timestamp", time.time()))
        except (TypeError, ValueError):
            timestamp = time.time()
        HUB.publish_chat({
            "username": str(fields.get("username", "") or ""),
            "message": str(fields.get("message", "")),
            "timestamp": timestamp})

    def send(self, message):
        # Called from the HTTP thread, as the REPL calls from its own thread
        if not self.chat_server:
            return False
        self.chat_server.send_message(self.username, [self.channel], message)
        return True


@click.command()
@click.option("--name", "world_name", type=str, default=WORLD_NAME)
@click.option("--channel", type=str, default=_CHANNEL)
@click.option("--username", type=str,
    default=os.environ.get("USER", "anj"), show_default=True)
@click.option("--botname", type=str, default=_BOTNAME,
    help="robot mentioned by the quick-command buttons")
@click.option("--port", type=int, default=8123)
def main(world_name, channel, username, botname, port):
    global WATCHER
    init_args = aiko.actor_args("anj_world_viewer_web", tags=["ec=true"])
    init_args.update({"world_name": world_name, "channel": channel,
                      "username": username, "botname": botname})
    WATCHER = aiko.compose_instance(Watcher, init_args)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"VIEWER: open http://localhost:{port}", flush=True)
    aiko.process.run()


if __name__ == "__main__":
    main()
