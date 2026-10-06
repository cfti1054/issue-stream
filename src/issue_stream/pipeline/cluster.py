"""온라인 이슈 클러스터링.

새 기사 임베딩을 최근 N시간(기본 48h) 활성 이슈의 중심 벡터와 코사인 비교해
임계값 이상이면 편입, 아니면 새 이슈를 만든다. 중심은 편입될 때마다 이동평균으로 갱신.

임계값은 임베딩 모델마다 분포가 다르다. hashing 과 e5 는 같은 사건이라도 유사도 값대가
다르므로, 모델을 바꾸면 `issue-stream tune-threshold` 로 분포를 보고 다시 정한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class ClusterState:
    issue_id: int | None        # None = 이번 배치에서 새로 생긴 이슈
    centroid: np.ndarray
    size: int
    members: list[int] = field(default_factory=list)   # 이번 배치에서 편입된 입력 인덱스
    tickers: set[str] = field(default_factory=set)


def assign(embeddings: np.ndarray, clusters: list[ClusterState], threshold: float,
           tickers: list[list[str]] | None = None, kinds: list[str] | None = None,
           disclosure_factor: float = 0.3) -> list[ClusterState]:
    """embeddings(정규화됨)를 clusters 에 순서대로 배정. clusters 를 제자리에서 갱신하고 반환.

    공시 규칙: 공시 제목("[공시] 삼성전자 - 연결재무제표기준영업(잠정)실적")은 뉴스 제목과 글자가
    거의 겹치지 않는다. 그래서 공시는 같은 종목을 가진 이슈에 한해 임계값 × disclosure_factor 만
    넘으면 편입시킨다. 뉴스에는 이 완화를 적용하지 않는다(같은 종목의 다른 사건이 섞이는 것 방지).
    """
    n = len(embeddings)
    tickers = tickers or [[] for _ in range(n)]
    kinds = kinds or ["news"] * n
    for idx, v in enumerate(embeddings):
        best = None
        own = set(tickers[idx])
        is_disc = kinds[idx] == "disclosure"
        if clusters:
            sims = np.stack([c.centroid for c in clusters]) @ v
            for k in np.argsort(-sims):
                c, sim = clusters[int(k)], float(sims[int(k)])
                if sim >= threshold:
                    best = c
                    break
                if is_disc and own & c.tickers and sim >= threshold * disclosure_factor:
                    best = c
                    break
                if sim < threshold * disclosure_factor:
                    break
        if best is not None:
            c = best
            if not is_disc:  # 공시는 중심 벡터를 끌어당기지 않게 한다
                c.centroid = (c.centroid * c.size + v) / (c.size + 1)
                c.centroid /= np.linalg.norm(c.centroid) or 1.0
            c.size += 1
            c.members.append(idx)
            c.tickers |= own
        else:
            clusters.append(ClusterState(issue_id=None, centroid=v.copy(), size=1, members=[idx],
                                         tickers=set(own)))
    return clusters


def similarity_histogram(embeddings: np.ndarray, bins: int = 20) -> list[tuple[float, int]]:
    """임계값 튜닝용: 모든 기사 쌍의 코사인 유사도 분포."""
    if len(embeddings) < 2:
        return []
    sims = embeddings @ embeddings.T
    iu = np.triu_indices(len(embeddings), k=1)
    counts, edges = np.histogram(sims[iu], bins=bins, range=(-0.2, 1.0))
    return [(round(float(e), 2), int(c)) for e, c in zip(edges[:-1], counts)]
