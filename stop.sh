#!/usr/bin/env bash
#
# Stop everything ./start.sh started, plus the robot's lazily started
# elements (world, camera, turn, forward)

cd "$(dirname "$0")" || exit 1
HERE=$(pwd)

pkill -f "^python3 ./world_viewer_web.py"   && echo "stopped web_viewer"
pkill -f "^python3 ./chat_llm_agent.py"     && echo "stopped llm_agent"
pkill -f "^python3 ./chat_robot_agent.py"   && echo "stopped robot"
pkill -f "^python3 $HERE/virtual_world.py"  && echo "stopped world"
pkill -f "^python3 $HERE/robot_elements.py" && echo "stopped elements"
exit 0
