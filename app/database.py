"""SQLite database setup and queries."""
import aiosqlite
from pathlib import Path
from app.config import DATABASE_PATH


async def init_db():
    """Create tables if they don't exist."""
    db_path = Path(DATABASE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS groups (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                code TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                group_id TEXT REFERENCES groups(id),
                student_name TEXT DEFAULT '',
                persona_id TEXT NOT NULL,
                scenario_number INTEGER NOT NULL,
                mission TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP,
                ended_by TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT REFERENCES sessions(id),
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                visible_content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Insert a default group for testing
            INSERT OR IGNORE INTO groups (id, name, code)
            VALUES ('default', 'Testhold', 'TEST2026');
        """)
        await db.commit()

        # Add evaluation column if it doesn't exist (safe migration)
        try:
            await db.execute("ALTER TABLE sessions ADD COLUMN evaluation TEXT")
            await db.commit()
        except Exception:
            pass  # Column already exists

        # Add feedback table if it doesn't exist
        await db.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                content TEXT NOT NULL,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                read_at TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
        """)
        await db.commit()

        # Add questionnaire table if it doesn't exist
        await db.execute("""
            CREATE TABLE IF NOT EXISTS questionnaire (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                q1_realisme INTEGER CHECK(q1_realisme BETWEEN 1 AND 5),
                q2_immersion INTEGER CHECK(q2_immersion BETWEEN 1 AND 5),
                q3_overraskelse INTEGER CHECK(q3_overraskelse BETWEEN 1 AND 5),
                q4_responsivitet INTEGER CHECK(q4_responsivitet BETWEEN 1 AND 5),
                q5_udfordring INTEGER CHECK(q5_udfordring BETWEEN 1 AND 5),
                q6_tvivl TEXT DEFAULT '',
                q7_anderledes TEXT DEFAULT '',
                q8_praksis TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


def get_db_path():
    return DATABASE_PATH


async def get_db():
    """Get a database connection."""
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    return db


# --- Group queries ---

async def validate_group_code(code: str) -> dict | None:
    """Check if a group code is valid. Returns group dict or None."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, name, code FROM groups WHERE code = ?", (code.upper(),)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


# --- Session queries ---

async def create_session(session_id: str, group_id: str, persona_id: str,
                         scenario_number: int, mission: str | None = None,
                         student_name: str = "") -> str:
    """Create a new conversation session."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT INTO sessions (id, group_id, student_name, persona_id, scenario_number, mission)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, group_id, student_name, persona_id, scenario_number, mission)
        )
        await db.commit()
    return session_id


async def end_session(session_id: str, ended_by: str = "student"):
    """Mark a session as ended."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE sessions SET ended_at = CURRENT_TIMESTAMP, ended_by = ? WHERE id = ?",
            (ended_by, session_id)
        )
        await db.commit()


async def get_session(session_id: str) -> dict | None:
    """Get session details."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


# --- Message queries ---

async def save_message(session_id: str, role: str, content: str, visible_content: str | None = None):
    """Save a message to the database."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT INTO messages (session_id, role, content, visible_content)
               VALUES (?, ?, ?, ?)""",
            (session_id, role, content, visible_content)
        )
        await db.commit()


async def get_messages(session_id: str) -> list[dict]:
    """Get all messages for a session, ordered chronologically."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# --- Admin queries ---

async def get_group_stats(group_id: str) -> dict:
    """Get usage stats for a group."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Total sessions
        cursor = await db.execute(
            "SELECT COUNT(*) as count FROM sessions WHERE group_id = ?", (group_id,)
        )
        total = (await cursor.fetchone())["count"]

        # Sessions per persona
        cursor = await db.execute(
            """SELECT persona_id, COUNT(*) as count
               FROM sessions WHERE group_id = ?
               GROUP BY persona_id""",
            (group_id,)
        )
        per_persona = {row["persona_id"]: row["count"] for row in await cursor.fetchall()}

        return {"total_sessions": total, "per_persona": per_persona}


async def save_evaluation(session_id: str, evaluation: str):
    """Save evaluation text for a session."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE sessions SET evaluation = ? WHERE id = ?",
            (evaluation, session_id)
        )
        await db.commit()


async def create_group(group_id: str, name: str, code: str):
    """Create a new group."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO groups (id, name, code) VALUES (?, ?, ?)",
            (group_id, name, code.upper())
        )
        await db.commit()


async def get_all_groups() -> list[dict]:
    """Get all groups with session counts."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT g.*, COUNT(s.id) as session_count
            FROM groups g
            LEFT JOIN sessions s ON s.group_id = g.id
            GROUP BY g.id
            ORDER BY g.name
        """)
        return [dict(row) for row in await cursor.fetchall()]


async def get_sessions_for_group(group_id: str) -> list[dict]:
    """Get all sessions for a group, newest first."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT s.*,
                   (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) as message_count
            FROM sessions s
            WHERE s.group_id = ?
            ORDER BY s.started_at DESC
        """, (group_id,))
        return [dict(row) for row in await cursor.fetchall()]


async def get_all_sessions(group_id: str | None = None) -> list[dict]:
    """Get all sessions with group info, newest first. Optionally filter by group."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        if group_id:
            cursor = await db.execute("""
                SELECT s.*, g.name as group_name, g.code as group_code,
                       (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) as message_count
                FROM sessions s
                LEFT JOIN groups g ON g.id = s.group_id
                WHERE s.group_id = ?
                ORDER BY s.started_at DESC
            """, (group_id,))
        else:
            cursor = await db.execute("""
                SELECT s.*, g.name as group_name, g.code as group_code,
                       (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) as message_count
                FROM sessions s
                LEFT JOIN groups g ON g.id = s.group_id
                ORDER BY s.started_at DESC
            """)
        return [dict(row) for row in await cursor.fetchall()]


async def get_session_with_messages(session_id: str) -> dict | None:
    """Get a session with all its messages for admin review."""
    session = await get_session(session_id)
    if not session:
        return None
    messages = await get_messages(session_id)
    session["messages"] = messages
    return session


# --- Feedback queries ---

async def save_feedback(session_id: str, content: str, status: str = "generated"):
    """Save feedback for a session."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT INTO feedback (session_id, content, status)
               VALUES (?, ?, ?)""",
            (session_id, content, status)
        )
        await db.commit()


async def get_feedback(session_id: str) -> dict | None:
    """Get feedback for a session, if it exists."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM feedback WHERE session_id = ? ORDER BY generated_at DESC LIMIT 1",
            (session_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def mark_feedback_read(session_id: str):
    """Mark feedback as read for a session."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE feedback SET read_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (session_id,)
        )
        await db.commit()


# --- Questionnaire queries ---

async def save_questionnaire(session_id: str, data: dict):
    """Save questionnaire responses for a session."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO questionnaire (session_id, q1_realisme, q2_immersion, q3_overraskelse,
                q4_responsivitet, q5_udfordring, q6_tvivl, q7_anderledes, q8_praksis)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            data.get("q1"), data.get("q2"), data.get("q3"),
            data.get("q4"), data.get("q5"),
            data.get("q6", ""), data.get("q7", ""), data.get("q8", ""),
        ))
        await db.commit()


async def get_questionnaire(session_id: str) -> dict | None:
    """Get questionnaire responses for a session."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM questionnaire WHERE session_id = ? LIMIT 1",
            (session_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
