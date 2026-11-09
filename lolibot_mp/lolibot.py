# lolibot.py: LoliBot application for the Aiko engine, interface
# "org.geekscape.protocol.lolibot:1" (see robots/lolibot.py in aiko_turtle)
#
# MQTT commands on $me/in, S-expression or the bare 2018 word:
#   (forward [SECONDS])  (reverse [SECONDS])  (left [SECONDS])
#   (right [SECONDS])    (stop)               (led R G B)
#   (speed PERCENT)      forward | reverse | left | right | stop
# No SECONDS (or 0) runs until the next command.  Each action is echoed on
# $me/out, e.g. (forward 1.0), (led 0 0 255), (stop) when a timed move ends.

import configuration.lolibot

from machine import Pin
from machine import PWM
import time

import aiko.event as event
import aiko.led as led
import aiko.mqtt as mqtt
import aiko.services as services

left_motor1 = None
left_motor2 = None
right_motor1 = None
right_motor2 = None

duty_cycle_max = 1023
duty_cycle_min = 200
pwm_frequency = 30
speed_percent = 100
stop_time = None        # time.ticks_ms() deadline of a timed move, or None
last_command = "stop"

motor_commands = {
  "stop":    (   0,    0,    0,    0),
  "forward": (1023,    0, 1023,    0),
  "left":    ( 200,    0, 1023,    0),
  "right":   (1023,    0,  200,    0),
  "reverse": (   0, 1023,    0, 1023)
}

def echo(text):
  print("lolibot: " + text)
  mqtt.client.publish(services.topic_out, text)

def scaled(duty):
  span = duty_cycle_max - duty_cycle_min
  full = duty_cycle_min + span * (speed_percent - 20) // 80
  return duty * full // 1023  # 1023 is full speed; 200 is the slow wheel of a turn

def motor_action(command):
  left_motor1.duty(scaled(command[0]))
  left_motor2.duty(scaled(command[1]))
  right_motor1.duty(scaled(command[2]))
  right_motor2.duty(scaled(command[3]))

def do_motion(word, seconds):
  global stop_time, last_command
  last_command = word
  motor_action(motor_commands[word])
  if word != "stop" and seconds > 0:
    stop_time = time.ticks_add(time.ticks_ms(), int(seconds * 1000))
  else:
    stop_time = None
  if word == "stop": echo("(stop)")
  elif seconds > 0: echo("(" + word + " " + str(seconds) + ")")
  else: echo("(" + word + ")")

def do_led(red, green, blue):
  color = (red, green, blue)
  led.pixel(color, 0)
  led.pixel(color, 1)
  led.pixel(color, 2, True)
  echo("(led " + str(red) + " " + str(green) + " " + str(blue) + ")")

def do_speed(percent):
  global speed_percent
  speed_percent = max(20, min(100, percent))
  if last_command != "stop": motor_action(motor_commands[last_command])
  echo("(speed " + str(speed_percent) + ")")

def timer_handler():  # the engine has no one-shot timer: poll for the deadline
  global stop_time
  if stop_time is not None and time.ticks_diff(time.ticks_ms(), stop_time) >= 0:
    do_motion("stop", 0)

def parse(payload):
  text = payload.strip()
  if text.startswith("("): text = text[1:]
  if text.endswith(")"): text = text[:-1]
  return text.split()

def on_lolibot_message(topic, payload_in):
  tokens = parse(payload_in)
  if len(tokens) == 0: return False
  word = tokens[0]
  try:
    if word == "stop" and len(tokens) == 1:
      do_motion("stop", 0)
    elif word in motor_commands and len(tokens) <= 2:
      do_motion(word, float(tokens[1]) if len(tokens) == 2 else 0)
    elif word == "led" and len(tokens) == 4:
      do_led(*[max(0, min(255, int(t))) for t in tokens[1:]])
    elif word == "speed" and len(tokens) == 2:
      do_speed(int(float(tokens[1])))
    else:
      return False
  except ValueError:
    return False
  return True

def initialise_motor(settings, motor_pin_name):
  motor = PWM(Pin(int(settings[motor_pin_name])))
  motor.freq(pwm_frequency)
  motor.duty(0)
  return motor

def initialise(settings=configuration.lolibot.settings):
  global duty_cycle_max, duty_cycle_min, pwm_frequency
  global left_motor1, left_motor2, right_motor1, right_motor2

  if "duty_cycle_max" in settings:
    duty_cycle_max = int(settings["duty_cycle_max"])
  if "duty_cycle_min" in settings:
    duty_cycle_min = int(settings["duty_cycle_min"])
  if "pwm_frequency" in settings:
    pwm_frequency = int(settings["pwm_frequency"])

  left_motor1 = initialise_motor(settings, "left_motor_pin1")
  left_motor2 = initialise_motor(settings, "left_motor_pin2")
  right_motor1 = initialise_motor(settings, "right_motor_pin1")
  right_motor2 = initialise_motor(settings, "right_motor_pin2")

  mqtt.add_message_handler(on_lolibot_message, "$me/in")
  event.add_timer_handler(timer_handler, 50)
