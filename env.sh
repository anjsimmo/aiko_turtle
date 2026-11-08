# Source this to set up the Aiko environment for today's imagineering session
# Uses the "aiko" conda env, which has aiko_services and aiko_chat installed
# in editable mode from /home/anj/src/aiko/{aiko_services,aiko_chat}

export PATH="/home/anj/miniconda3/envs/aiko/bin:$PATH"
export AIKO_MQTT_HOST=aiko.hashtag.ai
export AIKO_MQTT_PORT=1883
# Default/shared namespace, so plain "AIKO_MQTT_HOST=aiko.hashtag.ai
# aiko_dashboard" finds the registrar (which we run)
export AIKO_NAMESPACE=aiko
export AIKO_LOG_LEVEL=INFO
export USER="${USER:-anj}"
# Unbuffered stdout so "script > log &" streams live
export PYTHONUNBUFFERED=1
