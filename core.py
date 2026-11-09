# Pure logic shared by the robot, the LLM agent and the tests: LLM
# output parsing, a token-bucket rate limiter and the robot name rule.
# Chat command parsing lives with each interface in robots/.  No Aiko imports, so it is testable without a broker.

import re
import threading
import time

ROBOT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def valid_robot_name(name):
    """Names go into MQTT topics, S-expressions, tags and @@mentions"""
    return bool(ROBOT_NAME_PATTERN.match(name or ""))


_ACTION_PATTERN = re.compile(r"^\((say|command)\s+(.*)\)\s*$")


def parse_actions(output):
    """LLM output -> [("say", text) | ("command", "@@bot move 100")]"""
    actions = []
    for line in (output or "").splitlines():
        match = _ACTION_PATTERN.match(line.strip())
        if match:
            actions.append((match.group(1), match.group(2).strip()))
    return actions


class RateLimiter:
    """Token buckets: one global, one per key (e.g. per chat user).
    allow(key) is True when both buckets have a token, and spends them"""

    def __init__(self, per_minute, per_key_per_minute, clock=time.monotonic):
        self.rate = per_minute / 60.0
        self.key_rate = per_key_per_minute / 60.0
        self.capacity = per_minute
        self.key_capacity = per_key_per_minute
        self.clock = clock
        self.lock = threading.Lock()
        self.buckets = {}       # key -> [tokens, last_time]; None = global

    def _tokens(self, key, rate, capacity, now):
        tokens, last = self.buckets.get(key, (capacity, now))
        tokens = min(capacity, tokens + (now - last) * rate)
        return tokens

    def allow(self, key="anonymous"):
        with self.lock:
            now = self.clock()
            total = self._tokens(None, self.rate, self.capacity, now)
            mine = self._tokens(key, self.key_rate, self.key_capacity, now)
            if total < 1 or mine < 1:
                self.buckets[None] = (total, now)
                self.buckets[key] = (mine, now)
                return False
            self.buckets[None] = (total - 1, now)
            self.buckets[key] = (mine - 1, now)
            return True
