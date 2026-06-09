"""
KazmaAI Event Bus System

Provides:
- Central event dispatcher for all agent activities
- Event sourcing for memory updates
- Async event handling with priority queues
- Event persistence to SQLite
- Real-time event streaming (for web/Telegram)
"""

import asyncio
import json
import uuid
from datetime import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Awaitable
from pathlib import Path
import sqlite3

from .localization import get_ui_string, is_arabic_text


class EventType(str, Enum):
    """Core event types tracked by KazmaAI."""
    
    # User interactions
    USER_MESSAGE = "user_message"
    USER_COMMAND = "user_command"
    
    # Agent responses
    AGENT_RESPONSE = "agent_response"
    AGENT_THOUGHT = "agent_thought"
    
    # Tool usage
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    
    # Project management
    PROJECT_CREATED = "project_created"
    PROJECT_UPDATED = "project_updated"
    PROJECT_DELETED = "project_deleted"
    FILE_CHANGED = "file_changed"
    TASK_ADDED = "task_added"
    TASK_COMPLETED = "task_completed"
    
    # Memory system
    MEMORY_CREATED = "memory_created"
    MEMORY_UPDATED = "memory_updated"
    MEMORY_SEARCHED = "memory_searched"
    SUMMARY_GENERATED = "summary_generated"
    
    # System events
    AGENT_STARTED = "agent_started"
    AGENT_STOPPED = "agent_stoppped"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Event:
    """
    Immutable event record.
    
    All events in KazmaAI are immutable facts that happened.
    They are stored, indexed, and used to drive memory updates.
    """
    
    event_type: EventType
    data: Dict[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = "core"  # Component that emitted this event
    priority: int = 0  # Higher = processed first
    language: str = "auto"  # 'ar', 'en', or 'auto' for detection
    
    def __post_init__(self):
        # Auto-detect language from message content
        if self.language == "auto" and "message" in self.data:
            msg = self.data.get("message", "")
            self.language = "ar" if is_arabic_text(msg) else "en"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "priority": self.priority,
            "language": self.language,
            "data": self.data,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """Reconstruct event from dictionary."""
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            event_type=EventType(data["event_type"]),
            data=data.get("data", {}),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.utcnow(),
            source=data.get("source", "core"),
            priority=data.get("priority", 0),
            language=data.get("language", "auto"),
        )


class EventBus:
    """
    Central event bus for KazmaAI AI Agent.
    
    Features:
    - Async event publishing/subscribing
    - Event persistence to SQLite
    - Priority-based processing
    - Real-time event streaming
    - Event handlers with filtering
    """
    
    def __init__(self, storage_manager=None, db_path: Optional[Path] = None):
        """
        Initialize event bus.
        
        Args:
            storage_manager: Optional storage manager for event persistence
            db_path: Optional explicit path to event database
        """
        self._storage = storage_manager
        self._db_path = db_path
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._async_subscribers: Dict[EventType, List[Callable]] = {}
        self._event_queue: asyncio.PriorityQueue = None
        self._running = False
        self._event_count = 0
        self._max_stored = 10000  # From config
        
        # Initialize storage
        if db_path:
            self._init_db()
    
    def _init_db(self) -> None:
        """Initialize SQLite table for event storage."""
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                source TEXT,
                priority INTEGER DEFAULT 0,
                language TEXT DEFAULT 'auto',
                data_json TEXT NOT NULL,
                indexed INTEGER DEFAULT 0
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_indexed ON events(indexed)")
        
        conn.commit()
        conn.close()
    
    # =========================================================================
    # EVENT PUBLISHING
    # =========================================================================
    
    def publish(self, event: Event) -> str:
        """
        Publish an event to the bus (synchronous).
        
        Args:
            event: Event to publish
            
        Returns:
            Event ID
        """
        event_id = event.event_id
        
        # Store event if persistence enabled
        if self._db_path:
            self._store_event(event)
        
        # Notify sync subscribers
        for handler in self._subscribers.get(event.event_type, []):
            try:
                handler(event)
            except Exception as e:
                print(f"Event handler error: {e}")
        
        self._event_count += 1
        return event_id
    
    async def publish_async(self, event: Event) -> str:
        """
        Publish an event to the bus (async, queued).
        
        Args:
            event: Event to publish
            
        Returns:
            Event ID
        """
        if self._event_queue is None:
            self._event_queue = asyncio.PriorityQueue()
        
        # Add to priority queue (negative priority for min-heap behavior)
        await self._event_queue.put((-event.priority, event.timestamp.timestamp(), event))
        
        # Store event
        if self._db_path:
            self._store_event(event)
        
        self._event_count += 1
        return event.event_id
    
    def _store_event(self, event: Event) -> None:
        """Persist event to SQLite."""
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO events 
            (event_id, event_type, timestamp, source, priority, language, data_json, indexed)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            event.event_id,
            event.event_type.value,
            event.timestamp.isoformat(),
            event.source,
            event.priority,
            event.language,
            json.dumps(event.data),
        ))
        
        conn.commit()
        conn.close()
        
        # Cleanup old events
        self._cleanup_events()
    
    def _cleanup_events(self) -> None:
        """Remove old events beyond max_stored limit."""
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM events")
        count = cursor.fetchone()[0]
        
        if count > self._max_stored:
            cursor.execute("""
                DELETE FROM events
                WHERE event_id IN (
                    SELECT event_id FROM events
                    ORDER BY timestamp ASC
                    LIMIT ?
                )
            """, (count - self._max_stored,))
            
            conn.commit()
        
        conn.close()
    
    # =========================================================================
    # EVENT SUBSCRIBING
    # =========================================================================
    
    def subscribe(self, event_type: EventType, handler: Callable[[Event], None]) -> None:
        """
        Subscribe to events of a specific type (synchronous handler).
        
        Args:
            event_type: Type of events to subscribe to
            handler: Function to call when event occurs
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
    
    def subscribe_async(self, event_type: EventType, handler: Callable[[Event], Awaitable[None]]) -> None:
        """
        Subscribe to events of a specific type (async handler).
        
        Args:
            event_type: Type of events to subscribe to
            handler: Async function to call when event occurs
        """
        if event_type not in self._async_subscribers:
            self._async_subscribers[event_type] = []
        self._async_subscribers[event_type].append(handler)
    
    def unsubscribe(self, event_type: EventType, handler: Callable) -> None:
        """
        Unsubscribe a handler from events.
        
        Args:
            event_type: Type of events to unsubscribe from
            handler: Handler function to remove
        """
        for handler_list in [self._subscribers.get(event_type, []), 
                            self._async_subscribers.get(event_type, [])]:
            if handler in handler_list:
                handler_list.remove(handler)
    
    # =========================================================================
    # EVENT PROCESSING LOOP
    # =========================================================================
    
    async def start_processing(self) -> None:
        """Start the async event processing loop."""
        if self._running:
            return
        
        self._running = True
        
        while self._running:
            try:
                # Get next event from queue
                _, _, event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=1.0
                )
                
                # Process event
                await self._process_event(event)
                
                # Mark as processed
                self._mark_event_indexed(event.event_id)
                
            except asyncio.TimeoutError:
                # No events, wait a bit
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Event processing error: {e}")
                await asyncio.sleep(1.0)
    
    async def _process_event(self, event: Event) -> None:
        """Process a single event with async handlers."""
        handlers = self._async_subscribers.get(event.event_type, [])
        
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                print(f"Async handler error for {event.event_type}: {e}")
    
    def stop_processing(self) -> None:
        """Stop the event processing loop."""
        self._running = False
    
    def _mark_event_indexed(self, event_id: str) -> None:
        """Mark event as indexed in database."""
        if not self._db_path:
            return
        
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE events SET indexed = 1 WHERE event_id = ?
        """, (event_id,))
        
        conn.commit()
        conn.close()
    
    # =========================================================================
    # EVENT QUERYING
    # =========================================================================
    
    def get_events(
        self,
        event_type: Optional[EventType] = None,
        limit: int = 100,
        offset: int = 0,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        language: Optional[str] = None,
    ) -> List[Event]:
        """
        Query events from storage.
        
        Args:
            event_type: Filter by event type
            limit: Maximum events to return
            offset: Pagination offset
            start_time: Filter events after this time
            end_time: Filter events before this time
            language: Filter by language ('ar' or 'en')
            
        Returns:
            List of events matching criteria
        """
        if not self._db_path:
            return []
        
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        
        query = "SELECT data_json FROM events WHERE 1=1"
        params = []
        
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type.value)
        
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time.isoformat())
        
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time.isoformat())
        
        if language:
            query += " AND language = ?"
            params.append(language)
        
        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [Event.from_dict(json.loads(row[0])) for row in rows]
    
    def get_event_by_id(self, event_id: str) -> Optional[Event]:
        """Get a single event by ID."""
        if not self._db_path:
            return None
        
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT data_json FROM events WHERE event_id = ?
        """, (event_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Event.from_dict(json.loads(row[0]))
        return None
    
    def get_unprocessed_events(self, limit: int = 100) -> List[Event]:
        """Get events that haven't been processed yet."""
        if not self._db_path:
            return []
        
        conn = sqlite3.connect(str(self._db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT data_json FROM events 
            WHERE indexed = 0 
            ORDER BY priority DESC, timestamp ASC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [Event.from_dict(json.loads(row[0])) for row in rows]
    
    # =========================================================================
    # STATISTICS
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get event bus statistics."""
        stats = {
            "total_events": self._event_count,
            "queue_size": self._event_queue.qsize() if self._event_queue else 0,
            "subscribers": {
                et.value: len(handlers) 
                for et, handlers in {**self._subscribers, **self._async_subscribers}.items()
            },
        }
        
        if self._db_path:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM events")
            stats["stored_events"] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM events WHERE indexed = 0")
            stats["unprocessed_events"] = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT event_type, COUNT(*) 
                FROM events 
                GROUP BY event_type 
                ORDER BY COUNT(*) DESC
                LIMIT 10
            """)
            stats["top_event_types"] = dict(cursor.fetchall())
            
            conn.close()
        
        return stats


# Convenience functions for creating common events
def user_message_event(message: str, user_id: Optional[str] = None, **extras) -> Event:
    """Create a user message event."""
    return Event(
        event_type=EventType.USER_MESSAGE,
        data={"message": message, "user_id": user_id or "anonymous", **extras},
        priority=10,
    )


def agent_response_event(message: str, conversation_id: Optional[str] = None, **extras) -> Event:
    """Create an agent response event."""
    return Event(
        event_type=EventType.AGENT_RESPONSE,
        data={"message": message, "conversation_id": conversation_id or "default", **extras},
        priority=10,
    )


def project_event(event_type: EventType, project_id: str, **extras) -> Event:
    """Create a project-related event."""
    return Event(
        event_type=event_type,
        data={"project_id": project_id, **extras},
        priority=5,
    )


def error_event(message: str, error_type: Optional[str] = None, **extras) -> Event:
    """Create an error event."""
    return Event(
        event_type=EventType.ERROR,
        data={"message": message, "error_type": error_type, **extras},
        priority=100,  # High priority
    )