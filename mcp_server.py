#!/usr/bin/env python3
#
# An MCP server for the robots, so an LLM agent (Claude Code, Claude
# Desktop, anything that speaks the Model Context Protocol) can see and
# drive them as tools.  It is a thin wrapper over the REST API, so it
# needs no Aiko on the agent's machine: just "pip install mcp".
#
#   python3 mcp_server.py                     # stdio, for an MCP client
#   TURTLE_URL=https://turtle.aiko.hashtag.ai TURTLE_API_TOKEN=... python3 mcp_server.py
#
# Claude Code:   claude mcp add turtle -- python3 /path/to/mcp_server.py
# Claude Desktop / others: see /guide on the web server.
#
# An agent that has Python and Aiko installed gets more by using Aiko
# directly (examples/agent_bot.py): discovery, its own robots, every
# channel.  This is the no-install path.

import json
import os
import urllib.error
import urllib.request

try:                                            # mcp 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:                             # mcp 1.x
    from mcp.server.fastmcp import FastMCP

BASE = os.environ.get("TURTLE_URL", "http://localhost:8123").rstrip("/")
TOKEN = os.environ.get("TURTLE_API_TOKEN", "")
AGENT_NAME = os.environ.get("TURTLE_MCP_USERNAME", "@@mcp")

mcp = FastMCP("aiko_turtle",
    instructions=(
        "Virtual robots in a shared world (aiko_turtle). Robots have a pose "
        "(x, y, heading in degrees counter-clockwise, 0 = +x). Use list_kinds "
        "to see what each kind can do, create_robot to add one, move/turn "
        "to drive it, and chat to talk in the #robots channel where humans "
        "and other agents are. Say who you are: bots are named @@name."))


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read()).get("detail", error.reason)
        except Exception:
            detail = error.reason
        return {"error": f"{error.code}: {detail}"}
    except (urllib.error.URLError, OSError) as error:
        return {"error": f"cannot reach {BASE}: {error}"}


@mcp.tool()
def list_robots() -> list:
    """Every robot in the world with its pose, kind and owner"""
    return call("GET", "/api/robots")


@mcp.tool()
def list_kinds() -> list:
    """The robot kinds, with the Interfaces and commands each supports"""
    return call("GET", "/api/kinds")


@mcp.tool()
def create_robot(name: str, kind: str = "turtle", owner: str = AGENT_NAME) -> dict:
    """Create a robot (idempotent). name: letters, digits, '_' and '-'"""
    return call("POST", "/api/robots", {"name": name, "kind": kind, "owner": owner})


@mcp.tool()
def destroy_robot(name: str) -> dict:
    """Remove a robot from the world"""
    return call("DELETE", f"/api/robots/{name}")


@mcp.tool()
def move(name: str, distance: float | list[float], username: str = AGENT_NAME) -> dict:
    """Move a robot: a number = forward (negative = backwards), or a vector
    [forward, left, up] in its own frame for kinds with more axes (a drone
    has 3, an omni base 2; see list_kinds).  Returns the new pose"""
    return call("POST", f"/api/robots/{name}/move",
                {"distance": distance, "username": username})


@mcp.tool()
def turn(name: str, angle: float, username: str = AGENT_NAME) -> dict:
    """Turn a robot by angle degrees counter-clockwise; returns the new pose"""
    return call("POST", f"/api/robots/{name}/turn",
                {"angle": angle, "username": username})


@mcp.tool()
def reset(name: str, x: float = 0, y: float = 0, heading: float = 0,
          username: str = AGENT_NAME) -> dict:
    """Put a robot at (x, y) facing heading, on the ground; no arguments =
    the origin.  Works for every kind, even ones that cannot move"""
    return call("POST", f"/api/robots/{name}/reset",
                {"x": x, "y": y, "heading": heading, "username": username})


@mcp.tool()
def command(name: str, command: str, username: str = AGENT_NAME) -> dict:
    """Any chat command for a robot, without the @@mention: grasp or
    release (arms: LeKiwi, SO-101), telemetry, interfaces, stop, look.
    The reply text comes back; a command the kind lacks is an error"""
    return call("POST", f"/api/robots/{name}/command",
                {"command": command, "username": username})


@mcp.tool()
def history(name: str, limit: int = 50) -> list:
    """What happened to a robot: every command, who sent it, the pose after"""
    return call("GET", f"/api/robots/{name}/history?limit={limit}")


@mcp.tool()
def chat(message: str, username: str = AGENT_NAME, channel: str = "robots") -> dict:
    """Say something in a chat channel. A message starting with @@ROBOT COMMAND
    drives that robot through the chat (e.g. "@@my_turtle move 100")"""
    return call("POST", "/api/chat",
                {"message": message, "username": username, "channel": channel})


@mcp.tool()
def read_chat(channel: str = "robots") -> list:
    """Recent messages in a channel (humans are @name, bots @@name)"""
    return call("GET", f"/api/chat?channel={channel}")


if __name__ == "__main__":
    mcp.run()
