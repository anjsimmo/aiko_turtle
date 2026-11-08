# aiko_turtle

Virtual robots in a shared world, for AI + ML + robotics experiments.
Anyone can create a robot, drive it from the chat, from a REST API or
from an LLM agent, and watch every robot move in the browser.

Built on the official, unmodified
[aiko_services](https://github.com/geekscape/aiko_services) and
[aiko_chat](https://github.com/geekscape/aiko_chat). Everything here is
application code; the shared services (MQTT broker, Registrar, HyperSpace,
ChatServer) run on the community instance **aiko.hashtag.ai**.

**Last tested with** aiko_services `39796ee` (2026-11-07) and aiko_chat
`9edb211` (2026-10-31), the heads of `master` and `main` at the time. The
aim is that it always works with the latest; if it does not, those are the
commits to compare against.

## How it fits together

| Process | What it is |
|---|---|
| `virtual_world.py` | **VirtualWorld** Actor: holds every robot's pose, persists them in a database, publishes them as the share `robots.<name>` |
| `robot.py` | **ChatRobotAgent**: one Actor per robot, implementing the `<Chat>` and `<Robot>` (`<Move>` `<Perceive>` `<Telemetry>`) Interfaces. Its body is in the world; it is the robot's voice in the chat and its entry in the Registrar |
| `web.py` | **web server** (FastAPI): the page, the REST API (`/docs`) and a live SSE stream. It also *hosts* a ChatRobotAgent for every robot created over REST, so those answer in the chat too |
| `agent.py` | **LLM ChatAgent** `@@pilot`: discovers robots from Registrar tags and drives them in natural language. Rate limited |

Every robot in the world is always answerable in the chat and listed in
the Registrar:

- **Over REST / the page**: `POST /api/robots`. The web server hosts the
  robot's chat Actor, and re-hosts every robot after a restart.
- **Over Aiko, from any machine**: `./robot.py run --name NAME`. While
  your process runs, *it* speaks for the robot and the web server steps
  back; when it exits, the web server takes over again. So your own code
  (or a physical robot) can stand in for a virtual one at any time.

Both are the same thing: a row in the world's database and a
`<Chat>`+`<Robot>` Service in the Registrar.

Identity is deliberately not validated: pick any user name and any robot
name. If you do not want others driving your robot, pick a longer, more
unusual name.

## Install

```bash
git clone https://github.com/geekscape/aiko_services && pip install -e aiko_services
git clone https://github.com/geekscape/aiko_chat     && pip install -e aiko_chat
git clone https://github.com/anjsimmo/aiko_turtle    && cd aiko_turtle
pip install -r requirements.txt
cp .env.example .env          # optional: edit what you need
```

Python 3.12+. A venv or conda env is fine; `env.sh` warns if the `python3`
it finds lacks the packages. Set `AIKO_PYTHON_BIN` in `.env` to the `bin`
of your environment if you do not want to activate it each time.

## Configure

Everything is a variable with a default, read from the environment, then
`.env` (not committed), then `config.py`. See `.env.example`. The ones
you are most likely to touch:

| Variable | Default | |
|---|---|---|
| `AIKO_MQTT_HOST` | `aiko.hashtag.ai` | the shared services |
| `TURTLE_WORLD` | `turtle_world` | name of the VirtualWorld Service |
| `TURTLE_DATABASE_URL` | `sqlite:///turtle.db` | any SQLAlchemy URL; relative to the working directory, like HyperSpace storage |
| `TURTLE_CHANNEL` | `robots` | chat channel |
| `TURTLE_WEB_PORT` | `8123` | the web server binds `127.0.0.1` |
| `OPENAI_API_KEY` | | the agent falls back to the `claude` CLI without it |
| `TURTLE_LLM_RATE_PER_MINUTE` | `10` | agent requests per minute (also `_USER_` per user, and `_QUEUE_LIMIT`) |

## Run

```bash
./start.sh      # world, web server, agent (logs in logs/)
./stop.sh
```

Or by hand, each in its own terminal, after `source env.sh`:

```bash
./virtual_world.py run
./web.py
./agent.py run
./robot.py run --name my_turtle      # a robot of your own, from anywhere
```

## Try it

Open **http://localhost:8123**. The world is on the left: create a robot,
click one to select it, use the quick-command buttons. The `#robots`
channel is on the right, with your name in the box (any name).

**REST** (interactive docs at http://localhost:8123/docs):

```bash
curl -X POST localhost:8123/api/robots -H 'Content-Type: application/json' \
     -d '{"name": "my_turtle", "kind": "turtle", "owner": "me"}'
curl -X POST localhost:8123/api/robots/my_turtle/turn -H 'Content-Type: application/json' \
     -d '{"angle": 90, "username": "me"}'
curl -X POST localhost:8123/api/robots/my_turtle/move -H 'Content-Type: application/json' \
     -d '{"distance": 100, "username": "me"}'
curl localhost:8123/api/robots                 # everyone's robots
curl localhost:8123/api/robots/my_turtle/history
curl -N localhost:8123/events                  # live poses + chat (SSE)
curl -X DELETE localhost:8123/api/robots/my_turtle
```

Every drive call returns the new pose. Kinds: `turtle`, `arrow`.

**Chat** (the page, `aiko_chat repl` after `:cc robots`, or
`aiko_chat send robots "..."`):

```text
@@my_turtle move 100         ;; <Move>, replies with the new pose
@@my_turtle turn 90          ;; degrees counter-clockwise
@@my_turtle look             ;; <Perceive>
@@my_turtle telemetry        ;; <Telemetry>
@@my_turtle interfaces       ;; <Robot>
@@my_turtle reset
@@pilot draw a square with my_turtle     ;; the LLM agent
```

Robots act only on messages that *start* with their `@@name`. Replies end
with ` !!!!`, the aiko_chat convention that stops bots answering bots.

## Tests

```bash
python3 -m pytest -q tests      # 13 tests, well under a second, no broker needed
```

They cover the world maths and persistence, the chat command and LLM
output parsers, the rate limiter, and the REST API against a fake
backend.

## State

| What | Where | Owner |
|---|---|---|
| robot definitions and poses | `robots` table | the world |
| every command, who sent it, the resulting pose | `events` table (`/api/robots/NAME/history`) | the world |
| live poses | the share `robots.<name>` on the world's topic | the world |
| which robots the web server speaks for | `host` column = `web` | the world, written by the web server |

The world is the only writer. Restart anything and the robots are where
they were. Change the database with one variable (`TURTLE_DATABASE_URL`).

## Deploying on a server

[docs/deployment.md](docs/deployment.md) walks through the public
instance at **https://turtle.aiko.hashtag.ai** step by step: the
aiko_services production instance, `.env`, the three entries in
`${HOST}_supervisor.json` (from `supervisor.json.example`), nginx with a
Let's Encrypt certificate, DNS, and how to update it (`git pull`, then
`sudo systemctl restart aiko.service`). The web server binds localhost;
the proxy needs `proxy_buffering off` for the SSE endpoint.

## Files

| File | Purpose |
|---|---|
| `config.py` | settings: environment, then `.env`, then defaults |
| `db.py` | the `robots` and `events` tables (SQLAlchemy Core) |
| `world_model.py` | the world without Aiko: poses, maths, persistence |
| `virtual_world.py` | the VirtualWorld Actor |
| `interfaces.py` | `<Chat>` `<Robot>` `<Move>` `<Perceive>` `<Telemetry>` and the aspect tags |
| `core.py` | chat command parser, LLM output parser, rate limiter, name rule |
| `robot.py` | ChatRobotAgent (`./robot.py run`, and `host_robot()` for the web server) |
| `agent.py` | the LLM ChatAgent |
| `webapp.py` | the FastAPI app and page (no Aiko; testable) |
| `web.py` | the Aiko-connected backend and server |
| `tests/` | pytest |
| `start.sh` `stop.sh` `env.sh` | local convenience |
| `supervisor.json.example` | ProcessManager definition entries |
| `docs/` | `deployment.md` (server setup and updates) and the 2026-08-22 imagineering session report |

## Design notes

- **Aspect tags.** A robot registers with one tag per Interface it
  implements, `chat=0 robot=0 move=0 perceive=0 telemetry=0` (the ADR-025
  convention), plus `botname=`, `channel=`, `kind=`, `commands=`. The
  agent discovers robots with `implements(tags, "Robot")`; a
  ServiceFilter can select on `tags=["robot=0"]`. Versioning comes free:
  a `move=1` robot simply does not match a `move=0` client.
- **One world process, one Actor per robot.** The earlier design (each
  robot a hyperspace collection of lazily started source/target
  processes, with an embedded ProcessManager) is in the git history. It
  was replaced because every known issue came from the process split.
- **Hosting.** The web server creates ChatRobotAgent Actors in its own
  process (Aiko Services supports several Services per process). One
  framework detail: discovery registered after the services cache has
  loaded gets no replay of known Services (a TODO in `share.py`), so
  `ChatRobotAgent.attach_known_services()` reads the cache itself.
- **Service ids are never reused.** `aiko.process.remove_service()`
  decrements the counter that also generates Service ids, so the next
  Actor created in the process would share a topic path with a live one
  and the two would hear each other's messages. `ChatRobotAgent.detach()`
  restores the counter. Worth an upstream fix.
- **Request/response from HTTP threads.** `web.py` calls the world with a
  per-request response topic and waits on a queue. Never do that on the
  Aiko event thread: the reply arrives on it.

## Known issues

- Channel `robots` is not in the ChatServer's channel list (`:lc`); the
  server relays to any channel, so it works. Avoid the channel `robot`,
  which the server routes to XGO robots.
- The agent sends robot commands one second apart; order is kept because
  the world applies each instantly.
- No identity: anyone can drive any robot, by design for now.
