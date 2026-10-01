"""Persistenter Übersetzungs-Cache (SQLite).

Bei langen Dokumenten kann ein Lauf abbrechen (Netzwerk, Rate-Limit). Mit dem
Cache wird beim erneuten Start nur der noch fehlende Teil übersetzt; zudem
werden wiederkehrende Texte (Kopfzeilen, Fußzeilen) nur einmal übersetzt.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading


class TranslationCache:
    def __init__(self, path: str | None):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path or ":memory:", check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS t (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self._db.commit()

    @staticmethod
    def _key(namespace: str, text: str) -> str:
        return hashlib.sha256(f"{namespace}\x00{text}".encode()).hexdigest()

    def get(self, namespace: str, text: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM t WHERE key=?", (self._key(namespace, text),)).fetchone()
        return row[0] if row else None

    def put(self, namespace: str, text: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO t (key, value) VALUES (?, ?)", (self._key(namespace, text), value)
            )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()
