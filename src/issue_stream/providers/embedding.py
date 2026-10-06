"""문서 임베딩.

- hashing : 글자 n-gram 해시 벡터. 설치할 것이 없고 매우 빠르다. 같은 사건의 제목끼리는
            글자가 많이 겹치므로 초기 클러스터링에 쓸 만하다. 의미 유사(표현이 다른 기사)는 약함.
- local   : sentence-transformers 로 로컬 실행하는 다국어 모델 (무료, `pip install -e .[ml]` 필요).
            기본 모델 intfloat/multilingual-e5-small = 384차원, CPU로도 기사 1천 건/일 충분.
- openai  : text-embedding-3-small (유료, 1536차원). ALLOW_PAID_APIS=true 필요.

모든 구현은 L2 정규화된 벡터를 반환한다 → 내적 = 코사인 유사도.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from functools import lru_cache

import numpy as np

from ..core.config import get_settings


class Embedder(ABC):
    name: str
    dim: int
    use_snippet: bool = True   # hashing 은 스니펫이 섞이면 제목 유사도가 희석돼 제목만 쓴다

    def text_for(self, title: str, snippet: str | None) -> str:
        return f"{title}. {snippet}"[:512] if (self.use_snippet and snippet) else title

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:  # shape (n, dim)
        ...


def _normalize(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


class HashingEmbedder(Embedder):
    use_snippet = False

    def __init__(self, dim: int):
        self.dim = dim
        self.name = f"hashing-{dim}"

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        t = "".join(text.split()).lower()
        for n in (2, 3):
            for i in range(len(t) - n + 1):
                h = int.from_bytes(hashlib.blake2b(t[i:i + n].encode(), digest_size=8).digest(), "little")
                v[h % self.dim] += 1.0 if (h >> 63) == 0 else -1.0
        return v

    def embed(self, texts: list[str]) -> np.ndarray:
        return _normalize(np.stack([self._vec(t) for t in texts])) if texts else np.zeros((0, self.dim))


class LocalEmbedder(Embedder):
    def __init__(self, model: str, dim: int):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError("EMBEDDING_PROVIDER=local 은 `pip install -e .[ml]` 이 필요합니다.") from e
        self.model = SentenceTransformer(model)
        self.dim = self.model.get_sentence_embedding_dimension()
        if self.dim != dim:
            raise RuntimeError(f"모델 차원({self.dim})과 EMBEDDING_DIM({dim})이 다릅니다. .env 를 맞추세요.")
        self.name = model
        self._prefix = "passage: " if "e5" in model.lower() else ""

    def embed(self, texts: list[str]) -> np.ndarray:
        m = self.model.encode([self._prefix + t for t in texts], batch_size=32, normalize_embeddings=True)
        return np.asarray(m, dtype=np.float32)


class OpenAIEmbedder(Embedder):
    """유료. 기사 1천 건/일 × 300토큰 기준 월 약 $0.2."""
    API = "https://api.openai.com/v1/embeddings"

    def __init__(self, model: str, dim: int):
        self.name, self.dim = model, dim
        self.key = get_settings().openai_api_key

    def embed(self, texts: list[str]) -> np.ndarray:
        import httpx

        r = httpx.post(self.API, headers={"Authorization": f"Bearer {self.key}"},
                       json={"model": self.name, "input": texts, "dimensions": self.dim}, timeout=60)
        r.raise_for_status()
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        return _normalize(np.array([d["embedding"] for d in data], dtype=np.float32))


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    p = s.embedding_provider
    s.require_paid("EMBEDDING_PROVIDER", p)
    if p == "hashing":
        return HashingEmbedder(s.embedding_dim)
    if p == "local":
        return LocalEmbedder(s.embedding_model, s.embedding_dim)
    if p == "openai":
        return OpenAIEmbedder(s.embedding_model, s.embedding_dim)
    raise ValueError(f"알 수 없는 EMBEDDING_PROVIDER: {p}")
