# Source this to set up the environment for the imagineering demo.
#
# Needs aiko_services and aiko_chat installed (official repos, no local
# modifications):  pip install -e aiko_services  &&  pip install -e aiko_chat
# Activate your own venv/conda env first, or set AIKO_PYTHON_BIN below.
#
# Every variable here is only a default: a value already in the environment
# wins, e.g.  AIKO_MQTT_HOST=localhost ./start.sh

AIKO_PYTHON_BIN="${AIKO_PYTHON_BIN:-$HOME/miniconda3/envs/aiko/bin}"
if [ -d "$AIKO_PYTHON_BIN" ]; then
  export PATH="$AIKO_PYTHON_BIN:$PATH"
fi

export AIKO_MQTT_HOST="${AIKO_MQTT_HOST:-aiko.hashtag.ai}"
export AIKO_MQTT_PORT="${AIKO_MQTT_PORT:-1883}"
export AIKO_NAMESPACE="${AIKO_NAMESPACE:-aiko}"   # the shared default namespace
export AIKO_LOG_LEVEL="${AIKO_LOG_LEVEL:-INFO}"
export USER="${USER:-$(id -un)}"
export PYTHONUNBUFFERED=1   # so "script > log &" streams live
