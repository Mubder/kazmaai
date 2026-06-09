"""
KazmaAI Vector Memory Module

Provides:
- Semantic memory search with embeddings
- ChromaDB integration for vector storage
- Sentence transformers for Arabic/English embeddings
- Similarity search and clustering
"""

import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import hashlib

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import chromadb
    from chromadb.config import Settings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False
    chromadb = None

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    SentenceTransformer = None


@dataclass
class MemoryEmbedding:
    """Embedded memory with vector."""
    id: str
    content: str
    embedding: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "embedding": self.embedding,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class SearchResult:
    """Search result with similarity score."""
    memory: MemoryEmbedding
    similarity: float
    rank: int


class VectorMemoryManager:
    """
    Vector-based memory manager for semantic search.
    
    Features:
    - Bilingual embeddings (Arabic + English)
    - Semantic similarity search
    - Automatic clustering
    - Persistent storage with ChromaDB
    """
    
    def __init__(self, config: Dict[str, Any], data_dir: Optional[Path] = None):
        """
        Initialize vector memory manager.
        
        Args:
            config: Vector memory configuration
            data_dir: Directory for persistent storage
        """
        self.config = config
        self.data_dir = data_dir or Path(__file__).parent.parent.parent / "data" / "vectors"
        
        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize embedding model
        self._embedding_model = None
        
        # Initialize ChromaDB
        self._collection = None
        
        # Cache for embeddings
        self._embedding_cache: Dict[str, List[float]] = {}
    
    @property
    def embedding_model(self) -> Optional[Any]:
        """Lazy-load embedding model."""
        if self._embedding_model is None and SENTENCE_TRANSFORMERS_AVAILABLE:
            # Use multilingual model for Arabic + English support
            model_name = self.config.get('model', 'paraphrase-multilingual-MiniLM-L12-v2')
            self._embedding_model = SentenceTransformer(model_name)
        return self._embedding_model
    
    @property
    def collection(self) -> Optional[Any]:
        """Lazy-load ChromaDB collection."""
        if self._collection is None and CHROMA_AVAILABLE:
            # Initialize ChromaDB with persistence
            client = chromadb.PersistentClient(
                path=str(self.data_dir / "chroma"),
                settings=Settings(anonymized_telemetry=False),
            )
            
            # Get or create collection
            self._collection = client.get_or_create_collection(
                name="kazma_memories",
                metadata={"hnsw:space": "cosine"},  # Cosine similarity
            )
        
        return self._collection
    
    async def initialize(self) -> bool:
        """
        Initialize vector memory system.
        
        Returns:
            True if successful, False if dependencies missing
        """
        if not CHROMA_AVAILABLE:
            print("⚠️  ChromaDB not installed. Run: pip install chromadb")
            return False
        
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            print("⚠️  Sentence Transformers not installed. Run: pip install sentence-transformers")
            return False
        
        # Warm up the model
        if self.embedding_model:
            # Generate a dummy embedding to load the model
            _ = self.embedding_model.encode("test")
            print("✅ Vector memory initialized")
        
        return True
    
    async def add_memory(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Add memory with embedding.
        
        Args:
            content: Memory text
            metadata: Additional metadata
            
        Returns:
            Memory ID
        """
        if not self.collection or not self.embedding_model:
            raise RuntimeError("Vector memory not initialized")
        
        # Generate embedding
        embedding = await self._generate_embedding(content)
        
        # Create unique ID
        memory_id = hashlib.md5(
            f"{content}{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()
        
        # Add to collection
        self.collection.add(
            ids=[memory_id],
            embeddings=[embedding],
            metadatas=[metadata or {}],
            documents=[content],
        )
        
        # Cache embedding
        self._embedding_cache[content] = embedding
        
        return memory_id
    
    async def search_memories(
        self,
        query: str,
        limit: int = 5,
        min_similarity: float = 0.5,
    ) -> List[SearchResult]:
        """
        Search memories by semantic similarity.
        
        Args:
            query: Search query
            limit: Max results
            min_similarity: Minimum similarity threshold
            
        Returns:
            List of search results
        """
        if not self.collection or not self.embedding_model:
            return []
        
        # Generate query embedding
        query_embedding = await self._generate_embedding(query)
        
        # Search collection
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=limit * 2,  # Get more to filter by similarity
            include=["documents", "metadatas", "distances"],
        )
        
        # Parse results
        search_results = []
        
        if results and results['ids'] and results['ids'][0]:
            for i, memory_id in enumerate(results['ids'][0]):
                distance = results['distances'][0][i]
                similarity = 1.0 - distance  # Convert distance to similarity
                
                if similarity >= min_similarity:
                    memory = MemoryEmbedding(
                        id=memory_id,
                        content=results['documents'][0][i],
                        embedding=[],  # Don't return full embedding
                        metadata=results['metadatas'][0][i] if results['metadatas'] else {},
                    )
                    
                    search_results.append(SearchResult(
                        memory=memory,
                        similarity=similarity,
                        rank=len(search_results) + 1,
                    ))
        
        return search_results[:limit]
    
    async def _generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for text."""
        if not self.embedding_model:
            raise RuntimeError("Embedding model not loaded")
        
        # Check cache
        if text in self._embedding_cache:
            return self._embedding_cache[text]
        
        # Generate embedding
        embedding = self.embedding_model.encode(
            text,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        
        embedding_list = embedding.tolist()
        
        # Cache it
        self._embedding_cache[text] = embedding_list
        
        return embedding_list
    
    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory by ID."""
        if not self.collection:
            return False
        
        self.collection.delete(ids=[memory_id])
        return True
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        if not self.collection:
            return {"total_memories": 0, "cache_size": 0}
        
        return {
            "total_memories": self.collection.count(),
            "cache_size": len(self._embedding_cache),
            "collection_name": self.collection.name,
        }
    
    async def clear_cache(self) -> None:
        """Clear embedding cache."""
        self._embedding_cache.clear()
    
    async def cluster_memories(
        self,
        n_clusters: int = 5,
    ) -> List[List[SearchResult]]:
        """
        Cluster memories by similarity.
        
        Args:
            n_clusters: Number of clusters
            
        Returns:
            List of clusters (each cluster is a list of memories)
        """
        from sklearn.cluster import KMeans
        import numpy as np
        
        if not self.collection:
            return []
        
        # Get all memories
        all_memories = self.collection.get(
            include=["embeddings", "documents", "metadatas"],
        )
        
        if not all_memories['embeddings']:
            return []
        
        # Convert to numpy array
        embeddings = np.array(all_memories['embeddings'])
        
        # Cluster
        kmeans = KMeans(n_clusters=min(n_clusters, len(embeddings)))
        labels = kmeans.fit_predict(embeddings)
        
        # Group by cluster
        clusters = []
        for cluster_id in range(n_clusters):
            cluster_indices = np.where(labels == cluster_id)[0]
            
            cluster_memories = []
            for idx in cluster_indices:
                memory = MemoryEmbedding(
                    id=all_memories['ids'][idx],
                    content=all_memories['documents'][idx],
                    embedding=[],
                    metadata=all_memories['metadatas'][idx] if all_memories['metadatas'] else {},
                )
                
                cluster_memories.append(SearchResult(
                    memory=memory,
                    similarity=1.0,  # All in cluster
                    rank=0,
                ))
            
            if cluster_memories:
                clusters.append(cluster_memories)
        
        return clusters


# Convenience function for integration
async def search_semantic_memories(
    query: str,
    config: Dict[str, Any],
    data_dir: Optional[Path] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Quick semantic search.
    
    Args:
        query: Search query
        config: Vector memory configuration
        data_dir: Data directory
        limit: Max results
        
    Returns:
        List of search results (as dicts)
    """
    manager = VectorMemoryManager(config, data_dir)
    
    if not await manager.initialize():
        return []
    
    results = await manager.search_memories(query, limit=limit)
    
    return [
        {
            "content": r.memory.content,
            "similarity": r.similarity,
            "metadata": r.memory.metadata,
        }
        for r in results
    ]