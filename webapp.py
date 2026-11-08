# The web application (FastAPI): the robots-and-chat page, a REST API for
# creating and driving robots, and one SSE stream of poses and chat.
#
# No Aiko here: create_app(backend) takes any object with the Backend
# methods below.  web.py provides the Aiko-connected backend; the tests a
# fake one.  Interactive API docs are served at /docs.

import json
import queue
import threading
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

import config
from core import valid_robot_name
from world_model import KINDS

_HISTORY_LIMIT = 300
_TRAIL_LIMIT = 500      # per robot, replayed to a newly opened page


class BackendError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class Backend:
    """What create_app() needs.  Every method may raise BackendError"""
    hub = None                                  # an EventHub

    def status(self): ...                       # {"world": bool, "chat": str|None}
    def list_robots(self): ...                  # [robot, ...]
    def create_robot(self, name, kind, owner): ...
    def destroy_robot(self, name): ...
    def move(self, name, distance, username): ...
    def turn(self, name, angle, username): ...
    def reset(self, name, username): ...
    def pose(self, name): ...
    def history(self, name, limit): ...         # [event, ...]
    def send_chat(self, username, message): ...


class EventHub:
    """Fan-out of robot poses, chat messages and status to the page's SSE
    clients, with replay of recent history for a newly connected page"""

    def __init__(self):
        self.clients = set()
        self.trails = {}            # robot name -> [pose event, ...]
        self.chat = []
        self.status = {"kind": "status", "world": False, "chat": None}
        self.lock = threading.Lock()

    def _broadcast(self, event):
        with self.lock:
            clients = list(self.clients)
        for client in clients:
            client.put(event)

    def publish_robot(self, robot):
        event = {"kind": "robot", "name": robot["name"], "x": robot["x"],
                 "y": robot["y"], "heading": robot["heading"],
                 "type": robot.get("kind", "turtle")}
        with self.lock:
            trail = self.trails.setdefault(robot["name"], [])
            trail.append(event)
            del trail[:-_TRAIL_LIMIT]
        self._broadcast(event)

    def remove_robot(self, name):
        with self.lock:
            self.trails.pop(name, None)
        self._broadcast({"kind": "robot_removed", "name": name})

    def clear_robots(self):
        with self.lock:
            names = list(self.trails)
            self.trails.clear()
        for name in names:
            self._broadcast({"kind": "robot_removed", "name": name})

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

    def subscribe(self):
        client = queue.Queue()
        with self.lock:
            replay = [dict(self.status)]
            for trail in self.trails.values():
                replay.extend(trail)
            replay.extend(self.chat)
            self.clients.add(client)
        return client, replay

    def unsubscribe(self, client):
        with self.lock:
            self.clients.discard(client)


# -- request / response models -------------------------------------------------

Username = Field(default="anonymous", min_length=1, max_length=64,
                 description="any name you like; no login (community sandbox)")


class RobotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64,
        description="letters, digits, '_' and '-'; also the chat mention @@name")
    kind: str = Field(default="turtle", description=f"one of {KINDS}")
    owner: str = Username


class MoveRequest(BaseModel):
    distance: float = Field(description="units forward (negative = backwards)")
    username: str = Username


class TurnRequest(BaseModel):
    angle: float = Field(description="degrees counter-clockwise")
    username: str = Username


class ResetRequest(BaseModel):
    username: str = Username


class ChatMessage(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    username: str = Username


# -- the app ---------------------------------------------------------------------

def create_app(backend, channel=config.CHANNEL, username=config.WEB_USERNAME,
               agent=config.AGENT_BOTNAME):
    app = FastAPI(
        title="aiko_turtle",
        description=(
            "Virtual robots in a shared world, driven over REST here or over "
            "Aiko Chat (`@@name move 100` in the channel).  Create a robot "
            "with any name; a longer, unusual name is less likely to clash "
            "with someone else's.  Live poses and chat: GET /events (SSE)."),
        version="1.0")
    app.state.backend = backend

    def call(function, *arguments):
        try:
            return function(*arguments)
        except BackendError as error:
            raise HTTPException(error.status, error.detail)

    def check_name(name):
        if not valid_robot_name(name):
            raise HTTPException(422,
                "robot name: letters, digits, '_' and '-' only (max 64)")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def page():
        return (_PAGE.replace("__CHANNEL__", channel)
                     .replace("__USERNAME__", username)
                     .replace("__AGENT__", agent))

    @app.get("/events", include_in_schema=False)
    def events(request: Request):
        hub = backend.hub
        client, replay = hub.subscribe()

        def stream():
            try:
                for event in replay:
                    yield f"data: {json.dumps(event)}\n\n"
                while True:
                    try:
                        event = client.get(timeout=15)
                        yield f"data: {json.dumps(event)}\n\n"
                    except queue.Empty:
                        yield ": keepalive\n\n"
            finally:
                hub.unsubscribe(client)

        return StreamingResponse(stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/status", tags=["world"])
    def status():
        return call(backend.status)

    @app.get("/api/robots", tags=["robots"])
    def list_robots():
        return call(backend.list_robots)

    @app.post("/api/robots", tags=["robots"], status_code=201)
    def create_robot(robot: RobotCreate):
        check_name(robot.name)
        if robot.kind not in KINDS:
            raise HTTPException(422, f"kind must be one of {KINDS}")
        return call(backend.create_robot, robot.name, robot.kind, robot.owner)

    @app.get("/api/robots/{name}", tags=["robots"])
    def get_robot(name: str):
        check_name(name)
        return call(backend.pose, name)

    @app.delete("/api/robots/{name}", tags=["robots"])
    def destroy_robot(name: str):
        check_name(name)
        return call(backend.destroy_robot, name)

    @app.post("/api/robots/{name}/move", tags=["drive"])
    def move(name: str, body: MoveRequest):
        check_name(name)
        return call(backend.move, name, body.distance, body.username)

    @app.post("/api/robots/{name}/turn", tags=["drive"])
    def turn(name: str, body: TurnRequest):
        check_name(name)
        return call(backend.turn, name, body.angle, body.username)

    @app.post("/api/robots/{name}/reset", tags=["drive"])
    def reset(name: str, body: Optional[ResetRequest] = None):
        check_name(name)
        username = body.username if body else "anonymous"
        return call(backend.reset, name, username)

    @app.get("/api/robots/{name}/history", tags=["robots"])
    def history(name: str, limit: int = 100):
        check_name(name)
        return call(backend.history, name, max(1, min(limit, 1000)))

    @app.post("/api/chat", tags=["chat"], status_code=202)
    def send_chat(body: ChatMessage):
        call(backend.send_chat, body.username, body.message)
        return {"sent": True}

    @app.get("/api/chat", tags=["chat"])
    def chat_history():
        with backend.hub.lock:
            return list(backend.hub.chat)

    return app


_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Turtle World</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root { --bg:#f7f6f2; --surface:#ffffff; --ink:#1c2420; --muted:#5c6b62;
        --line:#d8ded9; --accent:#0b7a4b; --bot:#2456a6; --me:#eef7f1; --danger:#b23a3a; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#101512; --surface:#182019; --ink:#e6ece7; --muted:#93a398;
          --line:#2a352c; --accent:#3ecf8e; --bot:#8fb4ff; --me:#1f2d24; --danger:#ff7b7b; }
}
* { box-sizing:border-box; }
body { background:var(--bg); color:var(--ink); margin:0; padding:0 16px 24px;
       font-family:"IBM Plex Mono",monospace; display:flex; flex-direction:column;
       align-items:center; min-height:100vh; }
h1 { font-family:"Sora",sans-serif; font-size:1.3rem; margin:24px 0 4px; }
h1 small { font-family:"IBM Plex Mono",monospace; font-weight:normal; font-size:0.75rem; color:var(--muted); }
#status { color:var(--muted); font-size:0.78rem; margin-bottom:16px; text-align:center; }
#grid { display:grid; grid-template-columns:minmax(0,1.2fr) minmax(0,1fr); gap:16px;
        width:min(100%,1240px); align-items:start; }
@media (max-width: 900px) { #grid { grid-template-columns:1fr; } }
.panel { background:var(--surface); border:1px solid var(--line); border-radius:6px;
         padding:12px; min-width:0; }
.panel h2 { font-family:"Sora",sans-serif; font-size:0.95rem; margin:0 0 10px; }
.panel h2 span { color:var(--muted); font-weight:normal; font-size:0.78rem; font-family:"IBM Plex Mono",monospace; }
canvas { display:block; width:100%; height:auto; aspect-ratio:1/1; }
#robots { list-style:none; margin:10px 0 0; padding:0; display:flex; flex-wrap:wrap; gap:6px; font-size:0.78rem; }
#robots li { display:flex; align-items:center; gap:6px; border:1px solid var(--line); border-radius:4px; padding:4px 8px; cursor:pointer; }
#robots li.selected { border-color:var(--accent); background:var(--me); }
#robots .dot { width:10px; height:10px; border-radius:50%; display:inline-block; }
#robots .x { color:var(--danger); background:none; border:none; padding:0 2px; font-size:0.9rem; }
#create { display:flex; gap:6px; margin-top:10px; flex-wrap:wrap; }
#create input, #create select { font-family:inherit; font-size:0.8rem; padding:5px 8px;
   border:1px solid var(--line); border-radius:4px; background:var(--bg); color:var(--ink); }
#pose { color:var(--accent); font-size:0.8rem; margin-top:8px; min-height:1.2em; }
button { font-family:"IBM Plex Mono",monospace; font-size:0.78rem;
         background:var(--accent); color:var(--bg); border:none;
         border-radius:4px; padding:6px 12px; cursor:pointer; }
button:hover { opacity:0.88; }
button:focus-visible, input:focus-visible, select:focus-visible { outline:2px solid var(--muted); outline-offset:2px; }
#messages { list-style:none; margin:0; padding:0; height:min(55vh,480px); overflow-y:auto;
            border:1px solid var(--line); border-radius:4px; font-size:0.82rem; }
#messages li { display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:0 8px;
               padding:6px 10px; border-bottom:1px solid var(--line); word-break:break-word; }
#messages li:last-child { border-bottom:none; }
#messages .who { color:var(--muted); }
#messages .bot .who { color:var(--bot); }
#messages .me { background:var(--me); }
#messages .me .who { color:var(--accent); }
#messages .time { color:var(--muted); font-size:0.7rem; white-space:nowrap; }
#empty { color:var(--muted); font-size:0.8rem; padding:10px; }
#chips { display:flex; gap:6px; flex-wrap:wrap; margin:10px 0; }
#chips button { background:var(--surface); color:var(--ink); border:1px solid var(--line); }
#chips button:hover { border-color:var(--accent); opacity:1; }
#send { display:flex; gap:8px; }
#text, #who { font-family:"IBM Plex Mono",monospace; font-size:0.85rem;
        padding:8px 10px; border:1px solid var(--line); border-radius:4px;
        background:var(--bg); color:var(--ink); }
#text { flex:1; min-width:0; } #who { width:9em; }
a { color:var(--accent); }
</style></head><body>
<h1>Turtle World <small>&nbsp;REST API: <a href="/docs">/docs</a></small></h1>
<div id="status">connecting…</div>
<main id="grid">
<section class="panel">
  <h2>World <span id="world"></span></h2>
  <canvas id="c" width="600" height="600"></canvas>
  <ul id="robots"></ul>
  <form id="create" autocomplete="off">
    <input id="newname" placeholder="new robot name" aria-label="new robot name" pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,63}" required>
    <select id="newkind" aria-label="kind"><option value="turtle">turtle</option><option value="arrow">arrow</option></select>
    <button type="submit">create robot</button>
  </form>
  <div id="pose"></div>
</section>
<section class="panel">
  <h2>#__CHANNEL__ <span id="chatstate"></span></h2>
  <ol id="messages"><li id="empty">no messages yet</li></ol>
  <div id="chips"></div>
  <form id="send" autocomplete="off">
    <input id="who" aria-label="your name" title="your name (anything you like)">
    <input id="text" placeholder="@@robot move 100 — or ask __AGENT__" aria-label="message">
    <button type="submit">send</button>
  </form>
</section>
</main>
<script>
var AGENT = "__AGENT__", S = 600;
var who = document.getElementById("who");
try { who.value = localStorage.getItem("turtle.username") || "__USERNAME__"; } catch (e) { who.value = "__USERNAME__"; }
who.addEventListener("change", function () { try { localStorage.setItem("turtle.username", who.value); } catch (e) {} });
function me() { return who.value.trim() || "anonymous"; }

var canvas = document.getElementById("c"), ctx = canvas.getContext("2d");
if (!ctx.roundRect) {
  ctx.roundRect = function (x, y, w, h, r) {
    this.moveTo(x + r, y); this.arcTo(x + w, y, x + w, y + h, r);
    this.arcTo(x + w, y + h, x, y + h, r); this.arcTo(x, y + h, x, y, r);
    this.arcTo(x, y, x + w, y, r);
  };
}
var robots = {}, selected = null;
var PALETTE = ["#0b7a4b","#2456a6","#b5651d","#7b3fa0","#b23a3a","#1f8a8a","#8a7a1f","#c2185b"];
function colorOf(name) {
  var h = 0; for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
function colors() {
  var s = getComputedStyle(document.documentElement);
  return { line: s.getPropertyValue("--line").trim(), muted: s.getPropertyValue("--muted").trim() };
}
function bounds() {
  var xs = [0], ys = [0];
  Object.values(robots).forEach(function (r) { r.trail.forEach(function (p) { xs.push(p[0]); ys.push(p[1]); }); });
  var minX = Math.min.apply(null, xs) - 60, maxX = Math.max.apply(null, xs) + 60;
  var minY = Math.min.apply(null, ys) - 60, maxY = Math.max.apply(null, ys) + 60;
  var span = Math.max(maxX - minX, maxY - minY, 300);
  return { minX: (minX + maxX) / 2 - span / 2, minY: (minY + maxY) / 2 - span / 2, span: span };
}
function draw() {
  var c = colors(), b = bounds();
  function T(p) { return [(p[0] - b.minX) / b.span * S, S - (p[1] - b.minY) / b.span * S]; }
  ctx.clearRect(0, 0, S, S);
  var step = Math.pow(10, Math.floor(Math.log10(b.span / 4)));
  ctx.strokeStyle = c.line; ctx.lineWidth = 1;
  for (var gx = Math.ceil(b.minX / step) * step; gx < b.minX + b.span; gx += step) {
    var a = T([gx, b.minY]), z = T([gx, b.minY + b.span]);
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(z[0], z[1]); ctx.stroke();
  }
  for (var gy = Math.ceil(b.minY / step) * step; gy < b.minY + b.span; gy += step) {
    var a2 = T([b.minX, gy]), z2 = T([b.minX + b.span, gy]);
    ctx.beginPath(); ctx.moveTo(a2[0], a2[1]); ctx.lineTo(z2[0], z2[1]); ctx.stroke();
  }
  var o = T([0, 0]);
  ctx.fillStyle = c.muted; ctx.beginPath(); ctx.arc(o[0], o[1], 3, 0, 7); ctx.fill();
  ctx.font = "10px 'IBM Plex Mono',monospace"; ctx.fillText("0,0", o[0] + 6, o[1] - 5);
  var names = Object.keys(robots);
  if (!names.length) {
    ctx.fillStyle = c.muted; ctx.font = "12px 'IBM Plex Mono',monospace";
    ctx.fillText("no robots yet \\u2014 create one below", 20, 30);
  }
  names.forEach(function (name) {
    var r = robots[name], col = colorOf(name);
    if (r.trail.length > 1) {
      ctx.strokeStyle = col; ctx.lineWidth = name === selected ? 3 : 2; ctx.lineCap = "round";
      ctx.globalAlpha = name === selected || !selected ? 1 : 0.5;
      ctx.beginPath(); var p0 = T(r.trail[0]); ctx.moveTo(p0[0], p0[1]);
      for (var i = 1; i < r.trail.length; i++) { var p = T(r.trail[i]); ctx.lineTo(p[0], p[1]); }
      ctx.stroke(); ctx.globalAlpha = 1;
    }
    var rp = T([r.x, r.y]), rad = r.heading * Math.PI / 180;
    if (r.type === "arrow") drawArrow(rp[0], rp[1], rad, col); else drawLoliBot(rp[0], rp[1], rad, c, col);
    ctx.fillStyle = col; ctx.font = "11px 'IBM Plex Mono',monospace";
    ctx.fillText(name, rp[0] + 22, rp[1] + 24);
  });
  var sel = robots[selected];
  document.getElementById("pose").textContent = sel ?
    selected + ":  x=" + sel.x.toFixed(1) + "  y=" + sel.y.toFixed(1) + "  heading=" + sel.heading.toFixed(1) : "";
}
function drawArrow(x, y, rad, col) {
  ctx.save(); ctx.translate(x, y); ctx.rotate(-rad);
  ctx.fillStyle = col; ctx.beginPath();
  ctx.moveTo(18, 0); ctx.lineTo(-12, 11); ctx.lineTo(-6, 0); ctx.lineTo(-12, -11); ctx.closePath(); ctx.fill();
  ctx.restore();
}
// Stylised top-down LoliBot (openhardwareconf.org): PCB chassis in the
// robot's colour, yellow-hub wheels, red 18650 battery, ESP32, underglow
function drawLoliBot(x, y, rad, c, col) {
  ctx.save(); ctx.translate(x, y); ctx.rotate(-rad);
  var glow = ctx.createRadialGradient(0, 0, 4, 0, 0, 30);
  glow.addColorStop(0, "rgba(62,207,142,0.45)"); glow.addColorStop(1, "rgba(62,207,142,0)");
  ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(0, 0, 30, 0, 7); ctx.fill();
  function wheel(wy) {
    ctx.fillStyle = "#1c1c1e"; ctx.beginPath(); ctx.roundRect(-2, wy - 5, 22, 10, 5); ctx.fill();
    ctx.fillStyle = "#f0b429"; ctx.beginPath(); ctx.roundRect(4, wy - 2, 10, 4, 2); ctx.fill();
  }
  wheel(-17); wheel(17);
  ctx.fillStyle = col; ctx.strokeStyle = c.line; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(-16, -13); ctx.quadraticCurveTo(-21, 0, -16, 13); ctx.lineTo(8, 13);
  ctx.quadraticCurveTo(22, 8, 25, 0); ctx.quadraticCurveTo(22, -8, 8, -13); ctx.closePath(); ctx.fill(); ctx.stroke();
  ctx.fillStyle = "#c03535"; ctx.beginPath(); ctx.roundRect(-2, -10, 6, 20, 3); ctx.fill();
  ctx.fillStyle = "#e8e2d4"; ctx.fillRect(-2, -10, 6, 2.5);
  ctx.fillStyle = "#232323"; ctx.beginPath(); ctx.roundRect(-13, -6, 8, 12, 1.5); ctx.fill();
  ctx.fillStyle = "#ff5348"; ctx.beginPath(); ctx.arc(18, 0, 1.8, 0, 7); ctx.fill();
  ctx.fillStyle = "#cfcfcf"; ctx.strokeStyle = "#8a8a8a"; ctx.beginPath(); ctx.arc(-17, 0, 2.5, 0, 7); ctx.fill(); ctx.stroke();
  ctx.restore();
}

// ---- robots list ----------------------------------------------------------
var list = document.getElementById("robots");
function renderRobots() {
  list.innerHTML = "";
  Object.keys(robots).sort().forEach(function (name) {
    var li = document.createElement("li");
    li.className = name === selected ? "selected" : "";
    var dot = document.createElement("span"); dot.className = "dot"; dot.style.background = colorOf(name);
    var label = document.createElement("span"); label.textContent = name;
    var x = document.createElement("button"); x.className = "x"; x.type = "button"; x.title = "remove " + name; x.textContent = "\\u00d7";
    x.addEventListener("click", function (e) {
      e.stopPropagation();
      if (confirm("Remove robot " + name + "?")) fetch("/api/robots/" + name, { method: "DELETE" });
    });
    li.append(dot, label, x);
    li.addEventListener("click", function () { selected = name; renderRobots(); draw(); });
    list.append(li);
  });
}
document.getElementById("create").addEventListener("submit", function (e) {
  e.preventDefault();
  var name = document.getElementById("newname").value.trim();
  fetch("/api/robots", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name, kind: document.getElementById("newkind").value, owner: me() }) })
    .then(function (r) { return r.json().then(function (j) { return [r.ok, j]; }); })
    .then(function (res) {
      if (!res[0]) { document.getElementById("pose").textContent = "create failed: " + (res[1].detail || JSON.stringify(res[1])); return; }
      selected = name; document.getElementById("newname").value = ""; renderRobots(); draw();
    });
});

// ---- chat -------------------------------------------------------------------
var messages = document.getElementById("messages");
function addMessage(m) {
  var empty = document.getElementById("empty"); if (empty) empty.remove();
  var u = m.username || "?", text = (m.message || "").replace(/ !!!!$/, "");
  var li = document.createElement("li");
  li.className = u.startsWith("@@") ? "bot" : (u === me() ? "me" : "human");
  var t = document.createElement("span"); t.className = "time"; t.textContent = new Date(m.timestamp * 1000).toLocaleTimeString();
  var w = document.createElement("span"); w.className = "who"; w.textContent = u + ":";
  var x = document.createElement("span"); x.textContent = text;
  li.append(w, x, t); messages.append(li);
  while (messages.children.length > 300) messages.firstChild.remove();
  messages.scrollTop = messages.scrollHeight;
}
function send(text) {
  text = text.trim(); if (!text) return;
  fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: text, username: me() }) })
    .then(function (r) { if (!r.ok) document.getElementById("chatstate").textContent = "send failed: chat server not connected"; });
}
document.getElementById("send").addEventListener("submit", function (e) {
  e.preventDefault(); var box = document.getElementById("text"); send(box.value); box.value = "";
});
var chips = document.getElementById("chips");
["move 100", "turn 90", "look", "reset", "telemetry"].forEach(function (cmd) {
  var b = document.createElement("button"); b.type = "button"; b.textContent = cmd;
  b.addEventListener("click", function () {
    if (!selected) { document.getElementById("pose").textContent = "select or create a robot first"; return; }
    send("@@" + selected + " " + cmd);
  });
  chips.append(b);
});
var ask = document.createElement("button"); ask.type = "button"; ask.textContent = AGENT + " draw a square";
ask.addEventListener("click", function () { send(AGENT + " draw a square" + (selected ? " with " + selected : "")); });
chips.append(ask);

function setStatus(s) {
  document.getElementById("world").textContent = s.world ? "live" : "waiting for world";
  document.getElementById("chatstate").textContent = s.chat ? "connected" : "waiting for chat server";
}
var events = new EventSource("/events");
events.onopen = function () { document.getElementById("status").textContent = "live \\u2014 create a robot, then drive it from the chat or the REST API"; };
events.onerror = function () { document.getElementById("status").textContent = "reconnecting\\u2026"; };
events.onmessage = function (message) {
  var d = JSON.parse(message.data);
  if (d.kind === "chat") { addMessage(d); return; }
  if (d.kind === "status") { setStatus(d); return; }
  if (d.kind === "robot_removed") { delete robots[d.name]; if (selected === d.name) selected = null; renderRobots(); draw(); return; }
  if (d.kind !== "robot") return;
  var r = robots[d.name];
  if (!r) { r = robots[d.name] = { trail: [] }; if (!selected) selected = d.name; renderRobots(); }
  r.x = d.x; r.y = d.y; r.heading = d.heading; r.type = d.type;
  var last = r.trail[r.trail.length - 1];
  if (!last || last[0] !== d.x || last[1] !== d.y) r.trail.push([d.x, d.y]);
  if (r.trail.length > 2000) r.trail.shift();
  draw();
};
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
draw();
</script></body></html>"""
