import hashlib
import math
import re
import uuid
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
import httpx

from services.configuration.settings import settings
from services.logging.logger import logger

COLLECTION_USER_MEMORY = "user_memory"
COLLECTION_PROJECT_MEMORY = "project_memory"
COLLECTION_KNOWLEDGE = "knowledge"
COLLECTION_RESEARCH = "research"
COLLECTION_DOCUMENTATION = "documentation"
COLLECTION_NOTES = "notes"

DEFAULT_COLLECTION = COLLECTION_KNOWLEDGE
CANONICAL_COLLECTIONS = (
    COLLECTION_USER_MEMORY,
    COLLECTION_PROJECT_MEMORY,
    COLLECTION_KNOWLEDGE,
    COLLECTION_RESEARCH,
    COLLECTION_DOCUMENTATION,
    COLLECTION_NOTES,
)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for pluggable embedding providers."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


class DefaultEmbeddingProvider:
    """Lightweight, deterministic, offline embedding provider.

    Generates dense vector embeddings using token hashing and n-gram subword
    hashing normalized to unit length. Requires 0 network calls and runs in
    microseconds.
    """

    def __init__(self, dimension: int = 128) -> None:
        self.dimension = dimension

    def _embed_text(self, text: str) -> list[float]:
        tokens = re.findall(r"\w+", text.lower())
        vec = [0.0] * self.dimension
        if not tokens:
            return vec

        for token in tokens:
            idx = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % self.dimension
            vec[idx] += 1.0

        for i in range(len(text) - 2):
            ngram = text[i : i + 3].lower()
            idx = int(hashlib.md5(ngram.encode("utf-8")).hexdigest(), 16) % self.dimension
            vec[idx] += 0.5

        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [round(x / norm, 6) for x in vec]
        return vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_text(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_text(text)


class OllamaEmbeddingProvider:
    """Embedding provider connecting to a local Ollama instance."""

    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
        fallback: EmbeddingProvider | None = None,
    ) -> None:
        self.host = host or settings.ollama_host
        self.model = model or settings.ollama_model
        self.fallback = fallback or DefaultEmbeddingProvider()

    def _get_embedding(self, text: str) -> list[float]:
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    f"{self.host}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                if response.status_code == 200:
                    data = response.json()
                    embedding = data.get("embedding")
                    if embedding:
                        return [float(x) for x in embedding]
        except Exception as exc:
            logger.warning(
                "Ollama embedding request failed: {}, falling back to local provider",
                exc,
            )

        return self.fallback.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._get_embedding(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._get_embedding(text)


class ChromaEmbeddingAdapter(EmbeddingFunction[Documents]):
    """Adapts an EmbeddingProvider to ChromaDB's EmbeddingFunction interface."""

    def __init__(self, provider: EmbeddingProvider) -> None:
        self.provider = provider

    @staticmethod
    def name() -> str:
        return "echo_embedding_adapter"

    def get_config(self) -> dict[str, Any]:
        return {}

    @classmethod
    def build_from_config(cls, config: dict[str, Any]):
        return cls(DefaultEmbeddingProvider())

    def __call__(self, input: Documents) -> Embeddings:
        return self.provider.embed_documents(list(input))


class SemanticMemory:
    """Manages semantic and vector-based long-term memory via ChromaDB."""

    def __init__(
        self,
        persist_path: str | Path | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.persist_path = Path(persist_path or settings.chroma_path)
        self.persist_path.mkdir(parents=True, exist_ok=True)

        self.embedding_provider = (
            embedding_provider or self._resolve_embedding_provider()
        )
        self._embedding_function = ChromaEmbeddingAdapter(self.embedding_provider)

        self.client = chromadb.PersistentClient(path=str(self.persist_path))

    def _resolve_embedding_provider(self) -> EmbeddingProvider:
        if settings.embedding_provider == "ollama":
            return OllamaEmbeddingProvider()
        return DefaultEmbeddingProvider()

    def _get_collection(self, collection_name: str):
        return self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self._embedding_function,
        )

    def _sanitize_metadata(
        self, metadata: dict[str, Any] | None
    ) -> dict[str, str | int | float | bool]:
        if not metadata:
            return {}

        clean: dict[str, str | int | float | bool] = {}
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool)):
                clean[k] = v
            elif v is not None:
                clean[k] = str(v)
        return clean

    def add(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        collection_name: str = DEFAULT_COLLECTION,
        memory_id: str | None = None,
    ) -> str:
        if not content or not content.strip():
            raise ValueError("Content for semantic memory cannot be empty.")

        collection = self._get_collection(collection_name)
        mem_id = memory_id or str(uuid.uuid4())
        clean_metadata = self._sanitize_metadata(metadata)

        collection.add(
            ids=[mem_id],
            documents=[content.strip()],
            metadatas=[clean_metadata] if clean_metadata else None,
        )

        logger.info(
            "Added semantic memory {} to collection '{}'",
            mem_id,
            collection_name,
        )
        return mem_id

    def search(
        self,
        query: str,
        limit: int = 5,
        collection_name: str = DEFAULT_COLLECTION,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not query or not query.strip():
            return []

        collection = self._get_collection(collection_name)
        total_items = collection.count()
        if total_items == 0:
            return []

        n_results = min(max(1, limit), total_items)
        query_kwargs: dict[str, Any] = {
            "query_texts": [query.strip()],
            "n_results": n_results,
        }
        if where:
            query_kwargs["where"] = where

        results = collection.query(**query_kwargs)

        output: list[dict[str, Any]] = []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0] if "distances" in results else []

        for idx, mem_id in enumerate(ids):
            item: dict[str, Any] = {
                "id": mem_id,
                "content": documents[idx] if idx < len(documents) else "",
                "metadata": metadatas[idx] if metadatas and idx < len(metadatas) else {},
            }
            if distances and idx < len(distances):
                item["distance"] = distances[idx]
            output.append(item)

        return output

    def get(
        self,
        memory_id: str,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> dict[str, Any] | None:
        collection = self._get_collection(collection_name)
        data = collection.get(ids=[memory_id])
        ids = data.get("ids", [])
        if not ids:
            return None

        documents = data.get("documents", [""])
        metadatas = data.get("metadatas", [{}])

        return {
            "id": ids[0],
            "content": documents[0] if documents else "",
            "metadata": metadatas[0] if metadatas else {},
        }

    def delete(
        self,
        memory_id: str,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> bool:
        collection = self._get_collection(collection_name)
        existing = collection.get(ids=[memory_id])
        if not existing or not existing.get("ids"):
            return False

        collection.delete(ids=[memory_id])
        logger.info(
            "Deleted semantic memory {} from collection '{}'",
            memory_id,
            collection_name,
        )
        return True

    def count(self, collection_name: str = DEFAULT_COLLECTION) -> int:
        collection = self._get_collection(collection_name)
        return int(collection.count())

    def clear(self, collection_name: str | None = None) -> None:
        if collection_name:
            try:
                self.client.delete_collection(name=collection_name)
                logger.info("Cleared collection '{}'", collection_name)
            except Exception:
                pass
        else:
            collections = self.client.list_collections()
            for coll in collections:
                name = coll.name if hasattr(coll, "name") else str(coll)
                try:
                    self.client.delete_collection(name=name)
                except Exception:
                    pass
            logger.info("Cleared all semantic collections")


semantic_memory = SemanticMemory()
