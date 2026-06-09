"""
KazmaAI LLM Provider Module

Provides:
- Unified interface for multiple LLM providers (Ollama, OpenAI, Anthropic, OpenRouter)
- Arabic-optimized prompting
- Streaming support
- Context management
- Model fallback logic
"""

import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.localization import is_arabic_text, get_ui_string


@dataclass
class Message:
    """A single chat message."""
    role: str  # 'system', 'user', 'assistant'
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class LLMResponse:
    """Response from LLM provider."""
    content: str
    model: str
    provider: str
    usage: Dict[str, int] = field(default_factory=dict)
    finish_reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "model": self.model,
            "provider": self.provider,
            "usage": self.usage,
            "finish_reason": self.finish_reason,
        }


class LLMProvider:
    """
    Unified LLM provider for KazmaAI.
    
    Supports:
    - Ollama (local models)
    - OpenAI API
    - Anthropic API
    - OpenRouter
    - Local API (LM Studio, etc.)
    
    Features:
    - Automatic provider fallback
    - Arabic-optimized prompts
    - Streaming responses
    - Context window management
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize LLM provider.
        
        Args:
            config: Model configuration from config.yaml
        """
        self.config = config
        self.chat_config = config.get('chat', {})
        self.embedding_config = config.get('embedding', {})
        
        # Current provider
        self.current_provider = self.chat_config.get('provider', 'ollama')
        self.current_model = self.chat_config.get('model', 'llama3.1:8b')
        
        # Context management
        self.context_window = self.chat_config.get('context_length', 8192)
        self.max_tokens = self.chat_config.get('max_tokens', 4096)
        self.temperature = self.chat_config.get('temperature', 0.7)
        
        # Conversation history
        self.conversations: Dict[str, List[Message]] = {}
        
        # System prompt (bilingual)
        self.system_prompt = """You are KazmaAI (كازما أي آي), a helpful, bilingual AI assistant.

You speak both Arabic and English fluently. Respond in the same language the user uses.
If the user writes in Arabic, respond in Arabic. If they write in English, respond in English.

You are:
- Helpful and friendly / مفيد وودي
- Knowledgeable across many topics / ملم بالعديد من المواضيع
- Able to help with coding, writing, analysis, and more / قادر على المساعدة في البرمجة والكتابة والتحليل وأكثر

Keep your responses concise but informative. Use markdown formatting when appropriate.
Use Arabic script (العربية) for Arabic and Latin script for English.

أنت كازما أي آي، مساعد ذكي ثنائي اللغة. تحدث بنفس لغة المستخدم."""
    
    def _get_provider_config(self, provider_name: str) -> Dict[str, Any]:
        """Get configuration for a specific provider."""
        provider_config = self.chat_config.get(provider_name, {})
        
        # Merge with API keys
        api_keys = self.config.get('api_keys', {})
        if provider_name == 'openai':
            provider_config['api_key'] = api_keys.get('openai', '')
        elif provider_name == 'anthropic':
            provider_config['api_key'] = api_keys.get('anthropic', '')
        elif provider_name == 'openrouter':
            provider_config['api_key'] = api_keys.get('openrouter', '')
        
        return provider_config
    
    async def chat(
        self,
        message: str,
        conversation_id: str = "default",
        stream: bool = False,
    ) -> LLMResponse:
        """
        Send a chat message and get response.
        
        Args:
            message: User message
            conversation_id: Conversation identifier
            stream: If True, stream the response
            
        Returns:
            LLMResponse object
        """
        # Detect language
        language = 'ar' if is_arabic_text(message) else 'en'
        
        # Initialize conversation if needed
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = [
                Message(role="system", content=self.system_prompt),
            ]
        
        # Add user message to history
        self.conversations[conversation_id].append(Message(role="user", content=message))
        
        # Try providers in order of preference
        providers_to_try = [
            self.current_provider,
            'ollama',  # Fallback to local
            'openai',
            'openrouter',
        ]
        
        last_error = None
        
        for provider in providers_to_try:
            try:
                config = self._get_provider_config(provider)
                
                if provider == 'ollama':
                    response = await self._chat_ollama(
                        conversation_id,
                        config,
                        stream=stream,
                    )
                elif provider == 'openai':
                    response = await self._chat_openai(
                        conversation_id,
                        config,
                        stream=stream,
                    )
                elif provider == 'anthropic':
                    response = await self._chat_anthropic(
                        conversation_id,
                        config,
                        stream=stream,
                    )
                elif provider == 'openrouter':
                    response = await self._chat_openrouter(
                        conversation_id,
                        config,
                        stream=stream,
                    )
                else:
                    continue
                
                # Add assistant response to history
                self.conversations[conversation_id].append(
                    Message(role="assistant", content=response.content)
                )
                
                return response
                
            except Exception as e:
                last_error = e
                print(f"Provider {provider} failed: {e}")
                continue
        
        # All providers failed
        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")
    
    async def _chat_ollama(
        self,
        conversation_id: str,
        config: Dict[str, Any],
        stream: bool = False,
    ) -> LLMResponse:
        """Chat using Ollama."""
        import httpx
        
        base_url = config.get('base_url', 'http://localhost:11434')
        model = config.get('model', self.current_model)
        
        messages = [m.to_dict() for m in self.conversations[conversation_id]]
        
        # Remove timestamps for API
        for msg in messages:
            msg.pop('timestamp', None)
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            payload = {
                "model": model,
                "messages": messages,
                "stream": stream,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                },
            }
            
            if stream:
                # Streaming not fully implemented yet
                pass
            
            response = await client.post(
                f"{base_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            
            data = response.json()
            
            content = data.get('message', {}).get('content', '')
            
            return LLMResponse(
                content=content,
                model=model,
                provider='ollama',
                usage=data.get('prompt_eval_count', 0),
                finish_reason=data.get('done_reason', 'stop'),
            )
    
    async def _chat_openai(
        self,
        conversation_id: str,
        config: Dict[str, Any],
        stream: bool = False,
    ) -> LLMResponse:
        """Chat using OpenAI API."""
        import httpx
        
        api_key = config.get('api_key', '')
        if not api_key:
            raise ValueError("OpenAI API key not configured")
        
        base_url = config.get('base_url', 'https://api.openai.com/v1')
        model = config.get('model', 'gpt-4o-mini')
        
        messages = [m.to_dict() for m in self.conversations[conversation_id]]
        for msg in messages:
            msg.pop('timestamp', None)
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "stream": stream,
            }
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            
            response = await client.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            
            data = response.json()
            
            content = data['choices'][0]['message']['content']
            usage = data.get('usage', {})
            
            return LLMResponse(
                content=content,
                model=model,
                provider='openai',
                usage=usage,
                finish_reason=data['choices'][0]['finish_reason'],
            )
    
    async def _chat_anthropic(
        self,
        conversation_id: str,
        config: Dict[str, Any],
        stream: bool = False,
    ) -> LLMResponse:
        """Chat using Anthropic API."""
        # Placeholder - similar to OpenAI but with Anthropic's API format
        raise NotImplementedError("Anthropic support coming soon")
    
    async def _chat_openrouter(
        self,
        conversation_id: str,
        config: Dict[str, Any],
        stream: bool = False,
    ) -> LLMResponse:
        """Chat using OpenRouter API."""
        import httpx
        
        api_key = config.get('api_key', '')
        if not api_key:
            raise ValueError("OpenRouter API key not configured")
        
        base_url = config.get('base_url', 'https://openrouter.ai/api/v1')
        model = config.get('model', 'meta-llama/llama-3-8b-instruct')
        
        messages = [m.to_dict() for m in self.conversations[conversation_id]]
        for msg in messages:
            msg.pop('timestamp', None)
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Mubder/kazmaai",
                "X-Title": "KazmaAI",
            }
            
            response = await client.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            
            data = response.json()
            
            content = data['choices'][0]['message']['content']
            
            return LLMResponse(
                content=content,
                model=model,
                provider='openrouter',
                usage=data.get('usage', {}),
                finish_reason=data['choices'][0]['finish_reason'],
            )
    
    def clear_conversation(self, conversation_id: str) -> None:
        """Clear conversation history."""
        if conversation_id in self.conversations:
            self.conversations[conversation_id] = [
                Message(role="system", content=self.system_prompt),
            ]
    
    def get_conversation_history(self, conversation_id: str) -> List[Message]:
        """Get conversation history."""
        return self.conversations.get(conversation_id, [])
    
    async def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text using configured embedding model."""
        # Placeholder - would integrate with embedding provider
        return None


# Convenience function
async def chat_with_llm(
    message: str,
    config: Dict[str, Any],
    conversation_id: str = "default",
) -> str:
    """
    Quick chat function.
    
    Args:
        message: User message
        config: LLM configuration
        conversation_id: Conversation ID
        
    Returns:
        AI response text
    """
    provider = LLMProvider(config)
    response = await provider.chat(message, conversation_id)
    return response.content