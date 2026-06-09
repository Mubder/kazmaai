#!/usr/bin/env python3
"""
KazmaAI - Main Entry Point

كازما أي آي - نقطة الدخول الرئيسية

Cross-platform AI Agent with Portable Persistence
وكيل ذكاء اصطناعي عبر المنصات مع ذاكرة محمولة

Usage:
    python app/main.py              # Start KazmaAI
    python app/main.py --status     # Show status
    python app/main.py --config     # Show configuration
"""

import asyncio
import sys
import signal
from pathlib import Path
from datetime import datetime
from typing import Optional

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent))

from core.storage.sqlite_backend import SQLiteStorageManager
from core.events import EventBus, Event, EventType, agent_response_event
from core.localization import get_ui_string, is_arabic_text
from core.llm import LLMProvider
from projects.workspace import ProjectWorkspace
from memory.manager import MemoryManager, SelfImprovementEngine


class KazmaAI:
    """
    Main KazmaAI Agent class.
    
    Orchestrates all subsystems:
    - Storage (SQLite + Vector DB)
    - Event Bus
    - Project Workspace
    - Memory Manager
    - Interfaces (Telegram, Web - Phase 2)
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize KazmaAI agent.
        
        Args:
            config_path: Optional path to config file
        """
        print("🚀 " + get_ui_string('agent_starting', 'ar'))
        print("🚀 " + get_ui_string('agent_starting', 'en'))
        
        # Initialize storage
        print("  📦 " + get_ui_string('storage_initialized', 'ar'))
        print("  📦 " + get_ui_string('storage_initialized', 'en'))
        self.storage = SQLiteStorageManager(config_path)
        
        # Initialize event bus
        self.event_bus = EventBus(
            storage_manager=self.storage,
            db_path=self.storage.data_dir / "events.db",
        )
        
        # Initialize project workspace
        self.workspace = ProjectWorkspace(
            storage_manager=self.storage,
            event_bus=self.event_bus,
        )
        
        # Initialize memory manager
        self.memory = MemoryManager(
            storage_manager=self.storage,
            event_bus=self.event_bus,
        )
        
        # Initialize LLM provider
        self.llm = LLMProvider(self.storage.config.get('models', {}))
        
        # Initialize RAG engine (Phase 4)
        from memory.vector import VectorMemoryManager
        from rag.engine import RAGEngine
        
        self.vector_memory = VectorMemoryManager(
            config=self.storage.config.get('models', {}).get('embedding', {}),
            data_dir=self.storage.data_dir / "vectors",
        )
        
        self.rag = RAGEngine(
            llm_provider=self.llm,
            vector_memory=self.vector_memory,
            config=self.storage.config.get('rag', {
                'chunk_size': 512,
                'chunk_overlap': 50,
                'top_k': 5,
                'min_relevance': 0.5,
            }),
        )
        
        # Initialize self-improvement engine
        from memory.manager import SelfImprovementEngine
        self.improvement_engine = SelfImprovementEngine(
            memory_manager=self.memory,
            storage_manager=self.storage,
        )
        
        # Interfaces (Phase 2)
        self.telegram_bot = None
        self.web_app = None
        
        # State
        self._running = False
        self._shutdown_event = asyncio.Event()
        
        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print("\n🛑 Shutting down KazmaAI...")
        self._running = False
        self._shutdown_event.set()
    
    async def start(self):
        """Start the KazmaAI agent."""
        self._running = True
        
        # Emit startup event
        self.event_bus.publish(Event(
            event_type=EventType.AGENT_STARTED,
            data={
                'timestamp': datetime.utcnow().isoformat(),
                'version': self.storage.config.get('agent', {}).get('version', '1.0.0'),
            },
            priority=100,
        ))
        
        print("\n✅ " + get_ui_string('agent_ready', 'ar'))
        print("✅ " + get_ui_string('agent_ready', 'en'))
        print(f"\n📊 Stats:")
        print(f"   Projects: {len(self.workspace.list_projects())}")
        print(f"   Memories: {self.memory.get_stats()['total_memories']}")
        print(f"   Events: {self.event_bus.get_stats()['total_events']}")
        
        # Start interfaces (Phase 2)
        await self._start_interfaces()
        
        # Start event processing loop
        print("\n🔄 Starting event processing loop...")
        await self.event_bus.start_processing()
    
    async def stop(self):
        """Stop the KazmaAI agent."""
        self._running = False
        
        # Stop event processing
        self.event_bus.stop_processing()
        
        # Emit shutdown event
        self.event_bus.publish(Event(
            event_type=EventType.AGENT_STOPPED,
            data={'timestamp': datetime.utcnow().isoformat()},
        ))
        
        # Auto-backup if enabled
        if self.storage.config.get('backup', {}).get('auto_backup', True):
            print(f"💾 Creating automatic backup...")
            from bootstrap import create_snapshot
            try:
                snapshot_path = create_snapshot(root_path=self.storage.root)
                print(f"✅ " + get_ui_string('backup_created', 'ar'))
                print(f"✅ " + get_ui_string('backup_created', 'en'))
                print(f"   {snapshot_path}")
            except Exception as e:
                print(f"⚠️  Backup failed: {e}")
        
        # Close storage
        self.storage.close()
        
        print("\n👋 KazmaAI stopped.")
    
    async def _start_interfaces(self):
        """Start Telegram and Web interfaces."""
        import asyncio
        
        telegram_config = self.storage.config.get('telegram', {})
        web_config = self.storage.config.get('web', {})
        
        # Start Telegram bot if enabled
        if telegram_config.get('enabled', False) and telegram_config.get('bot_token'):
            from interfaces.telegram_bot import run_telegram_bot
            
            print("\n📱 Starting Telegram bot...")
            asyncio.create_task(run_telegram_bot(self, telegram_config))
        
        # Start web server if enabled
        if web_config.get('enabled', False):
            from interfaces.web import run_web_server
            
            print("🌐 Starting web interface...")
            asyncio.create_task(run_web_server(self, web_config))
    
    # =========================================================================
    # USER INTERFACE METHODS
    # =========================================================================
    
    async def chat(self, message: str, conversation_id: str = "default", use_rag: bool = True) -> str:
        """
        Process a user message and return agent response.
        
        Args:
            message: User message
            conversation_id: Conversation identifier
            use_rag: Whether to use RAG for context-aware responses
        
        Returns:
            Agent response
        """
        # Detect language
        language = 'ar' if is_arabic_text(message) else 'en'
        
        # Emit user message event
        self.event_bus.publish(Event(
            event_type=EventType.USER_MESSAGE,
            data={
                'message': message,
                'conversation_id': conversation_id,
                'language': language,
            },
            priority=10,
        ))
        
        # Process through RAG + LLM
        try:
            if use_rag:
                # Use RAG for context-aware response
                response = await self.rag.generate_response(
                    query=message,
                    conversation_id=conversation_id,
                    use_rag=True,
                )
            else:
                # Direct LLM query
                response_text = await self.llm.chat(message, conversation_id)
                response = response_text.content
        except Exception as e:
            # Fallback response
            if language == 'ar':
                response = f"عذراً، حدث خطأ: {e}\nسأقوم بالتحسن قريباً."
            else:
                response = f"Sorry, an error occurred: {e}\nI'll improve soon."
        
        # Emit agent response event
        self.event_bus.publish(Event(
            event_type=EventType.AGENT_RESPONSE,
            data={
                'message': response,
                'conversation_id': conversation_id,
                'language': language,
            },
            priority=10,
        ))
        
        return response
    
    def create_project(self, name: str, description: str = "", template: str = "default") -> str:
        """
        Create a new project.
        
        Args:
            name: Project name
            description: Project description
            template: Template to use
            
        Returns:
            Project ID
        """
        project = self.workspace.create_project(name, description, template)
        
        language = 'ar' if is_arabic_text(name) or is_arabic_text(description) else 'en'
        
        if language == 'ar':
            return f"تم إنشاء المشروع '{name}' (المعرف: {project.project_id})"
        else:
            return f"Project '{name}' created (ID: {project.project_id})"
    
    def list_projects(self) -> str:
        """List all projects."""
        projects = self.workspace.list_projects()
        
        if not projects:
            return get_ui_string('memory_no_results', 'ar') + "\n" + get_ui_string('memory_no_results', 'en')
        
        lines = []
        for project in projects:
            status_emoji = "✅" if project.status == "active" else "📦" if project.status == "archived" else "❌"
            lines.append(f"{status_emoji} {project.name} ({project.project_id[:8]}...) - {len(project.tasks)} tasks")
        
        return "\n".join(lines)
    
    def get_status(self) -> str:
        """Get agent status."""
        storage_stats = self.storage.get_stats() if hasattr(self.storage, 'get_stats') else {}
        event_stats = self.event_bus.get_stats()
        workspace_stats = self.workspace.get_stats()
        memory_stats = self.memory.get_stats()
        
        lines = [
            "📊 KazmaAI Status / حالة كازما أي آي\n",
            f"📁 Projects: {workspace_stats['total_projects']} ({workspace_stats['active_projects']} active)",
            f"🧠 Memories: {memory_stats['total_memories']}",
            f"📡 Events: {event_stats['total_events']} ({event_stats.get('stored_events', 0)} stored)",
            f"💾 Storage: {self.storage.data_dir}",
            f"🌐 Language: {self.storage.config.get('agent', {}).get('language', 'auto')}",
        ]
        
        return "\n".join(lines)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="KazmaAI - Cross-platform AI Agent")
    parser.add_argument("--status", action="store_true", help="Show agent status")
    parser.add_argument("--config", action="store_true", help="Show configuration")
    parser.add_argument("--chat", type=str, help="Send a chat message")
    parser.add_argument("--create-project", type=str, help="Create a new project")
    parser.add_argument("--list-projects", action="store_true", help="List all projects")
    
    args = parser.parse_args()
    
    # Initialize agent
    agent = KazmaAI()
    
    if args.status:
        print(agent.get_status())
        sys.exit(0)
    
    if args.config:
        import yaml
        print(yaml.dump(agent.storage.config, default_flow_style=False, allow_unicode=True))
        sys.exit(0)
    
    if args.chat:
        # One-off chat mode
        response = asyncio.run(agent.chat(args.chat))
        print("\n" + response)
        sys.exit(0)
    
    if args.create_project:
        # Create project with optional description
        parts = args.create_project.split(":", 1)
        name = parts[0].strip()
        description = parts[1].strip() if len(parts) > 1 else ""
        
        result = agent.create_project(name, description)
        print(result)
        sys.exit(0)
    
    if args.list_projects:
        print(agent.list_projects())
        sys.exit(0)
    
    # Start agent (interactive mode)
    try:
        asyncio.run(agent.start())
    except KeyboardInterrupt:
        asyncio.run(agent.stop())


if __name__ == "__main__":
    main()