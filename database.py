import sqlite3
from datetime import datetime

DB_PATH = "ufc_bot.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            points INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_id TEXT,
            fight_id TEXT,
            fighter1 TEXT,
            fighter2 TEXT,
            predicted_winner TEXT,
            actual_winner TEXT,
            is_correct INTEGER DEFAULT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS events_cache (
            event_id TEXT PRIMARY KEY,
            data TEXT,
            cached_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def register_user(user_id: int, username: str, full_name: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO users (user_id, username, full_name)
        VALUES (?, ?, ?)
    """, (user_id, username, full_name))
    conn.commit()
    conn.close()


def save_prediction(user_id: int, event_id: str, fight_id: str,
                    fighter1: str, fighter2: str, predicted_winner: str):
    conn = get_conn()
    c = conn.cursor()
    # Проверяем нет ли уже прогноза на этот бой
    c.execute("""
        SELECT id FROM predictions
        WHERE user_id=? AND fight_id=?
    """, (user_id, fight_id))
    existing = c.fetchone()

    if existing:
        c.execute("""
            UPDATE predictions SET predicted_winner=?, created_at=?
            WHERE user_id=? AND fight_id=?
        """, (predicted_winner, datetime.now().isoformat(), user_id, fight_id))
        updated = True
    else:
        c.execute("""
            INSERT INTO predictions (user_id, event_id, fight_id, fighter1, fighter2, predicted_winner)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, event_id, fight_id, fighter1, fighter2, predicted_winner))
        updated = False

    conn.commit()
    conn.close()
    return updated


def get_user_predictions(user_id: int, event_id: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM predictions
        WHERE user_id=? AND event_id=?
        ORDER BY created_at DESC
    """, (user_id, event_id))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_leaderboard(limit: int = 10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT u.user_id, u.username, u.full_name, u.points,
               COUNT(p.id) as total_preds,
               SUM(CASE WHEN p.is_correct=1 THEN 1 ELSE 0 END) as correct_preds
        FROM users u
        LEFT JOIN predictions p ON u.user_id = p.user_id
        GROUP BY u.user_id
        ORDER BY u.points DESC, correct_preds DESC
        LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_user_stats(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT u.points,
               COUNT(p.id) as total,
               SUM(CASE WHEN p.is_correct=1 THEN 1 ELSE 0 END) as correct
        FROM users u
        LEFT JOIN predictions p ON u.user_id = p.user_id
        WHERE u.user_id=?
        GROUP BY u.user_id
    """, (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else {"points": 0, "total": 0, "correct": 0}


def add_points(user_id: int, points: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET points = points + ? WHERE user_id=?", (points, user_id))
    conn.commit()
    conn.close()


def mark_prediction_result(fight_id: str, actual_winner: str):
    """Вызывается после ивента, проставляет результаты и начисляет очки."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT id, user_id, predicted_winner FROM predictions
        WHERE fight_id=? AND is_correct IS NULL
    """, (fight_id,))
    preds = c.fetchall()

    for pred in preds:
        is_correct = 1 if pred["predicted_winner"] == actual_winner else 0
        c.execute("""
            UPDATE predictions SET is_correct=?, actual_winner=?
            WHERE id=?
        """, (is_correct, actual_winner, pred["id"]))
        if is_correct:
            c.execute("UPDATE users SET points = points + 10 WHERE user_id=?",
                      (pred["user_id"],))

    conn.commit()
    conn.close()
    return len(preds)
