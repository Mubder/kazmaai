"""
KazmaAI RAG (Retrieval-Augmented Generation) Module

Provides:
- Document ingestion and chunking
- Semantic search with vector embeddings
- Context-aware generation
- Multi-source retrieval (memory, files, web)
- Arabic/English bilingual support
"""

import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import re

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.llm import LLMProvider
from memory.vector import VectorMemoryManager, SearchResult


@dataclass
class Document:
    """Document for RAG."""
    id: str
    content: str
    source: str  # file path, URL, memory, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "source": self.source,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Chunk:
    """Document chunk for embedding."""
    id: str
    text: str
    document_id: str
    start_index: int
    end_index: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RAGContext:
    """Retrieved context for generation."""
    query: str
    documents: List[Document]
    chunks: List[Chunk]
    search_results: List[SearchResult]
    total_relevance: float = 0.0


class RAGEngine:
    """
    RAG engine for KazmaAI.
    
    Features:
    - Multi-source document ingestion
    - Smart chunking with overlap
    - Semantic retrieval
    - Context-aware generation
    - Bilingual support (Arabic/English)
    """
    
    def __init__(
        self,
        llm_provider: LLMProvider,
        vector_memory: VectorMemoryManager,
        config: Dict[str, Any],
    ):
        """
        Initialize RAG engine.
        
        Args:
            llm_provider: LLM provider for generation
            vector_memory: Vector memory for embeddings
            config: RAG configuration
        """
        self.llm = llm_provider
        self.vector_memory = vector_memory
        self.config = config
        
        # Chunking settings
        self.chunk_size = config.get('chunk_size', 512)
        self.chunk_overlap = config.get('chunk_overlap', 50)
        
        # Retrieval settings
        self.top_k = config.get('top_k', 5)
        self.min_relevance = config.get('min_relevance', 0.5)
        
        # Document cache
        self._documents: Dict[str, Document] = {}
    
    async def ingest_document(
        self,
        content: str,
        source: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Ingest a document into RAG system.
        
        Args:
            content: Document text
            source: Source identifier (file path, URL, etc.)
            metadata: Additional metadata
            
        Returns:
            Document ID
        """
        # Create document
        doc_id = hashlib.md5(
            f"{content}{source}{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()
        
        document = Document(
            id=doc_id,
            content=content,
            source=source,
            metadata=metadata or {},
        )
        
        # Cache it
        self._documents[doc_id] = document
        
        # Chunk the document
        chunks = self._chunk_text(content, doc_id)
        
        # Add chunks to vector memory
        for chunk in chunks:
            await self.vector_memory.add_memory(
                content=chunk.text,
                metadata={
                    "type": "chunk",
                    "document_id": doc_id,
                    "source": source,
                    "start_index": chunk.start_index,
                    "end_index": chunk.end_index,
                    **(metadata or {}),
                },
            )
        
        return doc_id
    
    async def ingest_file(
        self,
        file_path: Union[str, Path],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Ingest a file into RAG system.
        
        Args:
            file_path: Path to file
            metadata: Additional metadata
            
        Returns:
            Document ID
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Read file
        content = file_path.read_text(encoding='utf-8')
        
        # Add file metadata
        file_metadata = {
            "filename": file_path.name,
            "filepath": str(file_path.absolute()),
            "size": file_path.stat().st_size,
            "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
            **(metadata or {}),
        }
        
        return await self.ingest_document(
            content=content,
            source=str(file_path),
            metadata=file_metadata,
        )
    
    def _chunk_text(self, text: str, document_id: str) -> List[Chunk]:
        """
        Split text into overlapping chunks.
        
        Args:
            text: Text to chunk
            document_id: Parent document ID
            
        Returns:
            List of chunks
        """
        chunks = []
        
        # Simple sentence-aware chunking
        sentences = re.split(r'(?<=[.!?۔۔۔])\s+', text)
        
        current_chunk = ""
        current_start = 0
        
        for i, sentence in enumerate(sentences):
            if len(current_chunk) + len(sentence) <= self.chunk_size:
                current_chunk += " " + sentence if current_chunk else sentence
            else:
                # Save current chunk
                if current_chunk.strip():
                    chunk_id = hashlib.md5(
                        f"{document_id}{i}{current_chunk}".encode()
                    ).hexdigest()
                    
                    chunks.append(Chunk(
                        id=chunk_id,
                        text=current_chunk.strip(),
                        document_id=document_id,
                        start_index=current_start,
                        end_index=current_start + len(current_chunk),
                        metadata={"sentence_count": len(current_chunk.split())},
                    ))
                
                # Start new chunk with overlap
                overlap_text = current_chunk[-self.chunk_overlap:] if self.chunk_overlap > 0 else ""
                current_chunk = overlap_text + " " + sentence
                current_start = max(0, current_start + len(current_chunk) - self.chunk_overlap)
        
        # Add final chunk
        if current_chunk.strip():
            chunk_id = hashlib.md5(
                f"{document_id}final{current_chunk}".encode()
            ).hexdigest()
            
            chunks.append(Chunk(
                id=chunk_id,
                text=current_chunk.strip(),
                document_id=document_id,
                start_index=current_start,
                end_index=len(text),
                metadata={"sentence_count": len(current_chunk.split())},
            ))
        
        return chunks
    
    async def retrieve_context(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> RAGContext:
        """
        Retrieve relevant context for a query.
        
        Args:
            query: Search query
            top_k: Number of results (overrides default)
            filters: Metadata filters
            
        Returns:
            RAGContext with retrieved documents
        """
        top_k = top_k or self.top_k
        
        # Search vector memory
        search_results = await self.vector_memory.search_memories(
            query=query,
            limit=top_k * 2,  # Get more to filter
            min_similarity=self.min_relevance,
        )
        
        # Apply filters if provided
        if filters:
            filtered_results = []
            for result in search_results:
                if self._matches_filters(result.memory.metadata, filters):
                    filtered_results.append(result)
            search_results = filtered_results[:top_k]
        
        # Reconstruct documents from chunks
        documents = []
        chunks = []
        
        document_ids = set()
        for result in search_results:
            # Find or create document
            doc_id = result.memory.metadata.get('document_id')
            
            if doc_id and doc_id not in document_ids:
                document_ids.add(doc_id)
                
                if doc_id in self._documents:
                    documents.append(self._documents[doc_id])
            
            # Create chunk from search result
            chunk = Chunk(
                id=result.memory.id,
                text=result.memory.content,
                document_id=doc_id or "unknown",
                start_index=result.memory.metadata.get('start_index', 0),
                end_index=result.memory.metadata.get('end_index', len(result.memory.content)),
                metadata=result.memory.metadata,
            )
            chunks.append(chunk)
        
        # Calculate total relevance
        total_relevance = sum(r.similarity for r in search_results)
        
        return RAGContext(
            query=query,
            documents=documents,
            chunks=chunks,
            search_results=search_results,
            total_relevance=total_relevance,
        )
    
    def _matches_filters(
        self,
        metadata: Dict[str, Any],
        filters: Dict[str, Any],
    ) -> bool:
        """Check if metadata matches filters."""
        for key, value in filters.items():
            if metadata.get(key) != value:
                return False
        return True
    
    async def generate_response(
        self,
        query: str,
        context: Optional[RAGContext] = None,
        conversation_id: str = "default",
        use_rag: bool = True,
    ) -> str:
        """
        Generate response with optional RAG context.
        
        Args:
            query: User query
            context: Retrieved context (if None, will retrieve)
            conversation_id: Conversation ID
            use_rag: Whether to use RAG
            
        Returns:
            Generated response
        """
        if use_rag and not context:
            context = await self.retrieve_context(query)
        
        # Build prompt with context
        if use_rag and context and context.chunks:
            # Format retrieved context
            context_text = self._format_context(context)
            
            # Create RAG prompt
            prompt = f"""You are KazmaAI, a helpful bilingual assistant. Answer the user's question based on the retrieved context below.

**Retrieved Context:**
{context_text}

**Instructions:**
- Answer in the same language as the question
- Only use information from the context above
- If the context doesn't contain the answer, say you don't have that information
- Cite relevant sources when possible
- Be concise but informative

**Question:** {query}

**Answer:**"""
        else:
            # Regular query without context
            prompt = query
        
        # Generate response via LLM
        response = await self.llm.chat(prompt, conversation_id)
        
        return response.content
    
    def _format_context(self, context: RAGContext) -> str:
        """Format retrieved context for prompt."""
        formatted = []
        
        for i, chunk in enumerate(context.chunks, 1):
            source = chunk.metadata.get('source', 'Unknown')
            relevance = next(
                (r.similarity for r in context.search_results if r.memory.id == chunk.id),
                0.0
            )
            
            formatted.append(f"""
[Source {i}] (Relevance: {relevance:.2f})
{chunk.text[:300]}{'...' if len(chunk.text) > 300 else ''}
---
""")
        
        return "\n".join(formatted)
    
    async def clear_cache(self) -> None:
        """Clear document cache."""
        self._documents.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get RAG statistics."""
        return {
            "cached_documents": len(self._documents),
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "top_k": self.top_k,
            "min_relevance": self.min_relevance,
        }


# Convenience function for integration
async def rag_query(
    query: str,
    llm_provider: LLMProvider,
    vector_memory: VectorMemoryManager,
    config: Dict[str, Any],
    conversation_id: str = "default",
) -> str:
    """
    Quick RAG query.
    
    Args:
        query: User query
        llm_provider: LLM provider
        vector_memory: Vector memory manager
        config: RAG configuration
        conversation_id: Conversation ID
        
    Returns:
        Generated response
    """
    engine = RAGEngine(llm_provider, vector_memory, config)
    return await engine.generate_response(
        query=query,
        conversation_id=conversation_id,
        use_rag=True,
    )