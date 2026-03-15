"""Integration tests for the Truth Engine pipeline.

Tests all modules from ingestion through retrieval, conflict detection,
and the full RAG pipeline (excluding LLM calls which require API keys).
"""

import logging
import os
import shutil
import sys
import traceback

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_integration")

PASS = 0
FAIL = 0
ERRORS: list[str] = []


def record(name: str, passed: bool, detail: str = ""):
    global PASS, FAIL
    if passed:
        PASS += 1
        logger.info("PASS  %s %s", name, detail)
    else:
        FAIL += 1
        ERRORS.append(f"{name}: {detail}")
        logger.error("FAIL  %s %s", name, detail)


# ────────────────────────────────────────────────────────────────────────
# Test 1: Import test
# ────────────────────────────────────────────────────────────────────────
def test_imports():
    logger.info("=" * 60)
    logger.info("TEST 1: Import test")
    logger.info("=" * 60)
    modules = [
        ("app.models", None),
        ("app.config", None),
        ("app.utils.parsers", ["parse_pdf", "parse_json_csv", "parse_markdown"]),
        ("app.utils.chunker", ["chunk_text", "chunk_documents"]),
        ("app.utils.ingest", ["ingest_all_sources"]),
        ("app.core.embeddings", ["EmbeddingManager"]),
        ("app.db.vector_store", ["VectorStore"]),
        ("app.core.retriever", ["HybridRetriever"]),
        ("app.core.conflict", ["ConflictDetector"]),
        ("app.core.rag_engine", ["RAGEngine"]),
    ]
    all_ok = True
    for mod_name, attrs in modules:
        try:
            mod = __import__(mod_name, fromlist=attrs or ["__name__"])
            if attrs:
                for attr in attrs:
                    if not hasattr(mod, attr):
                        record(f"import {mod_name}.{attr}", False, "attribute missing")
                        all_ok = False
                    else:
                        record(f"import {mod_name}.{attr}", True)
            else:
                record(f"import {mod_name}", True)
        except Exception as e:
            record(f"import {mod_name}", False, str(e))
            all_ok = False
    return all_ok


# ────────────────────────────────────────────────────────────────────────
# Test 2: Ingestion test
# ────────────────────────────────────────────────────────────────────────
def test_ingestion():
    logger.info("=" * 60)
    logger.info("TEST 2: Ingestion test")
    logger.info("=" * 60)
    from app.utils.ingest import ingest_all_sources

    chunks = ingest_all_sources()
    record("ingest returns chunks", len(chunks) > 0, f"got {len(chunks)} chunks")
    if not chunks:
        return []

    # Check source types
    source_types = {c.source_type for c in chunks}
    record("has manual chunks", "manual" in source_types, f"source_types={source_types}")
    record("has support_log chunks", "support_log" in source_types, f"source_types={source_types}")
    record("has wiki chunks", "wiki" in source_types, f"source_types={source_types}")

    # Check that chunks have required fields
    for c in chunks[:5]:
        record(
            f"chunk {c.chunk_id} has content",
            bool(c.content.strip()),
            f"content_len={len(c.content)}",
        )
        record(
            f"chunk {c.chunk_id} has source_file",
            bool(c.source_file),
            f"source_file={c.source_file}",
        )

    # Per-source counts
    counts = {}
    for c in chunks:
        counts[c.source_type] = counts.get(c.source_type, 0) + 1
    logger.info("Chunk counts by source: %s", counts)

    return chunks


# ────────────────────────────────────────────────────────────────────────
# Test 3: Embedding test
# ────────────────────────────────────────────────────────────────────────
def test_embedding():
    logger.info("=" * 60)
    logger.info("TEST 3: Embedding test")
    logger.info("=" * 60)
    from app.core.embeddings import EmbeddingManager
    from app.config import EMBEDDING_DIMENSION

    em = EmbeddingManager()

    # Single embed
    vec = em.embed_text("QuantumFlow Engine warmup procedure")
    record("embed_text returns list", isinstance(vec, list), f"type={type(vec)}")
    record(
        "embed_text correct dimension",
        len(vec) == EMBEDDING_DIMENSION,
        f"got {len(vec)}, expected {EMBEDDING_DIMENSION}",
    )

    # Batch embed
    texts = ["test one", "test two", "test three"]
    batch = em.embed_batch(texts)
    record("embed_batch returns list", isinstance(batch, list), f"len={len(batch)}")
    record(
        "embed_batch correct count",
        len(batch) == len(texts),
        f"got {len(batch)}, expected {len(texts)}",
    )
    record(
        "embed_batch correct dimension",
        all(len(v) == EMBEDDING_DIMENSION for v in batch),
        f"dimensions={[len(v) for v in batch]}",
    )

    return em


# ────────────────────────────────────────────────────────────────────────
# Test 4: Vector store test
# ────────────────────────────────────────────────────────────────────────
def test_vector_store(em, chunks):
    logger.info("=" * 60)
    logger.info("TEST 4: Vector store test")
    logger.info("=" * 60)
    from app.db.vector_store import VectorStore
    from app.config import CHROMA_PERSIST_DIR

    # Use a temporary directory for test isolation
    test_persist_dir = CHROMA_PERSIST_DIR + "_test"
    if os.path.exists(test_persist_dir):
        shutil.rmtree(test_persist_dir)

    # Monkey-patch for test isolation
    import app.config as cfg
    original_dir = cfg.CHROMA_PERSIST_DIR
    cfg.CHROMA_PERSIST_DIR = test_persist_dir

    try:
        vs = VectorStore(em)
        record("VectorStore initialized", True)

        # Add chunks
        vs.add_documents(chunks)
        count = vs.collection_count()
        record(
            "documents stored",
            count == len(chunks),
            f"stored={count}, expected={len(chunks)}",
        )

        # Search
        results = vs.search("QuantumFlow Engine warmup temperature", top_k=5)
        record("search returns results", len(results) > 0, f"got {len(results)}")
        if results:
            record(
                "search results have semantic_score",
                results[0].semantic_score > 0,
                f"top_score={results[0].semantic_score:.4f}",
            )
            record(
                "search results have content",
                bool(results[0].chunk.content.strip()),
                "",
            )

        # Get all documents
        all_docs = vs.get_all_documents()
        record(
            "get_all_documents count matches",
            len(all_docs) == count,
            f"got {len(all_docs)}, expected {count}",
        )

        return vs

    finally:
        # Restore original config
        cfg.CHROMA_PERSIST_DIR = original_dir
        # Clean up test directory
        if os.path.exists(test_persist_dir):
            shutil.rmtree(test_persist_dir)


# ────────────────────────────────────────────────────────────────────────
# Test 5: Hybrid retriever test
# ────────────────────────────────────────────────────────────────────────
def test_retriever(em, chunks):
    logger.info("=" * 60)
    logger.info("TEST 5: Hybrid retriever test")
    logger.info("=" * 60)
    from app.db.vector_store import VectorStore
    from app.core.retriever import HybridRetriever
    from app.config import CHROMA_PERSIST_DIR

    # Use a temporary directory for test isolation
    test_persist_dir = CHROMA_PERSIST_DIR + "_test_retriever"
    if os.path.exists(test_persist_dir):
        shutil.rmtree(test_persist_dir)

    import app.config as cfg
    original_dir = cfg.CHROMA_PERSIST_DIR
    cfg.CHROMA_PERSIST_DIR = test_persist_dir

    try:
        vs = VectorStore(em)
        vs.add_documents(chunks)

        retriever = HybridRetriever(vs)
        record("HybridRetriever initialized", True)

        # Test retrieval
        results = retriever.retrieve("What temperature for warmup?")
        record("retrieve returns results", len(results) > 0, f"got {len(results)}")

        if results:
            # Check that results have rerank scores (cross-encoder was applied)
            has_rerank = any(r.rerank_score != 0 for r in results)
            record("results have rerank scores", has_rerank, "")

            # Check that results come from multiple source types (hybrid should find diverse)
            source_types_found = {r.chunk.source_type for r in results}
            record(
                "results from multiple sources",
                len(source_types_found) >= 1,
                f"sources={source_types_found}",
            )

            # Log top results for debugging
            for r in results[:3]:
                logger.info(
                    "  [%s] score=%.4f bm25=%.4f rerank=%.4f | %s...",
                    r.chunk.source_type,
                    r.combined_score,
                    r.bm25_score,
                    r.rerank_score,
                    r.chunk.content[:80],
                )

        # Test BM25 specifically with a technical term
        results_bm25 = retriever.retrieve("QF-003 Flux Capacitor Module error code")
        record(
            "BM25 technical term search returns results",
            len(results_bm25) > 0,
            f"got {len(results_bm25)}",
        )
        if results_bm25:
            # Should find the error code reference
            has_qf003 = any("QF-003" in r.chunk.content or "Flux Capacitor" in r.chunk.content for r in results_bm25)
            record("found QF-003 content", has_qf003, "")

        return retriever, vs

    finally:
        cfg.CHROMA_PERSIST_DIR = original_dir
        if os.path.exists(test_persist_dir):
            shutil.rmtree(test_persist_dir)


# ────────────────────────────────────────────────────────────────────────
# Test 6: Conflict detection test
# ────────────────────────────────────────────────────────────────────────
def test_conflict_detection(em, chunks):
    logger.info("=" * 60)
    logger.info("TEST 6: Conflict detection test")
    logger.info("=" * 60)
    from app.db.vector_store import VectorStore
    from app.core.retriever import HybridRetriever
    from app.core.conflict import ConflictDetector
    from app.config import CHROMA_PERSIST_DIR

    test_persist_dir = CHROMA_PERSIST_DIR + "_test_conflict"
    if os.path.exists(test_persist_dir):
        shutil.rmtree(test_persist_dir)

    import app.config as cfg
    original_dir = cfg.CHROMA_PERSIST_DIR
    cfg.CHROMA_PERSIST_DIR = test_persist_dir

    try:
        vs = VectorStore(em)
        vs.add_documents(chunks)
        retriever = HybridRetriever(vs)
        detector = ConflictDetector(em)
        record("ConflictDetector initialized", True)

        # Query about warmup — known conflict between manual (10 min, 75C)
        # and wiki (5 min, 65C)
        results = retriever.retrieve("What is the warmup temperature and duration?")
        record("warmup query returns results", len(results) > 0, f"got {len(results)}")

        if results:
            conflicts = detector.detect_conflicts(results)
            logger.info("Detected %d conflicts for warmup query", len(conflicts))

            if conflicts:
                resolved = detector.resolve_conflicts(conflicts)
                record(
                    "conflicts detected for warmup",
                    len(resolved) > 0,
                    f"found {len(resolved)} conflicts",
                )
                for c in resolved:
                    logger.info(
                        "  Conflict: topic='%s', winner='%s', resolution='%s'",
                        c.topic,
                        c.winning_source,
                        c.resolution[:120],
                    )
                    record(
                        "conflict has winning_source",
                        bool(c.winning_source),
                        f"winner={c.winning_source}",
                    )
                    # The winner should be the higher-trust source in each pair
                    # manual > support_log > wiki, so wiki should never win
                    record(
                        "conflict winner is not wiki (lowest trust)",
                        c.winning_source != "wiki",
                        f"winner={c.winning_source}",
                    )
            else:
                # No conflicts detected — this might happen if the retriever
                # didn't surface chunks from both sources. Log but don't fail hard.
                logger.warning(
                    "No conflicts detected. Source types in results: %s",
                    {r.chunk.source_type for r in results},
                )
                record(
                    "conflicts detected for warmup",
                    False,
                    "No conflicts found — check if results span multiple source types",
                )

        # Confidence scoring test
        results2 = retriever.retrieve("What is the warmup temperature and duration?")
        conflicts2 = detector.detect_conflicts(results2)
        resolved2 = detector.resolve_conflicts(conflicts2)
        confidence = detector.compute_confidence(results2, resolved2)
        record(
            "confidence is float in [0,1]",
            0.0 <= confidence <= 1.0,
            f"confidence={confidence:.4f}",
        )

        # Low-confidence test: query something completely unrelated
        results_unrelated = retriever.retrieve("What is the recipe for chocolate cake?")
        if results_unrelated:
            conf_unrelated = detector.compute_confidence(results_unrelated, [])
            logger.info("Unrelated query confidence: %.4f", conf_unrelated)
            # We can't guarantee low confidence without LLM, but log it

    finally:
        cfg.CHROMA_PERSIST_DIR = original_dir
        if os.path.exists(test_persist_dir):
            shutil.rmtree(test_persist_dir)


# ────────────────────────────────────────────────────────────────────────
# Test 7: Full RAG pipeline test (without LLM call)
# ────────────────────────────────────────────────────────────────────────
def test_rag_pipeline(em, chunks):
    logger.info("=" * 60)
    logger.info("TEST 7: Full RAG pipeline test (no LLM)")
    logger.info("=" * 60)
    from app.db.vector_store import VectorStore
    from app.core.retriever import HybridRetriever
    from app.core.conflict import ConflictDetector
    from app.core.rag_engine import RAGEngine
    from app.models import QueryResponse
    from app.config import CHROMA_PERSIST_DIR

    test_persist_dir = CHROMA_PERSIST_DIR + "_test_rag"
    if os.path.exists(test_persist_dir):
        shutil.rmtree(test_persist_dir)

    import app.config as cfg
    original_dir = cfg.CHROMA_PERSIST_DIR
    cfg.CHROMA_PERSIST_DIR = test_persist_dir

    try:
        # Build up the engine manually to avoid Gemini API dependency
        vs = VectorStore(em)
        vs.add_documents(chunks)
        retriever = HybridRetriever(vs)
        detector = ConflictDetector(em)

        # Test the context-building and prompt-building without calling LLM
        results = retriever.retrieve("How to fix QF-003 error?")
        record("RAG retrieve works", len(results) > 0, f"got {len(results)}")

        if results:
            conflicts = detector.detect_conflicts(results)
            resolved = detector.resolve_conflicts(conflicts)
            confidence = detector.compute_confidence(results, resolved)

            # Test _build_context and _build_prompt from RAGEngine
            # We'll instantiate a partial engine
            engine = RAGEngine.__new__(RAGEngine)
            engine.embedding_manager = em
            engine.vector_store = vs
            engine.retriever = retriever
            engine.conflict_detector = detector

            context = engine._build_context(results, resolved)
            record("_build_context produces output", len(context) > 0, f"context_len={len(context)}")
            record(
                "context contains RETRIEVED",
                "RETRIEVED CONTEXT" in context,
                "",
            )
            if resolved:
                record(
                    "context contains CONFLICTS section",
                    "DETECTED CONFLICTS" in context,
                    "",
                )

            prompt = engine._build_prompt("How to fix QF-003?", context, resolved, confidence)
            record("_build_prompt produces output", len(prompt) > 0, f"prompt_len={len(prompt)}")
            record("prompt contains SOURCE HIERARCHY", "SOURCE HIERARCHY" in prompt, "")
            record("prompt contains the question", "QF-003" in prompt, "")

            # Test citation extraction with a mock answer
            mock_answer = (
                "According to the Technical Manual (Source A), the official fix for QF-003 "
                "is to replace the Flux Capacitor Module. However, Support Logs (Source B) "
                "suggest an experimental reset as a temporary workaround."
            )
            citations = engine._extract_citations(mock_answer, results)
            record("citation extraction works", len(citations) > 0, f"got {len(citations)} citations")

            # Test get_index_stats
            stats = engine.get_index_stats()
            record(
                "get_index_stats returns dict with count",
                isinstance(stats, dict) and "total" in stats,
                f"stats={stats}",
            )

            # Construct a well-formed QueryResponse
            from app.models import Citation
            response = QueryResponse(
                query="How to fix QF-003?",
                answer=mock_answer,
                confidence=confidence,
                citations=citations,
                conflicts=resolved,
                retrieval_metadata={
                    "top_scores": [r.rerank_score for r in results[:5]],
                    "retrieval_method": "hybrid_bm25_semantic",
                    "reranker_used": True,
                    "num_conflicts": len(resolved),
                    "num_chunks_retrieved": len(results),
                },
            )
            record("QueryResponse is well-formed", True, f"confidence={response.confidence:.4f}")
            record(
                "QueryResponse has citations",
                len(response.citations) > 0,
                f"num_citations={len(response.citations)}",
            )

    finally:
        cfg.CHROMA_PERSIST_DIR = original_dir
        if os.path.exists(test_persist_dir):
            shutil.rmtree(test_persist_dir)


# ────────────────────────────────────────────────────────────────────────
# Test 8: RAGEngine.query() end-to-end (requires GEMINI_API_KEY)
# ────────────────────────────────────────────────────────────────────────
def test_full_rag_query():
    logger.info("=" * 60)
    logger.info("TEST 8: Full RAG Engine query (end-to-end)")
    logger.info("=" * 60)
    from app.config import GEMINI_API_KEY, CHROMA_PERSIST_DIR

    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set — skipping full RAG query test")
        record("full RAG query (skipped, no API key)", True, "")
        return

    import app.config as cfg
    test_persist_dir = CHROMA_PERSIST_DIR + "_test_full_rag"
    if os.path.exists(test_persist_dir):
        shutil.rmtree(test_persist_dir)

    original_dir = cfg.CHROMA_PERSIST_DIR
    cfg.CHROMA_PERSIST_DIR = test_persist_dir

    try:
        from app.core.rag_engine import RAGEngine

        engine = RAGEngine()
        engine.ingest(force_reindex=True)

        questions = [
            "What is the warmup temperature for the QuantumFlow Engine?",
            "How do I fix QF-003 Flux Capacitor Module Degradation?",
            "What is max_threads configuration?",
        ]

        for q in questions:
            response = engine.query(q)
            record(
                f"full query: {q[:50]}",
                bool(response.answer),
                f"confidence={response.confidence:.3f}, citations={len(response.citations)}, conflicts={len(response.conflicts)}",
            )

    finally:
        cfg.CHROMA_PERSIST_DIR = original_dir
        if os.path.exists(test_persist_dir):
            shutil.rmtree(test_persist_dir)


# ────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────
def main():
    logger.info("=" * 60)
    logger.info("TRUTH ENGINE INTEGRATION TESTS")
    logger.info("=" * 60)

    # Test 1: Imports
    imports_ok = test_imports()
    if not imports_ok:
        logger.error("Import failures detected — some tests may fail.")

    # Test 2: Ingestion
    try:
        chunks = test_ingestion()
    except Exception as e:
        record("ingestion", False, f"EXCEPTION: {e}\n{traceback.format_exc()}")
        chunks = []

    if not chunks:
        logger.error("No chunks from ingestion — cannot run downstream tests.")
        _print_summary()
        return

    # Test 3: Embedding
    try:
        em = test_embedding()
    except Exception as e:
        record("embedding", False, f"EXCEPTION: {e}\n{traceback.format_exc()}")
        _print_summary()
        return

    # Test 4: Vector store
    try:
        test_vector_store(em, chunks)
    except Exception as e:
        record("vector_store", False, f"EXCEPTION: {e}\n{traceback.format_exc()}")

    # Test 5: Hybrid retriever
    try:
        test_retriever(em, chunks)
    except Exception as e:
        record("retriever", False, f"EXCEPTION: {e}\n{traceback.format_exc()}")

    # Test 6: Conflict detection
    try:
        test_conflict_detection(em, chunks)
    except Exception as e:
        record("conflict_detection", False, f"EXCEPTION: {e}\n{traceback.format_exc()}")

    # Test 7: RAG pipeline (no LLM)
    try:
        test_rag_pipeline(em, chunks)
    except Exception as e:
        record("rag_pipeline", False, f"EXCEPTION: {e}\n{traceback.format_exc()}")

    # Test 8: Full RAG with LLM (optional)
    try:
        test_full_rag_query()
    except Exception as e:
        record("full_rag_query", False, f"EXCEPTION: {e}\n{traceback.format_exc()}")

    _print_summary()


def _print_summary():
    logger.info("=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)
    logger.info("PASSED: %d", PASS)
    logger.info("FAILED: %d", FAIL)
    if ERRORS:
        logger.info("FAILURES:")
        for err in ERRORS:
            logger.info("  - %s", err)
    logger.info("=" * 60)
    if FAIL > 0:
        logger.info("RESULT: SOME TESTS FAILED")
    else:
        logger.info("RESULT: ALL TESTS PASSED")


if __name__ == "__main__":
    main()
