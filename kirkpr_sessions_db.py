"""SQLite shramba sej KIR/KPR (vzorec Projest)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping

import kirkpr_minimax_core as core

DB_NAME = "kirkpr_sessions.sqlite3"
SESSIONS_LIMIT = 50

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    company_key TEXT NOT NULL DEFAULT '',
    company_label TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL DEFAULT '',
    working_copy TEXT NOT NULL DEFAULT '',
    period_from TEXT NOT NULL DEFAULT '',
    period_to TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    opened_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sessions_company ON sessions(company_key);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
"""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def default_db_path(base_dir: Path | None = None) -> Path:
    root = Path(base_dir) if base_dir else Path(core.config_path()).parent
    return root / DB_NAME


class SessionsDb:
    """CRUD za shranjene seje (firma + obdobje + vir / delovna kopija)."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self.session() as conn:
            conn.executescript(SCHEMA)

    def _row_to_dict(self, row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
        data = dict(row)
        sid = int(data.get("id") or 0)
        title = str(data.get("title") or "").strip()
        company_label = str(data.get("company_label") or data.get("company_key") or "—").strip()
        period_from = str(data.get("period_from") or "")[:10]
        period_to = str(data.get("period_to") or "")[:10]
        source = str(data.get("source_path") or data.get("source") or "")
        working = str(data.get("working_copy") or "")
        entry = {
            "id": sid,
            "title": title,
            "company_key": str(data.get("company_key") or ""),
            "company_label": company_label,
            "source": source,
            "source_path": source,
            "working_copy": working,
            "period_from": period_from,
            "period_to": period_to,
            "notes": str(data.get("notes") or ""),
            "opened_at": str(data.get("opened_at") or ""),
            "updated_at": str(data.get("updated_at") or ""),
        }
        if title:
            entry["label"] = title
        else:
            entry["label"] = core.format_recent_session_label(
                {
                    "company_label": company_label,
                    "period_from": period_from,
                    "period_to": period_to,
                    "working_copy": working,
                    "source": source,
                }
            )
        return entry

    def list_sessions(self, *, limit: int = SESSIONS_LIMIT) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC, id DESC LIMIT ?",
                (max(1, int(limit or SESSIONS_LIMIT)),),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get(self, session_id: int) -> dict[str, Any] | None:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (int(session_id),)).fetchone()
        return self._row_to_dict(row) if row else None

    def upsert(
        self,
        *,
        company_key: str,
        company_label: str,
        source: str | Path,
        working_copy: str | Path | None = None,
        period_from: str = "",
        period_to: str = "",
        title: str = "",
        notes: str = "",
        session_id: int | None = None,
    ) -> dict[str, Any]:
        key = str(company_key or "").strip()
        source_s = str(source or "").strip()
        working_s = str(working_copy or "").strip()
        if not key or (not source_s and not working_s):
            raise ValueError("Za shranjevanje seje manjka podjetje ali datoteka.")
        now = _now()
        p_from = str(period_from or "")[:10]
        p_to = str(period_to or "")[:10]
        title_s = str(title or "").strip()
        notes_s = str(notes or "").strip()
        with self.session() as conn:
            existing = None
            if session_id:
                existing = conn.execute(
                    "SELECT * FROM sessions WHERE id = ?", (int(session_id),)
                ).fetchone()
            if existing is None:
                # Ista firma + isti vir/kopija → posodobi.
                existing = conn.execute(
                    """
                    SELECT * FROM sessions
                    WHERE company_key = ?
                      AND (
                        (? <> '' AND source_path = ?)
                        OR (? <> '' AND working_copy = ?)
                      )
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (key, source_s, source_s, working_s, working_s),
                ).fetchone()
            if existing:
                sid = int(existing["id"])
                keep_title = title_s or str(existing["title"] or "")
                keep_notes = notes_s if notes_s or title_s else str(existing["notes"] or "")
                conn.execute(
                    """
                    UPDATE sessions SET
                        title = ?, company_key = ?, company_label = ?,
                        source_path = ?, working_copy = ?,
                        period_from = ?, period_to = ?, notes = ?,
                        opened_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        keep_title,
                        key,
                        str(company_label or key).strip(),
                        source_s,
                        working_s,
                        p_from,
                        p_to,
                        keep_notes,
                        now,
                        now,
                        sid,
                    ),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO sessions (
                        title, company_key, company_label, source_path, working_copy,
                        period_from, period_to, notes, opened_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        title_s,
                        key,
                        str(company_label or key).strip(),
                        source_s,
                        working_s,
                        p_from,
                        p_to,
                        notes_s,
                        now,
                        now,
                    ),
                )
                sid = int(cur.lastrowid)
            # Obreži starejše seje.
            conn.execute(
                """
                DELETE FROM sessions WHERE id NOT IN (
                    SELECT id FROM sessions ORDER BY updated_at DESC, id DESC LIMIT ?
                )
                """,
                (SESSIONS_LIMIT,),
            )
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        return self._row_to_dict(row)

    def update_meta(self, session_id: int, *, title: str = "", notes: str = "") -> dict[str, Any] | None:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (int(session_id),)).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE sessions SET title = ?, notes = ?, updated_at = ? WHERE id = ?",
                (str(title or "").strip(), str(notes or "").strip(), _now(), int(session_id)),
            )
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (int(session_id),)).fetchone()
        return self._row_to_dict(row) if row else None

    def delete(self, session_id: int) -> bool:
        with self.session() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE id = ?", (int(session_id),))
            return cur.rowcount > 0

    def delete_virtual_for_company_period(
        self,
        company_key: str,
        period_from: str,
        period_to: str,
        *,
        keep_id: int | None = None,
    ) -> int:
        """Izbriši Minimax/virtualne seje iste firme in obdobja (nadomestitev prenosa)."""
        key = str(company_key or "").strip()
        p_from = str(period_from or "")[:10]
        p_to = str(period_to or "")[:10]
        if not key or not p_from or not p_to:
            return 0
        with self.session() as conn:
            params: list[Any] = [key, p_from, p_to]
            keep_sql = ""
            if keep_id:
                keep_sql = " AND id <> ?"
                params.append(int(keep_id))
            cur = conn.execute(
                f"""
                DELETE FROM sessions
                WHERE company_key = ?
                  AND period_from = ?
                  AND period_to = ?
                  AND (
                    lower(source_path) LIKE '%.virtual'
                    OR lower(source_path) LIKE '%minimax%'
                    OR lower(title) LIKE '%minimax%'
                  )
                  {keep_sql}
                """,
                tuple(params),
            )
            return int(cur.rowcount or 0)

    def find_virtual_for_company_period(
        self,
        company_key: str,
        period_from: str,
        period_to: str,
    ) -> dict[str, Any] | None:
        """Najdi obstoječo Minimax sejo za firmo + obdobje (za upsert namesto duplikata)."""
        key = str(company_key or "").strip()
        p_from = str(period_from or "")[:10]
        p_to = str(period_to or "")[:10]
        if not key or not p_from or not p_to:
            return None
        with self.session() as conn:
            row = conn.execute(
                """
                SELECT * FROM sessions
                WHERE company_key = ?
                  AND period_from = ?
                  AND period_to = ?
                  AND (
                    lower(source_path) LIKE '%.virtual'
                    OR lower(source_path) LIKE '%minimax%'
                    OR lower(title) LIKE '%minimax%'
                  )
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (key, p_from, p_to),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def migrate_from_config(self, config: Mapping[str, Any]) -> int:
        """Enkratni uvoz iz config recent_sessions (JSON)."""
        rows = [r for r in (config.get("recent_sessions") or []) if isinstance(r, dict)]
        if not rows:
            return 0
        existing = self.list_sessions()
        if existing:
            return 0
        count = 0
        for row in reversed(rows):  # starejše najprej, da novejše ostanejo zgoraj
            try:
                self.upsert(
                    company_key=str(row.get("company_key") or ""),
                    company_label=str(row.get("company_label") or ""),
                    source=str(row.get("source") or ""),
                    working_copy=str(row.get("working_copy") or "") or None,
                    period_from=str(row.get("period_from") or ""),
                    period_to=str(row.get("period_to") or ""),
                    title=str(row.get("title") or row.get("label") or ""),
                    notes=str(row.get("notes") or ""),
                )
                count += 1
            except ValueError:
                continue
        return count

    def open_path(self, entry: Mapping[str, Any]) -> Path | None:
        return core.recent_session_open_path(entry)


__all__ = ["DB_NAME", "SESSIONS_LIMIT", "SessionsDb", "default_db_path"]
