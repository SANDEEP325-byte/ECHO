from services.memory.database import get_connection


class FactMemory:
    def save_fact(self, key: str, value: str) -> None:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO facts (key, value)
                VALUES (?, ?)
                ON CONFLICT(KEY)
                DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, value),
            )
            
            connection.commit()
            
    def get_fact(self, key: str) -> str | None:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT value
                FROM facts
                WHERE key = ?
                """,
                (key,),
            ).fetchone()
            
            if row is None:
                return None
            
            return str(row["value"])
        
    def get_all_facts(self) -> dict[str, str]:
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT key, value
                FROM facts
                ORDER BY key
                """
            ).fetchall()
            
            return {
                row["key"]: row["value"]
                for row in rows
            }
            
    def get_context(self) -> str:
        facts = self.get_all_facts()
        
        if not facts:
            return ""
        
        lines = ["Known facts about the user:"]
        
        for key, value in facts.items():
            lines.append(f"- {key}: {value}")
            
        return "\n".join(lines)
            
    def delete_fact(self, key: str) -> None:
        with get_connection() as connection:
            connection.execute(
                "DELETE FROM facts WHERE key = ?",
                (key,),
            )
            
            connection.commit()
            
    def clear(self) -> None:
        with get_connection() as connection:
            connection.execute("DELETE FROM facts")
            connection.commit()
            
fact_memory = FactMemory()