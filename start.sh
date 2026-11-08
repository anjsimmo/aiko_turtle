#!/usr/bin/env bash
#
# Start the local half of the imagineering stack in the background:
# the ChatRobotAgent, the LLM ChatAgent and the robot+chat web page.
# The Registrar, HyperSpace and ChatServer run on aiko.hashtag.ai.
#
#   ./start.sh          # then open http://localhost:8123
#   ./stop.sh

cd "$(dirname "$0")" || exit 1
source env.sh
mkdir -p logs

if [ ! -d _robot_space_ ]; then
  ./robot_space_setup.py                # once: the robot's bootstrap entries
fi

__start() {                             # __start NAME COMMAND...
  local name=$1; shift
  if pgrep -f "^python3 $1" > /dev/null; then
    echo "$name: already running"
  else
    (setsid nohup "$@" > "logs/$name.log" 2>&1 &)
    echo "$name: started -> logs/$name.log"
  fi
}

__start robot      ./chat_robot_agent.py run
__start llm_agent  ./chat_llm_agent.py run
__start web_viewer ./world_viewer_web.py

echo "Open http://localhost:8123  (robot on the left, #robots chat on the right)"
