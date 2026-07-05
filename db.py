"""
db.py — SQLite: схема + доступ к данным.

Всё партиционировано по предмету (subject_code): у каждого предмета своя
колода карточек, а прогресс/состояние повторения хранятся на пару
(пользователь, карточка), так что статистика и SRS считаются раздельно.
"""
import json
import os
import sqlite3
from datetime import date
from pathlib import Path

from srs import CardState

SCHEMA = """
CREATE TABLE IF NOT EXISTS subjects (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_code TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    reference TEXT NOT NULL,
    UNIQUE(subject_code, number)
);
CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    name TEXT,
    active_subject TEXT,
    reminder_hour INTEGER,
    exam_date TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS card_state (
    tg_id INTEGER NOT NULL,
    card_id INTEGER NOT NULL,
    ease REAL NOT NULL DEFAULT 2.5,
    interval INTEGER NOT NULL DEFAULT 0,
    reps INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    due_date TEXT,
    last_rating TEXT,
    PRIMARY KEY (tg_id, card_id)
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL,
    card_id INTEGER NOT NULL,
    mode TEXT NOT NULL,
    rating TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS explanations (
    card_id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def import_subject(conn: sqlite3.Connection, json_path: str) -> int:
    """Загрузить предмет из JSON (idempotent — можно перезаливать)."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    code, name = data["subject_code"], data["subject_name"]
    conn.execute(
        "INSERT INTO subjects(code, name) VALUES(?, ?) "
        "ON CONFLICT(code) DO UPDATE SET name=excluded.name",
        (code, name),
    )
    n = 0
    for t in data["tickets"]:
        conn.execute(
            "INSERT INTO cards(subject_code, number, title, reference) "
            "VALUES(?,?,?,?) "
            "ON CONFLICT(subject_code, number) DO UPDATE SET "
            "title=excluded.title, reference=excluded.reference",
            (code, t["number"], t["title"], t["reference"]),
        )
        n += 1
    conn.commit()
    return n


def load_all_data(conn: sqlite3.Connection, data_dir: str) -> None:
    """Загрузить все *.json из папки data (кроме служебных с префиксом _)."""
    init_db(conn)
    for fn in sorted(os.listdir(data_dir)):
        if fn.endswith(".json") and not fn.startswith("_"):
            import_subject(conn, os.path.join(data_dir, fn))


# ---------- пользователи ----------

def ensure_user(conn, tg_id: int, name: str) -> None:
    conn.execute(
        "INSERT INTO users(tg_id, name, created_at) VALUES(?,?,?) "
        "ON CONFLICT(tg_id) DO UPDATE SET name=excluded.name",
        (tg_id, name, date.today().isoformat()),
    )
    conn.commit()


def get_user(conn, tg_id: int):
    return conn.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()


def set_active_subject(conn, tg_id: int, code: str) -> None:
    conn.execute("UPDATE users SET active_subject=? WHERE tg_id=?", (code, tg_id))
    conn.commit()


def set_reminder_hour(conn, tg_id: int, hour) -> None:
    conn.execute("UPDATE users SET reminder_hour=? WHERE tg_id=?", (hour, tg_id))
    conn.commit()


def set_exam_date(conn, tg_id: int, iso_date) -> None:
    conn.execute("UPDATE users SET exam_date=? WHERE tg_id=?", (iso_date, tg_id))
    conn.commit()


def list_subjects(conn):
    return conn.execute("SELECT * FROM subjects ORDER BY name").fetchall()


# ---------- карточки и выбор следующей ----------

def get_card(conn, card_id: int):
    return conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()


def get_state(conn, tg_id: int, card_id: int) -> CardState:
    row = conn.execute(
        "SELECT * FROM card_state WHERE tg_id=? AND card_id=?", (tg_id, card_id)
    ).fetchone()
    if not row:
        return CardState()
    return CardState(
        ease=row["ease"], interval=row["interval"], reps=row["reps"],
        lapses=row["lapses"], due_date=row["due_date"] or "",
        last_rating=row["last_rating"] or "",
    )


def save_state(conn, tg_id: int, card_id: int, st: CardState) -> None:
    conn.execute(
        "INSERT INTO card_state(tg_id, card_id, ease, interval, reps, lapses, "
        "due_date, last_rating) VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(tg_id, card_id) DO UPDATE SET ease=excluded.ease, "
        "interval=excluded.interval, reps=excluded.reps, lapses=excluded.lapses, "
        "due_date=excluded.due_date, last_rating=excluded.last_rating",
        (tg_id, card_id, st.ease, st.interval, st.reps, st.lapses,
         st.due_date, st.last_rating),
    )
    conn.commit()


def log_review(conn, tg_id: int, card_id: int, mode: str, rating: str) -> None:
    conn.execute(
        "INSERT INTO reviews(tg_id, card_id, mode, rating, created_at) "
        "VALUES(?,?,?,?,?)",
        (tg_id, card_id, mode, rating, date.today().isoformat()),
    )
    conn.commit()


def pick_next_card(conn, tg_id: int, subject: str, mode: str = "smart"):
    """
    Выбрать следующую карточку для предмета.
    smart  — сначала просроченные по SRS, потом новые, потом слабые;
    weak   — только отмеченные слабыми/проваленными;
    random — любая случайная.
    """
    today = date.today().isoformat()
    base = (
        "SELECT c.* FROM cards c "
        "LEFT JOIN card_state s ON s.card_id=c.id AND s.tg_id=? "
        "WHERE c.subject_code=? "
    )
    if mode == "random":
        q = base + "ORDER BY RANDOM() LIMIT 1"
        return conn.execute(q, (tg_id, subject)).fetchone()

    if mode == "weak":
        q = base + ("AND (s.last_rating='again' OR s.lapses>=1) "
                    "ORDER BY s.lapses DESC, RANDOM() LIMIT 1")
        row = conn.execute(q, (tg_id, subject)).fetchone()
        return row

    # smart: просроченные -> новые -> всё по возрастанию интервала
    q_due = base + "AND s.due_date IS NOT NULL AND s.due_date<=? " \
                   "ORDER BY s.due_date ASC LIMIT 1"
    row = conn.execute(q_due, (tg_id, subject, today)).fetchone()
    if row:
        return row
    q_new = base + "AND s.card_id IS NULL ORDER BY c.number ASC LIMIT 1"
    row = conn.execute(q_new, (tg_id, subject)).fetchone()
    if row:
        return row
    q_any = base + "ORDER BY COALESCE(s.interval, 0) ASC, RANDOM() LIMIT 1"
    return conn.execute(q_any, (tg_id, subject)).fetchone()


def due_count(conn, tg_id: int, subject: str) -> int:
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) n FROM cards c "
        "LEFT JOIN card_state s ON s.card_id=c.id AND s.tg_id=? "
        "WHERE c.subject_code=? AND (s.card_id IS NULL OR s.due_date<=?)",
        (tg_id, subject, today),
    ).fetchone()
    return row["n"]


def count_cards(conn, subject: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) n FROM cards WHERE subject_code=?", (subject,)
    ).fetchone()["n"]


def list_cards(conn, subject: str, limit: int, offset: int):
    """Страница билетов для экрана выбора."""
    return conn.execute(
        "SELECT id, number, title FROM cards WHERE subject_code=? "
        "ORDER BY number ASC LIMIT ? OFFSET ?",
        (subject, limit, offset),
    ).fetchall()


def random_card(conn, subject: str, exclude_id: int | None = None,
                require_text: bool = True):
    """Случайный билет предмета (для «следующего билета» в опросе)."""
    q = "SELECT * FROM cards WHERE subject_code=? "
    params = [subject]
    if require_text:
        q += "AND length(reference)>=40 "
    if exclude_id:
        q += "AND id!=? "
        params.append(exclude_id)
    q += "ORDER BY RANDOM() LIMIT 1"
    return conn.execute(q, params).fetchone()


# ---------- вопросы ИИ и кэш объяснений ----------

def get_cached_questions(conn, card_id: int):
    return conn.execute(
        "SELECT question FROM ai_questions WHERE card_id=?", (card_id,)
    ).fetchall()


def save_question(conn, card_id: int, question: str) -> None:
    conn.execute(
        "INSERT INTO ai_questions(card_id, question, created_at) VALUES(?,?,?)",
        (card_id, question, date.today().isoformat()),
    )
    conn.commit()


def get_explanation(conn, card_id: int):
    row = conn.execute(
        "SELECT text FROM explanations WHERE card_id=?", (card_id,)
    ).fetchone()
    return row["text"] if row else None


def save_explanation(conn, card_id: int, text: str) -> None:
    conn.execute(
        "INSERT INTO explanations(card_id, text, created_at) VALUES(?,?,?) "
        "ON CONFLICT(card_id) DO UPDATE SET text=excluded.text",
        (card_id, text, date.today().isoformat()),
    )
    conn.commit()


# ---------- статистика ----------

def stats(conn, tg_id: int, subject: str) -> dict:
    total = conn.execute(
        "SELECT COUNT(*) n FROM cards WHERE subject_code=?", (subject,)
    ).fetchone()["n"]
    rows = conn.execute(
        "SELECT c.id, c.number, c.title, s.interval, s.reps, s.lapses, s.last_rating "
        "FROM cards c LEFT JOIN card_state s "
        "ON s.card_id=c.id AND s.tg_id=? WHERE c.subject_code=? ORDER BY c.number",
        (tg_id, subject),
    ).fetchall()

    new = weak = learning = strong = 0
    weak_list = []
    for r in rows:
        if r["reps"] is None and not r["last_rating"]:
            new += 1
            continue
        last = r["last_rating"] or ""
        interval = r["interval"] or 0
        lapses = r["lapses"] or 0
        if last == "again" or (lapses >= 2 and interval <= 2):
            weak += 1
            weak_list.append((r["number"], r["title"]))
        elif interval >= 14 and last == "good":
            strong += 1
        else:
            learning += 1

    studied = total - new
    readiness = round(100 * strong / total) if total else 0
    return {
        "total": total, "new": new, "weak": weak, "learning": learning,
        "strong": strong, "studied": studied, "readiness": readiness,
        "weak_list": weak_list[:10],
    }


def streak(conn, tg_id: int) -> int:
    """Сколько дней подряд были повторения (включая сегодня)."""
    rows = conn.execute(
        "SELECT DISTINCT created_at FROM reviews WHERE tg_id=? "
        "ORDER BY created_at DESC", (tg_id,),
    ).fetchall()
    if not rows:
        return 0
    from datetime import date as _date, timedelta
    days = {r["created_at"] for r in rows}
    n, cur = 0, _date.today()
    # допускаем, что сегодня ещё не занимались — тогда считаем со вчера
    if cur.isoformat() not in days:
        cur = cur - timedelta(days=1)
    while cur.isoformat() in days:
        n += 1
        cur -= timedelta(days=1)
    return n
