import sqlite3
from pathlib import Path

DB_PATH = Path("data/echo_memory.db")

def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    
    return connection

def initialize_database() -> None:
    with get_connection() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )"""
        )
        
        connection.commit()