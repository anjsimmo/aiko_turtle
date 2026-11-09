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
        "Virtual robots in a shared world (the Aiko sandbox), each speaking "
        "the interface of a real robot. Robots have a pose (x, y, heading in "
        "degrees counter-clockwise, 0 = +x). Use list_interfaces to see the "
        "commands of each interface, list_kinds for the bodies, create_robot "
        "to add one, command to drive it in its own words (move 0.2 for an "
        "irobot, action sit for an xgo_robot), and chat to talk in the "
        "#robots channel where humans and other agents are. Twins of real "
        "robots forward your commands to the real one. Say who you are: "
        "bots are named @@name."))


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
def list_interfaces() -> list:
    """Every interface a robot may speak: its functions, example commands,
    units, and whether a real robot speaks it (real), an older one did
    (legacy) or it is a proposal"""
    return call("GET", "/api/interfaces")


@mcp.tool()
def create_robot(name: str, kind: str = "turtle", owner: str = AGENT_NAME,
                 interface: str = "") -> dict:
    """Create a robot (idempotent). name: letters, digits, '_' and '-';
    interface: one the kind may speak (list_kinds), default its own"""
    body = {"name": name, "kind": kind, "owner": owner}
    if interface:
        body["interface"] = interface
    return call("POST", "/api/robots", body)


@mcp.tool()
def robot_interface(name: str) -> dict:
    """A robot's interface spec (functions, example commands) and its
    topic path on the MQTT bus"""
    return call("GET", f"/api/robots/{name}/interface")


@mcp.tool()
def destroy_robot(name: str) -> dict:
    """Remove a robot from the world"""
    return call("DELETE", f"/api/robots/{name}")


@mcp.tool()
def move(name: str, distance: float | list[float], username: str = AGENT_NAME) -> dict:
    """The sandbox's hand: move the body in world units whatever interface
    it speaks (a number = forward, or [forward, left, up]).  To drive a
    robot in its own words use command().  Returns the new pose"""
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
    """A command in the robot's own interface, without the @@mention
    (see robot_interface or list_interfaces for the words): move 100 for
    the proposed interface, move 0.2 for an irobot, action sit for an
    xgo_robot, forward 100 for a legacy turtle; "help" lists them.  The
    reply text comes back; a command the interface lacks is an error"""
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
