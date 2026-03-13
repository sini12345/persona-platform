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


# --- Admin: all groups ---

async def get_all_groups() -> list[dict]:
    """Get all groups."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM groups ORDER BY created_at DESC")
        return [dict(row) for row in await cursor.fetchall()]


async def create_group(group_id: str, name: str, code: str):
    """Create a new group."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO groups (id, name, code) VALUES (?, ?, ?)",
            (group_id, name, code.upper())
        )
        await db.commit()


# --- Admin: all sessions with details ---

async def get_all_sessions(group_id: str | None = None) -> list[dict]:
    """Get all sessions, optionally filtered by group. Includes message count."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        if group_id:
            cursor = await db.execute(
                """SELECT s.*, g.name as group_name, g.code as group_code,
                          (SELECT COUNT(*) FROM messages WHERE session_id = s.id) as message_count
                   FROM sessions s
                   LEFT JOIN groups g ON s.group_id = g.id
                   WHERE s.group_id = ?
                   ORDER BY s.started_at DESC""",
                (group_id,)
            )
        else:
            cursor = await db.execute(
                """SELECT s.*, g.name as group_name, g.code as group_code,
                          (SELECT COUNT(*) FROM messages WHERE session_id = s.id) as message_count
                   FROM sessions s
                   LEFT JOIN groups g ON s.group_id = g.id
                   ORDER BY s.started_at DESC"""
            )
        return [dict(row) for row in await cursor.fetchall()]


async def get_session_with_messages(session_id: str) -> dict | None:
    """Get a session with all its messages for admin review."""
    session = await get_session(session_id)
    if not session:
        return None
    messages = await get_messages(session_id)
    session["messages"] = messages
    return session
