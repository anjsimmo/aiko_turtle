# lolibot_mp: LoliBot firmware that speaks the sandbox `lolibot` interface

An updated MicroPython firmware for the ESP32 LoliBot (OHC LCA2018 robot). It
replaces the trivial files in `od_micro_py_files/` and the 2018 motor driver,
and runs on the Aiko engine (`aiko_engine_mp`). It speaks the `lolibot`
interface of the sandbox at https://turtle.aiko.hashtag.ai, so the virtual
LoliBot and the real one take the same words.

Status: written against the engine source, not yet flashed to a bot. Reports
welcome.

## Files

- `boot.py`: greeting; esp/webrepl lines left commented.
- `main.py`: engine start-up flow, minimal; calls `aiko.services.initialise()`
  so the bot registers with the Registrar, then the application.
- `lolibot.py`: the application (copy to `lib/lolibot.py` on the board).
- `configuration/`: `main.py`, `mqtt.py`, `services.py`, `lolibot.py`.

## Wiring and pins (unchanged from 2018)

| Function         | GPIO |
|------------------|------|
| left motor 1     | 15   |
| left motor 2     | 13   |
| right motor 1    | 5    |
| right motor 2    | 23   |
| I2C SCL / SDA    | 19 / 18 |
| servo            | 16   |

PWM 30 Hz, duty 200..1023. The engine's `configuration/led.py` defaults to
NeoPixel pin 13, which is also left motor 2: set `neopixel_pin` for your board.

## Flashing

Follow `aiko_engine_mp/scripts/ampy/flash_lolibot.sh`: flash MicroPython, copy
the engine's `lib/` (aiko/, umqtt/, threading.py) and its `configuration/led.py`
and `configuration/net.py`, then copy this directory over the engine's files:

    ampy put lolibot_mp/main.py main.py
    ampy put lolibot_mp/boot.py boot.py
    ampy put lolibot_mp/lolibot.py lib/lolibot.py
    ampy put lolibot_mp/configuration/main.py configuration/main.py
    ampy put lolibot_mp/configuration/mqtt.py configuration/mqtt.py
    ampy put lolibot_mp/configuration/services.py configuration/services.py
    ampy put lolibot_mp/configuration/lolibot.py configuration/lolibot.py

(`mpremote cp` works the same way.) Set Wi-Fi in the engine's
`configuration/net.py`. Rename `name` in `configuration/services.py` per bot.

## Commands

On the bot's `$me/in` topic. The bare 2018 words still work.

| Command             | Effect                                         | Echo on out      |
|---------------------|------------------------------------------------|------------------|
| `(forward [SECS])`  | both wheels forward                            | `(forward 1.0)`  |
| `(reverse [SECS])`  | both wheels back                               | `(reverse 1.0)`  |
| `(left [SECS])`     | spin left                                      | `(left 1.0)`     |
| `(right [SECS])`    | spin right                                     | `(right 1.0)`    |
| `(stop)`            | motors off                                     | `(stop)`         |
| `(led R G B)`       | three NeoPixels, 0-255 each                    | `(led 0 0 255)`  |
| `(speed PERCENT)`   | duty scaled between min and max, 20..100       | `(speed 60)`     |
| `forward` etc.      | same as the S-expression, no seconds           | as above         |

No seconds (or 0) means run until the next command. A timed move publishes
`(stop)` on `$me/out` when it ends.

## Testing from a laptop

`aiko/HOSTNAME/0/0` is the engine's topic path convention
(namespace/hostname/0/0); the bot prints it when it connects.

    mosquitto_sub -h aiko.hashtag.ai -t 'aiko/HOSTNAME/0/0/out'
    mosquitto_pub -h aiko.hashtag.ai -t aiko/HOSTNAME/0/0/in -m '(forward 1)'
    mosquitto_pub -h aiko.hashtag.ai -t aiko/HOSTNAME/0/0/in -m '(led 0 0 255)'

## In the sandbox

Once the bot registers with the Registrar (name from `configuration/services.py`,
protocol `org.geekscape.protocol.lolibot:1`) it appears in the sandbox as a replica
of the virtual LoliBot.
