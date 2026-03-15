"""Hybrid retriever combining BM25 lexical search, semantic search, and cross-encoder re-ranking."""

import logging

from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from app.config import (
    BM25_WEIGHT,
    RERANKER_MODEL,
    SEMANTIC_WEIGHT,
    TOP_K_RERANK,
    TOP_K_RETRIEVAL,
)
from app.db.vector_store import VectorStore
from app.models import DocumentChunk, RetrievalResult

logger = logging.getLogger(__name__)


class HybridRetriever:
    """Hybrid search combining BM25 + semantic search with cross-encoder re-ranking."""

    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store
        self.bm25_index: BM25Okapi | None = None
        self.bm25_corpus: list[DocumentChunk] = []
        self.cross_encoder = CrossEncoder(RERANKER_MODEL)

    def _build_bm25_index(self):
        """Lazy-build BM25 index from all documents in the vector store."""
        self.bm25_corpus = self.vector_store.get_all_documents()
        if not self.bm25_corpus:
            logger.warning("No documents in vector store; BM25 index is empty.")
            self.bm25_index = None
            return

        tokenized = [doc.content.lower().split() for doc in self.bm25_corpus]
        self.bm25_index = BM25Okapi(tokenized)
        logger.info("Built BM25 index over %d documents.", len(self.bm25_corpus))

    def _bm25_search(self, query: str, top_k: int) -> list[RetrievalResult]:
        """Return top_k BM25-scored results. Scores are normalized to [0, 1]."""
        if self.bm25_index is None or not self.bm25_corpus:
            return []

        tokenized_query = query.lower().split()
        scores = self.bm25_index.get_scores(tokenized_query)

        max_score = float(scores.max()) if scores.max() > 0 else 1.0
        indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]

        results = []
        for idx, score in indexed:
            if score <= 0:
                continue
            normalized = score / max_score
            results.append(
                RetrievalResult(
                    chunk=self.bm25_corpus[idx],
                    bm25_score=normalized,
                )
            )
        return results

    def _semantic_search(self, query: str, top_k: int) -> list[RetrievalResult]:
        """Delegate to vector_store.search() for embedding-based retrieval."""
        return self.vector_store.search(query, top_k=top_k)

    def _combine_scores(
        self,
        semantic_results: list[RetrievalResult],
        bm25_results: list[RetrievalResult],
    ) -> list[RetrievalResult]:
        """Merge results by chunk_id using weighted combination.

        combined_score = SEMANTIC_WEIGHT * semantic_score + BM25_WEIGHT * bm25_score
        Deduplicates by chunk_id, keeping the maximum individual scores.
        """
        merged: dict[str, RetrievalResult] = {}

        for r in semantic_results:
            cid = r.chunk.chunk_id
            if cid not in merged:
                merged[cid] = RetrievalResult(chunk=r.chunk)
            merged[cid].semantic_score = max(merged[cid].semantic_score, r.semantic_score)

        for r in bm25_results:
            cid = r.chunk.chunk_id
            if cid not in merged:
                merged[cid] = RetrievalResult(chunk=r.chunk)
            merged[cid].bm25_score = max(merged[cid].bm25_score, r.bm25_score)

        for result in merged.values():
            result.combined_score = (
                SEMANTIC_WEIGHT * result.semantic_score
                + BM25_WEIGHT * result.bm25_score
            )

        combined = sorted(merged.values(), key=lambda r: r.combined_score, reverse=True)
        return combined

    def _rerank(
        self, query: str, results: list[RetrievalResult], top_k: int
    ) -> list[RetrievalResult]:
        """Re-score results with the cross-encoder and return the top_k."""
        if not results:
            return []

        pairs = [(query, r.chunk.content) for r in results]
        scores = self.cross_encoder.predict(pairs)

        for result, score in zip(results, scores):
            result.rerank_score = float(score)

        reranked = sorted(results, key=lambda r: r.rerank_score, reverse=True)
        return reranked[:top_k]

    def retrieve(self, query: str, top_k: int | None = None) -> list[RetrievalResult]:
        """Full hybrid retrieval pipeline.

        1. Ensure BM25 index exists.
        2. Run semantic search and BM25 search in parallel (conceptually).
        3. Combine scores with weighted fusion.
        4. Re-rank top candidates with the cross-encoder.
        5. Return final top_k results.
        """
        final_k = top_k or TOP_K_RERANK

        # Lazy-build BM25 index on first call
        if self.bm25_index is None:
            self._build_bm25_index()

        # Step 1 & 2: Dual retrieval
        semantic_results = self._semantic_search(query, top_k=TOP_K_RETRIEVAL)
        bm25_results = self._bm25_search(query, top_k=TOP_K_RETRIEVAL)

        logger.info(
            "Retrieved %d semantic + %d BM25 results for query: %.80s",
            len(semantic_results),
            len(bm25_results),
            query,
        )

        # Step 3: Combine
        combined = self._combine_scores(semantic_results, bm25_results)

        if not combined:
            logger.warning("No results found for query: %.80s", query)
            return []

        # Step 4: Re-rank the top candidates
        candidates = combined[: TOP_K_RETRIEVAL]  # feed at most TOP_K_RETRIEVAL into re-ranker
        reranked = self._rerank(query, candidates, top_k=final_k)

        logger.info(
            "Re-ranked to %d results (top rerank_score=%.4f).",
            len(reranked),
            reranked[0].rerank_score if reranked else 0.0,
        )

        return reranked
