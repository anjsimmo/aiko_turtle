#!/usr/bin/env python3
#
# Browser version of the world viewer: the same live pose feed as
# world_viewer.py, drawn on a canvas like the session report's replay.
# Serves http://localhost:8123 with an SSE stream of live poses.
# (A claude.ai Artifact page can't connect to MQTT -- its sandbox blocks
# external connections -- hence this small local web app.)
#
# Usage
# ~~~~~
#   source env.sh
#   ./world_viewer_web.py [--name anj_turtle_world] [--port 8123]
#   then open http://localhost:8123

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import queue
import threading

import click

import aiko_services as aiko
from virtual_world import VirtualWorld, WORLD_NAME

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>TurtleBot Live</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root { --bg:#f7f6f2; --surface:#ffffff; --ink:#1c2420; --muted:#5c6b62;
        --line:#d8ded9; --accent:#0b7a4b; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#101512; --surface:#182019; --ink:#e6ece7; --muted:#93a398;
          --line:#2a352c; --accent:#3ecf8e; }
}
body { background:var(--bg); color:var(--ink); margin:0;
       font-family:"IBM Plex Mono",monospace; display:flex; flex-direction:column;
       align-items:center; min-height:100vh; }
h1 { font-family:"Sora",sans-serif; font-size:1.3rem; margin:24px 0 4px; }
#status { color:var(--muted); font-size:0.78rem; margin-bottom:16px; }
#wrap { background:var(--surface); border:1px solid var(--line); border-radius:6px;
        padding:12px; }
canvas { display:block; width:min(90vw,560px); height:auto; }
#bar { display:flex; gap:16px; align-items:center; margin-top:12px; }
#pose { color:var(--accent); font-size:0.85rem; }
button { font-family:"IBM Plex Mono",monospace; font-size:0.78rem;
         background:var(--accent); color:var(--bg); border:none;
         border-radius:4px; padding:6px 12px; cursor:pointer; }
button:hover { opacity:0.88; }
button:focus-visible { outline:2px solid var(--muted); outline-offset:2px; }
</style></head><body>
<h1>TurtleBot Live</h1>
<div id="status">connecting…</div>
<div id="wrap"><canvas id="c" width="560" height="560"></canvas></div>
<div id="bar">
  <button id="clear">clear trail</button>
  <div id="pose"></div>
</div>
<script>
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
  }
}
// Stylised top-down LoliBot (openhardwareconf.org LoliBot): blue PCB
// chassis, two yellow-hub wheels, red 18650 battery, ESP32 board, green
// underglow. Nose points along the heading.
function drawLoliBot(x, y, rad, c) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(-rad);              // canvas y is flipped vs world y
  // green underglow (the real bot has an LED glow beneath the board)
  var glow = ctx.createRadialGradient(0, 0, 4, 0, 0, 30);
  glow.addColorStop(0, "rgba(62,207,142,0.45)");
  glow.addColorStop(1, "rgba(62,207,142,0)");
  ctx.fillStyle = glow;
  ctx.beginPath(); ctx.arc(0, 0, 30, 0, 7); ctx.fill();
  // wheels: black tyres with yellow hubs, either side, mid-front
  function wheel(wy) {
    ctx.fillStyle = "#1c1c1e";
    ctx.beginPath(); ctx.roundRect(-2, wy - 5, 22, 10, 5); ctx.fill();
    ctx.fillStyle = "#f0b429";
    ctx.beginPath(); ctx.roundRect(4, wy - 2, 10, 4, 2); ctx.fill();
  }
  wheel(-17); wheel(17);
  // PCB chassis: rounded board, tapered nose at the front (+x)
  ctx.fillStyle = "#2456a6";
  ctx.strokeStyle = c.line; ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(-16, -13);
  ctx.quadraticCurveTo(-21, 0, -16, 13);       // rounded tail
  ctx.lineTo(8, 13);
  ctx.quadraticCurveTo(22, 8, 25, 0);          // tapered nose
  ctx.quadraticCurveTo(22, -8, 8, -13);
  ctx.closePath();
  ctx.fill(); ctx.stroke();
  // red 18650 battery across the middle (perpendicular to travel)
  ctx.fillStyle = "#c03535";
  ctx.beginPath(); ctx.roundRect(-2, -10, 6, 20, 3); ctx.fill();
  ctx.fillStyle = "#e8e2d4";
  ctx.fillRect(-2, -10, 6, 2.5);               // battery cap
  // ESP32 board behind the battery
  ctx.fillStyle = "#232323";
  ctx.beginPath(); ctx.roundRect(-13, -6, 8, 12, 1.5); ctx.fill();
  // status LED at the nose
  ctx.fillStyle = "#ff5348";
  ctx.beginPath(); ctx.arc(18, 0, 1.8, 0, 7); ctx.fill();
  // rear castor
  ctx.fillStyle = "#cfcfcf";
  ctx.strokeStyle = "#8a8a8a";
  ctx.beginPath(); ctx.arc(-17, 0, 2.5, 0, 7); ctx.fill(); ctx.stroke();
  ctx.restore();
}
var events = new EventSource("/events");
events.onopen = function () {
  document.getElementById("status").textContent = "live \\u2014 drive the robot from chat";
};
events.onerror = function () {
  document.getElementById("status").textContent = "reconnecting\\u2026";
};
events.onmessage = function (message) {
  var data = JSON.parse(message.data);
  if (data.clear) { trail = pose ? [[pose.x, pose.y]] : []; draw(); return; }
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


class PoseHub:
    def __init__(self):
        self.clients = set()
        self.trail = []
        self.lock = threading.Lock()

    def publish(self, pose):
        with self.lock:
            self.trail.append(pose)
            del self.trail[:-2000]
            clients = list(self.clients)
        for client in clients:
            client.put(pose)

    def clear(self):
        with self.lock:
            del self.trail[:-1]     # keep the current pose as the new start
            clients = list(self.clients)
        for client in clients:
            client.put({"clear": True})

    def subscribe(self):
        client = queue.Queue()
        with self.lock:
            replay = list(self.trail)
            self.clients.add(client)
        return client, replay

    def unsubscribe(self, client):
        with self.lock:
            self.clients.discard(client)


HUB = PoseHub()


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
                for pose in replay:
                    self._send(pose)
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
            body = _PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def _send(self, pose):
        self.wfile.write(f"data: {json.dumps(pose)}\n\n".encode())
        self.wfile.flush()


class PoseWatcher(aiko.Actor):
    def __init__(self, context, world_name=WORLD_NAME):
        context.call_init(self, "Actor", context)
        self.ec_consumer = None
        print(f"VIEWER: waiting for world \"{world_name}\" ...", flush=True)
        aiko.do_discovery(
            VirtualWorld,
            aiko.ServiceFilter("*", world_name, "*", "*", "*", "*"),
            self._add_handler, self._remove_handler)

    def _add_handler(self, service_details, service):
        print(f"VIEWER: world connected: {service_details[0]}", flush=True)
        if self.ec_consumer:
            self.ec_consumer.terminate()
        self.ec_consumer = aiko.ECConsumer(
            self, 0, {}, f"{service_details[0]}/control", "(pose)")
        self.ec_consumer.add_handler(self._pose_handler)

    def _remove_handler(self, service_details):
        print("VIEWER: world disconnected", flush=True)
        if self.ec_consumer:
            self.ec_consumer.terminate()
            self.ec_consumer = None

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
        HUB.publish({"x": x, "y": y, "heading": heading})


@click.command()
@click.option("--name", "world_name", type=str, default=WORLD_NAME)
@click.option("--port", type=int, default=8123)
def main(world_name, port):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"VIEWER: open http://localhost:{port}", flush=True)

    init_args = aiko.actor_args("anj_world_viewer_web", tags=["ec=true"])
    init_args["world_name"] = world_name
    aiko.compose_instance(PoseWatcher, init_args)
    aiko.process.run()


if __name__ == "__main__":
    main()
