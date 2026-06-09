"""
Localization Utilities for KazmaAI

Provides:
- RTL/LTR text direction detection
- Arabic text normalization
- Multi-language message formatting
- Unicode-safe I/O helpers
"""

import re
import unicodedata
from pathlib import Path
from typing import Optional, Dict, Any


# Arabic Unicode range
ARABIC_RANGE = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]')

# Arabic punctuation
ARABIC_PUNCTUATION = {
    '؟': '?',  # Arabic question mark
    '،': ',',  # Arabic comma
    '؛': ';',  # Arabic semicolon
    '۔': '.',  # Arabic full stop
    '«': '"',  # Arabic left quote
    '»': '"',  # Arabic right quote
}


def is_arabic_text(text: str, threshold: float = 0.3) -> bool:
    """
    Detect if text is primarily Arabic.
    
    Args:
        text: Text to analyze
        threshold: Minimum ratio of Arabic characters (0.0-1.0)
        
    Returns:
        True if text is primarily Arabic
    """
    if not text:
        return False
    
    arabic_chars = len(ARABIC_RANGE.findall(text))
    total_chars = len(text.strip())
    
    if total_chars == 0:
        return False
    
    ratio = arabic_chars / total_chars
    return ratio >= threshold


def get_text_direction(text: str) -> str:
    """
    Determine text direction (RTL or LTR).
    
    Args:
        text: Text to analyze
        
    Returns:
        'rtl' for Arabic/Hebrew, 'ltr' for others
    """
    if is_arabic_text(text):
        return 'rtl'
    
    # Check for Hebrew
    if re.search(r'[\u0590-\u05FF]', text):
        return 'rtl'
    
    return 'ltr'


def normalize_arabic(text: str) -> str:
    """
    Normalize Arabic text for consistent processing.
    
    Normalizations:
    - Normalize alef forms (أ, إ, آ → ا)
    - Normalize yeh forms (ي, ى → ي)
    - Normalize heh forms (ة, ه → ه)
    - Remove tatweel (elongation character)
    - Normalize punctuation
    
    Args:
        text: Arabic text to normalize
        
    Returns:
        Normalized Arabic text
    """
    if not text:
        return text
    
    # Normalize alef forms
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    
    # Normalize yeh forms
    text = text.replace('ى', 'ي')
    
    # Normalize heh forms (ta marbuta)
    text = text.replace('ة', 'ه')
    
    # Remove tatweel (elongation)
    text = text.replace('ـ', '')
    
    # Normalize Unicode characters
    text = unicodedata.normalize('NFKC', text)
    
    return text


def denormalize_arabic(text: str, original: Optional[str] = None) -> str:
    """
    Convert normalized Arabic back to readable form.
    
    Note: This is approximate - some information is lost in normalization.
    
    Args:
        text: Normalized Arabic text
        original: Optional original text for reference
        
    Returns:
        Denormalized Arabic text
    """
    if not text:
        return text
    
    # Basic denormalization (context-aware would be better)
    # This is a simplified version
    text = text.replace('الله', 'الله')  # Keep "Allah" as is
    
    return text


def format_message(template: str, context: Dict[str, Any], language: str = 'ar') -> str:
    """
    Format a message template with context, supporting Arabic.
    
    Args:
        template: Message template with {placeholders}
        context: Dictionary of replacement values
        language: Language code ('ar' or 'en')
        
    Returns:
        Formatted message
    """
    try:
        # Ensure UTF-8 safe formatting
        if language == 'ar':
            # Normalize context values for Arabic
            context = {
                k: normalize_arabic(str(v)) if isinstance(v, str) else v
                for k, v in context.items()
            }
        
        return template.format(**context)
    except KeyError as e:
        # Fallback: return template with missing placeholders marked
        return f"[MISSING: {e}] {template}"


def wrap_rtl_text(text: str) -> str:
    """
    Wrap RTL text with Unicode direction markers.
    
    Args:
        text: Text to wrap
        
    Returns:
        Text with RTL direction markers
    """
    if get_text_direction(text) == 'rtl':
        # U+202B: RIGHT-TO-LEFT EMBEDDING
        # U+202C: POP DIRECTIONAL FORMATTING
        return '\u202b' + text + '\u202c'
    return text


def ensure_utf8_file(path: Path) -> None:
    """
    Ensure a file is readable as UTF-8 (for Arabic support).
    
    Args:
        path: Path to file
        
    Raises:
        UnicodeDecodeError: If file is not valid UTF-8
    """
    path = Path(path)
    if not path.exists():
        return
    
    # Try reading as UTF-8
    with open(path, 'r', encoding='utf-8') as f:
        f.read()


def write_utf8_file(path: Path, content: str) -> None:
    """
    Write content to file with UTF-8 encoding (Arabic-safe).
    
    Args:
        path: Path to file
        content: Text content (can contain Arabic)
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def read_utf8_file(path: Path) -> str:
    """
    Read file content as UTF-8 (Arabic-safe).
    
    Args:
        path: Path to file
        
    Returns:
        File content as string
    """
    path = Path(path)
    
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# Arabic UI strings for localization
ARABIC_UI_STRINGS = {
    # Agent status
    'agent_starting': 'جاري تشغيل الوكيل...',
    'agent_ready': 'الوكيل جاهز',
    'agent_processing': 'جاري المعالجة...',
    'agent_error': 'حدث خطأ',
    
    # Storage
    'storage_initialized': 'تم تهيئة التخزين',
    'storage_error': 'خطأ في التخزين',
    'backup_created': 'تم إنشاء نسخة احتياطية',
    'backup_restored': 'تم استعادة النسخة الاحتياطية',
    
    # Projects
    'project_created': 'تم إنشاء المشروع',
    'project_updated': 'تم تحديث المشروع',
    'project_deleted': 'تم حذف المشروع',
    'project_not_found': 'المشروع غير موجود',
    
    # Memory
    'memory_updated': 'تم تحديث الذاكرة',
    'memory_search': 'جاري البحث في الذاكرة...',
    'memory_no_results': 'لا توجد نتائج',
    
    # Commands
    'cmd_help': 'المساعدة',
    'cmd_status': 'الحالة',
    'cmd_new_project': 'مشروع جديد',
    'cmd_list_projects': 'قائمة المشاريع',
    'cmd_backup': 'نسخ احتياطي',
    'cmd_restore': 'استعادة',
    'cmd_settings': 'الإعدادات',
    
    # Errors
    'error_not_found': 'غير موجود',
    'error_permission_denied': 'تم رفض الإذن',
    'error_invalid_input': 'إدخال غير صالح',
    'error_network': 'خطأ في الشبكة',
    'error_timeout': 'انتهت المهلة',
    
    # Time
    'time_just_now': 'الآن',
    'time_minutes_ago': 'منذ {minutes} دقائق',
    'time_hours_ago': 'منذ {hours} ساعات',
    'time_days_ago': 'منذ {days} أيام',
}

ENGLISH_UI_STRINGS = {
    # Agent status
    'agent_starting': 'Starting agent...',
    'agent_ready': 'Agent ready',
    'agent_processing': 'Processing...',
    'agent_error': 'An error occurred',
    
    # Storage
    'storage_initialized': 'Storage initialized',
    'storage_error': 'Storage error',
    'backup_created': 'Backup created',
    'backup_restored': 'Backup restored',
    
    # Projects
    'project_created': 'Project created',
    'project_updated': 'Project updated',
    'project_deleted': 'Project deleted',
    'project_not_found': 'Project not found',
    
    # Memory
    'memory_updated': 'Memory updated',
    'memory_search': 'Searching memory...',
    'memory_no_results': 'No results found',
    
    # Commands
    'cmd_help': 'Help',
    'cmd_status': 'Status',
    'cmd_new_project': 'New Project',
    'cmd_list_projects': 'List Projects',
    'cmd_backup': 'Backup',
    'cmd_restore': 'Restore',
    'cmd_settings': 'Settings',
    
    # Errors
    'error_not_found': 'Not found',
    'error_permission_denied': 'Permission denied',
    'error_invalid_input': 'Invalid input',
    'error_network': 'Network error',
    'error_timeout': 'Timeout',
    
    # Time
    'time_just_now': 'Just now',
    'time_minutes_ago': '{minutes} minutes ago',
    'time_hours_ago': '{hours} hours ago',
    'time_days_ago': '{days} days ago',
}


def get_ui_string(key: str, language: str = 'ar') -> str:
    """
    Get a UI string in the specified language.
    
    Args:
        key: String key (e.g., 'agent_ready')
        language: Language code ('ar' or 'en')
        
    Returns:
        Localized string, or English fallback
    """
    if language == 'ar':
        return ARABIC_UI_STRINGS.get(key, ENGLISH_UI_STRINGS.get(key, key))
    else:
        return ENGLISH_UI_STRINGS.get(key, key)


def format_time_ago(minutes: int = 0, hours: int = 0, days: int = 0, 
                    language: str = 'ar') -> str:
    """
    Format a relative time string (e.g., "5 minutes ago").
    
    Args:
        minutes: Minutes ago
        hours: Hours ago
        days: Days ago
        language: Language code
        
    Returns:
        Formatted time string
    """
    if days > 0:
        return get_ui_string('time_days_ago', language).format(days=days)
    elif hours > 0:
        return get_ui_string('time_hours_ago', language).format(hours=hours)
    elif minutes > 0:
        return get_ui_string('time_minutes_ago', language).format(minutes=minutes)
    else:
        return get_ui_string('time_just_now', language)