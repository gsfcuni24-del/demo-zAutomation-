"""IEC 61131-3 / machine-safety knowledge retrieval backed by Qdrant.

Embeddings come from LiteLLM when live LLM credentials exist; otherwise a deterministic
feature-hashing embedder is used so retrieval still works offline. If Qdrant is unreachable the
retriever degrades to an in-memory cosine search over the same corpus.
"""

import hashlib
import json
import math
import re
import uuid
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Protocol

import litellm
import structlog
from pydantic import BaseModel
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm

from app.core.config import settings

logger = structlog.get_logger(__name__)

CORPUS_PATH = Path(__file__).with_name("iec61131_corpus.json")
_WORD = re.compile(r"[a-z0-9]+")


class StandardSnippet(BaseModel):
    id: str
    source: str
    title: str
    text: str
    score: float = 0.0


def load_corpus() -> list[StandardSnippet]:
    return [StandardSnippet.model_validate(d) for d in json.loads(CORPUS_PATH.read_text())]


class Embedder(Protocol):
    name: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Signed feature hashing over unigrams + bigrams (deterministic, no network)."""

    name = "hash"

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        words = _WORD.findall(text.lower())
        vec = [0.0] * self.dim
        for feature in words + [f"{a}_{b}" for a, b in pairwise(words)]:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            vec[idx] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


class LiteLLMEmbedder:
    name = "llm"

    def __init__(self, model: str, api_key: str | None, dim: int = 1536) -> None:
        self.model, self.api_key, self.dim = model, api_key, dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await litellm.aembedding(model=self.model, input=texts, api_key=self.api_key)
        return [list(item["embedding"]) for item in response.data]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class StandardsRetriever:
    def __init__(
        self,
        client: AsyncQdrantClient | None,
        embedder: Embedder,
        collection: str,
        corpus: list[StandardSnippet] | None = None,
    ) -> None:
        self.client = client
        self.embedder = embedder
        self.collection = f"{collection}_{embedder.name}_{embedder.dim}"
        self.corpus = corpus if corpus is not None else load_corpus()
        self._indexed = False
        self._local: list[list[float]] | None = None
        self.backend = "qdrant" if client else "memory"

    async def ensure_index(self) -> None:
        if self._indexed or self.client is None:
            return
        if not await self.client.collection_exists(self.collection):
            await self.client.create_collection(
                self.collection,
                vectors_config=qm.VectorParams(size=self.embedder.dim, distance=qm.Distance.COSINE),
            )
        count = (await self.client.count(self.collection, exact=True)).count
        if count != len(self.corpus):
            vectors = await self.embedder.embed([f"{s.title}. {s.text}" for s in self.corpus])
            await self.client.upsert(
                self.collection,
                points=[
                    qm.PointStruct(
                        id=str(uuid.uuid5(uuid.NAMESPACE_URL, s.id)),
                        vector=v,
                        payload=s.model_dump(exclude={"score"}),
                    )
                    for s, v in zip(self.corpus, vectors, strict=True)
                ],
                wait=True,
            )
            logger.info("rag.indexed", collection=self.collection, points=len(self.corpus))
        self._indexed = True

    async def _search_memory(self, vector: list[float], k: int) -> list[StandardSnippet]:
        if self._local is None:
            self._local = await self.embedder.embed([f"{s.title}. {s.text}" for s in self.corpus])
        scored = sorted(
            ((s, _cosine(vector, v)) for s, v in zip(self.corpus, self._local, strict=True)),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return [s.model_copy(update={"score": round(score, 4)}) for s, score in scored[:k]]

    async def retrieve(self, query: str, k: int = 4) -> list[StandardSnippet]:
        (vector,) = await self.embedder.embed([query])
        if self.client is not None:
            try:
                await self.ensure_index()
                response = await self.client.query_points(
                    self.collection, query=vector, limit=k, with_payload=True
                )
                self.backend = "qdrant"
                return [
                    StandardSnippet.model_validate(
                        {**(p.payload or {}), "score": round(p.score, 4)}
                    )
                    for p in response.points
                ]
            except Exception as exc:  # Qdrant down / misconfigured: keep the pipeline usable
                logger.warning("rag.qdrant_unavailable", error=str(exc)[:300])
        self.backend = "memory"
        return await self._search_memory(vector, k)


@lru_cache
def get_retriever() -> StandardsRetriever:
    if settings.llm_mock or settings.OPENAI_API_KEY is None:
        embedder: Embedder = HashingEmbedder()
    else:
        embedder = LiteLLMEmbedder(
            settings.LLM.embedding, settings.OPENAI_API_KEY.get_secret_value()
        )
    client = AsyncQdrantClient(
        url=str(settings.QDRANT_URL),
        api_key=settings.QDRANT_API_KEY.get_secret_value() if settings.QDRANT_API_KEY else None,
        timeout=5,
        check_compatibility=False,
    )
    return StandardsRetriever(client, embedder, settings.QDRANT_STANDARDS_COLLECTION)
