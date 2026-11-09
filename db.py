# Persistent state of the world: robots (current pose) and events (history).
#
# One table of robots and one append-only table of events, through
# SQLAlchemy Core so the database is whatever TURTLE_DATABASE_URL says:
# SQLite by default, PostgreSQL or MySQL with no code change.

import time

from sqlalchemy import (
    Column, Float, Integer, MetaData, String, Table, create_engine, delete,
    inspect, insert, select, text, update,
)
from sqlalchemy.pool import StaticPool

metadata = MetaData()

robots = Table("robots", metadata,
    Column("name", String(64), primary_key=True),
    Column("kind", String(32), nullable=False, default="turtle"),
    Column("interface", String(32), nullable=False, default="robot"),
    Column("owner", String(64), nullable=False, default="anonymous"),
    Column("host", String(32), nullable=False, default="external"),
    Column("source", String(128), nullable=False, default=""),   # a replica: the real robot's topic path
    Column("x", Float, nullable=False, default=0.0),
    Column("y", Float, nullable=False, default=0.0),
    Column("heading", Float, nullable=False, default=0.0),
    Column("z", Float, nullable=False, default=0.0),      # altitude (drones)
    Column("pen", Integer, nullable=False, default=1),     # 1: leaves a trail
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
)

events = Table("events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("timestamp", Float, nullable=False),
    Column("robot", String(64), nullable=False, index=True),
    Column("username", String(64), nullable=False, default="anonymous"),
    Column("command", String(32), nullable=False),
    Column("argument", String(64), nullable=False, default=""),
    Column("x", Float, nullable=False),
    Column("y", Float, nullable=False),
    Column("heading", Float, nullable=False),
    Column("z", Float, nullable=False, default=0.0),
)

_ROBOT_COLUMNS = ("kind", "interface", "owner", "host", "source",
                  "x", "y", "heading", "z", "pen")
_ADDED = {        # columns added since the first release: name -> SQL type and default
    "z": "FLOAT NOT NULL DEFAULT 0.0",
    "interface": "VARCHAR(32) NOT NULL DEFAULT 'robot'",
    "source": "VARCHAR(128) NOT NULL DEFAULT ''",
    "pen": "INTEGER NOT NULL DEFAULT 1",
}


class Database:
    def __init__(self, url):
        kwargs = {}
        if url.startswith("sqlite"):
            # one connection shared across threads, so "sqlite://" (memory)
            # behaves and a file database needs no pool tuning
            kwargs = {"connect_args": {"check_same_thread": False},
                      "poolclass": StaticPool}
        self.engine = create_engine(url, **kwargs)
        metadata.create_all(self.engine)
        self._migrate()

    def _migrate(self):
        """Columns added since the first release, for databases that
        predate them (create_all never alters an existing table)"""
        inspector = inspect(self.engine)
        with self.engine.begin() as connection:
            for table in (robots, events):
                present = {column["name"]
                           for column in inspector.get_columns(table.name)}
                for column in table.columns:
                    if column.name not in present and column.name in _ADDED:
                        connection.execute(text(
                            f"ALTER TABLE {table.name} "
                            f"ADD COLUMN {column.name} {_ADDED[column.name]}"))

    # -- robots ------------------------------------------------------------

    def list_robots(self):
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(robots).order_by(robots.c.created_at)).mappings()
            return [dict(row) for row in rows]

    def get_robot(self, name):
        with self.engine.begin() as connection:
            row = connection.execute(
                select(robots).where(robots.c.name == name)).mappings().first()
            return dict(row) if row else None

    def save_robot(self, record):
        now = time.time()
        with self.engine.begin() as connection:
            exists = connection.execute(
                select(robots.c.name).where(robots.c.name == record["name"])
            ).first()
            values = {key: record[key] for key in _ROBOT_COLUMNS if key in record}
            values["updated_at"] = now
            if exists:
                connection.execute(update(robots)
                    .where(robots.c.name == record["name"]).values(**values))
            else:
                connection.execute(insert(robots).values(
                    name=record["name"], created_at=now, **values))

    def delete_robot(self, name):
        with self.engine.begin() as connection:
            result = connection.execute(
                delete(robots).where(robots.c.name == name))
            return result.rowcount > 0

    # -- events --------------------------------------------------------------

    def add_event(self, robot, username, command, argument, x, y, heading,
                  z=0.0):
        with self.engine.begin() as connection:
            connection.execute(insert(events).values(
                timestamp=time.time(), robot=robot, username=username,
                command=command, argument=str(argument)[:64],
                x=x, y=y, heading=heading, z=z))

    def list_events(self, robot, limit=100):
        with self.engine.begin() as connection:
            rows = connection.execute(select(events)
                .where(events.c.robot == robot)
                .order_by(events.c.id.desc()).limit(limit)).mappings()
            return [dict(row) for row in rows][::-1]     # oldest first
