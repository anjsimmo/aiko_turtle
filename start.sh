#!/usr/bin/env bash
#
# Start the local processes in the background: the VirtualWorld, the web
# server (page + REST API) and the LLM ChatAgent.  The Registrar,
# HyperSpace and ChatServer are the shared ones at $AIKO_MQTT_HOST.
# For a 24x7 instance use the ProcessManager instead (see README).
#
#   ./start.sh          # then open http://localhost:8123
#   ./stop.sh

cd "$(dirname "$0")" || exit 1
source env.sh
mkdir -p logs

__start() {                             # __start NAME COMMAND...
  local name=$1; shift
  if pgrep -f "^python3 $1" > /dev/null; then
    echo "$name: already running"
  else
    (setsid nohup "$@" > "logs/$name.log" 2>&1 &)
    echo "$name: started -> logs/$name.log"
  fi
}

__start world  ./virtual_world.py run
__start web    ./web.py
__start agent  ./agent.py run

echo "Open http://localhost:${TURTLE_WEB_PORT:-8123}  (REST API docs at /docs)"
echo "A robot of your own from any machine:  ./robot.py run --name NAME"
