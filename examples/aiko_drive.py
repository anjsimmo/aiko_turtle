#!/usr/bin/env python3
#
# Drive a robot over Aiko Services directly: find its Service in the
# Registrar and call its <Move> functions, no web server in the loop.
# This is what the web page and the chat do underneath, and it works
# from any machine that can reach the MQTT broker.
#
#   pip install -e aiko_services -e aiko_chat          # once, see README
#   export AIKO_MQTT_HOST=aiko.hashtag.ai              # the community instance
#   python3 aiko_drive.py my_turtle                     # a robot that exists (page or REST)
#
# Every robot in the world is a Service with the tags "robot=0 move=0 ..."
# (one per Interface it implements) and "botname=@@NAME".  The robot's
# replies go to the chat channel, so run "aiko_chat repl" (then ":cc
# robots") in another terminal to see them, or watch /world in a browser.

import sys
import time

import aiko_services as aiko

NAME = sys.argv[1] if len(sys.argv) > 1 else "my_turtle"
ME = "@aiko_drive"
ROBOT_PROTOCOL = "ai.hashtag.ai/chat_robot:0"


class Move(aiko.Interface):         # the subset of <Move> we call (interfaces.py)
    def move(self, distance, username="anonymous"): pass
    def turn(self, angle, username="anonymous"): pass


def found(service_details, robot):
    topic_path, name, protocol, transport, owner, tags = service_details[:6]
    print(f"found @@{name} at {topic_path}")
    print(f"  tags: {' '.join(str(tag) for tag in tags)}")
    if "move=0" not in [str(tag) for tag in tags]:
        print("  this kind cannot move (no <Move>): try look/telemetry in the chat")
        aiko.process.terminate()
        return
    for _ in range(4):                                # a square
        robot.move(100, ME)
        robot.turn(90, ME)
        time.sleep(0.5)
    print("done: the robot reported each pose in the chat channel")
    aiko.process.terminate()


def lost(service_details):
    print(f"@@{service_details[1]} went away")


aiko.do_discovery(Move,
    aiko.ServiceFilter("*", NAME, ROBOT_PROTOCOL, "*", "*", "*"), found, lost)
print(f"looking for @@{NAME} in the Registrar (Ctrl-C to stop) ...")
aiko.process.run()
