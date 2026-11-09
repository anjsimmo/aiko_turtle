# main.py: LoliBot firmware entry point, a minimal copy of the Aiko engine's
# main.py flow (aiko_engine_mp/main.py), plus Registrar registration.
#
# Order matters: aiko.services.initialise() adds "$me/in" and the registrar
# topic to the MQTT subscriptions, so it runs before the network comes up.

import configuration.main
configuration.globals = globals()  # used by aiko.mqtt.on_exec_message()
parameter = configuration.main.parameter

import aiko.event
import aiko.net
import aiko.mqtt

if parameter("led_enabled"):
  import aiko.led
  aiko.led.initialise()

if parameter("oled_enabled"):
  import aiko.oled
  aiko.oled.initialise()

if parameter("services_enabled"):
  import aiko.services
  aiko.services.initialise()  # registers with the Aiko Registrar

aiko.net.initialise()

if parameter("application"):
  application_name = parameter("application")
  application = __import__(application_name)
  application.initialise()

aiko.event.loop_thread()
