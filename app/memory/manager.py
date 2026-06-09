"""
KazmaAI Memory & Self-Improvement System

Provides:
- Event-driven memory updates
- Conversation summarization
- Semantic memory storage (vector embeddings)
- Operational parameter self-improvement
- Memory search and retrieval
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.events import EventBus, EventType, Event
from core.storage.base import BaseStorageManager
from core.localization import is_arabic_text, get_ui_string


@dataclass
class Memory:
    """A single memory unit in KazmaAI."""
    
    memory_id: str
    content: str
    memory_type: str  # episodic, semantic, procedural
    importance: float = 0.5  # 0.0-1.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None  # Vector embedding
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "content": self.content,
            "memory_type": self.memory_type,
            "importance": self.importance,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "metadata": self.metadata,
            "embedding": self.embedding,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Memory":
        return cls(
            memory_id=data.get("memory_id", ""),
            content=data.get("content", ""),
            memory_type=data.get("memory_type", "episodic"),
            importance=data.get("importance", 0.5),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.utcnow(),
            last_accessed=datetime.fromisoformat(data["last_accessed"]) if data.get("last_accessed") else None,
            metadata=data.get("metadata", {}),
            embedding=data.get("embedding"),
        )


@dataclass
class ConversationSummary:
    """Summary of a conversation session."""
    
    conversation_id: str
    summary: str
    key_points: List[str]
    entities: List[str]
    language: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    message_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "summary": self.summary,
            "key_points": self.key_points,
            "entities": self.entities,
            "language": self.language,
            "created_at": self.created_at.isoformat(),
            "message_count": self.message_count,
        }


class MemoryManager:
    """
    Memory management system for KazmaAI.
    
    Features:
    - Event-driven memory creation
    - Conversation summarization
    - Vector-based semantic search
    - Memory importance decay
    - Self-improvement through pattern detection
    """
    
    def __init__(
        self,
        storage_manager: BaseStorageManager,
        event_bus: EventBus,
        model_provider=None,
    ):
        """
        Initialize memory manager.
        
        Args:
            storage_manager: Storage backend
            event_bus: Event bus for subscribing to events
            model_provider: Optional LLM provider for summarization
        """
        self._storage = storage_manager
        self._event_bus = event_bus
        self._model_provider = model_provider
        
        # Configuration
        config = storage_manager.config.get('memory', {})
        self._enabled = config.get('enabled', True)
        self._event_loop_interval = config.get('event_loop_interval', 60)
        self._summarize_after_messages = config.get('summarize_after_messages', 10)
        self._self_improvement_enabled = config.get('self_improvement', {}).get('enabled', False)
        
        # State
        self._running = False
        self._conversation_buffers: Dict[str, List[Event]] = {}
        self._memory_count = 0
        
        # Subscribe to events
        self._subscribe_to_events()
    
    def _subscribe_to_events(self) -> None:
        """Subscribe to relevant events for memory updates."""
        self._event_bus.subscribe_async(EventType.USER_MESSAGE, self._on_user_message)
        self._event_bus.subscribe_async(EventType.AGENT_RESPONSE, self._on_agent_response)
        self._event_bus.subscribe_async(EventType.TOOL_CALL, self._on_tool_call)
        self._event_bus.subscribe_async(EventType.ERROR, self._on_error)
    
    async def _on_user_message(self, event: Event) -> None:
        """Handle user message events."""
        conversation_id = event.data.get('conversation_id', 'default')
        
        # Add to conversation buffer
        if conversation_id not in self._conversation_buffers:
            self._conversation_buffers[conversation_id] = []
        
        self._conversation_buffers[conversation_id].append(event)
        
        # Check if summarization needed
        if len(self._conversation_buffers[conversation_id]) >= self._summarize_after_messages:
            await self._summarize_conversation(conversation_id)
    
    async def _on_agent_response(self, event: Event) -> None:
        """Handle agent response events."""
        # Store as episodic memory if important
        if self._is_important_event(event):
            await self._create_memory(event, memory_type="episodic")
    
    async def _on_tool_call(self, event: Event) -> None:
        """Handle tool call events - store as procedural memory."""
        if event.data.get('success', True):
            await self._create_memory(event, memory_type="procedural")
    
    async def _on_error(self, event: Event) -> None:
        """Handle error events - high priority memory."""
        memory = await self._create_memory(event, memory_type="episodic", importance=0.9)
        
        # Trigger self-improvement if enabled
        if self._self_improvement_enabled and memory:
            await self._analyze_error_for_improvement(event, memory)
    
    def _is_important_event(self, event: Event) -> bool:
        """Determine if an event should be stored as memory."""
        # High priority events are always important
        if event.priority >= 10:
            return True
        
        # Check for key phrases in Arabic or English
        message = event.data.get('message', '')
        important_phrases = [
            'remember', 'important', 'learn', 'save',
            'تذكر', 'مهم', 'تعلم', 'احفظ',
        ]
        
        return any(phrase in message.lower() for phrase in important_phrases)
    
    async def _create_memory(
        self,
        event: Event,
        memory_type: str = "episodic",
        importance: Optional[float] = None,
    ) -> Optional[Memory]:
        """
        Create a memory from an event.
        
        Args:
            event: Source event
            memory_type: Type of memory (episodic, semantic, procedural)
            importance: Importance score (0.0-1.0)
            
        Returns:
            Created memory or None if disabled
        """
        if not self._enabled:
            return None
        
        import uuid
        
        memory = Memory(
            memory_id=str(uuid.uuid4()),
            content=event.data.get('message', str(event.data)),
            memory_type=memory_type,
            importance=importance or event.data.get('importance', 0.5),
            metadata={
                'event_id': event.event_id,
                'event_type': event.event_type.value,
                'source': event.source,
                'language': event.language,
            },
        )
        
        # Generate embedding if available
        embedding = await self._generate_embedding(memory.content)
        if embedding:
            memory.embedding = embedding
        
        # Store memory
        self._storage.store(
            f"memory:{memory.memory_id}",
            memory.to_dict(),
            collection="memories",
        )
        
        self._memory_count += 1
        
        # Emit event
        self._event_bus.publish(Event(
            event_type=EventType.MEMORY_CREATED,
            data={
                'memory_id': memory.memory_id,
                'memory_type': memory.memory_type,
            },
        ))
        
        return memory
    
    async def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate vector embedding for text."""
        # TODO: Integrate with actual embedding model
        # For now, return None - memories will still work with keyword search
        return None
    
    async def _summarize_conversation(self, conversation_id: str) -> None:
        """
        Summarize a conversation buffer.
        
        Args:
            conversation_id: Conversation to summarize
        """
        events = self._conversation_buffers.get(conversation_id, [])
        
        if len(events) < 2:
            return
        
        # Extract messages
        messages = []
        for event in events:
            if event.event_type in [EventType.USER_MESSAGE, EventType.AGENT_RESPONSE]:
                messages.append({
                    'role': 'user' if event.event_type == EventType.USER_MESSAGE else 'assistant',
                    'content': event.data.get('message', ''),
                    'timestamp': event.timestamp.isoformat(),
                })
        
        if not messages:
            return
        
        # Generate summary (placeholder - would use LLM)
        summary_text = f"Conversation with {len(messages)} messages"
        key_points = [f"Message {i+1}" for i in range(min(5, len(messages)))]
        
        # Detect language
        language = 'ar' if any(is_arabic_text(m.get('content', '')) for m in messages) else 'en'
        
        summary = ConversationSummary(
            conversation_id=conversation_id,
            summary=summary_text,
            key_points=key_points,
            entities=[],
            language=language,
            message_count=len(messages),
        )
        
        # Store summary
        self._storage.store(
            f"summary:{conversation_id}",
            summary.to_dict(),
            collection="summaries",
        )
        
        # Create semantic memory from summary
        await self._create_memory(
            Event(
                event_type=EventType.SUMMARY_GENERATED,
                data={'summary': summary_text, 'conversation_id': conversation_id},
            ),
            memory_type="semantic",
            importance=0.7,
        )
        
        # Clear buffer
        self._conversation_buffers[conversation_id] = []
    
    async def _analyze_error_for_improvement(
        self,
        error_event: Event,
        memory: Memory,
    ) -> None:
        """Analyze an error for potential self-improvement."""
        # Placeholder for self-improvement logic
        # In production, this would:
        # 1. Analyze error patterns
        # 2. Identify root causes
        # 3. Suggest parameter adjustments
        # 4. Update config if confident
        
        error_type = error_event.data.get('error_type', 'unknown')
        
        # Track error frequency
        error_key = f"errors:{error_type}"
        error_count = self._storage.retrieve(error_key, collection="stats") or 0
        error_count = (error_count.get('count', 0) if isinstance(error_count, dict) else 0) + 1
        
        self._storage.store(
            error_key,
            {'count': error_count, 'last_occurrence': datetime.utcnow().isoformat()},
            collection="stats",
        )
        
        # If error is frequent, flag for review
        if error_count >= 5:
            self._event_bus.publish(Event(
                event_type=EventType.WARNING,
                data={
                    'message': f"Frequent error detected: {error_type} ({error_count} times)",
                    'action_required': 'review_configuration',
                },
                priority=50,
            ))
    
    # =========================================================================
    # MEMORY SEARCH
    # =========================================================================
    
    def search_memories(
        self,
        query: str,
        memory_type: Optional[str] = None,
        limit: int = 10,
        min_importance: float = 0.0,
    ) -> List[Memory]:
        """
        Search memories by keyword matching.
        
        Args:
            query: Search query
            memory_type: Optional filter by type
            limit: Maximum results
            min_importance: Minimum importance threshold
            
        Returns:
            List of matching memories
        """
        all_memories = self._storage.list_keys(collection="memories")
        
        results = []
        query_lower = query.lower()
        
        for key in all_memories:
            memory_data = self._storage.retrieve(key, collection="memories")
            if not memory_data:
                continue
            
            memory = Memory.from_dict(memory_data)
            
            # Filter by type
            if memory_type and memory.memory_type != memory_type:
                continue
            
            # Filter by importance
            if memory.importance < min_importance:
                continue
            
            # Keyword match
            if (
                query_lower in memory.content.lower() or
                any(query_lower in str(v).lower() for v in memory.metadata.values())
            ):
                memory.last_accessed = datetime.utcnow()
                results.append(memory)
        
        # Sort by relevance (simple: importance + recency)
        results.sort(
            key=lambda m: m.importance * 0.7 + (0.3 if m.last_accessed and (datetime.utcnow() - m.last_accessed).days < 7 else 0),
            reverse=True,
        )
        
        return results[:limit]
    
    def get_memory(self, memory_id: str) -> Optional[Memory]:
        """Get a specific memory by ID."""
        memory_data = self._storage.retrieve(f"memory:{memory_id}", collection="memories")
        if not memory_data:
            return None
        return Memory.from_dict(memory_data)
    
    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory."""
        success = self._storage.delete(f"memory:{memory_id}", collection="memories")
        if success:
            self._memory_count = max(0, self._memory_count - 1)
        return success
    
    def get_conversation_summary(self, conversation_id: str) -> Optional[ConversationSummary]:
        """Get a conversation summary."""
        summary_data = self._storage.retrieve(f"summary:{conversation_id}", collection="summaries")
        if not summary_data:
            return None
        return ConversationSummary(**summary_data)
    
    # =========================================================================
    # MAINTENANCE
    # =========================================================================
    
    def decay_importance(self, decay_factor: float = 0.95) -> None:
        """
        Decay importance of all memories (run periodically).
        
        Args:
            decay_factor: Factor to multiply importance by (0.0-1.0)
        """
        all_keys = self._storage.list_keys(collection="memories")
        
        for key in all_keys:
            memory_data = self._storage.retrieve(key, collection="memories")
            if not memory_data:
                continue
            
            memory = Memory.from_dict(memory_data)
            memory.importance *= decay_factor
            memory.importance = max(0.0, min(1.0, memory.importance))
            
            self._storage.store(key, memory.to_dict(), collection="memories")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory system statistics."""
        return {
            "total_memories": self._memory_count,
            "conversation_buffers": len(self._conversation_buffers),
            "enabled": self._enabled,
            "self_improvement_enabled": self._self_improvement_enabled,
        }


class SelfImprovementEngine:
    """
    Self-improvement engine for KazmaAI.
    
    Analyzes patterns in memories and events to suggest operational improvements.
    """
    
    def __init__(self, memory_manager: MemoryManager, storage_manager: BaseStorageManager):
        self._memory = memory_manager
        self._storage = storage_manager
        self._config = storage_manager.config
    
    async def review_and_improve(self) -> List[Dict[str, Any]]:
        """
        Review operational parameters and suggest improvements.
        
        Returns:
            List of suggested improvements
        """
        suggestions = []
        
        # Analyze error patterns
        error_stats = self._analyze_errors()
        if error_stats:
            suggestions.append({
                'type': 'error_reduction',
                'description': f"Reduce frequent errors: {', '.join(error_stats[:3])}",
                'priority': 'high',
            })
        
        # Analyze memory patterns
        memory_patterns = self._analyze_memory_patterns()
        if memory_patterns:
            suggestions.append({
                'type': 'memory_optimization',
                'description': memory_patterns,
                'priority': 'medium',
            })
        
        # Analyze language usage
        lang_stats = self._analyze_language_usage()
        if lang_stats.get('arabic_ratio', 0) > 0.5:
            suggestions.append({
                'type': 'language_optimization',
                'description': "High Arabic usage detected - consider Arabic-first models",
                'priority': 'medium',
            })
        
        return suggestions
    
    def _analyze_errors(self) -> List[str]:
        """Analyze error patterns from stats."""
        error_keys = self._storage.list_keys(collection="stats", pattern="errors:*")
        
        frequent_errors = []
        for key in error_keys:
            data = self._storage.retrieve(key, collection="stats")
            if data and isinstance(data, dict):
                count = data.get('count', 0)
                if count >= 3:
                    error_type = key.replace('errors:', '')
                    frequent_errors.append(f"{error_type} ({count})")
        
        return frequent_errors
    
    def _analyze_memory_patterns(self) -> Optional[str]:
        """Analyze memory creation patterns."""
        # Placeholder for pattern analysis
        return None
    
    def _analyze_language_usage(self) -> Dict[str, float]:
        """Analyze language usage from events."""
        # Placeholder - would analyze event language distribution
        return {'arabic_ratio': 0.0, 'english_ratio': 1.0}