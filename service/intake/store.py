"""SQLite storage: the ledger (approved invoices), the review queue, rejected invoices and an append-only audit log."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  status TEXT NOT NULL,            -- approved | review | rejected
  vendor_gstin TEXT, invoice_number TEXT, vendor_name TEXT, invoice_date TEXT, total REAL,
  file_name TEXT, file_sha256 TEXT, extraction TEXT, decision TEXT,
  created_at TEXT NOT NULL, decided_by TEXT, decided_at TEXT, note TEXT
);
CREATE INDEX IF NOT EXISTS ix_vendor_no ON invoices(vendor_gstin, invoice_number);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, invoice_id INTEGER, event TEXT NOT NULL, detail TEXT
);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.db.executescript(SCHEMA)

    def audit(self, event: str, invoice_id: int | None = None, **detail: Any) -> None:
        with self.lock:
            self.db.execute("INSERT INTO audit(at, invoice_id, event, detail) VALUES (?,?,?,?)",
                            (now(), invoice_id, event, json.dumps(detail, default=str)))  # fmt: skip
            self.db.commit()

    def seen(self) -> set[tuple[str, str]]:
        """(vendor GSTIN, invoice number) of everything received and not rejected."""
        rows = self.db.execute(
            "SELECT vendor_gstin, invoice_number FROM invoices WHERE status != 'rejected'"
        ).fetchall()
        return {((r[0] or "").upper(), (r[1] or "").strip().upper()) for r in rows if r[0] and r[1]}

    def file_seen(self, sha256: str) -> int | None:
        r = self.db.execute(
            "SELECT id FROM invoices WHERE file_sha256 = ? AND status != 'rejected'", (sha256,)
        ).fetchone()
        return r[0] if r else None

    def add(self, status: str, inv: dict, decision: dict, file_name: str = "", sha256: str = "") -> int:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO invoices(status, vendor_gstin, invoice_number, vendor_name, invoice_date, total, file_name,"
                " file_sha256, extraction, decision, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (status, inv.get("vendor_gstin"), inv.get("invoice_number"), inv.get("vendor_name"),
                 inv.get("invoice_date"), inv.get("total"), file_name, sha256, json.dumps(inv), json.dumps(decision), now()),
            )  # fmt: skip
            self.db.commit()
            return int(cur.lastrowid)

    def decide(self, invoice_id: int, approve: bool, by: str, note: str = "") -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT status FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            if not row or row[0] != "review":
                return None
            status = "approved" if approve else "rejected"
            self.db.execute("UPDATE invoices SET status=?, decided_by=?, decided_at=?, note=? WHERE id=?",
                            (status, by, now(), note, invoice_id))  # fmt: skip
            self.db.commit()
        self.audit(f"reviewer_{status}", invoice_id, by=by, note=note)
        return self.get(invoice_id)

    def get(self, invoice_id: int) -> dict | None:
        r = self.db.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        return self._row(r) if r else None

    def list(self, status: str | None = None, limit: int = 200) -> list[dict]:
        q = "SELECT * FROM invoices" + (" WHERE status = ?" if status else "") + " ORDER BY id DESC LIMIT ?"
        return [self._row(r) for r in self.db.execute(q, ((status, limit) if status else (limit,))).fetchall()]

    def audit_log(self, limit: int = 500) -> list[dict]:
        rows = self.db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(r), "detail": json.loads(r["detail"] or "{}")} for r in rows]

    def reset(self) -> None:
        with self.lock:
            self.db.executescript("DELETE FROM invoices; DELETE FROM audit;")
            self.db.commit()

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        d = dict(r)
        for k in ("extraction", "decision"):
            d[k] = json.loads(d[k] or "{}")
        return d
