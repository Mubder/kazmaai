"""
SQLite Backend Implementation for KazmaAI

Provides:
- Metadata storage (projects, conversations, agent state)
- ACID compliance
- Cross-platform compatibility (single file)
- WAL mode for concurrent reads
"""

import sqlite3
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from .base import BaseStorageManager, StorageError


class SQLiteStorageManager(BaseStorageManager):
    """
    SQLite-based storage backend for KazmaAI.
    
    Features:
    - Single-file database (portable)
    - WAL mode for concurrent access
    - JSON serialization for complex types
    - Automatic schema migration
    """
    
    SCHEMA_VERSION = 1
    
    def __init__(self, config_path: Optional[Path] = None):
        self._db_path: Optional[Path] = None
        self._conn: Optional[sqlite3.Connection] = None
        super().__init__(config_path)
    
    def _connect(self) -> None:
        """Initialize SQLite connection with WAL mode."""
        try:
            db_config = self.config.get('storage', {}).get('sqlite', {})
            db_relative = db_config.get('path', 'data/storage.db')
            
            self._db_path = self._root / db_relative
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            
            self._conn = sqlite3.connect(
                str(self._db_path),
                timeout=db_config.get('timeout', 30),
                check_same_thread=False
            )
            
            journal_mode = db_config.get('journal_mode', 'WAL')
            self._conn.execute(f"PRAGMA journal_mode={journal_mode}")
            
            self._init_schema()
            
        except sqlite3.Error as e:
            raise StorageError(f"Failed to initialize SQLite: {e}")
    
    def _disconnect(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
    
    def _init_schema(self) -> None:
        """Create database schema if not exists."""
        cursor = self._conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_versions (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("SELECT MAX(version) FROM schema_versions")
        current_version = cursor.fetchone()[0] or 0
        
        if current_version < self.SCHEMA_VERSION:
            self._migrate_schema(cursor, current_version)
        
        self._conn.commit()
    
    def _migrate_schema(self, cursor: sqlite3.Cursor, from_version: int) -> None:
        """Apply schema migrations."""
        migrations = [
            (1, self._migration_v1),
        ]
        
        for version, migration_fn in migrations:
            if version > from_version:
                migration_fn(cursor)
                cursor.execute(
                    "INSERT INTO schema_versions (version) VALUES (?)",
                    (version,)
                )
    
    def _migration_v1(self, cursor: sqlite3.Cursor) -> None:
        """Initial schema - creates core tables."""
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                value TEXT NOT NULL,
                collection TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_metadata_key ON metadata(key)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_metadata_collection ON metadata(collection)")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                state_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_projects_id ON projects(project_id)")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL UNIQUE,
                messages_json TEXT NOT NULL,
                metadata_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_id ON conversations(conversation_id)")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                state_key TEXT NOT NULL UNIQUE,
                state_data TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    
    # =========================================================================
    # BASE CLASS IMPLEMENTATION
    # =========================================================================
    
    def store(self, key: str, value: Any, collection: Optional[str] = None) -> bool:
        """Store data in SQLite database."""
        if not self._conn:
            raise StorageError("Database not connected")
        
        try:
            value_json = json.dumps(value, default=str)
            
            cursor = self._conn.cursor()
            cursor.execute("""
                INSERT INTO metadata (key, value, collection, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    collection = excluded.collection,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, value_json, collection))
            
            self._conn.commit()
            return True
            
        except sqlite3.Error as e:
            raise StorageError(f"Failed to store {key}: {e}")
    
    def retrieve(self, key: str, collection: Optional[str] = None) -> Optional[Any]:
        """Retrieve data from SQLite database."""
        if not self._conn:
            raise StorageError("Database not connected")
        
        try:
            cursor = self._conn.cursor()
            
            if collection:
                cursor.execute("""
                    SELECT value FROM metadata
                    WHERE key = ? AND collection = ?
                """, (key, collection))
            else:
                cursor.execute("""
                    SELECT value FROM metadata
                    WHERE key = ?
                """, (key,))
            
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return None
            
        except sqlite3.Error as e:
            raise StorageError(f"Failed to retrieve {key}: {e}")
    
    def delete(self, key: str, collection: Optional[str] = None) -> bool:
        """Delete data from SQLite database."""
        if not self._conn:
            raise StorageError("Database not connected")
        
        try:
            cursor = self._conn.cursor()
            
            if collection:
                cursor.execute("""
                    DELETE FROM metadata
                    WHERE key = ? AND collection = ?
                """, (key, collection))
            else:
                cursor.execute("""
                    DELETE FROM metadata
                    WHERE key = ?
                """, (key,))
            
            self._conn.commit()
            return cursor.rowcount > 0
            
        except sqlite3.Error as e:
            raise StorageError(f"Failed to delete {key}: {e}")
    
    def list_keys(self, collection: Optional[str] = None,
                  pattern: Optional[str] = None) -> List[str]:
        """List all keys in the database."""
        if not self._conn:
            raise StorageError("Database not connected")
        
        try:
            cursor = self._conn.cursor()
            
            if collection:
                if pattern:
                    cursor.execute("""
                        SELECT key FROM metadata
                        WHERE collection = ? AND key LIKE ?
                    """, (collection, pattern))
                else:
                    cursor.execute("""
                        SELECT key FROM metadata
                        WHERE collection = ?
                    """, (collection,))
            else:
                if pattern:
                    cursor.execute("""
                        SELECT key FROM metadata
                        WHERE key LIKE ?
                    """, (pattern,))
                else:
                    cursor.execute("SELECT key FROM metadata")
            
            return [row[0] for row in cursor.fetchall()]
            
        except sqlite3.Error as e:
            raise StorageError(f"Failed to list keys: {e}")
    
    # =========================================================================
    # SQLITE-SPECIFIC METHODS
    # =========================================================================
    
    def execute_query(self, query: str, params: tuple = ()) -> List[Dict]:
        """Execute raw SQL query and return results as list of dicts."""
        if not self._conn:
            raise StorageError("Database not connected")
        
        cursor = self._conn.cursor()
        cursor.execute(query, params)
        
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def begin_transaction(self) -> None:
        """Begin explicit transaction."""
        if self._conn:
            self._conn.execute("BEGIN")
    
    def commit_transaction(self) -> None:
        """Commit current transaction."""
        if self._conn:
            self._conn.commit()
    
    def rollback_transaction(self) -> None:
        """Rollback current transaction."""
        if self._conn:
            self._conn.rollback()
    
    def vacuum(self) -> None:
        """Reclaim database space."""
        if self._conn:
            self._conn.execute("VACUUM")