"""Entry point for the Truth Engine application."""

import sys
import subprocess


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--ingest":
        from app.core.rag_engine import RAGEngine

        engine = RAGEngine()
        engine.ingest(force_reindex=True)
        print("Ingestion complete!")
    else:
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run", "app/ui/streamlit_app.py"],
            check=True,
        )


if __name__ == "__main__":
    main()
