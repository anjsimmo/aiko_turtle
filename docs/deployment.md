# Deploying aiko_turtle on a server

How the public instance at **https://turtle.aiko.hashtag.ai** is set up,
written so that anyone can reproduce it on their own host or add another
application next to it. Everything below is done on the server over
`ssh`; no files are ever copied to the server by hand. Code goes to the
server by `git push` here and `git pull` there, and nothing else.

```
browser ──HTTPS──> nginx ──> 127.0.0.1:8123 web.py ──┐
                                                     │  MQTT (localhost)
   ProcessManager (systemd aiko.service) runs: ──────┤
     Registrar, HyperSpace, ChatServer   (aiko_services / aiko_chat)
     virtual_world.py, web.py, agent.py  (aiko_turtle)
```

## 0. What you need

- A Linux host with a public IP (the reference instance is a GCP VM,
  Ubuntu 24.04) and `sudo`.
- An **aiko_services production instance** on it: the Mosquitto broker,
  Registrar, HyperSpace and ChatServer, started at boot by the
  ProcessManager under `systemd`. Set that up first by following the
  upstream tutorial
  [production_instance.md](https://github.com/geekscape/aiko_services/blob/master/documentation/tutorials/production_instance.md).
  When it is done you have a `systemd` unit (called `aiko.service` below)
  and a definition file `${HOST}_supervisor.json` listing the processes it
  starts. aiko_turtle adds three entries to that file.
- A DNS name that resolves to the host (see step 5).
- Optionally an `OPENAI_API_KEY` for the LLM ChatAgent.

The reference instance has one Python environment shared by everything:
a venv at `~/venvs/venv_3.14` with `aiko_services`, `aiko_chat` and this
project's requirements installed. Use whatever you like, as long as the
same `python3` serves all the processes in the definition file.

## 1. Install the code

```bash
ssh USER@HOST
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/anjsimmo/aiko_turtle
source ~/venvs/venv_3.14/bin/activate          # the env that has aiko_services + aiko_chat
pip install -r aiko_turtle/requirements.txt
```

If `aiko_services` and `aiko_chat` are not installed yet:

```bash
git clone https://github.com/geekscape/aiko_services && pip install -e aiko_services
git clone https://github.com/geekscape/aiko_chat     && pip install -e aiko_chat
```

Check it works before wiring it into the ProcessManager. With the shared
services already running on this host:

```bash
cd ~/projects/aiko_turtle
AIKO_MQTT_HOST=localhost python3 -m pytest -q tests     # no broker needed; sanity check
AIKO_MQTT_HOST=localhost python3 virtual_world.py run   # Ctrl-C when "robots loaded" appears
```

## 2. Configure: `.env`

`config.py` reads `.env` from the project directory in every process, so
the ProcessManager definition needs no variables at all. Create it:

```bash
cd ~/projects/aiko_turtle
cp .env.example .env
```

and set, at minimum:

```bash
AIKO_MQTT_HOST=localhost          # the broker is on this host
TURTLE_USERNAME=web               # chat name the web server speaks under
OPENAI_API_KEY=sk-...             # optional; without it the agent needs the claude CLI
```

Leave `TURTLE_WEB_HOST` at `127.0.0.1`. The web server is only ever
reached through nginx. The database defaults to `turtle.db` in the
project directory, which is fine for one instance; it is in
`.gitignore` so `git pull` never touches it.

**One world per broker.** Every process finds the world by its name
(`TURTLE_WORLD`, default `turtle_world`) in the shared Registrar. If
somebody runs a second `virtual_world.py` against the same broker with
the same name, the two worlds fight over the robots. The production
instance owns the default name. For development against the same broker,
set a different `TURTLE_WORLD` (and `TURTLE_CHANNEL`) in your local
`.env`.

## 3. Start it at boot: the ProcessManager definition

Append the three entries from `supervisor.json.example` to
`~/${HOST}_supervisor.json` (the file your `aiko.service` unit points at),
with `cwd` set to the real path:

```json
  {"enabled": true,
   "command": "python3 virtual_world.py run",
   "cwd":     "/home/USER/projects/aiko_turtle"},

  {"enabled": true,
   "command": "python3 web.py",
   "cwd":     "/home/USER/projects/aiko_turtle"},

  {"enabled": true,
   "command": "python3 agent.py run",
   "cwd":     "/home/USER/projects/aiko_turtle"}
```

The definition is a single JSON list, so mind the commas between entries.
The `systemd` unit must put the right `python3` first on the `PATH`
(`Environment=PATH=/home/USER/venvs/venv_3.14/bin:/usr/bin:/bin` in its
`[Service]` section); the same `python3` then runs the Aiko services and
these three processes.

Then:

```bash
sudo systemctl restart aiko.service
journalctl -u aiko -f            # watch the processes come up
curl -s localhost:8123/api/robots
```

Two things to know about the ProcessManager, both learnt the hard way:

- **The definition file is read only when the service starts.** Editing
  it does nothing until `sudo systemctl restart aiko.service`.
- **`aiko_process create` and `destroy` are silently ignored** in this
  mode (it runs in "safe mode"), so there is no way to start or stop one
  process on its own. A restart of `aiko.service` restarts *everything*
  it manages, including the Registrar, HyperSpace and ChatServer. They
  are back within a few seconds and the robots reload from the database,
  so this is harmless, but it is a blip for anyone connected.

Logs of all managed processes go to the journal: `journalctl -u aiko`.

## 4. Put it behind nginx with HTTPS

The web server binds localhost and knows nothing about TLS. nginx
terminates HTTPS and proxies to it. The one non-default requirement is
that `/events` is a server-sent-events stream, so buffering must be off
and the read timeout long.

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo tee /etc/nginx/sites-available/turtle.aiko.hashtag.ai > /dev/null <<'NGINX'
server {
    listen 80;
    server_name turtle.aiko.hashtag.ai;

    location / {
        proxy_pass http://127.0.0.1:8123;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;          # /events is server-sent events
        proxy_read_timeout 1h;
    }
}
NGINX
sudo ln -s /etc/nginx/sites-available/turtle.aiko.hashtag.ai /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d turtle.aiko.hashtag.ai      # adds the 443 block and the redirect
```

certbot installs a `systemd` timer that renews the certificate
automatically. Ports 80 and 443 must be open in the host's firewall; on
GCP that is the `http-server` and `https-server` network tags on the
instance.

## 5. DNS

The reference instance uses a wildcard so that new applications need no
DNS change at all: in the `hashtag.ai` zone (Route 53),
`*.aiko.hashtag.ai` is a `CNAME` to `aiko.hashtag.ai`. Any
`NAME.aiko.hashtag.ai` already resolves; giving it a site is just step 4
with a different name. Without a wildcard, add an `A` or `CNAME` record
for the name before running certbot, which validates over HTTP.

## 6. Updating a running instance

The server is a plain clone of the GitHub repository. Never edit or copy
files on the server directly: the next `git pull` would conflict and
nobody else could see what changed.

```bash
# on your machine
git push

# on the server
ssh USER@HOST
cd ~/projects/aiko_turtle && git pull
pip install -r requirements.txt           # only if requirements.txt changed
sudo systemctl restart aiko.service       # the only way to reload code (see step 3)
```

If `supervisor.json.example` gained an entry, mirror it in
`~/${HOST}_supervisor.json` before the restart. Robot definitions,
poses and history live in the database and survive restarts.

## 7. Checking that it is alive

```bash
systemctl is-active aiko nginx mosquitto
journalctl -u aiko --since "5 min ago"
curl -s https://turtle.aiko.hashtag.ai/api/robots
curl -N https://turtle.aiko.hashtag.ai/events        # should stream, Ctrl-C to stop
aiko_chat send robots "@@pilot which robots are there?"   # from any machine on the broker
```

## Troubleshooting

| Symptom | Cause, fix |
|---|---|
| Page loads, "world not connected", REST returns 503 | `virtual_world.py` is not running or has another `TURTLE_WORLD` name. `journalctl -u aiko`, check `.env`. |
| Robots jump around or vanish and reappear | Two worlds with the same name on one broker. Find the stray `virtual_world.py` (usually a developer's laptop with default settings) and stop it. |
| Edited the definition file, nothing changed | It is read only at start: `sudo systemctl restart aiko.service`. |
| `/events` stalls or disconnects after a minute | nginx buffering or timeout: the site must have `proxy_buffering off` and a long `proxy_read_timeout`. |
| `ModuleNotFoundError` in the journal | The unit's `PATH` does not start with the venv's `bin`, so the system `python3` runs. |
| `@@pilot` does not answer | No `OPENAI_API_KEY` and no `claude` CLI on the `PATH` of the unit, or the rate limit (`TURTLE_LLM_*`) is reached. |

## Adding another application on the same host

Repeat the pattern: clone it under `~/projects`, add its processes to
`~/${HOST}_supervisor.json`, give it its own localhost port, add an nginx
site for `NAME.aiko.hashtag.ai` and run `certbot --nginx -d` for it. The
shared broker, Registrar, HyperSpace and ChatServer are already there.
