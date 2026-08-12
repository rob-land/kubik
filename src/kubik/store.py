"""Solve history, in a small SQLite file under the user's data directory."""

from __future__ import annotations

import sqlite3
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

from gi.repository import GLib

SCHEMA = """
CREATE TABLE IF NOT EXISTS solves (
    id        INTEGER PRIMARY KEY,
    stamp     REAL    NOT NULL,
    millis    INTEGER NOT NULL,
    scramble  TEXT    NOT NULL DEFAULT '',
    penalty   TEXT    NOT NULL DEFAULT '',
    moves     INTEGER NOT NULL DEFAULT 0,
    cube_type TEXT    NOT NULL DEFAULT '3x3'
);
CREATE TABLE IF NOT EXISTS progress (
    lesson    TEXT PRIMARY KEY,
    completed REAL NOT NULL
);
"""


@dataclass
class Solve:
    id: int
    stamp: float
    millis: int
    scramble: str
    penalty: str
    moves: int
    cube_type: str

    @property
    def effective(self) -> float | None:
        """Time in seconds with the WCA penalty applied; None for a DNF."""
        if self.penalty == "dnf":
            return None
        extra = 2000 if self.penalty == "+2" else 0
        return (self.millis + extra) / 1000


def format_time(seconds: float | None) -> str:
    if seconds is None:
        return "DNF"
    if seconds >= 60:
        return f"{int(seconds // 60)}:{seconds % 60:06.3f}"
    return f"{seconds:.3f}"


class Store:
    def __init__(self, path: Path | None = None):
        if path is None:
            base = Path(GLib.get_user_data_dir()) / "kubik"
            base.mkdir(parents=True, exist_ok=True)
            path = base / "solves.db"
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self):
        columns = {row[1] for row in
                   self.db.execute("PRAGMA table_info(solves)")}
        if "cube_type" not in columns:
            self.db.execute("ALTER TABLE solves ADD COLUMN cube_type "
                            "TEXT NOT NULL DEFAULT '3x3'")

    # -- solves ------------------------------------------------------------

    def add_solve(self, millis: int, scramble: str, moves: int = 0,
                  cube_type: str = "3x3") -> int:
        cur = self.db.execute(
            "INSERT INTO solves (stamp, millis, scramble, moves, cube_type) "
            "VALUES (?, ?, ?, ?, ?)",
            (time.time(), millis, scramble, moves, cube_type))
        self.db.commit()
        return cur.lastrowid

    def set_penalty(self, solve_id: int, penalty: str):
        self.db.execute("UPDATE solves SET penalty = ? WHERE id = ?",
                        (penalty, solve_id))
        self.db.commit()

    def delete_solve(self, solve_id: int):
        self.db.execute("DELETE FROM solves WHERE id = ?", (solve_id,))
        self.db.commit()

    def recent(self, limit: int = 200,
               cube_type: str = "3x3") -> list[Solve]:
        rows = self.db.execute(
            "SELECT id, stamp, millis, scramble, penalty, moves, cube_type "
            "FROM solves WHERE cube_type = ? ORDER BY id DESC LIMIT ?",
            (cube_type, limit)).fetchall()
        return [Solve(*row) for row in rows]

    # -- statistics --------------------------------------------------------

    def average_of(self, n: int, cube_type: str = "3x3") -> float | None:
        """WCA average: drop the best and worst, mean the rest."""
        solves = self.recent(n, cube_type)
        if len(solves) < n:
            return None
        times = [s.effective for s in solves]
        if sum(1 for t in times if t is None) > 1:
            return None
        worst = max((t for t in times if t is not None), default=None)
        if worst is None:
            return None
        values = [t if t is not None else worst for t in times]
        values.remove(min(values))
        values.remove(max(values))
        return statistics.mean(values)

    def best(self, cube_type: str = "3x3") -> float | None:
        times = [s.effective for s in self.recent(10_000, cube_type)
                 if s.effective is not None]
        return min(times) if times else None

    def count(self, cube_type: str = "3x3") -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM solves WHERE cube_type = ?",
            (cube_type,)).fetchone()[0]

    # -- course progress ---------------------------------------------------

    def mark_done(self, lesson: str):
        self.db.execute(
            "INSERT OR REPLACE INTO progress (lesson, completed) VALUES (?, ?)",
            (lesson, time.time()))
        self.db.commit()

    def clear_done(self, lesson: str):
        self.db.execute("DELETE FROM progress WHERE lesson = ?", (lesson,))
        self.db.commit()

    def completed(self) -> set[str]:
        return {row[0] for row in
                self.db.execute("SELECT lesson FROM progress")}
