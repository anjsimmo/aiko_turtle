#!/usr/bin/env python3
#
# Drive a robot over the REST API with nothing but Python's standard
# library.  No Aiko, no packages: this is the "I just want to see it move"
# path.  For the full power (discovery, your own robot, your own agent)
# see aiko_drive.py and agent_bot.py next to this file.
#
#   python3 rest_drive.py my_turtle                         # local server
#   python3 rest_drive.py my_turtle https://turtle.aiko.hashtag.ai
#   TURTLE_API_TOKEN=... python3 rest_drive.py my_turtle    # if the instance needs a token

import json
import os
import sys
import urllib.request

BASE = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8123"
NAME = sys.argv[1] if len(sys.argv) > 1 else "rest_turtle"
TOKEN = os.environ.get("TURTLE_API_TOKEN", "")
ME = "@" + os.environ.get("USER", "someone")


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})})
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


print("robots in the world:", [r["name"] for r in call("GET", "/api/robots")])
print("created:", call("POST", "/api/robots",
                       {"name": NAME, "kind": "turtle", "owner": ME}))

for _ in range(4):                                   # a square
    call("POST", f"/api/robots/{NAME}/move", {"distance": 100, "username": ME})
    pose = call("POST", f"/api/robots/{NAME}/turn", {"angle": 90, "username": ME})
    print(f"  at x={pose['x']:g} y={pose['y']:g} heading={pose['heading']:g}")

call("POST", "/api/chat", {"username": ME, "message": f"{NAME} drew a square over REST"})
print("history:", [e["command"] for e in call("GET", f"/api/robots/{NAME}/history")])
print(f"watch it at {BASE}/world")
