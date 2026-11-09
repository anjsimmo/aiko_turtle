# configuration/mqtt.py: LoliBot (lolibot_mp)

settings = {
  "host":            "aiko.hashtag.ai",
  "keepalive":       60,
  "port":            1883,
  "topic_path":      "$me",
  "topic_subscribe": ["$me/in"],

# Enable processing *INSECURE* exec() commands received via MQTT
  "mqtt_insecure_exec": False
}
