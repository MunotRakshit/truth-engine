"""Conflict detection, source prioritization, and confidence scoring.

This module implements the "Truth Resolver" — the expert-tier feature that
detects contradictions between sources and applies the trust hierarchy to
determine which source should be believed.
"""

import re
from itertools import combinations

import numpy as np

from app.config import (
    CONFIDENCE_THRESHOLD,
    CONFLICT_SIMILARITY_THRESHOLD,
    SOURCE_LABELS,
    SOURCE_TRUST,
)
from app.models import ConflictInfo, RetrievalResult


# Patterns that suggest a statement is outdated or superseded
_CONTRADICTION_KEYWORDS = re.compile(
    r"\b(deprecated|outdated|replaced|instead|no longer|obsolete|superseded|"
    r"do not use|removed|changed to|updated to|was previously|formerly)\b",
    re.IGNORECASE,
)

# Extracts bare numbers (integers and decimals) from text
_NUMBER_PATTERN = re.compile(r"\b(\d+\.?\d*)\b")

# Matches quantities with units: durations, temperatures, percentages, etc.
_QUANTITY_PATTERN = re.compile(
    r"(\d+\.?\d*)\s*"
    r"(minutes?|mins?|hours?|hrs?|seconds?|secs?|days?|weeks?|months?|years?|"
    r"\u00b0[CF]|degrees?|percent|%|psi|bar|rpm|kg|lbs?|ml|liters?|mg|g|mm|cm|m|"
    r"steps?|times?|attempts?)",
    re.IGNORECASE,
)


class ConflictDetector:
    """Detects conflicts between retrieved chunks and resolves them
    using a source-trust hierarchy.

    Designed to work without an LLM — uses embeddings for topical similarity
    and heuristics for contradiction detection so it is fully unit-testable.
    """

    def __init__(self, embedding_manager):
        """
        Args:
            embedding_manager: An object with an ``embed_text(str) -> list[float]``
                method (typically :class:`app.core.embeddings.EmbeddingManager`).
        """
        self.embedding_manager = embedding_manager

    # ------------------------------------------------------------------
    # Similarity helpers
    # ------------------------------------------------------------------

    def _compute_similarity(self, text1: str, text2: str) -> float:
        """Return cosine similarity between the embeddings of *text1* and *text2*."""
        emb1 = np.asarray(self.embedding_manager.embed_text(text1))
        emb2 = np.asarray(self.embedding_manager.embed_text(text2))
        norm1 = np.linalg.norm(emb1)
        norm2 = np.linalg.norm(emb2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(emb1, emb2) / (norm1 * norm2))

    # ------------------------------------------------------------------
    # Contradiction heuristics
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_quantities(text: str) -> list[tuple[str, str]]:
        """Return ``(value, unit)`` pairs found in *text*."""
        return _QUANTITY_PATTERN.findall(text)

    @staticmethod
    def _extract_numbers(text: str) -> set[str]:
        """Return all bare numbers found in *text*."""
        return set(_NUMBER_PATTERN.findall(text))

    def _extract_contradiction_signals(self, text1: str, text2: str) -> bool:
        """Heuristic check for contradictions between two pieces of text.

        Returns ``True`` if the texts likely contradict each other:
        - Mismatched numerical quantities with the same unit
        - Presence of deprecation / replacement language
        - Different step counts or procedural differences
        """
        # 1. Quantity mismatches (same unit, different value)
        q1 = self._extract_quantities(text1)
        q2 = self._extract_quantities(text2)
        units1: dict[str, set[str]] = {}
        for val, unit in q1:
            units1.setdefault(unit.lower(), set()).add(val)
        units2: dict[str, set[str]] = {}
        for val, unit in q2:
            units2.setdefault(unit.lower(), set()).add(val)
        shared_units = set(units1) & set(units2)
        for unit in shared_units:
            if units1[unit] != units2[unit]:
                return True

        # 2. Bare-number mismatches (fallback when no units)
        if not shared_units:
            nums1 = self._extract_numbers(text1)
            nums2 = self._extract_numbers(text2)
            if nums1 and nums2 and nums1 != nums2:
                # Only flag if the intersection is non-empty (they share some
                # context) but they also have divergent values.
                if nums1 & nums2 and nums1.symmetric_difference(nums2):
                    return True

        # 3. Deprecation / replacement language
        has_kw1 = bool(_CONTRADICTION_KEYWORDS.search(text1))
        has_kw2 = bool(_CONTRADICTION_KEYWORDS.search(text2))
        if has_kw1 or has_kw2:
            return True

        return False

    # ------------------------------------------------------------------
    # Core detection
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_topic(content: str) -> str:
        """Extract a short topic string from chunk content.

        Uses the first sentence (up to 120 chars) as a topic identifier.
        """
        first_line = content.strip().split("\n")[0]
        first_sentence = re.split(r"[.!?]", first_line)[0].strip()
        if len(first_sentence) > 120:
            first_sentence = first_sentence[:117] + "..."
        return first_sentence

    def detect_conflicts(
        self, results: list[RetrievalResult]
    ) -> list[ConflictInfo]:
        """Detect conflicts between chunks from different source types.

        Algorithm
        ---------
        1. Group results by ``source_type``.
        2. For each pair of chunks from *different* source types:
           a. Compute semantic similarity.
           b. If similarity exceeds ``CONFLICT_SIMILARITY_THRESHOLD``, they
              likely discuss the same topic.
           c. Apply heuristic contradiction signals.
           d. If contradicting, produce a :class:`ConflictInfo`.
        3. Deduplicate by topic (keep the first occurrence).
        """
        conflicts: list[ConflictInfo] = []
        seen_topics: set[str] = set()

        for r1, r2 in combinations(results, 2):
            # Only consider cross-source pairs
            if r1.chunk.source_type == r2.chunk.source_type:
                continue

            sim = self._compute_similarity(r1.chunk.content, r2.chunk.content)
            if sim < CONFLICT_SIMILARITY_THRESHOLD:
                continue

            if not self._extract_contradiction_signals(
                r1.chunk.content, r2.chunk.content
            ):
                continue

            topic = self._extract_topic(r1.chunk.content)

            # Deduplicate by topic
            topic_key = topic.lower()
            if topic_key in seen_topics:
                continue
            seen_topics.add(topic_key)

            conflicts.append(
                ConflictInfo(
                    topic=topic,
                    chunks=[r1, r2],
                    resolution="",
                    winning_source="",
                )
            )

        return conflicts

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve_conflicts(
        self, conflicts: list[ConflictInfo]
    ) -> list[ConflictInfo]:
        """Apply the source-trust hierarchy to resolve each conflict.

        For every conflict the chunk whose ``source_type`` has the highest
        ``SOURCE_TRUST`` score wins.  A human-readable ``resolution`` string
        is generated using ``SOURCE_LABELS``.
        """
        resolved: list[ConflictInfo] = []
        for conflict in conflicts:
            best_chunk = max(
                conflict.chunks,
                key=lambda r: SOURCE_TRUST.get(r.chunk.source_type, 0),
            )
            worst_chunk = min(
                conflict.chunks,
                key=lambda r: SOURCE_TRUST.get(r.chunk.source_type, 0),
            )
            winner = best_chunk.chunk.source_type
            loser = worst_chunk.chunk.source_type

            winner_label = SOURCE_LABELS.get(winner, winner)
            loser_label = SOURCE_LABELS.get(loser, loser)

            # Build a detail snippet highlighting the divergence
            detail = self._build_detail_snippet(
                best_chunk.chunk.content, worst_chunk.chunk.content
            )

            resolution = (
                f"{winner_label} takes priority over {loser_label} "
                f"as the golden source of truth. {detail}"
            )

            resolved.append(
                conflict.model_copy(
                    update={
                        "winning_source": winner,
                        "resolution": resolution,
                    }
                )
            )
        return resolved

    def _build_detail_snippet(self, winner_text: str, loser_text: str) -> str:
        """Produce a short sentence contrasting divergent quantities."""
        q_win = self._extract_quantities(winner_text)
        q_lose = self._extract_quantities(loser_text)

        if q_win and q_lose:
            win_val, win_unit = q_win[0]
            lose_val, lose_unit = q_lose[0]
            return (
                f"The trusted source specifies {win_val} {win_unit} "
                f"while the other states {lose_val} {lose_unit} "
                f"(likely outdated)."
            )
        return ""

    # ------------------------------------------------------------------
    # Confidence scoring
    # ------------------------------------------------------------------

    def compute_confidence(
        self,
        results: list[RetrievalResult],
        conflicts: list[ConflictInfo],
    ) -> float:
        """Compute an overall answer-confidence score in ``[0.0, 1.0]``.

        Factors (weights):
            1. **Top retrieval score** (40%) — best ``rerank_score`` or
               ``combined_score`` among the results.
            2. **Score gap** between rank-1 and rank-2 (20%) — a larger gap
               signals a more decisive retrieval.
            3. **Conflict penalty** (20%) — 0.1 per conflict, capped at 0.3.
            4. **Source agreement bonus** (20%) — +0.1 if all results share
               the same source type (full agreement).

        If the best score falls below ``CONFIDENCE_THRESHOLD``, the
        confidence is clamped to a very low value to trigger an
        "I don't know" response.
        """
        if not results:
            return 0.0

        def _best_score(r: RetrievalResult) -> float:
            return r.rerank_score if r.rerank_score > 0 else r.combined_score

        scores = sorted([_best_score(r) for r in results], reverse=True)
        top_score = scores[0]

        # Gate: if the best retrieval score is too low, bail out early
        if top_score < CONFIDENCE_THRESHOLD:
            return max(0.05, top_score * 0.3)

        # Factor 1: top retrieval score (40%)
        factor_top = min(top_score, 1.0) * 0.4

        # Factor 2: score gap between #1 and #2 (20%)
        if len(scores) >= 2:
            gap = scores[0] - scores[1]
        else:
            gap = scores[0]
        factor_gap = min(gap, 1.0) * 0.2

        # Factor 3: conflict penalty (20%)
        conflict_penalty = min(len(conflicts) * 0.1, 0.3)
        factor_conflict = (1.0 - conflict_penalty) * 0.2

        # Factor 4: source agreement (20%)
        source_types = {r.chunk.source_type for r in results}
        agreement_bonus = 0.1 if len(source_types) == 1 else 0.0
        factor_agreement = agreement_bonus + 0.1  # base 0.1 + bonus 0.1
        factor_agreement *= 0.2 / 0.2  # scale to the 20% bucket
        # Simplify: base of 0.1 out of 0.2, or 0.2 out of 0.2 with agreement
        factor_agreement = (0.1 + agreement_bonus) * (0.2 / 0.2)
        # Normalize to [0, 0.2]
        factor_agreement = min(factor_agreement, 0.2)

        confidence = factor_top + factor_gap + factor_conflict + factor_agreement
        return round(max(0.0, min(1.0, confidence)), 4)
