# Deploying aiko_turtle on a server

How the public instance at **https://turtle.aiko.hashtag.ai** is set up,
written so that anyone can reproduce it on their own host or add another
application next to it. Everything below is done on the server over
`ssh`; no files are ever copied to the server by hand. Code goes to the
server by `git push` here and `git pull` there, and nothing else.

```
browser ──HTTPS──> nginx ──> 127.0.0.1:8123 web.py ──┐
                                                     │  MQTT (localhost)
   ProcessManager (systemd unit $HOST.service) runs: ┤
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
  It leaves you with three things this guide builds on, all named after
  the `--name` you gave `aiko_supervisor install` (the tutorial calls it
  `$HOST`; on the reference instance it is `aiko`):
  - the definition file `/home/$USERNAME/${HOST}_supervisor.json`, a JSON
    list of the processes the ProcessManager starts;
  - the unit `/etc/systemd/system/$HOST.service`, **rendered** by
    `aiko_supervisor install` from that file and its options. It sets
    `AIKO_MQTT_HOST=localhost` and a `PATH` that starts with the venv's
    `bin`, so every managed process gets both without any configuration
    of its own;
  - a venv with `aiko_services` and `aiko_chat` installed, `$VENV` below
    (`~/venvs/venv_3.14`, Python 3.14, on the reference instance).
- A DNS name that resolves to the host (see step 5).
- Optionally an `OPENAI_API_KEY` for the LLM ChatAgent.

The shell variables used below are the tutorial's:

```bash
HOST=aiko                         # whatever you gave aiko_supervisor --name
USERNAME=$(id -un)
VENV=/home/$USERNAME/venvs/venv_3.14
```

## 1. Install the code

```bash
ssh $USERNAME@HOST
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/anjsimmo/aiko_turtle
$VENV/bin/pip install -r aiko_turtle/requirements.txt
```

Check it works before wiring it into the ProcessManager. The tests need
no broker; the world needs the shared services, which are already
running on this host:

```bash
cd ~/projects/aiko_turtle
$VENV/bin/python3 -m pytest -q tests                              # 13 passed
AIKO_MQTT_HOST=localhost $VENV/bin/python3 virtual_world.py run   # Ctrl-C once it is up
```

## 2. Configure: `.env`

`config.py` reads `.env` from the project directory in every process, so
the ProcessManager definition needs no variables. The broker host comes
from the unit (`AIKO_MQTT_HOST=localhost`), so `.env` only needs:

```bash
cd ~/projects/aiko_turtle
cp .env.example .env
```

```bash
TURTLE_USERNAME=web               # chat name the web server speaks under
OPENAI_API_KEY=sk-...             # optional; without it the agent needs the claude CLI
#TURTLE_API_TOKEN=TURTLES_ALL_THE_WAY_DOWN   # optional: then POST/DELETE need a bearer token
```

With `TURTLE_API_TOKEN` set, reads and the pages stay open but every
request that changes something (create, drive, delete, chat) needs
`Authorization: Bearer <token>`. By default the token is shown on the
page and in `/guide` and pre-filled, so for developers it is one header
to copy; set `TURTLE_API_TOKEN_PUBLIC=false` to hide it and hand it out
by other means. Leave the token unset for a fully open sandbox.

Everything else keeps its default. `TURTLE_WEB_HOST` stays
`127.0.0.1`: the web server is only ever reached through nginx. The
database is `turtle.db` in the project directory, fine for one instance
and in `.gitignore`, so `git pull` never touches it.

**One world per broker.** Every process finds the world by its name
(`TURTLE_WORLD`, default `turtle_world`) in the shared Registrar. If
somebody runs a second `virtual_world.py` against the same broker with
the same name, the two worlds fight over the robots. The production
instance owns the default name. For development against the same broker,
set a different `TURTLE_WORLD` (and `TURTLE_CHANNEL`) in your local
`.env`.

## 3. Start it at boot: the ProcessManager definition

Back up the definition file, then append the three entries from
`supervisor.json.example` with `cwd` set to the real path. The file is
one JSON list, so mind the comma after the previous entry. On the
reference instance it ends like this:

```json
[
  "true  aiko_registrar",
  {"enabled": true, "command": "aiko_hyperspace run", "cwd": "/home/anj/hyperspace"},
  {"enabled": true, "command": "aiko_chat run",       "cwd": "/home/anj/chat/_chat_server_"},
  "false aiko_recorder",

  {"enabled": true,
   "command": "python3 virtual_world.py run",
   "cwd":     "/home/anj/projects/aiko_turtle"},
  {"enabled": true,
   "command": "python3 web.py",
   "cwd":     "/home/anj/projects/aiko_turtle"},
  {"enabled": true,
   "command": "python3 agent.py run",
   "cwd":     "/home/anj/projects/aiko_turtle"}
]
```

```bash
cd /home/$USERNAME
cp ${HOST}_supervisor.json ${HOST}_supervisor.json.bak-$(date +%Y%m%d)
vi ${HOST}_supervisor.json
python3 -c "import json; print(len(json.load(open('${HOST}_supervisor.json'))), 'entries')"
```

**Dry run first**, as the tutorial does, so a bad path shows up in front
of you and not in the journal. This starts a second copy of every
process under a throwaway name (`--unsafe` only so that `exit` works):

```bash
PATH=$VENV/bin:$PATH PYTHONUNBUFFERED=1 AIKO_MQTT_HOST=localhost \
  aiko_process run --name dryrun --unsafe ${HOST}_supervisor.json
```

Expect a `Create:` line per enabled entry and no `FileNotFoundError` or
`not a directory`. A second world does start here for a moment, so keep
it short, then from another terminal:

```bash
PATH=$VENV/bin:$PATH AIKO_MQTT_HOST=localhost aiko_process exit -n dryrun -gt 0
```

Then restart the real service and watch it come up:

```bash
sudo systemctl restart $HOST
journalctl -u $HOST -f
curl -s localhost:8123/api/robots
```

Three things to know about the ProcessManager, all learnt the hard way:

- **The definition file is read only when the service starts.** Editing
  it does nothing until `sudo systemctl restart $HOST`.
- **`aiko_process create` and `destroy` are silently ignored.** The
  installed unit runs the ProcessManager *safe*, which accepts only
  `list` and `exit` over the bus, so there is no way to start or stop one
  process on its own. A restart of the unit restarts *everything* it
  manages, including the Registrar, HyperSpace and ChatServer. They are
  back within a few seconds and the robots reload from the database, so
  it is harmless, but it is a blip for anyone connected.
- **The unit is rendered, not written.** Do not edit
  `/etc/systemd/system/$HOST.service` by hand. To change its `PATH`,
  broker host or anything else, re-run `aiko_supervisor install` with
  the options from the tutorial.

Logs of all managed processes go to the journal: `journalctl -u $HOST`.

## 4. Put it behind nginx with HTTPS

The web server binds localhost and knows nothing about TLS. nginx
terminates HTTPS and proxies to it. The one non-default requirement is
that `/events` is a server-sent-events stream, so buffering must be off
and the read timeout long. This is the site as written; certbot then
edits the same file.

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo tee /etc/nginx/sites-available/turtle.aiko.hashtag.ai > /dev/null <<'NGINX'
# aiko_turtle: https://turtle.aiko.hashtag.ai -> uvicorn on 127.0.0.1:8123
# certbot --nginx adds the HTTPS server block and the redirect
server {
    listen 80;
    listen [::]:80;
    server_name turtle.aiko.hashtag.ai;

    access_log /var/log/nginx/turtle.access.log;
    error_log  /var/log/nginx/turtle.error.log;

    location / {
        proxy_pass http://127.0.0.1:8123;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;          # /events is server-sent events
        proxy_read_timeout 1h;
    }
}
NGINX
sudo ln -s /etc/nginx/sites-available/turtle.aiko.hashtag.ai /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d turtle.aiko.hashtag.ai
```

`certbot --nginx` rewrites the file in place: the `server` block above
becomes the `listen 443 ssl` one, with the certificate lines marked
`# managed by Certbot`, and a new port-80 block that redirects to HTTPS
is added. Then **turn on HTTP/2** on that block, which certbot does not
do: change `listen 443 ssl;` to `listen 443 ssl http2;` (and the `[::]`
line likewise) and `sudo systemctl reload nginx`. Every open tab holds
one connection for the `/events` stream, and over HTTP/1.1 a browser
allows only about six per host, so without HTTP/2 a sixth tab makes the
next page load wait. It also installs `certbot.timer`, which renews the certificate
automatically (`systemctl is-active certbot.timer`). Ports 80 and 443
must be open in the host's firewall; on GCP that is the `http-server`
and `https-server` network tags on the instance.

## 4b. The landing page at aiko.hashtag.ai

The bare host name gets a one-page static site that says what the server
is (a community broker, who hosts it, how to connect, the meetup) and
deliberately does not link to the applications on subdomains. The page
is `docs/aiko.hashtag.ai/index.html` in this repository, so it is
updated like everything else: `git pull`, then nginx serves it straight
from the clone.

```bash
sudo tee /etc/nginx/sites-available/aiko.hashtag.ai > /dev/null <<'NGINX'
# aiko.hashtag.ai: static landing page from the aiko_turtle clone
server {
    listen 80;
    listen [::]:80;
    server_name aiko.hashtag.ai;
    root /home/anj/projects/aiko_turtle/docs/aiko.hashtag.ai;
    index index.html;
    location / { try_files $uri $uri/ =404; }
}
NGINX
sudo ln -s /etc/nginx/sites-available/aiko.hashtag.ai /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default        # it was the catch-all until now
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d aiko.hashtag.ai
```

nginx runs as `www-data`, so the clone's directory path must be readable
by it (`chmod o+x /home/anj` if the home directory is `750`). The MQTT
broker on the same host is untouched: port 1883 is Mosquitto, ports 80
and 443 are nginx.

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
ssh $USERNAME@HOST
cd ~/projects/aiko_turtle && git pull
$VENV/bin/pip install -r requirements.txt     # only if requirements.txt changed
sudo systemctl restart $HOST                  # the only way to reload code (see step 3)
```

If `supervisor.json.example` gained an entry, mirror it in
`~/${HOST}_supervisor.json` before the restart. Robot definitions,
poses and history live in the database and survive restarts.

## 7. Checking that it is alive

```bash
systemctl is-active $HOST nginx mosquitto certbot.timer
journalctl -u $HOST --since "5 min ago"
PATH=$VENV/bin:$PATH AIKO_MQTT_HOST=localhost aiko_process list -n $HOST   # the managed processes
PATH=$VENV/bin:$PATH AIKO_MQTT_HOST=localhost aiko_registrar list          # turtle_world and the robots
curl -s https://turtle.aiko.hashtag.ai/api/robots
curl -N https://turtle.aiko.hashtag.ai/events        # should stream, Ctrl-C to stop
aiko_chat send robots "@@pilot which robots are there?"   # from any machine on the broker
```

## Troubleshooting

| Symptom | Cause, fix |
|---|---|
| Page loads, "world not connected", REST returns 503 | `virtual_world.py` is not running or has another `TURTLE_WORLD` name. `journalctl -u $HOST`, check `.env`. |
| Robots jump around or vanish and reappear | Two worlds with the same name on one broker. Find the stray `virtual_world.py` (usually a developer's laptop with default settings) and stop it. |
| Edited the definition file, nothing changed | It is read only at start: `sudo systemctl restart $HOST`. |
| `/events` stalls or disconnects after a minute | nginx buffering or timeout: the site must have `proxy_buffering off` and a long `proxy_read_timeout`. |
| `ModuleNotFoundError` in the journal | The unit's `PATH` does not start with `$VENV/bin`, so another `python3` runs. Re-run `aiko_supervisor install` with `--environment PATH=$VENV/bin:...`. |
| `@@pilot` does not answer | No `OPENAI_API_KEY` and no `claude` CLI on the unit's `PATH`, or the rate limit (`TURTLE_LLM_*`) is reached. |

## Adding another application on the same host

Repeat the pattern: clone it under `~/projects`, add its processes to
`~/${HOST}_supervisor.json`, give it its own localhost port, add an nginx
site for `NAME.aiko.hashtag.ai` and run `certbot --nginx -d` for it. The
shared broker, Registrar, HyperSpace and ChatServer are already there.
