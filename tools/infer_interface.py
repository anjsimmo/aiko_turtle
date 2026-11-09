#!/usr/bin/env python3
#
# infer_interface: draft robots/NAME.py for a robot whose interface is
# not yet written down, from whatever evidence you have, then review it.
#
# Evidence sources (all optional, combinable):
#   --watch TOPIC --seconds N   MQTT traffic captured from the broker
#   --registrar NAME            the Service in the Aiko Registrar and the
#                               traffic on its "in" and "out" topics
#   --code PATH                 a source file or directory that implements
#                               or drives the robot (any text, ~60 KB cap)
#   --notes TEXT                what a human knows ("turn is clockwise")
#
# An LLM (agent.call_llm: OPENAI_API_KEY, else the "claude" CLI) is shown
# the module contract, the template, a real example and the evidence, and
# writes the module.  It is a DRAFT: read it, then run pytest.
#
# Usage
# ~~~~~
#   source env.sh
#   # 1. watch a running robot for 30 seconds
#   ./tools/infer_interface.py my_bot --registrar my_bot --seconds 30 --write
#   # 2. read the code that drives it
#   ./tools/infer_interface.py my_bot --code ../my-bot/client.py --write
#   # 3. notes only, printed to stdout
#   ./tools/infer_interface.py my_bot --notes "move takes metres, turn is degrees clockwise"

import ast
import re
import sys
import threading
import time
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

CODE_CAP = 60_000
TRAFFIC_CAP = 20_000
CODE_SUFFIXES_SKIP = {".pyc", ".png", ".jpg", ".gif", ".bin", ".so", ".zip",
                      ".pdf", ".ico", ".woff", ".woff2", ".ttf"}


def capture_mqtt(topics, seconds):
    """Subscribe to topics for `seconds`; return a list of 'topic payload' lines"""
    import paho.mqtt.client as mqtt
    lines = []

    def on_connect(client, _userdata, _flags, *_rest):
        for topic in topics:
            client.subscribe(topic)

    def on_message(_client, _userdata, message):
        payload = message.payload.decode("utf-8", "replace")
        lines.append(f"{time.strftime('%H:%M:%S')} {message.topic} {payload}")

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(config.AIKO_MQTT_HOST, config.AIKO_MQTT_PORT)
    client.loop_start()
    time.sleep(seconds)
    client.loop_stop()
    client.disconnect()
    return lines


def lookup_registrar(name, wait=15):
    """Return [(topic_path, name, protocol, tags)] of Services matching name"""
    import aiko_services as aiko
    from aiko_services.main.share import services_cache_create_singleton
    threading.Thread(target=aiko.process.run, daemon=True).start()
    time.sleep(2)
    cache = services_cache_create_singleton(aiko.process)
    deadline = time.time() + wait
    while time.time() < deadline and cache.get_state() != "ready":
        time.sleep(0.5)
    found = []
    for details in cache.get_services():
        topic_path, svc_name, protocol = details[:3]
        tags = [str(tag) for tag in (details[5] or [])]
        if name in str(svc_name) or name in str(topic_path):
            found.append((topic_path, svc_name, protocol, tags))
    return found


def read_code(path):
    """Text of a file, or of the text files in a directory, capped"""
    path = Path(path)
    files = [path] if path.is_file() else sorted(
        p for p in path.rglob("*") if p.is_file()
        and p.suffix not in CODE_SUFFIXES_SKIP
        and not any(part.startswith(".") or part == "__pycache__"
                    for part in p.parts))
    out, used = [], 0
    for file in files:
        try:
            text = file.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        chunk = f"--- {file} ---\n{text}\n"
        if used + len(chunk) > CODE_CAP:
            chunk = chunk[:max(0, CODE_CAP - used)] + "\n[truncated]\n"
        out.append(chunk)
        used += len(chunk)
        if used >= CODE_CAP:
            break
    return "".join(out)


def contract_text():
    """The comment block at the top of robots/__init__.py, verbatim"""
    lines = []
    for line in (ROOT / "robots" / "__init__.py").read_text().splitlines():
        if not line.startswith("#"):
            break
        lines.append(line)
    return "\n".join(lines)


def build_prompt(name, evidence):
    template = (ROOT / "robots" / "_template.py").read_text()
    example = (ROOT / "robots" / "turtle_robot.py").read_text()
    return f"""You are writing a Python module robots/{name}.py for the aiko_turtle
sandbox, describing the interface of a robot called "{name}".

THE MODULE CONTRACT (verbatim from robots/__init__.py):
{contract_text()}

THE TEMPLATE (the shape to follow), robots/_template.py:
{template}

ONE REAL EXAMPLE, robots/turtle_robot.py:
{example}

EVIDENCE ABOUT THE ROBOT "{name}":
{evidence or "(none given)"}

INSTRUCTIONS
- NAME must be "{name}".
- Describe the interface AS IT IS today, exactly as the robot speaks it
  (its units, sign conventions, command words), not an idealised one.
- Every abstract method in Interface gets a one-line docstring.
- The Simulated class must implement every method of Interface.
- parse_command must reject unknown words with a helpful error naming
  the valid commands.
- Write observe() for dead reckoning if the evidence shows how the robot
  reports or receives motion.
- STATUS is base.STATUS_REAL only if the evidence came from a live robot;
  otherwise use a non-real status.
- Say in SOURCE where the evidence came from.
- Output ONLY the Python file, no commentary.
"""


def strip_fences(text):
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    return text.strip() + "\n"


@click.command()
@click.argument("name")
@click.option("--watch", "watch_topic", default=None,
              help="MQTT topic (wildcards ok) to capture, e.g. 'aiko/#'.")
@click.option("--seconds", default=20, show_default=True,
              help="How long to capture MQTT traffic.")
@click.option("--registrar", "registrar_name", default=None,
              help="Look up Services whose name or topic path contains this "
                   "in the Registrar and capture their in/out topics.")
@click.option("--code", "code_path", default=None,
              type=click.Path(exists=True),
              help="Source file or directory that implements or drives the "
                   "robot (capped at about 60 KB).")
@click.option("--notes", default=None,
              help="Free text from a human: units, sign conventions, quirks.")
@click.option("--write", is_flag=True,
              help="Write robots/NAME.py instead of printing to stdout.")
@click.option("--force", is_flag=True,
              help="With --write, overwrite an existing robots/NAME.py.")
def main(name, watch_topic, seconds, registrar_name, code_path, notes,
         write, force):
    """Draft robots/NAME.py for a robot with an unknown interface."""
    if not re.match(r"^[a-z0-9_]+$", name):
        raise click.UsageError("NAME must match [a-z0-9_]+")
    target = ROOT / "robots" / f"{name}.py"
    if write and target.exists() and not force:
        raise click.ClickException(f"{target} exists; use --force to overwrite")

    parts, topics = [], []
    if registrar_name:
        click.echo(f"Looking up '{registrar_name}' in the Registrar ...", err=True)
        found = lookup_registrar(registrar_name)
        if not found:
            click.echo("  no matching Service found", err=True)
        for topic_path, svc_name, protocol, tags in found:
            click.echo(f"  {topic_path} {svc_name} {protocol} {tags}", err=True)
            parts.append(f"Registrar Service: topic_path={topic_path} "
                         f"name={svc_name} protocol={protocol} tags={tags}")
            topics += [f"{topic_path}/in", f"{topic_path}/out"]
    if watch_topic:
        topics.append(watch_topic)
    if topics:
        click.echo(f"Capturing {topics} for {seconds} s ...", err=True)
        lines = capture_mqtt(topics, seconds)
        click.echo(f"  {len(lines)} messages", err=True)
        parts.append("MQTT traffic (time topic payload):\n"
                     + "\n".join(lines)[:TRAFFIC_CAP])
    if code_path:
        parts.append("Source code that implements or drives the robot:\n"
                     + read_code(code_path))
    if notes:
        parts.append(f"Notes from a human:\n{notes}")
    if not parts:
        click.echo("Warning: no evidence given; the draft will be generic.",
                   err=True)

    import agent
    log = lambda *args, **kwargs: click.echo(" ".join(map(str, args)), err=True)
    reply = agent.call_llm(build_prompt(name, "\n\n".join(parts)), log)
    if not reply:
        raise click.ClickException("the LLM returned nothing")
    source = strip_fences(reply)

    try:
        ast.parse(source)
    except SyntaxError as error:
        click.echo(f"The draft does not parse ({error}); NOT written.  "
                   "Printing it instead.", err=True)
        click.echo(source)
        sys.exit(1)

    if write:
        target.write_text(source)
        click.echo(f"Wrote {target}.  Review it, then run: "
                   "python3 -m pytest -q tests", err=True)
    else:
        click.echo(source)
        click.echo(f"Draft above (not written; use --write).  Save it as "
                   f"robots/{name}.py, review it, then run: "
                   "python3 -m pytest -q tests", err=True)


if __name__ == "__main__":
    main()
