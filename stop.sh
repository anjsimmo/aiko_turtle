#!/usr/bin/env bash
#
# Stop everything ./start.sh started (and any ./robot.py run from here).

cd "$(dirname "$0")" || exit 1
HERE=$(pwd)
# started as "./x.py" or as "$HERE/x.py" (e.g. by a ProcessManager);
# pkill patterns are extended regular expressions
ANY="^python3 (\./|$HERE/)(web|agent|robot|virtual_world)\.py"

for script in web agent robot virtual_world; do
  pkill -f "^python3 (\./|$HERE/)$script\.py" && echo "stopping $script.py"
done
for _ in $(seq 1 50); do                 # up to 5 s for a clean exit
  pgrep -f "$ANY" > /dev/null || exit 0
  sleep 0.1
done
pkill -9 -f "$ANY" && echo "killed stragglers"
exit 0
