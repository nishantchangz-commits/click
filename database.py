"""
Database layer: people + the documents attached to each person.

Design: SQLite stores METADATA (who, what type of document, when,
notes). The actual file bytes live on disk under storage/, organized
by person, so the database stays small and fast even with large PDFs
or images.
"""

from __future__ import annotations

import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path("people_docs.db")
STORAGE_DIR = Path("storage")

# The set of document types this app understands. "other" is a catch-all.
DOCUMENT_TYPES = ("resume", "photo", "id_proof", "certificate", "other")


@dataclass
class Person:
    name: str
    person_id: Optional[int] = None
    notes: str = ""
    created_at: Optional[str] = None


@dataclass
class Document:
    person_id: int
    doc_type: str            # one of DOCUMENT_TYPES
    original_filename: str
    stored_path: str         # path on disk, relative to STORAGE_DIR
    doc_id: Optional[int] = None
    notes: str = ""
    uploaded_at: Optional[str] = None


# ============================================================
# CONNECTION + SCHEMA
# ============================================================

def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS people (
                person_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER NOT NULL,
                doc_type TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                notes TEXT DEFAULT '',
                uploaded_at TEXT NOT NULL,
                FOREIGN KEY (person_id) REFERENCES people(person_id) ON DELETE CASCADE
            )
        """)


# ============================================================
# PEOPLE
# ============================================================

def add_person(name: str, notes: str = "", db_path: Path = DB_PATH) -> Person:
    created_at = datetime.now().isoformat(timespec="seconds")
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO people (name, notes, created_at) VALUES (?, ?, ?)",
            (name, notes, created_at),
        )
        return Person(person_id=cursor.lastrowid, name=name, notes=notes, created_at=created_at)


def get_all_people(db_path: Path = DB_PATH) -> list[Person]:
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM people ORDER BY name").fetchall()
    return [Person(person_id=r["person_id"], name=r["name"], notes=r["notes"], created_at=r["created_at"])
            for r in rows]


def get_person(person_id: int, db_path: Path = DB_PATH) -> Optional[Person]:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM people WHERE person_id = ?", (person_id,)).fetchone()
    if row is None:
        return None
    return Person(person_id=row["person_id"], name=row["name"], notes=row["notes"], created_at=row["created_at"])


def update_person(person_id: int, name: str, notes: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute("UPDATE people SET name = ?, notes = ? WHERE person_id = ?", (name, notes, person_id))


def delete_person(person_id: int, db_path: Path = DB_PATH) -> None:
    # Remove the person's whole folder of files, then their DB rows.
    person_dir = STORAGE_DIR / str(person_id)
    if person_dir.exists():
        shutil.rmtree(person_dir)
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM documents WHERE person_id = ?", (person_id,))
        conn.execute("DELETE FROM people WHERE person_id = ?", (person_id,))


# ============================================================
# DOCUMENTS
# ============================================================

def _person_storage_dir(person_id: int) -> Path:
    d = STORAGE_DIR / str(person_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_document(person_id: int, doc_type: str, original_filename: str,
                   file_bytes: bytes, notes: str = "", db_path: Path = DB_PATH) -> Document:
    if doc_type not in DOCUMENT_TYPES:
        raise ValueError(f"doc_type must be one of {DOCUMENT_TYPES}, got '{doc_type}'")

    # Store under a UUID-based filename on disk so two people uploading
    # "resume.pdf" never collide, while keeping the original name for display.
    ext = Path(original_filename).suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    person_dir = _person_storage_dir(person_id)
    full_path = person_dir / stored_name
    full_path.write_bytes(file_bytes)

    uploaded_at = datetime.now().isoformat(timespec="seconds")
    stored_path = str(Path(str(person_id)) / stored_name)  # relative to STORAGE_DIR

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO documents
               (person_id, doc_type, original_filename, stored_path, notes, uploaded_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (person_id, doc_type, original_filename, stored_path, notes, uploaded_at),
        )
        return Document(doc_id=cursor.lastrowid, person_id=person_id, doc_type=doc_type,
                         original_filename=original_filename, stored_path=stored_path,
                         notes=notes, uploaded_at=uploaded_at)


def get_documents_for_person(person_id: int, db_path: Path = DB_PATH) -> list[Document]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE person_id = ? ORDER BY doc_type, uploaded_at DESC",
            (person_id,),
        ).fetchall()
    return [
        Document(doc_id=r["doc_id"], person_id=r["person_id"], doc_type=r["doc_type"],
                  original_filename=r["original_filename"], stored_path=r["stored_path"],
                  notes=r["notes"], uploaded_at=r["uploaded_at"])
        for r in rows
    ]


def get_document_bytes(document: Document) -> bytes:
    return (STORAGE_DIR / document.stored_path).read_bytes()


def replace_document_file(doc_id: int, new_original_filename: str, new_file_bytes: bytes,
                           db_path: Path = DB_PATH) -> None:
    """Swap out the underlying file for an existing document record — e.g.
    uploading an updated resume without losing the doc's history/notes."""
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        if row is None:
            raise ValueError(f"No document with id {doc_id}")

        old_path = STORAGE_DIR / row["stored_path"]
        ext = Path(new_original_filename).suffix
        new_stored_name = f"{uuid.uuid4().hex}{ext}"
        new_stored_path = str(Path(str(row["person_id"])) / new_stored_name)
        (STORAGE_DIR / new_stored_path).write_bytes(new_file_bytes)

        conn.execute(
            """UPDATE documents SET original_filename = ?, stored_path = ?, uploaded_at = ?
               WHERE doc_id = ?""",
            (new_original_filename, new_stored_path, datetime.now().isoformat(timespec="seconds"), doc_id),
        )

        if old_path.exists():
            old_path.unlink()


def update_document_metadata(doc_id: int, doc_type: str, notes: str, db_path: Path = DB_PATH) -> None:
    if doc_type not in DOCUMENT_TYPES:
        raise ValueError(f"doc_type must be one of {DOCUMENT_TYPES}, got '{doc_type}'")
    with get_connection(db_path) as conn:
        conn.execute("UPDATE documents SET doc_type = ?, notes = ? WHERE doc_id = ?",
                     (doc_type, notes, doc_id))


def delete_document(doc_id: int, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT stored_path FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        if row is not None:
            path = STORAGE_DIR / row["stored_path"]
            if path.exists():
                path.unlink()
        conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at '{DB_PATH}', file storage at '{STORAGE_DIR}'.")
