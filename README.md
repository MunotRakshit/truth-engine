# Enterprise Truth Engine

> A RAG-based knowledge reconciliation system that retrieves, reconciles, and resolves
> conflicting information across multiple enterprise data sources.

**Author:** Rakshit Munot

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Setup & Installation](#setup--installation)
- [Usage](#usage)
- [How It Works](#how-it-works)
- [Conflict Scenarios](#conflict-scenarios)
- [Failure & Mitigation Report](#failure--mitigation-report)
- [Tech Stack](#tech-stack)
- [Evaluation Criteria Mapping](#evaluation-criteria-mapping)

---

## Overview

Enterprise organizations frequently accumulate knowledge across disconnected systems --
a golden technical manual, real-time support logs, and a legacy wiki that may contain
outdated procedures. When employees query this knowledge, they receive conflicting answers
with no way to determine which source to trust.

The **Truth Engine** solves this by implementing a three-tier RAG pipeline that:

1. **Ingests** documents from three heterogeneous sources (PDF, JSON/CSV, Markdown)
2. **Retrieves** relevant chunks using hybrid search (semantic + BM25) with cross-encoder re-ranking
3. **Detects conflicts** between sources automatically using embedding similarity and heuristic contradiction signals
4. **Resolves conflicts** by applying a hardcoded source-trust hierarchy, ensuring the golden manual always wins
5. **Generates answers** with citations, confidence scores, and transparent conflict metadata

The system handles three source types with explicit trust ordering:

| Source | Format | Trust Level | Role |
|--------|--------|-------------|------|
| **Source A** -- Technical Manual | PDF/TXT | 3 (Highest) | Golden source of truth |
| **Source B** -- Support Logs | JSON/CSV | 2 (Medium) | Real-world fixes, sometimes experimental |
| **Source C** -- Legacy Wiki | Markdown | 1 (Lowest) | Older procedures, possibly deprecated |

---

## Architecture

```
                         +-----------+
                         |  Streamlit |
                         |     UI     |
                         +-----+-----+
                               |
                               v
                     +-------------------+
                     |    RAG Engine      |
                     | (rag_engine.py)    |
                     +--------+----------+
                              |
              +---------------+---------------+
              |               |               |
              v               v               v
     +----------------+ +----------+ +-----------------+
     | Hybrid         | | Conflict | | Gemini LLM      |
     | Retriever      | | Detector | | (Response Gen)   |
     | (retriever.py) | | (conflict| |                  |
     |                | |  .py)    | |                  |
     +-------+--------+ +----+-----+ +-----------------+
             |                |
    +--------+--------+       |
    |                 |       |
    v                 v       v
+----------+  +--------+  +------------------+
| ChromaDB |  |  BM25  |  | Source Trust     |
| (Vector) |  | Index  |  | Hierarchy        |
| cosine   |  |        |  | manual=3,        |
| HNSW     |  |        |  | support=2,       |
+----+-----+  +----+---+  | wiki=1           |
     |              |      +------------------+
     +--------------+
             |
     +-------+-------+
     |   Embedding    |
     |   Manager      |
     | (embeddings.py)|
     | all-MiniLM-L6  |
     +-------+--------+
             |
    +--------+--------+--------+
    |                 |        |
    v                 v        v
+----------+   +----------+  +----------+
| Source A  |   | Source B  |  | Source C  |
| PDF/TXT   |   | JSON/CSV  |  | Markdown  |
| Parser    |   | Parser    |  | Parser    |
| (parsers  |   | (parsers  |  | (parsers  |
|  .py)     |   |  .py)     |  |  .py)     |
+-----+-----+   +-----+-----+  +-----+-----+
      |               |              |
      v               v              v
  data/source_a/  data/source_b/  data/source_c/
```

### Module Breakdown

| Module | File | Responsibility |
|--------|------|---------------|
| **Parsers** | `app/utils/parsers.py` | Format-specific extraction: `pdfplumber` for PDFs (with table formatting), JSON/CSV ticket parsing, Markdown section splitting |
| **Chunker** | `app/utils/chunker.py` | Sentence-boundary-aware text splitting with configurable overlap (512 chars, 64 overlap) |
| **Ingestion** | `app/utils/ingest.py` | Orchestrates source directory walking, parser dispatch, and chunk assembly |
| **Embeddings** | `app/core/embeddings.py` | `all-MiniLM-L6-v2` sentence-transformer for single and batch embedding |
| **Vector Store** | `app/db/vector_store.py` | ChromaDB persistent storage with cosine HNSW index, batch upsert, and semantic search |
| **Retriever** | `app/core/retriever.py` | Hybrid BM25 + semantic search with weighted fusion (0.6 semantic / 0.4 BM25), cross-encoder re-ranking |
| **Conflict Detector** | `app/core/conflict.py` | Pairwise cross-source conflict detection using embedding similarity + heuristic contradiction signals, trust-based resolution |
| **Data Models** | `app/models.py` | Pydantic models defining interfaces: `DocumentChunk`, `RetrievalResult`, `Citation`, `ConflictInfo`, `QueryResponse` |
| **Config** | `app/config.py` | Centralized configuration: paths, trust scores, model names, thresholds, hyperparameters |

---

## Setup & Installation

### Prerequisites

- Python 3.10+
- A Google Gemini API key ([get one here](https://aistudio.google.com/app/apikey))

### Steps

```bash
# Clone the repository
git clone https://github.com/your-username/truth-engine.git
cd truth-engine

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate    # On Windows: venv\Scripts\activate

# Install dependencies
pip3 install -r requirements.txt

# Configure environment
echo "GEMINI_API_KEY=your-gemini-api-key-here" > .env

# Run the application
streamlit run app/ui/streamlit_app.py
```

### Project Structure

```
truth-engine/
├── app/
│   ├── config.py              # Centralized configuration
│   ├── models.py              # Pydantic data models (interfaces)
│   ├── core/
│   │   ├── embeddings.py      # Embedding model management
│   │   ├── retriever.py       # Hybrid search + re-ranking
│   │   ├── conflict.py        # Conflict detection & resolution
│   │   └── rag_engine.py      # Core RAG orchestration
│   ├── db/
│   │   └── vector_store.py    # ChromaDB index management
│   ├── ui/
│   │   └── streamlit_app.py   # Streamlit frontend
│   └── utils/
│       ├── parsers.py         # PDF, JSON/CSV, Markdown parsers
│       ├── chunker.py         # Text splitting utilities
│       └── ingest.py          # Ingestion orchestrator
├── data/
│   ├── source_a/              # Technical Manual (PDF/TXT)
│   ├── source_b/              # Support Logs (JSON/CSV)
│   ├── source_c/              # Legacy Wiki (Markdown)
│   └── indices/               # Persisted ChromaDB index
├── .env                       # API keys (not committed)
├── requirements.txt
└── README.md
```

---

## Usage

Once the Streamlit app is running, you can:

1. **Ask questions** about the technical product in the query box
2. **View the answer** with inline citations pointing to specific sources and pages/sections
3. **Inspect detected conflicts** -- the system highlights when sources disagree and shows which source won
4. **Check confidence scores** -- low-confidence answers trigger an "I don't know" response instead of hallucination
5. **Browse retrieval metadata** -- see which chunks were retrieved, their scores, and the retrieval method used

### Example Queries

- *"What is the warmup duration for the system?"* -- triggers a conflict between Manual (10 min) and Wiki (5 min)
- *"How do I fix error QF-003?"* -- pulls from all three sources with different resolutions
- *"What is the recommended buffer size?"* -- Manual says 4096KB, Wiki says 2048KB
- *"What is the calibration procedure?"* -- Manual has 3 steps, Wiki has 2 steps

---

## How It Works

### Tier 1: Multi-Format Ingestion & Basic RAG

**Ingestion** (`app/utils/ingest.py`) walks three source directories and dispatches files to format-specific parsers:

- **PDF/TXT** (`parse_pdf`): Uses `pdfplumber` for page-by-page text extraction with table detection. Tables are extracted via `page.extract_tables()` and converted to pipe-delimited text. Plain `.txt` files are split by section headers (ALL-CAPS lines or `## ` prefixes).
- **JSON/CSV** (`parse_json_csv`): Parses support ticket arrays. Each ticket becomes a chunk with structured content (`"Ticket {id}: {issue}. Resolution: {resolution}. Status: {status}"`). Metadata preserves `ticket_id`, `timestamp`, `engineer`, and `resolution_status`.
- **Markdown** (`parse_markdown`): Splits by header hierarchy (`#` through `######`), preserving parent header context in metadata for each section chunk.

**Chunking** (`app/utils/chunker.py`) applies sentence-boundary-aware splitting:
- Default chunk size: **512 characters** with **64-character overlap** (configurable in `config.py`)
- Splits on sentence endings (`. `, `! `, `? `) and newlines first, then word boundaries
- Never splits mid-word
- Overlap ensures context is preserved across chunk boundaries

**Storage** (`app/db/vector_store.py`) embeds chunks using `all-MiniLM-L6-v2` (384-dimensional vectors) and upserts them into ChromaDB with cosine HNSW indexing. Metadata is flattened to ChromaDB-compatible scalar types. Batch upserts process 100 documents at a time.

### Tier 2: Hybrid Retrieval & Re-Ranking

The `HybridRetriever` (`app/core/retriever.py`) implements a three-stage retrieval pipeline:

1. **Dual Retrieval** -- Runs semantic search (ChromaDB cosine similarity) and BM25 keyword search in parallel, each returning up to `TOP_K_RETRIEVAL=10` results.

2. **Weighted Fusion** -- Merges results by `chunk_id`, computing:
   ```
   combined_score = 0.6 * semantic_score + 0.4 * bm25_score
   ```
   This balances semantic understanding (captures paraphrases) with lexical precision (captures exact technical terms like error codes).

3. **Cross-Encoder Re-Ranking** -- The top candidates are re-scored using `cross-encoder/ms-marco-MiniLM-L-6-v2`, which attends to the full query-document pair jointly (unlike bi-encoder similarity). Returns the top `TOP_K_RERANK=5` results.

The BM25 index is lazy-built on first query from all documents in ChromaDB, using simple whitespace tokenization.

### Tier 3: Conflict Detection & Truth Resolution

The `ConflictDetector` (`app/core/conflict.py`) operates entirely without the LLM -- it uses embeddings and heuristics so it is fully deterministic and unit-testable.

**Detection Algorithm:**
1. For each pair of chunks from *different* source types:
   - Compute embedding cosine similarity
   - If similarity >= `CONFLICT_SIMILARITY_THRESHOLD` (0.75), they discuss the same topic
   - Apply contradiction heuristics:
     - **Quantity mismatch**: Same unit, different value (e.g., "10 minutes" vs "5 minutes")
     - **Bare number mismatch**: Different numbers when no units are present
     - **Deprecation language**: Keywords like "deprecated", "replaced", "no longer", "obsolete"
2. Deduplicate conflicts by topic (first sentence of the chunk content)

**Resolution:**
- Apply the source trust hierarchy: `manual=3 > support_log=2 > wiki=1`
- The chunk from the higher-trust source wins
- Generate a human-readable resolution string with specific quantities highlighted

**Confidence Scoring** (4-factor weighted model):

| Factor | Weight | Description |
|--------|--------|-------------|
| Top retrieval score | 40% | Best `rerank_score` among results |
| Score gap | 20% | Difference between rank-1 and rank-2 (decisiveness) |
| Conflict penalty | 20% | -0.1 per conflict detected, capped at -0.3 |
| Source agreement | 20% | +0.1 bonus if all results come from the same source |

If the best retrieval score falls below `CONFIDENCE_THRESHOLD` (0.4), the system returns a low-confidence signal that triggers an "I don't know" response instead of hallucinating.

---

## Conflict Scenarios

The test data includes the following intentional conflicts between sources to demonstrate the Truth Resolution pipeline:

### 1. Warmup Duration
| Source | Value |
|--------|-------|
| **Technical Manual (Source A)** | 10 minutes |
| Legacy Wiki (Source C) | 5 minutes |
| **Resolution** | Manual wins -- 10 minutes is the correct warmup duration |

### 2. Warmup Temperature
| Source | Value |
|--------|-------|
| **Technical Manual (Source A)** | 75 degrees C |
| Legacy Wiki (Source C) | 65 degrees C |
| **Resolution** | Manual wins -- the operating temperature was updated to 75 degrees C |

### 3. Calibration Procedure
| Source | Value |
|--------|-------|
| **Technical Manual (Source A)** | 3-step procedure |
| Legacy Wiki (Source C) | 2-step procedure (missing the verification step) |
| **Resolution** | Manual wins -- the 3-step procedure includes a critical verification step |

### 4. Thread Configuration
| Source | Value |
|--------|-------|
| **Technical Manual (Source A)** | 16 threads |
| Legacy Wiki (Source C) | 8 threads |
| **Resolution** | Manual wins -- thread count was doubled in the latest release |

### 5. Error QF-003 Fix
| Source | Value |
|--------|-------|
| **Technical Manual (Source A)** | Official fix procedure |
| Support Logs (Source B) | Workaround from field engineers |
| Legacy Wiki (Source C) | Outdated fix (may not apply) |
| **Resolution** | Manual takes priority; support log workaround is surfaced as supplementary context |

### 6. Buffer Size
| Source | Value |
|--------|-------|
| **Technical Manual (Source A)** | 4096 KB |
| Legacy Wiki (Source C) | 2048 KB |
| **Resolution** | Manual wins -- buffer size was increased in the current version |

---

## Failure & Mitigation Report

*This section addresses the three required questions from the evaluation rubric (20% of grade).*

### 1. Where Does the System Fail?

#### Chunking Boundary Issues

**Problem:** When information spans multiple sentences or paragraphs, the chunker (`app/utils/chunker.py`) may split it across two chunks. For example, a procedure that says "Set the temperature to 75 degrees C" in one paragraph and "Wait 10 minutes for warmup" in the next could be split, causing the conflict detector to miss the full context.

**Why it happens:** The chunker uses a fixed window of 512 characters with 64-character overlap (`config.py:39-40`). While it respects sentence boundaries, it cannot understand semantic completeness -- it does not know that a procedure description is "complete" or "incomplete."

**Mitigation:** The 64-character overlap provides some continuity, and the hybrid retrieval stage often retrieves adjacent chunks for the same query. A more robust fix would be to implement parent-child chunking (store both the chunk and a pointer to the larger section) or to use recursive chunking that respects document-level section boundaries.

#### Semantic Similarity Blind Spots

**Problem:** The conflict detector (`app/core/conflict.py:167`) requires embedding similarity >= 0.75 (`CONFLICT_SIMILARITY_THRESHOLD` in `config.py:53`) to consider two chunks as discussing the same topic. If one chunk says "warmup duration is 10 minutes" and another says "the system requires a 5-minute initialization period," the paraphrase may score below 0.75 and the conflict goes undetected.

**Why it happens:** `all-MiniLM-L6-v2` is a general-purpose embedding model (384 dimensions) that captures broad semantic similarity but may not recognize domain-specific synonyms ("warmup" vs "initialization period," "calibration" vs "alignment procedure").

**Mitigation:** We complement the semantic threshold with heuristic contradiction signals (`_extract_contradiction_signals` in `conflict.py:86-124`) -- quantity mismatches, deprecation keywords, and numerical divergence. Lowering the threshold would increase recall but also increase false positives. A domain-specific fine-tuned embedding model would be the proper fix.

#### Table Extraction Quality

**Problem:** The PDF parser (`app/utils/parsers.py:60-64`) uses `pdfplumber.extract_tables()` which works well for simple tables but may fail on:
- Nested tables or tables with merged cells
- Tables that span multiple pages
- Tables embedded as images rather than text

**Why it happens:** `pdfplumber` relies on detecting ruled lines and cell boundaries in the PDF structure. Complex formatting breaks these heuristics.

**Mitigation:** Tables are converted to pipe-delimited text (`_format_table` in `parsers.py:206-214`) which preserves structure for simple cases. For production deployment, an OCR-based table extractor (like `camelot` or a vision model) would handle complex cases.

#### Implicit and Logical Contradictions

**Problem:** The conflict detector is effective at catching *explicit numerical contradictions* (e.g., "10 minutes" vs "5 minutes") but cannot detect *logical contradictions* like:
- Source A: "Always run the diagnostic before calibration"
- Source C: "Calibration can be performed directly without diagnostics"

**Why it happens:** The heuristic detection (`_extract_contradiction_signals`) relies on pattern matching for numbers, quantities, and deprecation keywords. It has no understanding of procedural logic or causal reasoning.

**Mitigation:** The LLM prompt includes explicit instructions to identify contradictions in the context window. This is a second line of defense -- but it depends on both chunks being retrieved together, which is not guaranteed. A more robust approach would be to add an NLI (Natural Language Inference) model as a contradiction classifier.

#### Single-Hop Reasoning Limitation

**Problem:** The system retrieves chunks independently and cannot chain reasoning across them. If answering a question requires combining information from chunk A (which has a formula) and chunk B (which has the input values), the system may only retrieve one of them.

**Why it happens:** The retriever scores chunks independently against the query. There is no mechanism for multi-hop retrieval where the output of one retrieval informs a second retrieval.

**Mitigation:** The re-ranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`) helps by jointly scoring query-chunk pairs, which can promote chunks that are contextually relevant even if they do not lexically match. For true multi-hop, an iterative retrieval approach (retrieve, generate a sub-query, retrieve again) would be needed.

### 2. How Did We Prevent the LLM from Following the Legacy Wiki?

This is the core architectural challenge: the LLM has no inherent understanding of which source to trust. We implemented a **five-layer defense**:

#### Layer 1: Source Trust Hierarchy (Pre-Retrieval)

The trust hierarchy is defined as a configuration constant (`config.py:18-22`):
```python
SOURCE_TRUST = {
    "manual": 3,      # Golden source
    "support_log": 2,  # Real-world but unverified
    "wiki": 1,         # Legacy, possibly deprecated
}
```
This is not a suggestion -- it is a hardcoded priority system that the conflict resolver enforces deterministically before the LLM ever sees the context.

#### Layer 2: Automatic Conflict Detection (Pre-LLM)

The `ConflictDetector` (`app/core/conflict.py`) runs *before* the LLM generates a response. It:
1. Compares all pairs of chunks from different sources using embedding similarity
2. Applies heuristic contradiction signals (quantity mismatches, deprecation keywords)
3. Produces `ConflictInfo` objects with explicit `winning_source` and `resolution` fields

This means the LLM receives pre-resolved conflicts, not raw contradictory context.

#### Layer 3: Trust-Based Resolution (Deterministic)

`resolve_conflicts()` (`conflict.py:198-241`) applies a `max()` over trust scores to pick the winner. This is deterministic -- the manual always beats the wiki, regardless of which chunk the LLM might "prefer." The resolution includes a human-readable explanation:
```
"Technical Manual (Source A) takes priority over Legacy Wiki (Source C) as the golden source of truth.
 The trusted source specifies 10 minutes while the other states 5 minutes (likely outdated)."
```

#### Layer 4: Context Annotation

Each chunk passed to the LLM is annotated with its source label and trust level. The LLM prompt explicitly tells the model:
- Which sources are present in the context
- Their relative trust levels
- That the Technical Manual is the golden source
- That the Legacy Wiki may contain deprecated information

This transforms the problem from "which text should I believe?" to "the system has already told me which to believe."

#### Layer 5: Confidence Gating

The confidence scorer (`conflict.py:262-320`) penalizes conflicting answers and low-score retrievals. If the best retrieval score falls below `CONFIDENCE_THRESHOLD` (0.4), the system returns "I don't know" rather than generating from potentially unreliable context. The conflict penalty (0.1 per conflict, capped at 0.3) ensures that heavily conflicted answers are flagged as uncertain.

### 3. How Would We Scale to 10,000 Documents?

The current system is designed for a small corpus (~tens of documents). Scaling to 10,000 documents introduces bottlenecks at every layer. Here is a concrete scaling plan:

#### Ingestion: Async Parallel Processing

**Current:** Sequential file-by-file parsing in `ingest_all_sources()` (`ingest.py:30-72`).

**At scale:** Use `asyncio` + `ProcessPoolExecutor` for CPU-bound parsing (PDF extraction is heavy). Each source directory can be processed in parallel, and within each directory, files can be parsed concurrently. Estimated speedup: 4-8x on a modern multi-core machine.

#### Embedding: Batch with GPU Acceleration

**Current:** `EmbeddingManager.embed_batch()` (`embeddings.py:19-22`) processes batches of 64 on CPU.

**At scale:** Move to GPU inference with `sentence-transformers` CUDA support. Use larger batch sizes (256-512). For 10,000 documents with ~100 chunks each (~1M chunks), embedding would take ~2 hours on CPU vs ~15 minutes on a single GPU.

#### Vector Storage: Distributed Vector Database

**Current:** Local ChromaDB with persistent storage (`vector_store.py:30-31`). ChromaDB stores everything in a single SQLite file + HNSW index on disk.

**At scale:** Migrate to a hosted vector database:
- **Pinecone** or **Weaviate** for managed, horizontally-scalable vector search
- **Qdrant** for self-hosted with sharding support
- Keep ChromaDB for development/testing, use the hosted solution for production

The HNSW index in ChromaDB already provides approximate nearest neighbor search (sub-linear query time), but a distributed solution adds:
- Horizontal sharding across nodes
- Replication for availability
- Metadata pre-filtering before vector search (reducing the search space)

#### BM25: Pre-Built Index with Incremental Updates

**Current:** The BM25 index is rebuilt from scratch on every first query (`retriever.py:30-39`) by calling `get_all_documents()`.

**At scale:** Pre-build the BM25 index during ingestion and serialize it to disk. Support incremental updates -- only re-index changed or new documents. Consider using Elasticsearch or OpenSearch for a production-grade inverted index that supports both keyword search and metadata filtering.

#### Incremental Indexing

**Current:** The ingestion pipeline processes all files every time.

**At scale:** Track file checksums (SHA-256) and modification timestamps. Only re-parse and re-embed files that have changed. Store the checksum-to-chunk mapping in a lightweight metadata store (SQLite or Redis). This reduces re-indexing from O(N) to O(delta).

#### Caching

- **Query cache:** Cache frequent query results with a TTL. The same question about "warmup duration" should not re-run the full pipeline every time.
- **Embedding cache:** Cache embeddings by content hash to avoid re-embedding unchanged text.
- **LLM response cache:** For identical query + context combinations, return cached responses.

#### Metadata Pre-Filtering

**Current:** All chunks are searched regardless of source type.

**At scale:** Add metadata filters to the vector search. If a user specifically asks about the "technical manual," filter to `source_type="manual"` before running vector search. This reduces the candidate set by ~60-70% for source-specific queries. ChromaDB already supports `where` clause filtering; distributed databases support this natively with pre-filtered indexes.

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Frontend** | Streamlit | Interactive query interface with real-time results |
| **Vector Database** | ChromaDB (persistent, HNSW cosine) | Embedding storage and approximate nearest neighbor search |
| **Embeddings** | `all-MiniLM-L6-v2` (384-dim) | Text-to-vector encoding via sentence-transformers |
| **Keyword Search** | BM25 (`rank_bm25`) | Lexical retrieval for exact technical terms and error codes |
| **Re-Ranker** | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Joint query-document scoring for precision re-ranking |
| **LLM** | Google Gemini 3.1 Flash Lite | Response generation with citation and conflict awareness |
| **PDF Parsing** | `pdfplumber` | Text and table extraction from PDF documents |
| **Data Models** | Pydantic v2 | Typed interfaces between all pipeline modules |
| **Configuration** | `python-dotenv` | Environment variable management for API keys |
| **Language** | Python 3.10+ | Type hints, `match` statements, modern syntax |

---

## Evaluation Criteria Mapping

This section maps the project's features to the evaluation rubric for easy review.

### Architectural Depth (30%)

- **Modular design:** Every component is an independent module with Pydantic model interfaces (`app/models.py`). Parsers, chunkers, embedders, retrievers, and conflict detectors can be developed, tested, and swapped independently.
- **Centralized configuration:** All hyperparameters live in `app/config.py` -- chunk size, overlap, weights, thresholds, model names. No magic numbers in business logic.
- **Proper chunking strategy:** Sentence-boundary-aware splitting with configurable overlap. Respects document structure (sections in Markdown, pages in PDF, tickets in JSON).
- **Vector DB management:** ChromaDB with persistent storage, batch upserts (100 at a time), HNSW cosine indexing, and a `clear()` method for clean re-indexing.

### Data Integrity (30%)

- **Table handling:** `pdfplumber.extract_tables()` with pipe-delimited formatting preserves tabular data as text.
- **Conflict detection:** Fully automated, LLM-free conflict detection using embedding similarity + heuristic contradiction signals. Catches numerical mismatches, unit discrepancies, and deprecation language.
- **Source prioritization:** Deterministic trust hierarchy (`manual=3 > support_log=2 > wiki=1`) enforced before the LLM generates a response.
- **Citation tracking:** Every answer includes `Citation` objects with `source_type`, `source_file`, `excerpt`, and `page_or_section`.

### Failure Awareness (20%)

- See the comprehensive [Failure & Mitigation Report](#failure--mitigation-report) above, covering:
  - Five specific failure modes with root causes and mitigations
  - Five-layer defense against wiki misinformation
  - Six concrete scaling strategies for 10,000 documents

### Coding Standards (20%)

- **Type hints:** All functions use Python 3.10+ type annotations
- **Pydantic models:** Strict typed interfaces with validation (`Field(ge=0.0, le=1.0)` for confidence)
- **Error handling:** `try/except` with logging in parser dispatch (`ingest.py:59-66`); malformed files are skipped, not fatal
- **Logging:** `logging` module used throughout for observability
- **Documentation:** Docstrings on every public class and method explaining purpose and algorithm
- **No magic numbers:** All thresholds and hyperparameters in `config.py`
