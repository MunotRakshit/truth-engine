"""Streamlit frontend for the Truth Engine."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
from app.core.rag_engine import RAGEngine
from app.models import QueryResponse
from app.config import SOURCE_LABELS, SOURCE_TRUST

# ── Page configuration ────────────────────────────────────────────────
st.set_page_config(page_title="Truth Engine", page_icon="\U0001f50d", layout="wide")

# ── Example queries ───────────────────────────────────────────────────
EXAMPLE_QUERIES = [
    "What is the recommended maintenance schedule?",
    "How do I reset the system after a failure?",
    "What are the known issues with the legacy module?",
]


# ── Engine initialisation (cached across reruns) ─────────────────────
@st.cache_resource
def get_engine() -> RAGEngine:
    engine = RAGEngine()
    engine.ingest()
    return engine


def _trust_rank(source_type: str) -> str:
    """Return a medal emoji based on trust level."""
    level = SOURCE_TRUST.get(source_type, 0)
    if level >= 3:
        return "\U0001f947"  # gold
    if level >= 2:
        return "\U0001f948"  # silver
    return "\U0001f949"      # bronze


def _trust_word(source_type: str) -> str:
    level = SOURCE_TRUST.get(source_type, 0)
    if level >= 3:
        return "HIGH"
    if level >= 2:
        return "MEDIUM"
    return "LOW"


# ── Sidebar ───────────────────────────────────────────────────────────
def render_sidebar(engine: RAGEngine) -> None:
    with st.sidebar:
        st.title("Truth Engine Controls")

        # Re-index button
        if st.button("Re-index Data", use_container_width=True):
            with st.spinner("Re-indexing all sources..."):
                try:
                    engine.ingest(force_reindex=True)
                    st.success("Re-indexing complete!")
                except Exception as exc:
                    st.error(f"Re-indexing failed: {exc}")

        st.divider()

        # Source trust hierarchy
        st.subheader("Source Hierarchy")
        sorted_sources = sorted(SOURCE_TRUST.items(), key=lambda x: x[1], reverse=True)
        hierarchy_lines = []
        for src_type, _trust in sorted_sources:
            medal = _trust_rank(src_type)
            label = SOURCE_LABELS.get(src_type, src_type)
            word = _trust_word(src_type)
            hierarchy_lines.append(f"{medal} **{label}** — Trust: {word}")
        st.info("\n\n".join(hierarchy_lines))

        st.divider()

        # Index stats
        st.subheader("Index Stats")
        try:
            stats = engine.get_index_stats()
            if isinstance(stats, dict):
                for key, value in stats.items():
                    st.metric(label=str(key), value=str(value))
            else:
                st.write(f"Documents indexed: **{stats}**")
        except Exception:
            st.caption("Stats unavailable — index may not be built yet.")

        st.divider()

        # Query history
        st.subheader("Query History")
        if st.session_state.get("history"):
            for i, past in enumerate(reversed(st.session_state["history"][-10:])):
                if st.button(past["query"][:60], key=f"hist_{i}", use_container_width=True):
                    st.session_state["selected_query"] = past["query"]
                    st.rerun()
        else:
            st.caption("No queries yet.")


# ── Result display helpers ────────────────────────────────────────────
def render_confidence(confidence: float) -> None:
    st.subheader("Confidence")
    st.progress(confidence)
    if confidence > 0.7:
        st.success(f"Confidence: {confidence:.0%}")
    elif confidence >= 0.4:
        st.warning(f"Confidence: {confidence:.0%}")
    else:
        st.error(f"Confidence: {confidence:.0%}")


def render_conflicts(response: QueryResponse) -> None:
    if not response.conflicts:
        return
    st.warning("\u26a0\ufe0f Conflicts Detected Between Sources")
    for conflict in response.conflicts:
        st.markdown(f"**Topic:** {conflict.topic}")
        cols = st.columns(2)
        for idx, chunk in enumerate(conflict.chunks[:2]):
            with cols[idx]:
                label = SOURCE_LABELS.get(chunk.chunk.source_type, chunk.chunk.source_type)
                is_winner = chunk.chunk.source_type == conflict.winning_source
                header_color = "green" if is_winner else "red"
                st.markdown(
                    f":{header_color}[**{label}**]"
                    + (" \u2714\ufe0f Winner" if is_winner else "")
                )
                st.markdown(f"> {chunk.chunk.content[:300]}")
                st.caption(f"Score: {chunk.combined_score:.3f}")
        st.markdown(f"**Resolution:** {conflict.resolution}")
        st.divider()


def render_citations(response: QueryResponse) -> None:
    if not response.citations:
        return
    with st.expander("\U0001f4da Citations", expanded=False):
        for i, cit in enumerate(response.citations, 1):
            label = SOURCE_LABELS.get(cit.source_type, cit.source_type)
            st.markdown(f"**[{i}] {label}** — `{cit.source_file}`")
            if cit.page_or_section:
                st.caption(f"Section: {cit.page_or_section}")
            st.markdown(f"> {cit.excerpt}")
            st.divider()


def render_debug(response: QueryResponse) -> None:
    with st.expander("\U0001f527 Retrieval Debug Info", expanded=False):
        st.json(response.retrieval_metadata)


def render_results(response: QueryResponse) -> None:
    # Answer card
    with st.container(border=True):
        st.markdown("### Answer")
        st.markdown(response.answer)

    render_confidence(response.confidence)
    render_conflicts(response)
    render_citations(response)
    render_debug(response)


# ── Main area ─────────────────────────────────────────────────────────
def main() -> None:
    # Session state defaults
    if "history" not in st.session_state:
        st.session_state["history"] = []
    if "selected_query" not in st.session_state:
        st.session_state["selected_query"] = ""

    engine = get_engine()
    render_sidebar(engine)

    st.title("\U0001f50d Enterprise Truth Engine")
    st.caption("Query knowledge across multiple sources with conflict detection")

    # Example queries
    st.markdown("**Try an example:**")
    example_cols = st.columns(len(EXAMPLE_QUERIES))
    for col, eq in zip(example_cols, EXAMPLE_QUERIES):
        with col:
            if st.button(eq, use_container_width=True):
                st.session_state["selected_query"] = eq
                st.rerun()

    st.divider()

    # Query input
    query = st.text_input(
        "Enter your question",
        value=st.session_state.get("selected_query", ""),
        placeholder="e.g. What is the recommended maintenance schedule?",
    )
    # Clear selected_query after it has been used
    if st.session_state.get("selected_query"):
        st.session_state["selected_query"] = ""

    if st.button("Ask Truth Engine", type="primary", use_container_width=True):
        if not query.strip():
            st.error("Please enter a question.")
            return

        with st.spinner("Querying knowledge base..."):
            try:
                response: QueryResponse = engine.query(query.strip())
            except Exception as exc:
                st.error(f"Query failed: {exc}")
                return

        # Store in history
        st.session_state["history"].append(
            {"query": query.strip(), "response": response}
        )

        render_results(response)

    # Show the last result if returning from a rerun without a new query
    elif st.session_state.get("history"):
        last = st.session_state["history"][-1]
        st.caption(f"Showing last result for: *{last['query']}*")
        render_results(last["response"])


if __name__ == "__main__":
    main()
