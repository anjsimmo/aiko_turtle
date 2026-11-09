# configuration/main.py: LoliBot (lolibot_mp)

settings = {
  "application":      "lolibot",  # module in lib/ whose initialise() is called
  "gc_enabled":       False,
  "led_enabled":      True,
  "lolibot_enabled":  True,
  "oled_enabled":     False,
  "services_enabled": True
}

def parameter(name, settings=settings):
  if name in settings: return settings[name]
  return False
