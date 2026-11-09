# Settings for aiko_turtle, from the environment and an optional ".env" file.
#
# Every value has a default, a value already in the environment wins, and
# ".env" (not committed; see ".env.example") fills in the rest.  Nothing
# here is a path to anyone's home directory.

import os
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).parent.resolve()
load_dotenv(HERE / ".env")      # does not override variables already set


def env(name, default):
    return os.environ.get(name, default)


# Aiko shared services (the defaults are the community instance)
AIKO_MQTT_HOST = env("AIKO_MQTT_HOST", "aiko.hashtag.ai")
AIKO_MQTT_PORT = int(env("AIKO_MQTT_PORT", "1883"))
AIKO_NAMESPACE = env("AIKO_NAMESPACE", "aiko")

# The world: one VirtualWorld Service holds every robot's pose
WORLD_NAME = env("TURTLE_WORLD", "turtle_world")

# "sqlite:///turtle.db" is relative to the working directory, like the
# HyperSpace and ChatServer storage.  Any SQLAlchemy URL works
DATABASE_URL = env("TURTLE_DATABASE_URL", "sqlite:///turtle.db")

# The page's name (the subdomain used to be turtle.; sandbox. is the plan)
TITLE = env("TURTLE_TITLE", "aiko_turtle")

# Chat
CHANNEL = env("TURTLE_CHANNEL", "robots")
AGENT_BOTNAME = env("TURTLE_AGENT", "@@pilot")

# Web server (FastAPI): bind to localhost and put nginx in front for HTTPS
WEB_HOST = env("TURTLE_WEB_HOST", "127.0.0.1")
WEB_PORT = int(env("TURTLE_WEB_PORT", "8123"))
WEB_USERNAME = env("TURTLE_USERNAME", os.environ.get("USER", "anonymous"))
# Empty = open.  Set it and every POST/DELETE on the REST API needs
# "Authorization: Bearer <token>" (the page asks for it once)
API_TOKEN = env("TURTLE_API_TOKEN", "")
# Show the token on the page and in /guide, pre-filled, so developers just
# use it (a community sandbox: the token keeps bots out, not people).
# Set to "false" to make visitors ask for it instead
API_TOKEN_PUBLIC = env("TURTLE_API_TOKEN_PUBLIC", "true").lower() in ("1", "true", "yes")

# LLM ChatAgent
OPENAI_API_KEY = env("OPENAI_API_KEY", "")
OPENAI_MODEL = env("OPENAI_MODEL", "gpt-4o-mini")
LLM_RATE_PER_MINUTE = int(env("TURTLE_LLM_RATE_PER_MINUTE", "10"))
LLM_RATE_PER_USER_PER_MINUTE = int(env("TURTLE_LLM_USER_RATE_PER_MINUTE", "4"))
LLM_QUEUE_LIMIT = int(env("TURTLE_LLM_QUEUE_LIMIT", "5"))
