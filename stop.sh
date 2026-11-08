#!/usr/bin/env bash
#
# Stop everything ./start.sh started, plus the robot's lazily started
# elements (world, camera, turn, forward). Waits until they have exited.

cd "$(dirname "$0")" || exit 1
HERE=$(pwd)

PATTERNS=(
  "^python3 ./world_viewer_web.py"
  "^python3 ./chat_llm_agent.py"
  "^python3 ./chat_robot_agent.py"
  "^python3 $HERE/virtual_world.py"
  "^python3 $HERE/robot_elements.py"
)
for pattern in "${PATTERNS[@]}"; do
  pkill -f "$pattern" && echo "stopping ${pattern#^python3 }"
done
for _ in $(seq 1 50); do                 # up to 5 s for a clean exit
  pgrep -f "^python3 \(./\|$HERE/\)" > /dev/null || exit 0
  sleep 0.1
done
pkill -9 -f "^python3 \(./\|$HERE/\)" && echo "killed stragglers"
exit 0
