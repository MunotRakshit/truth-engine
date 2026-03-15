# Enterprise Truth Engine -- Complete Code Deep-Dive

This document is a comprehensive walkthrough of every module, every design decision, and every line of reasoning behind the Truth Engine codebase. It is written so that someone who reads it cover-to-cover can confidently explain any part of the system in a walkthrough video or technical evaluation.

---

## Table of Contents

1. [The Big Picture](#1-the-big-picture)
2. [Project Architecture](#2-project-architecture)
3. [Configuration (config.py)](#3-configuration-configpy)
4. [Data Models (models.py)](#4-data-models-modelspy)
5. [Ingestion Pipeline (app/utils/)](#5-ingestion-pipeline-apputils)
   - 5.1 [Parsers (parsers.py)](#51-parsers-parserspy)
   - 5.2 [Chunker (chunker.py)](#52-chunker-chunkerpy)
   - 5.3 [Ingest Orchestrator (ingest.py)](#53-ingest-orchestrator-ingestpy)
6. [Embedding and Storage](#6-embedding-and-storage)
   - 6.1 [EmbeddingManager (embeddings.py)](#61-embeddingmanager-embeddingspy)
   - 6.2 [VectorStore (vector_store.py)](#62-vectorstore-vector_storepy)
7. [Hybrid Retrieval (retriever.py)](#7-hybrid-retrieval-retrieverpy)
   - 7.1 [Why Hybrid?](#71-why-hybrid)
   - 7.2 [BM25 Search](#72-bm25-search)
   - 7.3 [Score Combination](#73-score-combination)
   - 7.4 [Cross-Encoder Re-Ranking](#74-cross-encoder-re-ranking)
8. [Conflict Detection and Resolution (conflict.py)](#8-conflict-detection-and-resolution-conflictpy)
   - 8.1 [Conflict Detection Algorithm](#81-conflict-detection-algorithm)
   - 8.2 [Source Prioritization](#82-source-prioritization)
   - 8.3 [Confidence Scoring](#83-confidence-scoring)
9. [RAG Engine (rag_engine.py)](#9-rag-engine-rag_enginepy)
   - 9.1 [The 9-Step Pipeline](#91-the-9-step-pipeline)
   - 9.2 [Prompt Engineering](#92-prompt-engineering)
   - 9.3 [Gemini Integration](#93-gemini-integration)
   - 9.4 [Citation Extraction](#94-citation-extraction)
10. [Streamlit Frontend (streamlit_app.py)](#10-streamlit-frontend-streamlit_apppy)
11. [Why These Specific Technologies?](#11-why-these-specific-technologies)
12. [The 5 Layers of Defense Against Bad Sources](#12-the-5-layers-of-defense-against-bad-sources)
13. [Known Limitations and How to Explain Them](#13-known-limitations-and-how-to-explain-them)

---

## 1. The Big Picture

### What is RAG?

RAG stands for Retrieval-Augmented Generation. Think of it like a research assistant at a library:

**The Library Analogy:**

- **The Vector Database (ChromaDB)** is like the library's card catalog. Every book (document chunk) has a card that describes its topic using a set of coordinates in meaning-space. When you walk in with a question, the catalog instantly points you to the shelf where the most relevant books live.
- **Embeddings** are like the system the librarian uses to categorize books by topic. Instead of Dewey Decimal numbers, each piece of text gets a point in 384-dimensional space. Texts about similar topics end up near each other -- "how to fix a valve leak" and "valve maintenance procedure" land close together even though they use different words.
- **Retrieval** is the librarian walking through the shelves, pulling out the five most relevant books for your question. Our librarian is especially thorough: she checks both the card catalog (semantic search) AND an old-school keyword index (BM25), then does a final quality check by actually reading the first page of each book (cross-encoder re-ranking).
- **The LLM (Gemini)** is the expert scholar who reads those five books the librarian brought, synthesizes the information, and writes you a clear, cited answer. The scholar never makes things up -- they can only use what the librarian gave them.

Without RAG, the LLM would answer purely from its training data, which might be outdated or hallucinated. RAG grounds the LLM in your actual enterprise documents.

### Why Do We Need Conflict Detection?

**The Courtroom Analogy:**

Imagine a trial where multiple witnesses testify about the same event, but their stories contradict each other:

- **Witness A (Technical Manual)** is a credentialed expert with a perfect track record. Trust level: HIGH.
- **Witness B (Support Logs)** is someone who was at the scene -- their account is real and practical, but they might have misremembered details. Trust level: MEDIUM.
- **Witness C (Legacy Wiki)** is a neighbor who heard about it secondhand months ago and might be repeating outdated rumors. Trust level: LOW.

When Witness A says "the cooldown period is 30 minutes" and Witness C says "the cooldown period is 15 minutes," the **judge (Conflict Detector)** notices the contradiction, checks the credibility ranking, and rules that Witness A's testimony should be trusted. The jury (the LLM) is told about the conflict and instructed to follow the judge's ruling.

Without this system, the LLM might arbitrarily pick the wrong source, or worse, blend the two contradictory claims into a nonsensical answer.

### Data Flow Diagram

```
DATA SOURCES                    INGESTION                       STORAGE
+-------------------+     +-----------------+            +------------------+
| source_a/ (PDF)   | --> | parsers.py      | ---------> |                  |
| source_b/ (JSON)  | --> | (type-specific   | -- chunks  | chunker.py       |
| source_c/ (MD)    | --> |  extraction)     |            | (sentence-aware  |
+-------------------+     +-----------------+            |  splitting)      |
                                                         +--------+---------+
                                                                  |
                                                         DocumentChunks
                                                                  |
                                                                  v
                                                         +------------------+
                                                         | embeddings.py    |
                                                         | (all-MiniLM-L6)  |
                                                         +--------+---------+
                                                                  |
                                                            384-dim vectors
                                                                  |
                                                                  v
                                                         +------------------+
                                                         | vector_store.py  |
                                                         | (ChromaDB)       |
                                                         +------------------+

QUERY TIME
+-------------------+     +-----------------+     +------------------+     +------------------+
| User Question     | --> | retriever.py    | --> | conflict.py      | --> | rag_engine.py    |
|                   |     | (hybrid search  |     | (detect, resolve |     | (build prompt,   |
|                   |     |  + re-ranking)  |     |  score confidence)|    |  call Gemini,    |
+-------------------+     +-----------------+     +------------------+     |  extract cites)  |
                                                                          +--------+---------+
                                                                                   |
                                                                          QueryResponse
                                                                                   |
                                                                                   v
                                                                          +------------------+
                                                                          | streamlit_app.py |
                                                                          | (render answer,  |
                                                                          |  conflicts, UI)  |
                                                                          +------------------+
```

---

## 2. Project Architecture

### Modular Design Philosophy

The codebase is organized into independent, single-responsibility modules:

```
app/
  config.py          -- All tunable parameters in one place
  models.py          -- Pydantic data contracts shared by all modules
  utils/
    parsers.py       -- File format parsing (PDF, JSON, CSV, Markdown)
    chunker.py       -- Text splitting into embedding-sized pieces
    ingest.py        -- Orchestrates parsing + chunking for all sources
  core/
    embeddings.py    -- Text-to-vector conversion
    retriever.py     -- Hybrid search (BM25 + semantic + re-ranking)
    conflict.py      -- Contradiction detection and resolution
    rag_engine.py    -- Central orchestrator tying everything together
  db/
    vector_store.py  -- ChromaDB persistence and search
  ui/
    streamlit_app.py -- Web frontend
main.py              -- Entry point (CLI or Streamlit launcher)
```

**Why this structure matters:**

1. **Testability.** Each module can be tested in isolation. You can unit-test the chunker without needing ChromaDB. You can test conflict detection without calling Gemini.
2. **Replaceability.** Want to swap ChromaDB for FAISS? Change `vector_store.py` alone. Want to use GPT-4 instead of Gemini? Change `rag_engine.py` alone. No module reaches into another module's internals.
3. **Readability.** A new developer can understand the system by reading the modules in order: config, models, parsers, chunker, ingest, embeddings, vector_store, retriever, conflict, rag_engine, UI.

### How Pydantic Models Act as "Contracts"

The `models.py` file defines the exact shape of data that flows between modules. Think of these as legal contracts between teams:

- The **parsers** promise to output `DocumentChunk` objects.
- The **retriever** promises to output `RetrievalResult` objects.
- The **conflict detector** promises to output `ConflictInfo` objects.
- The **RAG engine** promises to output a `QueryResponse` to the UI.

Because these are Pydantic models, they come with automatic validation. If a parser accidentally sets `source_type` to an integer instead of a string, Pydantic will raise an error at construction time rather than letting a subtle bug propagate downstream. This is far more robust than using plain dictionaries.

---

## 3. Configuration (config.py)

**File:** `app/config.py`

Every tunable parameter lives in this single file. This is a deliberate design choice: you should never have to grep through five files to figure out what threshold controls conflict detection. Here is every value and why it was chosen:

### Paths (lines 10-15)

```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SOURCE_A_DIR = DATA_DIR / "source_a"   # Technical Manual (PDF)
SOURCE_B_DIR = DATA_DIR / "source_b"   # Support Logs (JSON/CSV)
SOURCE_C_DIR = DATA_DIR / "source_c"   # Legacy Wiki (Markdown)
INDEX_DIR = DATA_DIR / "indices"
```

Three source directories map to three source types. The naming convention (`source_a`, `source_b`, `source_c`) reflects the project specification. `INDEX_DIR` stores the ChromaDB persistence files so the vector database survives restarts.

### Source Trust Hierarchy (lines 18-28)

```python
SOURCE_TRUST = {
    "manual": 3,       # Source A -- Golden source
    "support_log": 2,  # Source B -- Real-world but unverified
    "wiki": 1,         # Source C -- Legacy, possibly deprecated
}
```

**Why 3/2/1 and not other values?**

The absolute values do not matter -- what matters is the ordering. We use integers so that `max()` and `min()` comparisons in `conflict.py` work cleanly. The gap between values is uniform (each step is 1) because the trust hierarchy is a strict total order: manual always beats support_log, support_log always beats wiki. There is no scenario where two sources are equally trusted.

- **Manual (3):** The official technical documentation. Written by engineers, reviewed, versioned. This is the golden source -- if the manual says the cooldown is 30 minutes, that is the truth.
- **Support Log (2):** Real-world incident data. Valuable because it reflects what actually happened in production, but individual tickets might contain errors, workarounds, or context-specific fixes that should not be generalized.
- **Wiki (1):** Legacy community-edited documentation. It might contain outdated procedures, deprecated advice, or information that was correct two years ago but has since been superseded. This is the least trusted source.

The `SOURCE_LABELS` dictionary provides human-readable names for the UI and LLM prompt.

### Embedding Model (lines 31-32)

```python
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384
```

**Why all-MiniLM-L6-v2?** It is the sweet spot of the sentence-transformers lineup:
- **Small:** ~80MB model size, loads fast, runs on CPU.
- **Fast:** ~14,000 sentences/second on GPU, still fast on CPU.
- **Good enough:** Competitive with much larger models on semantic textual similarity benchmarks.
- The alternative, `all-mpnet-base-v2`, is better on benchmarks but 5x larger (420MB) and slower. For this project, the accuracy difference is marginal.

The dimension (384) is fixed by the model architecture. Every text becomes a 384-element vector.

### Chunking Parameters (lines 39-40)

```python
CHUNK_SIZE = 512       # tokens (approx chars / 4)
CHUNK_OVERLAP = 64
```

**Why 512?** Embedding models have a maximum token limit (usually 256 or 512 tokens). Chunks that exceed this get truncated silently, losing information. 512 characters (approximately 128 tokens) is well within the model's window while being large enough to carry meaningful context. Too-small chunks (e.g., 100 characters) would fragment sentences and lose context; too-large chunks (e.g., 2000 characters) would dilute the embedding -- a chunk about five different topics would not match any single query well.

**Why 64 overlap?** Overlap means the last 64 characters of chunk N are repeated as the first 64 characters of chunk N+1. This prevents information loss at boundaries. If a critical sentence straddles two chunks, the overlap ensures it appears in full in at least one chunk. 64 is roughly 12-15% of the chunk size -- enough to bridge sentence boundaries without excessive duplication.

### Retrieval Parameters (lines 43-46)

```python
TOP_K_RETRIEVAL = 10    # initial retrieval count
TOP_K_RERANK = 5        # after cross-encoder re-ranking
SEMANTIC_WEIGHT = 0.6   # weight for semantic score in hybrid
BM25_WEIGHT = 0.4       # weight for BM25 score in hybrid
```

**Why retrieve 10, then keep 5?** The initial retrieval casts a wide net (10 candidates from each of semantic and BM25 search). After merging and deduplication, the cross-encoder re-ranker does a more expensive, more accurate scoring pass and keeps only the top 5. This two-stage approach balances recall (not missing relevant documents) with precision (not overwhelming the LLM with irrelevant context).

**Why 60/40 favoring semantic?** Semantic search understands meaning ("how to fix a leak" matches "valve repair procedure"), while BM25 matches exact keywords ("error code QF-003"). In most enterprise Q&A scenarios, users phrase questions in natural language, so semantic search is more generally useful -- hence 60%. But technical terms, error codes, and specific product names are where BM25 shines, so it gets a meaningful 40% weight. These weights were chosen empirically as a reasonable default.

### Re-Ranker Model (line 49)

```python
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
```

**Why ms-marco-MiniLM-L-6-v2?** This model was trained on the MS MARCO passage re-ranking dataset, which is a large-scale real-world information retrieval benchmark. It is small, fast, and specifically designed for the task of "given a query and a document, how relevant is this document?" -- exactly what we need. Larger re-rankers exist but are slower without meaningful accuracy gains at this scale.

### Confidence and Conflict Thresholds (lines 52-53)

```python
CONFIDENCE_THRESHOLD = 0.4
CONFLICT_SIMILARITY_THRESHOLD = 0.75
```

**Why 0.4 for confidence?** Below this threshold, the system says "I don't know" rather than guessing. 0.4 is deliberately low -- it means the system will attempt to answer even when somewhat uncertain, only refusing when retrieval scores are genuinely poor. A higher threshold (e.g., 0.7) would refuse too many legitimate questions; a lower threshold (e.g., 0.2) would let the system hallucinate answers from barely-relevant context.

**Why 0.75 for conflict similarity?** Two chunks must be at least 75% semantically similar to be considered as discussing the "same topic." This prevents false-positive conflict detection between chunks that happen to share a few words but are about different things. At 0.75, the chunks must be substantially about the same subject for the system to even check for contradictions.

### Gemini LLM (lines 56-57)

```python
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
```

The API key is loaded from environment variables (via `.env` file using `python-dotenv`), never hardcoded. The model choice (`gemini-3.1-flash-lite-preview`) balances cost, speed, and instruction-following ability.

---

## 4. Data Models (models.py)

**File:** `app/models.py`

This file defines five Pydantic models that serve as the data contracts between every module in the system. Every piece of data that flows through the pipeline has a well-defined shape.

### DocumentChunk (lines 11-19)

```python
class DocumentChunk(BaseModel):
    chunk_id: str
    content: str
    source_type: str          # "manual" | "support_log" | "wiki"
    source_file: str          # original filename
    metadata: dict = Field(default_factory=dict)
```

This is the fundamental unit of data in the system. Every document, regardless of format, gets broken down into `DocumentChunk` objects.

- **chunk_id:** A unique identifier constructed as `{source_type}_{filename}_{index}`. This serves as the primary key in ChromaDB and is used for deduplication during hybrid retrieval. Example: `manual_technical_guide.pdf_3`.
- **content:** The actual text of the chunk. This is what gets embedded and searched.
- **source_type:** One of `"manual"`, `"support_log"`, or `"wiki"`. This is critical for the conflict detection module, which compares chunks across different source types.
- **source_file:** The original filename. Preserved for citation purposes so the UI can tell the user exactly which file the information came from.
- **metadata:** A flexible dictionary carrying format-specific information. For PDFs, this might include `page_number`. For JSON support logs, it might include `ticket_id`, `timestamp`, `engineer`, and `resolution_status`. For markdown, it includes `section_title` and `header_hierarchy`. Using a dictionary rather than fixed fields allows each parser to attach whatever metadata is relevant without requiring schema changes.

### RetrievalResult (lines 22-28)

```python
class RetrievalResult(BaseModel):
    chunk: DocumentChunk
    semantic_score: float = 0.0
    bm25_score: float = 0.0
    combined_score: float = 0.0
    rerank_score: float = 0.0
```

A `DocumentChunk` enriched with four different relevance scores. Why four?

- **semantic_score:** How similar the chunk's embedding is to the query embedding (cosine similarity, 0 to 1). Assigned by ChromaDB during vector search.
- **bm25_score:** How well the chunk matches the query based on keyword frequency (normalized to 0-1). Assigned by the BM25 index.
- **combined_score:** The weighted fusion: `0.6 * semantic + 0.4 * bm25`. This is the score used to rank candidates before re-ranking.
- **rerank_score:** The cross-encoder's joint relevance score. This is the final, most accurate score and is used for the final ranking.

Having all four scores preserved (rather than just the final one) enables debugging and transparency. The UI's debug panel can show exactly why a particular chunk ranked where it did.

### Citation (lines 31-36)

```python
class Citation(BaseModel):
    source_type: str
    source_file: str
    excerpt: str              # the verbatim text snippet used
    page_or_section: Optional[str] = None
```

A citation connects the LLM's answer back to a specific source document. The `excerpt` field contains the first 300 characters of the chunk that was cited, giving the user enough context to verify the answer. The optional `page_or_section` field points to a specific location in the original document.

### ConflictInfo (lines 39-44)

```python
class ConflictInfo(BaseModel):
    topic: str                         # what the conflict is about
    chunks: list[RetrievalResult]      # the conflicting chunks
    resolution: str                    # how it was resolved
    winning_source: str                # which source was trusted
```

- **topic:** A short description of the conflicting subject (extracted from the first sentence of the first conflicting chunk). Example: "Ticket QF-003: Coolant flow rate deviation".
- **chunks:** The two (or more) chunks that contradict each other. Stored as full `RetrievalResult` objects so the UI can show their scores and content.
- **resolution:** A human-readable explanation of how the conflict was resolved. Example: "Technical Manual (Source A) takes priority over Legacy Wiki (Source C) as the golden source of truth. The trusted source specifies 30 minutes while the other states 15 minutes (likely outdated)."
- **winning_source:** The source_type that won (e.g., `"manual"`). Used by the UI to color-code the winner in green and the loser in red.

### QueryResponse (lines 47-55)

```python
class QueryResponse(BaseModel):
    query: str
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    citations: list[Citation] = Field(default_factory=list)
    conflicts: list[ConflictInfo] = Field(default_factory=list)
    retrieval_metadata: dict = Field(default_factory=dict)
```

The final "envelope" returned to the UI. It bundles everything the frontend needs to render a complete response:

- The original query (for display and history).
- The LLM-generated answer.
- A confidence score constrained to [0.0, 1.0] by Pydantic's `ge`/`le` validators.
- A list of citations linking the answer to source documents.
- A list of detected and resolved conflicts.
- Debug metadata (top scores, retrieval method, pipeline timing).

---

## 5. Ingestion Pipeline (app/utils/)

The ingestion pipeline transforms raw files (PDF, JSON, CSV, Markdown) into uniformly-sized `DocumentChunk` objects ready for embedding.

### 5.1 Parsers (parsers.py)

**File:** `app/utils/parsers.py`

This module contains three parser functions, one for each source type. Each parser reads a specific file format and outputs a list of `DocumentChunk` objects.

#### Encoding Fallback Chain (lines 16-23)

```python
def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, ValueError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")
```

**Why this matters:** Enterprise documents come from everywhere -- Windows machines (cp1252), legacy systems (latin-1), exports with BOM markers (utf-8-sig). Rather than crashing on the first non-UTF-8 file, the parser tries four common encodings in order of likelihood. If all fail, the final fallback uses `errors="replace"`, substituting undecodable bytes with a replacement character. This ensures the pipeline never crashes on a bad file.

#### PDF Parsing (lines 26-99)

**Why pdfplumber over PyPDF2?** pdfplumber was designed for extracting structured data from PDFs, particularly tables. PyPDF2 (and its successor pypdf) treat PDFs as flat text streams and have no concept of tables. When a PDF contains a specifications table with columns of values, pdfplumber can extract it as a structured grid (`page.extract_tables()`), while PyPDF2 would mangle the columns into a confusing text blob.

The parser handles two sub-formats:

1. **PDF files:** Opens with `pdfplumber.open()` (line 63), iterates page-by-page (line 69), extracts both regular text (`page.extract_text()`, line 72) and tables (`page.extract_tables()`, line 76). Tables are formatted into readable pipe-delimited text by `_format_table()` (lines 236-244). Each page becomes one `DocumentChunk` with `page_number` in metadata.

2. **TXT files:** Detected by extension check (line 38). Split into sections using `_split_txt_sections()` (line 44), which recognizes ALL-CAPS lines and `## ` prefixes as section headers. This handles technical manuals that use uppercase headers as section delimiters.

#### JSON/CSV Parsing (lines 102-195)

This parser handles support log data from Source B.

**JSON parsing (lines 113-160):** The parser handles three structural patterns:
1. A plain JSON array of ticket objects -- the common case.
2. A JSON object with a nested array field (lines 119-126). The code iterates through top-level keys looking for the first value that is a list of dictionaries. This handles formats like `{"tickets": [...]}` or `{"logs": [...]}` without requiring the field name to be hardcoded.
3. A single JSON object -- wrapped into a list (line 126).

**Flexible field mapping (lines 131-137):** Support log formats vary. The parser tries multiple field names for each concept:
- `ticket_id` OR `id`
- `issue` OR `summary` OR `description`
- `resolution_status` OR `status`
- `timestamp` OR `date`

This flexibility means the parser works with different JSON schemas without code changes.

**CSV parsing (lines 162-193):** Uses Python's `csv.DictReader` (line 168), which automatically uses the first row as column headers. Each row becomes a chunk. The entire row dictionary is stored as metadata (line 184: `metadata = {k: str(v) for k, v in row.items()}`), converting all values to strings for ChromaDB compatibility.

#### Markdown Parsing (lines 198-230)

Markdown files from the Legacy Wiki (Source C) are split by headers using `_split_md_sections()` (lines 275-307).

**The header hierarchy tracking** is a key feature. Consider a document structured like:

```markdown
# System Overview
## Architecture
### Components
```

The parser maintains a `hierarchy` list (line 279). When it encounters a `### Components` header, the hierarchy would be `["h1:System Overview", "h2:Architecture", "h3:Components"]`. This is stored in metadata as `"header_hierarchy": "h1:System Overview > h2:Architecture > h3:Components"`, preserving the document's structure for context.

Lines 292-296 maintain the hierarchy correctly: when a new header at level N is encountered, all headers at level N or deeper are removed before appending the new one. This ensures that when you jump from `### Components` to `## Deployment`, the hierarchy correctly becomes `["h1:System Overview", "h2:Deployment"]`.

### 5.2 Chunker (chunker.py)

**File:** `app/utils/chunker.py`

#### Why We Chunk

Embedding models have token limits (typically 256-512 tokens). If you feed a 5-page document into an embedding model, it either truncates or produces a diluted vector that tries to represent everything and represents nothing well. Smaller chunks produce more focused embeddings that match specific queries better.

**The Jigsaw Puzzle Analogy:** Think of a document as a picture. If you have one giant puzzle piece (the whole document), you can not tell what part of the picture answers your question. If you cut it into many small pieces (chunks), you can find the exact piece that shows what you need. The overlap between pieces is like making sure that when you cut between two puzzle pieces, both pieces preserve enough of the edge that you can still see the connection.

#### The Sentence-Boundary-Respecting Algorithm (lines 11-78)

The core function `chunk_text()` is carefully designed to never cut mid-sentence:

1. **First, split into sentences** using `_split_sentences()` (line 32). This function (lines 124-152) walks through the text character-by-character, splitting on:
   - Period/exclamation/question mark followed by a space (`. `, `! `, `? `)
   - Newline characters (`\n`)

   It preserves the delimiters (the period and the space stay attached to the sentence), so chunks read naturally.

2. **Accumulate sentences into chunks** (lines 37-71). The algorithm maintains a `current` buffer and a running `current_len`. For each sentence:
   - If adding the sentence would exceed `CHUNK_SIZE`, flush the buffer as a completed chunk.
   - Before flushing, compute the overlap: walk backwards through the buffer (lines 42-50) collecting sentences until we have at least `CHUNK_OVERLAP` characters. These sentences become the start of the next chunk.

3. **Handle oversized sentences** (lines 53-68). If a single sentence exceeds `CHUNK_SIZE` (e.g., a long list without period breaks), it gets split further by `_split_long_segment()` (lines 155-174), which splits on spaces (never mid-word).

#### The chunk_documents() Function (lines 81-118)

This is the entry point used by the ingest pipeline. It takes `DocumentChunk` objects (which may be too large after parsing) and applies text chunking:

- If a chunk's content is already within size limits, it passes through with a renumbered `chunk_id` (line 100-105).
- If it exceeds the size limit, it gets split into sub-chunks, each inheriting the parent's `source_type`, `source_file`, and all `metadata` (lines 106-116).

The `global_idx` dictionary (line 93) ensures unique chunk IDs across all sub-chunks from the same source file.

### 5.3 Ingest Orchestrator (ingest.py)

**File:** `app/utils/ingest.py`

This module ties parsers and chunking together. Its single public function `ingest_all_sources()` (line 30) does three things:

1. **Walks the three source directories** (lines 39-66). The `_SOURCE_MAP` dictionary (lines 14-27) maps each directory to its source type and a dictionary of file-extension-to-parser-function mappings. This is the single point of truth for "what file types go in what directory."

2. **Auto-detects file types** by extension (line 49-50). Unknown extensions are silently skipped with a debug log (lines 51-56). This means you can drop a `.docx` file into a source directory and the pipeline will not crash -- it will just skip it.

3. **Error handling philosophy** (lines 59-66): Each file is parsed inside a try/except block. If a single file fails (corrupt PDF, malformed JSON), the error is logged with a full stack trace (`logger.exception()`), and the pipeline continues to the next file. This "skip bad files, do not crash the pipeline" approach is critical for production robustness. You do not want one bad file to prevent ingestion of the other 99 files.

After all files are parsed, the raw chunks are passed through `chunk_documents()` (line 69) for size-appropriate splitting.

---

## 6. Embedding and Storage

### 6.1 EmbeddingManager (embeddings.py)

**File:** `app/core/embeddings.py`

#### What Are Embeddings?

**The GPS Coordinates Analogy:** Imagine you have a magical GPS that works for meaning instead of geography. When you type "how to fix a coolant leak," the GPS gives you coordinates like (0.23, -0.87, 0.14, ...) -- a point in 384-dimensional space. When someone else types "valve repair for coolant system," they get very nearby coordinates like (0.22, -0.85, 0.15, ...). Texts about unrelated topics, like "employee vacation policy," end up far away at something like (-0.91, 0.33, -0.67, ...).

This is how semantic search works: convert text to coordinates, then find the nearest points.

#### Why all-MiniLM-L6-v2

The `EmbeddingManager` class (lines 8-22) is a thin wrapper around SentenceTransformer:

- **`embed_text()`** (lines 14-17): Embeds a single string. Used during query time and in conflict detection's similarity computation.
- **`embed_batch()`** (lines 19-22): Embeds multiple strings at once with `batch_size=64`. Batch processing is significantly faster than calling `embed_text()` in a loop because the GPU (or CPU SIMD units) can process 64 texts simultaneously. This is used during ingestion, where thousands of chunks need embedding.

The `convert_to_numpy=True` parameter returns numpy arrays instead of PyTorch tensors, which is what ChromaDB expects. The `.tolist()` call converts to plain Python lists for JSON-serializable storage.

### 6.2 VectorStore (vector_store.py)

**File:** `app/db/vector_store.py`

#### Why ChromaDB Over FAISS

ChromaDB was chosen for three reasons:
1. **Persistence:** ChromaDB stores its index to disk (`PersistentClient`, line 30). FAISS indexes live in memory and require manual save/load logic.
2. **Metadata filtering:** ChromaDB stores metadata alongside vectors and supports filtering queries. FAISS is a pure vector index with no metadata support.
3. **Simpler API:** ChromaDB's `collection.query()` and `collection.upsert()` are higher-level abstractions than FAISS's raw numpy-array operations.

#### Cosine Similarity (line 31)

```python
self.collection = self.client.get_or_create_collection(
    name=CHROMA_COLLECTION_NAME,
    metadata={"hnsw:space": "cosine"},
)
```

The `"hnsw:space": "cosine"` metadata tells ChromaDB to use cosine distance for its HNSW (Hierarchical Navigable Small World) index. Cosine similarity measures the angle between two vectors, ignoring their magnitude. This is ideal for text embeddings because a longer document should not be considered more similar just because its embedding has larger values.

**Distance-to-score conversion (line 81):** ChromaDB returns cosine *distance* (0 = identical, 2 = opposite). We convert to similarity: `score = max(0.0, 1.0 - distance)`. The `max(0.0, ...)` clamp handles edge cases where rounding might produce a tiny negative value.

#### Metadata Flattening (lines 12-22)

```python
def _flatten_metadata(metadata: dict) -> dict:
    flat = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            flat[key] = value
        elif value is None:
            continue
        else:
            flat[key] = str(value)
    return flat
```

ChromaDB only accepts primitive metadata values (strings, numbers, booleans). If a parser stores a list or nested dict in metadata, this function converts it to a string representation. None values are dropped entirely.

#### Batch Upsert and Deduplication (lines 36-58)

Documents are added in batches of 100 (`_BATCH_SIZE = 100`, line 9). The key operation is `upsert` (line 53), not `add`. Upsert means "insert if new, update if existing" -- identified by `chunk_id`. This means re-running ingestion with the same data is safe: it will not create duplicates. This is important for the "Re-index" button in the UI.

#### get_all_documents() (lines 100-124)

This method retrieves every document from ChromaDB without any query. It is used by the BM25 indexer in `retriever.py`, which needs access to all documents to build its term-frequency index. The method reconstructs `DocumentChunk` objects from ChromaDB's stored data, separating `source_type` and `source_file` from the rest of the metadata.

---

## 7. Hybrid Retrieval (retriever.py)

**File:** `app/core/retriever.py`

### 7.1 Why Hybrid?

Neither semantic search nor keyword search alone is sufficient for enterprise Q&A.

**The Fishing Analogy:**
- **Semantic search is a wide fishing net.** It catches everything that means something similar to your query, even if the exact words differ. "How to repair a leak" catches "valve maintenance procedure" and "coolant system troubleshooting." But the net has wide gaps -- exact error codes like "QF-003" slip right through because the embedding model does not know that "QF-003" is semantically related to "coolant flow rate."
- **BM25 is a fishing spear.** It targets exact keyword matches with surgical precision. If you search for "QF-003," BM25 will find every document containing those characters. But it misses paraphrased content entirely -- "how to fix overheating" will not match "thermal management procedure" because none of the words overlap.
- **Using both catches more fish.** The net catches the paraphrased results, the spear catches the exact-keyword results, and together they cover both angles.

### 7.2 BM25 Search

#### How BM25 Works (lines 42-64)

BM25 (Best Matching 25) is a TF-IDF variant that scores documents based on term frequency and inverse document frequency. In plain terms: a document scores high if it contains the query words many times (TF) and those words are rare across the entire corpus (IDF). The "BM25" variant adds document length normalization so long documents are not unfairly advantaged.

#### Lazy Index Building (lines 30-40)

```python
def _build_bm25_index(self):
    self.bm25_corpus = self.vector_store.get_all_documents()
    tokenized = [doc.content.lower().split() for doc in self.bm25_corpus]
    self.bm25_index = BM25Okapi(tokenized)
```

The BM25 index is built on the first query, not at initialization time (`if self.bm25_index is None`, line 131). This is because at init time, the vector store might be empty (documents have not been ingested yet). By deferring to first query, we ensure documents are available.

Tokenization is simple: lowercase and split on whitespace (line 38). This is deliberately naive -- BM25's strength is exact matching, so stemming or lemmatization would actually hurt performance for technical terms and error codes.

#### Score Normalization (lines 50-57)

BM25 raw scores are unbounded (they can be any positive number). To combine them with semantic scores (which are in [0, 1]), we normalize by dividing by the maximum score in the result set: `normalized = score / max_score`. This maps the top result to 1.0 and others proportionally.

### 7.3 Score Combination

The `_combine_scores()` method (lines 70-101) merges semantic and BM25 results:

1. **Build a dictionary keyed by chunk_id** (lines 80-92). If a chunk appears in both result sets, it gets both scores. If it only appears in one, the other score defaults to 0.0.
2. **Compute the weighted combination** (lines 94-98): `combined_score = 0.6 * semantic_score + 0.4 * bm25_score`.
3. **Sort by combined score** (line 100).

**Deduplication by chunk_id** (lines 84-86, 90-92): If the same chunk appears in both semantic and BM25 results (which happens often for highly relevant documents), the `max()` call keeps the higher individual score. This prevents double-counting.

**Why 60/40 split favoring semantic:** Most user queries are natural-language questions ("what is the maintenance schedule?") rather than keyword searches ("QF-003 error code"). Semantic search handles natural language better, so it gets the majority weight. But 40% for BM25 is enough to boost exact-match results to the top when they exist.

### 7.4 Cross-Encoder Re-Ranking

#### Why Re-Rank? (lines 103-117)

**The Job Interview Analogy:** Initial retrieval (semantic + BM25) is like resume screening. You quickly scan 100 resumes and pick the 10 best-looking candidates. But resume screening is noisy -- you might miss a great candidate or pass a mediocre one. The cross-encoder re-ranker is the actual job interview: you sit down with each of those 10 candidates for a careful, in-depth evaluation.

#### How Cross-Encoders Differ from Bi-Encoders

The initial semantic search uses a **bi-encoder**: the query and each document are embedded independently, and similarity is computed as a dot product. This is fast (you only embed the query once) but approximate -- the two texts never "see" each other.

A **cross-encoder** takes the query and a document as a single input pair: `[CLS] query [SEP] document [SEP]`. The transformer processes both together, allowing it to compute attention between query tokens and document tokens. This is much more accurate (the model can notice that "coolant" in the query matches "coolant" in the document at a deeper level) but slower (it must run the transformer once per query-document pair).

This is why we only re-rank the top candidates, not the entire corpus.

#### Why ms-marco-MiniLM-L-6-v2

This cross-encoder model was trained specifically on the MS MARCO passage re-ranking task, which is about determining the relevance of a text passage to a query. It is small (6 transformer layers) and fast, while being highly effective for retrieval re-ranking. The code at lines 110-111 creates query-document pairs and scores them in a single batch call to `self.cross_encoder.predict()`.

#### The Full Retrieval Pipeline (lines 119-162)

The `retrieve()` method orchestrates the five-step pipeline:

1. **Lazy-build BM25 index** if not already built (lines 131-132).
2. **Run dual retrieval:** semantic search + BM25 search, each returning up to 10 results (lines 135-136).
3. **Combine scores** with weighted fusion (line 146).
4. **Re-rank** the top candidates with the cross-encoder (lines 153-154).
5. **Return** the final top 5 results (line 162).

---

## 8. Conflict Detection and Resolution (conflict.py)

**File:** `app/core/conflict.py`

This is the "Truth Resolver" -- the expert-tier feature that makes this system more than just a standard RAG pipeline. It detects when different sources contradict each other and applies the trust hierarchy to determine the truth.

### 8.1 Conflict Detection Algorithm

The `detect_conflicts()` method (lines 142-192) works in three stages:

**Stage 1: Pairwise comparison across sources (lines 161-164)**

```python
for r1, r2 in combinations(results, 2):
    if r1.chunk.source_type == r2.chunk.source_type:
        continue
```

Using `itertools.combinations`, the method examines every possible pair of retrieved chunks. It immediately skips pairs from the same source type -- a conflict between two manual pages is not a source-trust conflict; it is an internal inconsistency that should be handled differently.

**Stage 2: Topical similarity check (lines 166-168)**

```python
sim = self._compute_similarity(r1.chunk.content, r2.chunk.content)
if sim < CONFLICT_SIMILARITY_THRESHOLD:
    continue
```

Two chunks must be about the same topic to be in conflict. The system computes cosine similarity between their embeddings (using `_compute_similarity()`, lines 62-70). If the similarity is below 0.75, the chunks are about different topics and cannot conflict. For example, a manual chunk about "maintenance schedule" and a wiki chunk about "system architecture" would have low similarity and be skipped.

**Stage 3: Heuristic contradiction signals (lines 170-174)**

```python
if not self._extract_contradiction_signals(r1.chunk.content, r2.chunk.content):
    continue
```

Even if two chunks are about the same topic, they might agree. The `_extract_contradiction_signals()` method (lines 86-124) checks three heuristic patterns:

1. **Quantity mismatches with the same unit (lines 95-106):** Regex `_QUANTITY_PATTERN` (lines 33-39) extracts value-unit pairs like "30 minutes" or "150 psi". If both chunks mention the same unit but with different values (e.g., one says "30 minutes" and another says "15 minutes"), that is a contradiction.

2. **Bare number mismatches (lines 108-116):** A fallback for when no units are present. If both chunks contain numbers but the sets differ (while sharing some overlap -- suggesting they are about the same thing), it flags a potential contradiction. The `nums1 & nums2` check (line 115) ensures the texts share some numerical context before flagging.

3. **Deprecation/replacement language (lines 118-122):** The regex `_CONTRADICTION_KEYWORDS` (lines 23-27) matches terms like "deprecated," "replaced," "no longer," "obsolete," "superseded," "do not use," and "formerly." The presence of any such keyword in either chunk is a strong signal that one source has outdated information.

**Why we use heuristics AND embeddings (defense in depth):**
- Embeddings alone would tell us "these two chunks are about the same thing" but not "these two chunks say different things about it."
- Heuristics alone might match numerical differences in completely unrelated contexts.
- Together, embeddings establish topical relevance and heuristics identify the actual contradiction.

**Topic extraction and deduplication (lines 175-181):** For each detected conflict, a topic string is extracted from the first sentence of the first chunk (up to 120 characters). Conflicts are deduplicated by topic to prevent the same contradiction from being reported multiple times if it appears in multiple chunk pairs.

### 8.2 Source Prioritization

The `resolve_conflicts()` method (lines 198-241) applies the trust hierarchy as a deterministic override:

```python
best_chunk = max(
    conflict.chunks,
    key=lambda r: SOURCE_TRUST.get(r.chunk.source_type, 0),
)
```

For each conflict, the chunk with the highest `SOURCE_TRUST` score wins. This is not a suggestion -- it is a hard rule. The manual always beats the wiki. Period.

**Why this happens BEFORE the LLM sees the context:** If we let the LLM decide which source to trust, it might pick the wrong one based on writing style, detail level, or random chance. By resolving conflicts deterministically before calling the LLM, and then telling the LLM about the resolution in the prompt, we ensure consistent, predictable behavior.

The `_build_detail_snippet()` method (lines 243-256) adds a human-readable explanation of the divergence. If both conflicting chunks contain quantities, it produces text like: "The trusted source specifies 30 minutes while the other states 15 minutes (likely outdated)."

### 8.3 Confidence Scoring

The `compute_confidence()` method (lines 262-320) produces a score between 0.0 and 1.0 based on four factors:

**Factor 1: Top retrieval score (40%)** (lines 296)

```python
factor_top = min(top_score, 1.0) * 0.4
```

The best re-rank (or combined) score among all results. If the best chunk scores 0.9, this contributes 0.36. A high top score means at least one chunk is highly relevant.

**Factor 2: Score gap between #1 and #2 (20%)** (lines 298-303)

```python
gap = scores[0] - scores[1]
factor_gap = min(gap, 1.0) * 0.2
```

If the top result is far ahead of the second result, the answer is more decisive. A large gap (e.g., 0.5) means the system is confident about which chunk to use. A small gap (e.g., 0.02) means several chunks are nearly equally relevant, which is ambiguous.

**Factor 3: Conflict penalty (20%)** (lines 305-307)

```python
conflict_penalty = min(len(conflicts) * 0.1, 0.3)
factor_conflict = (1.0 - conflict_penalty) * 0.2
```

Each detected conflict reduces confidence by 10%, up to a maximum penalty of 30%. This is the system being honest: "I found relevant information, but my sources disagree, so I am less certain." Zero conflicts means this factor contributes the full 0.2; three or more conflicts cap the penalty at 0.3, contributing only 0.14.

**Factor 4: Source agreement bonus (20%)** (lines 309-317)

If all retrieved results come from the same source type, there is a +0.1 bonus (on top of a base 0.1). Full agreement from multiple sources is a strong confidence signal. Mixed sources get just the base 0.1.

**The gate (lines 292-293):** If the best retrieval score is below `CONFIDENCE_THRESHOLD` (0.4), the method short-circuits and returns a very low confidence (`max(0.05, top_score * 0.3)`). This triggers the "I don't know" response in the RAG engine.

---

## 9. RAG Engine (rag_engine.py)

**File:** `app/core/rag_engine.py`

This is the central orchestrator. It initializes all components and runs the end-to-end query pipeline.

### 9.1 The 9-Step Pipeline

The `query()` method (lines 238-317) executes the full RAG pipeline:

**Step 1: Retrieve relevant chunks (line 243)**

```python
results = self.retriever.retrieve(question)
```

Calls the HybridRetriever, which performs BM25 + semantic search, combines scores, and re-ranks with the cross-encoder. Returns the top 5 results.

If no results are found, returns an early "I could not find any relevant information" response (lines 245-250).

**Step 2: Detect conflicts (line 254)**

```python
conflicts = self.conflict_detector.detect_conflicts(results)
```

Examines all cross-source pairs for topical similarity and contradiction signals.

**Step 3: Resolve conflicts (line 257)**

```python
resolved_conflicts = self.conflict_detector.resolve_conflicts(conflicts)
```

Applies the trust hierarchy to each detected conflict.

**Step 4: Compute confidence (line 260)**

```python
confidence = self.conflict_detector.compute_confidence(results, resolved_conflicts)
```

Produces a [0, 1] confidence score factoring in retrieval quality, conflicts, and source agreement.

**Step 5: Low-confidence early return (lines 263-282)**

If confidence is below the threshold, the engine returns immediately with a canned "I don't have sufficient information" message. It does NOT call the LLM at all -- this saves API cost and avoids hallucination when the retrieval is poor.

**Step 6: Build context (line 285)**

```python
context = self._build_context(results, resolved_conflicts)
```

The `_build_context()` method (lines 97-126) assembles a structured text block for the LLM prompt. Each retrieved chunk is labeled with its source name, trust level (HIGH/MEDIUM/LOW), and filename. If conflicts were detected, they are appended as a separate `=== DETECTED CONFLICTS ===` section with excerpts from both sides and the resolution.

**Step 7: Build prompt (line 286)**

```python
prompt = self._build_prompt(question, context, resolved_conflicts, confidence)
```

Constructs the full prompt with system instructions. See the Prompt Engineering section below.

**Step 8: Call LLM (line 289)**

```python
answer = self._call_llm(prompt)
```

Sends the prompt to Gemini and gets the generated answer.

**Step 9: Extract citations and return (lines 292-317)**

Extracts citations from the answer, logs timing, and returns the complete `QueryResponse`.

### 9.2 Prompt Engineering

The `_build_prompt()` method (lines 128-174) is arguably the most critical code in the entire project. The prompt controls LLM behavior and is the last line of defense against hallucination.

**Why the prompt explicitly lists the source hierarchy (lines 137-138):**

```python
sorted_sources = sorted(SOURCE_TRUST.items(), key=lambda x: x[1], reverse=True)
hierarchy = " > ".join(SOURCE_LABELS.get(st, st) for st, _ in sorted_sources)
```

This generates text like "Technical Manual (Source A) > Support Logs (Source B) > Legacy Wiki (Source C)" and injects it as rule #1. The LLM needs to know the hierarchy to cite the right sources and defer to the manual when sources disagree.

**Why we inject pre-resolved conflicts into the context:**

The conflicts section in the context tells the LLM exactly what the conflict is, what each source says, and how it was resolved. This prevents the LLM from having to figure out contradictions on its own (which it might get wrong).

**The "I don't know" instruction (lines 165-166) as a hallucination guard:**

```
"5. If confidence is below the threshold, respond: 'I don't have sufficient
information to answer this question confidently.'"
```

Even though the pipeline already returns early for low-confidence queries (Step 5), this instruction is also in the prompt as a safety net. If the confidence score is slightly above the threshold but the context is still thin, the LLM has explicit permission to say "I don't know."

**Rule 6 (line 167): "Never make up information not present in the context."** This is the fundamental RAG instruction. Without it, the LLM might supplement retrieved context with its training data, which defeats the entire purpose of having a curated knowledge base.

**Dynamic conflict/low-confidence notes (lines 140-153):** If conflicts were detected, an extra `IMPORTANT` instruction is injected (lines 141-145) requiring the LLM to acknowledge each conflict. If confidence is low, a `WARNING` instruction is injected (lines 147-153). These conditional additions ensure the prompt is tailored to each query's situation.

### 9.3 Gemini Integration

The `_call_llm()` method (lines 178-185) is deliberately simple:

```python
def _call_llm(self, prompt: str) -> str:
    try:
        response = self.model.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error("Gemini API error: %s", e)
        return "I encountered an error processing your question. Please try again."
```

**Why try/except with graceful fallback:** API calls can fail for many reasons (network issues, rate limits, invalid responses, safety filters). Rather than crashing the entire application, the method returns a polite error message that the UI can display. The error is logged for debugging.

The Gemini client is configured at `__init__` time (lines 37-38) using the API key from environment variables.

### 9.4 Citation Extraction

The `_extract_citations()` method (lines 189-234) connects the LLM's answer back to specific source chunks:

**Matching logic (lines 200-207):**

```python
referenced = (
    label.lower() in answer.lower()
    or chunk.source_type.lower() in answer.lower()
    or chunk.source_file.lower() in answer.lower()
)
```

For each retrieved chunk, the method checks if the LLM's answer mentions:
- The source label (e.g., "Technical Manual (Source A)")
- The source type (e.g., "manual")
- The source filename (e.g., "technical_guide.pdf")

This works because the prompt instructs the LLM to cite sources by name.

**Deduplication (line 194, 207):** A `seen` set of chunk_ids prevents the same chunk from being cited multiple times.

**Fallback to top result (lines 224-232):** If the LLM used a generic citation pattern that could not be matched (e.g., "According to the documentation..."), the top-ranked retrieval result is included as an implicit citation. This ensures the UI always has at least one citation to display.

---

## 10. Streamlit Frontend (streamlit_app.py)

**File:** `app/ui/streamlit_app.py`

### Cached Engine Initialization (lines 24-28)

```python
@st.cache_resource
def get_engine() -> RAGEngine:
    engine = RAGEngine()
    engine.ingest()
    return engine
```

`@st.cache_resource` is a Streamlit decorator that ensures the RAGEngine is created only once, even when the user interacts with the page (which triggers a full script rerun in Streamlit). Without caching, every button click would reinitialize the embedding model, ChromaDB client, cross-encoder, and Gemini connection -- adding 30+ seconds of delay. The cached engine persists across reruns for the lifetime of the Streamlit server process.

The `engine.ingest()` call inside the cached function runs ingestion on first load. Because `ingest()` checks if the collection already has documents (line 48 in `rag_engine.py`), subsequent loads skip ingestion entirely.

### Session State for Query History (lines 170-174)

```python
if "history" not in st.session_state:
    st.session_state["history"] = []
if "selected_query" not in st.session_state:
    st.session_state["selected_query"] = ""
```

Streamlit reruns the entire script on every interaction, so state must be stored in `st.session_state` (a dictionary that persists across reruns). The history list stores past query-response pairs for the sidebar.

### Confidence Bar Color Coding (lines 105-113)

```python
def render_confidence(confidence: float) -> None:
    st.progress(confidence)
    if confidence > 0.7:
        st.success(f"Confidence: {confidence:.0%}")
    elif confidence >= 0.4:
        st.warning(f"Confidence: {confidence:.0%}")
    else:
        st.error(f"Confidence: {confidence:.0%}")
```

Three color zones provide immediate visual feedback:
- **Green (>70%):** High confidence. The system found highly relevant, non-conflicting sources.
- **Yellow (40-70%):** Moderate confidence. Some relevant information found, but possibly with conflicts or ambiguity.
- **Red (<40%):** Low confidence. The system is not sure about the answer (which is also when it says "I don't know").

### Conflict Panel Layout (lines 116-135)

Conflicts are rendered using `st.columns(2)` (line 122) to show the two conflicting sources side by side. The winning source is highlighted in green text, the losing source in red. This gives the user a clear visual of what disagreed and how the system resolved it. Each conflict also shows the relevance score (`chunk.combined_score`) and the resolution explanation.

### Example Queries (lines 16-20, 183-189)

```python
EXAMPLE_QUERIES = [
    "What is the recommended maintenance schedule?",
    "How do I reset the system after a failure?",
    "What are the known issues with the legacy module?",
]
```

Example queries serve as clickable buttons (line 187) that auto-fill the search box. This helps first-time users understand what kinds of questions the system can answer and reduces the "blank text box problem" -- users often do not know what to type.

### Re-Index Button (lines 56-62)

The sidebar includes a "Re-index Data" button that calls `engine.ingest(force_reindex=True)`. This clears the existing ChromaDB collection and rebuilds from scratch. Useful when source documents have been updated.

---

## 11. Why These Specific Technologies?

| Technology | Why We Chose It | What We Considered Instead |
|---|---|---|
| **ChromaDB** | Persistent storage, metadata filtering, simple Python API, built-in HNSW indexing | FAISS (faster for pure vector search but no persistence, no metadata filtering, requires manual save/load) |
| **all-MiniLM-L6-v2** | Fast, small (80MB), good general-purpose accuracy, well-supported | all-mpnet-base-v2 (better accuracy benchmarks but 420MB, slower inference) |
| **BM25 (rank-bm25)** | Perfect for exact technical terms and error codes, simple pure-Python library | Elasticsearch (much more powerful but requires a separate server -- overkill for this scale) |
| **Cross-Encoder (ms-marco-MiniLM-L-6-v2)** | Joint query-document scoring, trained specifically on passage re-ranking | ColBERT (better theoretical accuracy but requires complex token-level indexing setup) |
| **pdfplumber** | Best-in-class table extraction from PDFs, page-level text extraction | PyPDF2/pypdf (no table support, less reliable text extraction) |
| **Streamlit** | Fastest path from Python to interactive web UI, built-in state management, zero frontend code | Gradio (simpler but less customizable), Flask (requires HTML/CSS/JS) |
| **Gemini** | Free tier available, fast inference, good instruction following, Python SDK | GPT-4 (better quality but expensive), Ollama/local models (require GPU hardware) |
| **Pydantic** | Runtime type validation, automatic serialization, IDE autocomplete for all fields | dataclasses (no validation), plain dicts (no type safety, no autocomplete) |

---

## 12. The 5 Layers of Defense Against Bad Sources

The system has five layered defenses that work together to prevent the Legacy Wiki (or any low-trust source) from misleading the LLM:

### Layer 1: Source Trust Hierarchy (config.py:18-22)

Every source type has a hard-coded trust score. Manual = 3, Support Log = 2, Wiki = 1. This hierarchy is the foundation of all downstream conflict resolution. It is not learned, not fuzzy, not negotiable.

### Layer 2: Conflict Detection (conflict.py:142-192)

When chunks from different sources are retrieved, the conflict detector identifies contradictions using embedding similarity (are they about the same topic?) plus heuristic signals (do they say different things?). This detection happens automatically on every query.

### Layer 3: Deterministic Resolution (conflict.py:198-241)

Detected conflicts are resolved BEFORE the LLM sees the context. The higher-trust source always wins. The resolution text explicitly states which source was trusted and why. The LLM receives the resolution as a fait accompli, not as a choice to make.

### Layer 4: Prompt Engineering (rag_engine.py:128-174)

The LLM prompt contains explicit instructions:
- "SOURCE HIERARCHY: Technical Manual > Support Logs > Legacy Wiki"
- "If sources conflict, ALWAYS trust the higher-ranked source"
- "Never make up information not present in the context"

Even if the conflict detector misses a subtle contradiction, the prompt gives the LLM the hierarchy to follow.

### Layer 5: Confidence Scoring (conflict.py:262-320)

Conflicts actively penalize the confidence score. Each conflict costs 10% confidence (up to 30%). If enough conflicting information is found, the system's confidence drops below the threshold and it responds with "I don't know" rather than producing a potentially incorrect answer.

**How these layers work together:**

Imagine the wiki says "cooldown is 15 minutes" and the manual says "cooldown is 30 minutes."

1. Layer 1 established that manual > wiki.
2. Layer 2 detects the contradiction (same topic, different numbers).
3. Layer 3 resolves it: manual wins, wiki is flagged as outdated.
4. Layer 4 tells the LLM to trust the manual.
5. Layer 5 reduces confidence by 10% because a conflict was detected, signaling honest uncertainty.

The user sees: "According to the Technical Manual, the cooldown period is 30 minutes. Note: There is a discrepancy between sources -- the Legacy Wiki states 15 minutes, but the Technical Manual takes priority as the golden source."

---

## 13. Known Limitations and How to Explain Them

Each limitation below includes a one-liner explanation suitable for a walkthrough video.

### Chunking Boundary Issues

**What it is:** If a critical piece of information spans two chunks and falls right at the split point, the overlap may not fully capture both halves.

**One-liner:** "Our chunker respects sentence boundaries and uses overlap, but in rare cases information at chunk edges can be split -- a known trade-off in any chunking strategy."

### Semantic Blind Spots for Domain Terms

**What it is:** The embedding model (all-MiniLM-L6-v2) was trained on general-purpose text. Highly domain-specific terms, proprietary codes, or abbreviations may not have meaningful embeddings. "QF-003" might not be semantically close to "coolant flow rate" in the embedding space.

**One-liner:** "Our embedding model handles general English well, but very domain-specific codes rely on the BM25 keyword search component -- that is exactly why we use hybrid retrieval."

### Single-Hop Retrieval

**What it is:** The system retrieves chunks that directly match the query. It cannot reason over chains of information (e.g., "Document A says X depends on Y, Document B says Y is Z, therefore X depends on Z"). This would require multi-hop retrieval.

**One-liner:** "We do single-hop retrieval -- the system finds directly relevant chunks but does not chain reasoning across multiple documents, which would require a more complex architecture."

### Implicit Contradictions

**What it is:** The conflict detector catches explicit contradictions (different numbers, deprecation language). But if Source A says "always use method X" and Source C says "method Y is the best approach" without explicitly referencing method X, the system might not detect the conflict because there is no shared quantity or deprecation keyword.

**One-liner:** "Our conflict detector catches explicit contradictions like different numbers or deprecation keywords, but implicit contradictions -- where sources recommend different approaches without directly referencing each other -- can slip through."

### Table Parsing Limitations

**What it is:** pdfplumber is the best available tool for PDF tables, but complex tables (merged cells, nested tables, tables spanning multiple pages) may not be extracted perfectly. The extracted data might have misaligned columns or missing cells.

**One-liner:** "We use pdfplumber for table extraction which handles most table layouts well, but very complex tables with merged cells or multi-page spans may not parse perfectly -- a known limitation of all PDF parsing libraries."

---

*This document covers every module, every design decision, and every trade-off in the Truth Engine codebase. Each section can be mapped directly to source code using the file references throughout. For a 5-minute walkthrough, focus on Sections 1 (big picture), 7.1 (why hybrid), 8 (conflict detection), and 12 (five layers of defense) -- these are the differentiating features that elevate this from a standard RAG system to an enterprise truth resolution engine.*
