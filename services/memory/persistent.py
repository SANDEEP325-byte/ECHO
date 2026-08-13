from services.memory.database import get_connection

class PersistentMemory:
    def save_message(self, role: str, content: str) -> None:
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO messages (role, content)
                VALUES (?, ?)""",
                (role, content),
            )
            
            connection.commit()
            
    def get_recent_messages(self,limit: int= 20) -> list[dict[str, str]]:
        with get_connection() as connection:
            rows= connection.execute(
                """SELECT role, content FROM messages
                ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            
            messages = [
                {
                    "role": row["role"],
                    "content": row["content"],
                }
                for row in reversed(rows)
            ]
            
            return messages
        
        def clear(self) -> None:
            with get_connection() as connection:
                connection.execute("DELETE FROM messages")
                connection.commit()
                
persistent_memory = PersistentMemory()