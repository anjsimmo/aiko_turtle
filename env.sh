# Source this before running anything by hand:  source env.sh
#
# Reads ".env" (see ".env.example"; not committed) and fills in defaults.
# A value already in the environment always wins.  Needs aiko_services and
# aiko_chat installed (official repos, no local modifications):
#   pip install -e ../aiko_services -e ../aiko_chat -r requirements.txt

cd "$(dirname "${BASH_SOURCE[0]}")" || return 1
if [ -f .env ]; then
  set -a; source ./.env; set +a
fi

if [ -n "$AIKO_PYTHON_BIN" ] && [ -d "$AIKO_PYTHON_BIN" ]; then
  export PATH="$AIKO_PYTHON_BIN:$PATH"
fi

export AIKO_MQTT_HOST="${AIKO_MQTT_HOST:-aiko.hashtag.ai}"
export AIKO_MQTT_PORT="${AIKO_MQTT_PORT:-1883}"
export AIKO_NAMESPACE="${AIKO_NAMESPACE:-aiko}"
export AIKO_LOG_LEVEL="${AIKO_LOG_LEVEL:-INFO}"
export USER="${USER:-$(id -un)}"
export PYTHONUNBUFFERED=1   # so "script > log &" streams live

if ! python3 -c "import aiko_services, fastapi" 2>/dev/null; then
  echo "env.sh: python3 ($(command -v python3)) lacks aiko_services or fastapi:" \
       "activate your environment or set AIKO_PYTHON_BIN in .env" >&2
fi
