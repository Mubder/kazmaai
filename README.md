# KazmaAI / المنسق الشامل

**Cross-platform AI Agent with Portable Persistence - Arabic Support**

وكيل ذكاء اصطناعي عبر المنصات مع ذاكرة محمولة - دعم اللغة العربية

A modular, self-contained AI agent that runs identically on Windows, macOS, Linux, and WSL. The entire agent — code, dependencies, vector databases, and project memories — resides in a single directory that can be moved anywhere without reconfiguration.

وكيل ذكاء اصطناعي معياري ذاتي-contained يعمل بشكل متماثل على Windows و macOS و Linux و WSL. الوكيل بأكمله - الكود والاعتمادات وقواعد البيانات المتجهة وذاكرات المشاريع - موجود في مجلد واحد يمكن نقله إلى أي مكان دون إعادة تكوين.

---

## Quick Start / البدء السريع

### 1. Clone / Copy

```bash
# Clone or copy the kazmaai directory anywhere
git clone https://github.com/Mubder/kazmaai.git
cd kazmaai
```

### 2. Initialize / التهيئة

```bash
# Install dependencies / تثبيت الاعتمادات
pip install -r requirements.txt

# Initialize the agent (creates .agent_root marker, directories, configs)
# تهيئة الوكيل (ينشئ علامة .agent_root والمجلدات والملفات الإعدادية)
python app/bootstrap.py init
```

### 3. Configure / الإعداد

```bash
# Edit configuration / تعديل الإعدادات
nano config/config.yaml

# Or use Arabic config / أو استخدم الإعدادات العربية
nano config/config.ar.yaml

# Set API keys (copy from example) / تعيين مفاتيح API
cp .env.example .env
nano .env
```

### 4. Run / التشغيل

```bash
# Start the orchestrator / تشغيل المنسق
python app/main.py
```

---

## Directory Structure / هيكل المجلدات

```
kazmaai/
├── .agent_root              # ← Marker for self-discovery / علامة الاكتشاف التلقائي
├── app/                     # Application code / كود التطبيق
│   ├── bootstrap.py         # Initialization & snapshots
│   ├── main.py              # Entry point
│   └── core/
│       ├── storage/
│       │   ├── base.py      # BaseStorageManager ABC
│       │   └── sqlite_backend.py
│       └── localization.py  # Arabic support / الدعم العربي
│
├── data/                    # ALL persistent data (portable) / جميع البيانات المستدامة
│   ├── memory/              # Vector embeddings, conversations / الذاكرة المتجهة والمحادثات
│   ├── projects/            # Active project states / حالات المشاريع النشطة
│   ├── cache/               # Ephemeral (safe to delete) / مؤقت (آمن للحذف)
│   └── backups/             # Snapshot archives / أرشيف اللقطات
│
├── config/
│   ├── config.yaml          # Unified configuration (English)
│   └── config.ar.yaml       # Unified configuration (Arabic / العربية)
│
├── logs/                    # Logs / السجلات
├── models/                  # Optional local models / نماذج محلية اختيارية
└── requirements.txt
```

---

## Key Features / الميزات الرئيسية

### 🚀 Portable Persistence / ذاكرة محمولة
- **Self-discovery**: Agent finds its root via `.agent_root` marker
  - الاكتشاف التلقائي: الوكيل يجد جذره عبر علامة `.agent_root`
- **Zero absolute paths**: All I/O via `pathlib` relative paths
  - بلا مسارات مطلقة: جميع العمليات عبر مسارات نسبية
- **Bootstrappable**: Move the folder → run → works
  - قابل للإقلاع الذاتي: انقل المجلد → شغّل → يعمل

### 🌐 Arabic Support / الدعم العربي
- **Full Unicode**: UTF-8 everywhere (config, database, logs)
  - يونيكود كامل: UTF-8 في كل مكان
- **RTL UI**: Right-to-left interface support
  - واجهة من اليمين لليسار
- **Arabic models**: Pre-configured for Jais, AraT5, etc.
  - نماذج عربية: مهيأ لـ Jais و AraT5 وغيرها
- **Bilingual config**: Choose English or Arabic config.yaml
  - إعدادات ثنائية اللغة: اختر config.yaml بالعربية أو الإنجليزية

### 📦 Snapshot & Restore / اللقطات والاستعادة
```bash
# Create backup / إنشاء نسخة احتياطية
python app/bootstrap.py snapshot

# Restore on new system / استعادة على نظام جديد
python app/bootstrap.py restore 2026-06-09_120000.zip --target /new/location/
```

### ⚙️ Unified Configuration / إعدادات موحدة
Single `config.yaml` controls:
ملف `config.yaml` واحد يتحكم في:

- Storage backends (SQLite, ChromaDB, etc.) / محركات التخزين
- Model providers (Ollama, OpenAI, Anthropic, OpenRouter) / مزودو النماذج
- Telegram bot integration (Phase 2) / تكامل بوت تليجرام
- Web interface (Phase 2) / واجهة الويب
- API keys via environment variable interpolation: `${OPENAI_API_KEY:-}`
  - مفاتيح API عبر استبدال متغيرات البيئة

---

## Configuration / الإعدادات

### Environment Variables / متغيرات البيئة

Edit `.env` or set in your shell:
عدّل `.env` أو اضبط في شل:

```bash
# API Keys / مفاتيح API
OPENAI_API_KEY=sk-......n
# Arabic language / اللغة العربية
AGENT_LANGUAGE=ar
AGENT_LANGUAGE_FALLBACK=en
```

### Config.yaml Highlights / أبرز الإعدادات

```yaml
# Choose your chat model / اختر نموذج المحادثة
models:
  chat:
    provider: ollama  # أو openai أو anthropic
    model: llama3.1:8b  # للعربية: jais:7b أو arat5-large

# Vector storage / التخزين المتجه
storage:
  vector_backend: chromadb
  chromadb:
    path: data/memory/vectors

# Telegram (Phase 2) / تليجرام
telegram:
  enabled: true
  bot_token: ${TELEGRAM_BOT_TOKEN}
  language: ar  # Arabic interface

# Web UI (Phase 2) / واجهة الويب
web:
  enabled: true
  port: 8080
  rtl_enabled: true  # RTL support for Arabic
```

---

## Storage Backend / محرك التخزين

### BaseStorageManager API

```python
from app.core.storage import SQLiteStorageManager

# Auto-discovers agent root /#ac;تذ ≈≥≥≥≥≥≥
storage = SQLiteStorageManager()

# Store/retrieve data / تخزين واسترجاع البيانات
storage.store("user_preferences", {"theme": "dark"}, collection="settings")
prefs = storage.retrieve("user_preferences", collection="settings")

# List keys / سرد المفاتيح
all_keys = storage.list_keys(collection="settings")
```

### Pluggable Backends / محركات قابلة للإضافة

- **SQLite**: Metadata, projects, conversations (default)
- **JSON**: Small configs, state files
- **ChromaDB/Qdrant**: Vector embeddings for semantic memory

---

## Arabic Localization / الترجمة العربية

### Using the Localization Module

```python
from app.core.localization import (
    is_arabic_text,
    get_text_direction,
    normalize_arabic,
    get_ui_string,
    write_utf8_file,
)

# Detect Arabic / كشف العربية
if is_arabic_text(user_message):
    print("Message is in Arabic")

# Get UI strings / الحصول على نصوص الواجهة
welcome = get_ui_string('agent_ready', language='ar')
# Output: "الوكيل جاهز"

# Write Arabic-safe files / كتابة ملفات آمنة للعربية
write_utf8_file(Path("data/arabic_note.txt"), "مرحبا بالعالم")
```

### Recommended Arabic Models / النماذج العربية الموصى بها

```yaml
models:
  chat:
    provider: ollama
    model: "jais:7b"  # Best for Arabic / الأفضل للعربية
    # or: "arat5-large" for translation
```

---

## Phase 2 Roadmap / خطة المرحلة 2

Once Phase 1 (Portable Persistence) is stable, we build:
ب استقرار المرحلة 1 (الذاكرة المحمولة)، نبني:

1. **Project-Centric Workspace**: Context tracking, file trees, task histories
   - مساحة عمل مركزة على المشاريع: تتبع السياق وأشجار الملفات وسجل المهام

2. **Memory & Self-Improvement**: Event-driven loop, interaction summaries
   - الذاكرة والتحسين الذاتي: حلقة مدفوعة بالأحداث وملخصات التفاعل

3. **Multimodal Interface**: Remote APIs + local LLMs, image/video generation
   - واجهة متعددة الوسائط: واجهات API بعيدة + نماذج محلية وتوليد صور/فيديو

4. **Telegram-First Integration**: Native bot with Event Bus communication
   - تكامل تليجرام أولاً: بوت أصلي مع اتصال ناقل الأحداث

5. **Web Interface**: FastAPI + HTMX with Chat/Project/Create workspaces
   - واجهة ويب: FastAPI + HTMX مع مساحات دردشة/مشاريع/إبداع

---

## Troubleshooting / استكشاف الأخطاء

### "Cannot discover agent root" / "لا يمكن اكتشاف جذر الوكيل"
Ensure `.agent_root` marker exists in the directory you're running from.
تأكد من وجود علامة `.agent_root` في المجلد الذي تشغّل منه.

### "Configuration file not found" / "ملف الإعدادات غير موجود"
Run `python app/bootstrap.py init` to create default configs.
شغّل `python app/bootstrap.py init` لإنشاء الإعدادات الافتراضية.

### Database locked errors / أخطاء قفل قاعدة البيانات
SQLite WAL mode allows concurrent reads. If writes conflict, increase timeout in `config.yaml`.
وضع WAL في SQLite يسمح بالقراءة المتزامنة. إذا تعارضت الكتابات، زد المهلة في `config.yaml`.

### Arabic text not displaying correctly / النص العربي لا يظهر بشكل صحيح
1. Ensure terminal/IDE supports UTF-8
   تأكد من أن الطرفية/المحرر يدعم UTF-8
2. Check `logging.encoding` is `utf-8` in config
   تحقق من أن `logging.encoding` هو `utf-8` في الإعدادات
3. Use RTL-aware UI (Phase 2 web interface)
   استخدم واجهة تدعم RTL (واجهة الويب في المرحلة 2)

---

## License / الترخيص

MIT

---

**Built for portability. Designed for longevity. Arabic from day one.**

**بُني للتنقل. صُمّم للاستمرارية. العربية من اليوم الأول.**