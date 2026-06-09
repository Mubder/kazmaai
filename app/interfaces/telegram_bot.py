"""
KazmaAI Telegram Bot Integration

Provides:
- Native Telegram bot with Arabic/English support
- Command handlers for chat, projects, memory
- Event bus integration for real-time updates
- RTL-aware message formatting
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.events import EventBus, Event, EventType
from core.localization import get_ui_string, is_arabic_text, get_text_direction
from projects.workspace import ProjectWorkspace
from memory.manager import MemoryManager
from main import KazmaAI


# Arabic commands
ARABIC_COMMANDS = {
    "start": "ابدأ - بدء المحادثة",
    "help": "مساعدة - عرض المساعدة",
    "status": "حالة - حالة الوكيل",
    "chat": "دردشة - إرسال رسالة",
    "projects": "مشاريع - قائمة المشاريع",
    "newproject": "مشروع جديد - إنشاء مشروع",
    "memory": "ذاكرة - البحث في الذاكرة",
    "settings": "إعدادات - الإعدادات",
}

# English commands
ENGLISH_COMMANDS = {
    "start": "start - Begin conversation",
    "help": "help - Show help",
    "status": "status - Agent status",
    "chat": "chat - Send message",
    "projects": "projects - List projects",
    "newproject": "newproject - Create project",
    "memory": "memory - Search memory",
    "settings": "settings - Settings",
}


class TelegramBot:
    """
    Telegram bot for KazmaAI.
    
    Features:
    - Bilingual (Arabic/English) interface
    - Command-based interaction
    - Event-driven notifications
    - RTL-aware formatting
    """
    
    def __init__(
        self,
        agent: KazmaAI,
        bot_token: str,
        allowed_users: Optional[list] = None,
        home_chat_id: Optional[str] = None,
    ):
        """
        Initialize Telegram bot.
        
        Args:
            agent: KazmaAI agent instance
            bot_token: Telegram bot token
            allowed_users: List of allowed user IDs (None = all)
            home_chat_id: Chat ID for unprompted updates
        """
        self.agent = agent
        self.bot_token = bot_token
        self.allowed_users = allowed_users or []
        self.home_chat_id = home_chat_id
        
        # Event bus subscription
        self.event_bus = agent.event_bus
        
        # Bot application
        self.application: Optional[Application] = None
        
        # Logging
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO,
        )
        self.logger = logging.getLogger(__name__)
    
    def _is_user_allowed(self, user_id: int) -> bool:
        """Check if user is allowed to interact."""
        if not self.allowed_users:
            return True
        return user_id in self.allowed_users
    
    def _detect_language(self, text: str) -> str:
        """Detect message language."""
        return 'ar' if is_arabic_text(text) else 'en'
    
    def _format_message(self, text: str, language: str = 'ar') -> str:
        """Format message with appropriate direction markers."""
        if get_text_direction(text) == 'rtl':
            return f"\u202b{text}\u202c"
        return text
    
    async def start(self):
        """Start the Telegram bot."""
        # Create application
        self.application = Application.builder().token(self.bot_token).build()
        
        # Register handlers
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("help", self.cmd_help))
        self.application.add_handler(CommandHandler("status", self.cmd_status))
        self.application.add_handler(CommandHandler("projects", self.cmd_projects))
        self.application.add_handler(CommandHandler("newproject", self.cmd_newproject))
        self.application.add_handler(CommandHandler("memory", self.cmd_memory))
        self.application.add_handler(CommandHandler("settings", self.cmd_settings))
        
        # Chat message handler (non-command)
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.on_message,
        ))
        
        # Set bot commands
        await self._set_bot_commands()
        
        # Subscribe to events for notifications
        self._subscribe_to_events()
        
        # Start bot
        self.logger.info("Starting Telegram bot...")
        await self.application.initialize()
        await self.application.start()
        
        if self.home_chat_id:
            await self.send_notification(
                "🤖 " + get_ui_string('agent_ready', 'ar') + "\n" +
                "🤖 " + get_ui_string('agent_ready', 'en'),
                chat_id=self.home_chat_id,
            )
    
    async def stop(self):
        """Stop the Telegram bot."""
        if self.application:
            await self.application.stop()
            self.logger.info("Telegram bot stopped.")
    
    async def _set_bot_commands(self):
        """Set bot command list in Telegram."""
        if not self.application or not self.application.bot:
            return
        
        commands = [
            BotCommand("start", ARABIC_COMMANDS['start']),
            BotCommand("help", ARABIC_COMMANDS['help']),
            BotCommand("status", ARABIC_COMMANDS['status']),
            BotCommand("projects", ARABIC_COMMANDS['projects']),
            BotCommand("newproject", ARABIC_COMMANDS['newproject']),
            BotCommand("memory", ARABIC_COMMANDS['memory']),
        ]
        
        await self.application.bot.set_my_commands(commands)
    
    def _subscribe_to_events(self):
        """Subscribe to agent events for notifications."""
        self.event_bus.subscribe_async(EventType.AGENT_RESPONSE, self._on_agent_response)
        self.event_bus.subscribe_async(EventType.ERROR, self._on_error)
        self.event_bus.subscribe_async(EventType.PROJECT_CREATED, self._on_project_created)
    
    async def _on_agent_response(self, event: Event):
        """Handle agent response events."""
        # Only notify if there's a home chat
        if self.home_chat_id and event.data.get('conversation_id') == 'default':
            message = event.data.get('message', '')
            await self.send_notification(f"🤖 {message}", chat_id=self.home_chat_id)
    
    async def _on_error(self, event: Event):
        """Handle error events."""
        if self.home_chat_id:
            message = event.data.get('message', 'Unknown error')
            await self.send_notification(f"❌ خطأ: {message}", chat_id=self.home_chat_id)
    
    async def _on_project_created(self, event: Event):
        """Handle project creation events."""
        if self.home_chat_id:
            project_name = event.data.get('name', 'Unnamed')
            lang = event.data.get('language', 'en')
            
            if lang == 'ar':
                msg = f"✅ تم إنشاء المشروع: {project_name}"
            else:
                msg = f"✅ Project created: {project_name}"
            
            await self.send_notification(msg, chat_id=self.home_chat_id)
    
    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        if not self._is_user_allowed(update.effective_user.id):
            return
        
        language = 'ar'  # Default to Arabic for start
        
        welcome_ar = """
🤖 مرحباً بك في كازما أي آي!

أنا وكيل ذكاء اصطناعي عبر المنصات مع ذاكرة محمولة.

الأوامر المتاحة:
/start - بدء المحادثة
/help - عرض المساعدة
/status - حالة الوكيل
/projects - قائمة المشاريع
/newproject <name> - إنشاء مشروع جديد
/memory <query> - البحث في الذاكرة
/settings - الإعدادات

ابدأ بالدردشة مباشرة أو استخدم أحد الأوامر أعلاه!
"""
        
        welcome_en = """
🤖 Welcome to KazmaAI!

I'm a cross-platform AI agent with portable persistence.

Available commands:
/start - Start conversation
/help - Show help
/status - Agent status
/projects - List projects
/newproject <name> - Create new project
/memory <query> - Search memory
/settings - Settings

Start chatting or use one of the commands above!
"""
        
        response = welcome_ar + "\n" + welcome_en
        await update.message.reply_text(self._format_message(response, language))
    
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        if not self._is_user_allowed(update.effective_user.id):
            return
        
        help_text = """
📚 KazmaAI Help / مساعدة كازما أي آي

🗨️ Chat / دردشة:
Just send a message and I'll respond!
أرسل رسالة وسأرد عليك!

📁 Projects / المشاريع:
/projects - List all projects / عرض جميع المشاريع
/newproject My Project - Create project / إنشاء مشروع

🧠 Memory / الذاكرة:
/memory query - Search memories / البحث في الذكريات

⚙️ Settings / الإعدادات:
/status - Show agent status / عرض حالة الوكيل
/settings - Configure settings / تكوين الإعدادات

💡 Tips / نصائح:
- I support both Arabic and English / أدعم العربية والإنجليزية
- Your data is stored locally / بياناتك مخزنة محلياً
- Everything is portable / كل شيء قابل للنقل
"""
        
        await update.message.reply_text(self._format_message(help_text, 'ar'))
    
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        if not self._is_user_allowed(update.effective_user.id):
            return
        
        status = self.agent.get_status()
        await update.message.reply_text(self._format_message(status, 'ar'))
    
    async def cmd_projects(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /projects command."""
        if not self._is_user_allowed(update.effective_user.id):
            return
        
        projects = self.agent.list_projects()
        
        if not projects:
            response_ar = "📁 لا توجد مشاريع بعد. استخدم /newproject لإنشاء واحد!"
            response_en = "📁 No projects yet. Use /newproject to create one!"
            response = response_ar + "\n\n" + response_en
        else:
            response = projects
        
        await update.message.reply_text(self._format_message(response, 'ar'))
    
    async def cmd_newproject(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /newproject command."""
        if not self._is_user_allowed(update.effective_user.id):
            return
        
        if not context.args:
            response_ar = "❌ الاستخدام: /newproject <اسم المشروع>"
            response_en = "❌ Usage: /newproject <project name>"
            await update.message.reply_text(response_ar + "\n\n" + response_en)
            return
        
        project_name = " ".join(context.args)
        result = self.agent.create_project(project_name)
        
        await update.message.reply_text(self._format_message(result, 'ar'))
    
    async def cmd_memory(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /memory command."""
        if not self._is_user_allowed(update.effective_user.id):
            return
        
        if not context.args:
            response_ar = "❌ الاستخدام: /memory <search query>"
            response_en = "❌ Usage: /memory <search query>"
            await update.message.reply_text(response_ar + "\n\n" + response_en)
            return
        
        query = " ".join(context.args)
        
        # Search memories
        memories = self.agent.memory.search_memories(query, limit=5)
        
        if not memories:
            response_ar = f"🧠 لم يتم العثور على ذكريات لـ '{query}'"
            response_en = f"🧠 No memories found for '{query}'"
        else:
            response_ar = f"🧠 ذكريات لـ '{query}':\n"
            response_en = f"🧠 Memories for '{query}':\n"
            
            for i, mem in enumerate(memories, 1):
                response_ar += f"{i}. {mem.content[:100]}...\n"
                response_en += f"{i}. {mem.content[:100]}...\n"
        
        response = response_ar + "\n" + response_en
        await update.message.reply_text(self._format_message(response, 'ar'))
    
    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /settings command."""
        if not self._is_user_allowed(update.effective_user.id):
            return
        
        settings_ar = """
⚙️ إعدادات كازما أي آي

اللغة: العربية / English
التخزين: SQLite
الذاكرة: مفعلة
المشاريع: مفعلة

لتغيير الإعدادات، عدّل ملف config.yaml
"""
        
        settings_en = """
⚙️ KazmaAI Settings

Language: Arabic / English
Storage: SQLite
Memory: Enabled
Projects: Enabled

To change settings, edit config.yaml
"""
        
        response = settings_ar + "\n" + settings_en
        await update.message.reply_text(self._format_message(response, 'ar'))
    
    async def on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle regular chat messages."""
        if not self._is_user_allowed(update.effective_user.id):
            return
        
        message_text = update.message.text
        language = self._detect_language(message_text)
        
        # Process through agent
        response = await self.agent.chat(
            message_text,
            conversation_id=f"telegram_{update.effective_user.id}",
        )
        
        # Reply
        await update.message.reply_text(self._format_message(response, language))
    
    async def send_notification(self, message: str, chat_id: Optional[str] = None):
        """
        Send a notification message.
        
        Args:
            message: Message text
            chat_id: Target chat ID (uses home_chat_id if None)
        """
        if not self.application or not self.application.bot:
            return
        
        target_chat = chat_id or self.home_chat_id
        if not target_chat:
            return
        
        try:
            await self.application.bot.send_message(
                chat_id=target_chat,
                text=self._format_message(message, 'ar'),
                parse_mode=None,
            )
        except Exception as e:
            self.logger.error(f"Failed to send notification: {e}")


async def run_telegram_bot(agent: KazmaAI, config: Dict[str, Any]):
    """
    Run Telegram bot as part of KazmaAI.
    
    Args:
        agent: KazmaAI agent instance
        config: Telegram configuration from config.yaml
    """
    if not config.get('enabled', False):
        return
    
    bot_token = config.get('bot_token', '')
    if not bot_token:
        print("⚠️  Telegram bot token not configured")
        return
    
    bot = TelegramBot(
        agent=agent,
        bot_token=bot_token,
        allowed_users=config.get('allowed_users', []),
        home_chat_id=config.get('home_chat_id'),
    )
    
    try:
        await bot.start()
        
        # Keep running until shutdown
        while True:
            await asyncio.sleep(1)
    
    except KeyboardInterrupt:
        await bot.stop()