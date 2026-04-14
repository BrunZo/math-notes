"""CLI: python -m expand "section title" --model <model-id>

Finds the matching section in the course index, extracts its LaTeX block,
expands it with an LLM, and patches the .tex file in place.
"""
import argparse
import difflib
from dotenv import load_dotenv
import re
import sys
from pathlib import Path

from config.paths import DB_PATH, TEX_DIR
from models.helpers import build_outline as _db_build_outline, collect_sections as _db_collect_sections
from models.schema import init_db
from llm import MODEL_REGISTRY
from workflow.ingestion.config import LATEX_CONSTRAINTS

_RE_SECTION = re.compile(r'^\s*\\(chapter|section|subsection)\{([^}]*)\}')


def collect_sections() -> list[dict]:
    """Return all sections from the SQLite IR."""
    conn = init_db(DB_PATH)
    try:
        rows = _db_collect_sections(conn)
    finally:
        conn.close()
    candidates = []
    for row in rows:
        tex_path = TEX_DIR / row["file"]
        if not tex_path.exists():
            continue
        candidates.append({
            "title": row["title"],
            "type": row["type"],
            "line": row["line"],
            "tex_path": tex_path,
        })
    return candidates


def fuzzy_match(query: str, candidates: list[dict]) -> list[dict]:
    query_lower = query.lower()
    titles_lower = [c["title"].lower() for c in candidates]
    close = set(difflib.get_close_matches(query_lower, titles_lower, n=10, cutoff=0.4))
    seen: set[tuple] = set()
    matches = []
    for i, c in enumerate(candidates):
        t = titles_lower[i]
        if t in close or query_lower in t or t in query_lower:
            key = (c["tex_path"], c["line"])
            if key not in seen:
                seen.add(key)
                matches.append(c)
    return matches


def extract_block(tex_path: Path, start_line: int) -> tuple[int, int, list[str]]:
    """Return (start_idx, end_idx, all_lines) for the section block (0-indexed half-open)."""
    all_lines = tex_path.read_text(encoding="utf-8").splitlines()
    start = start_line - 1
    end = len(all_lines)
    for i in range(start + 1, len(all_lines)):
        if _RE_SECTION.match(all_lines[i]):
            end = i
            break
    return start, end, all_lines


def build_outline() -> str:
    """Build course outline from the SQLite IR."""
    conn = init_db(DB_PATH)
    try:
        return _db_build_outline(conn)
    finally:
        conn.close()


def build_system_prompt() -> str:
    return (
        "You are expanding a section of university-level mathematics lecture notes.\n"
        "The notes are in Spanish; maintain that language and register.\n"
        "Output ONLY the LaTeX for this section, starting with the \\section{...} line.\n\n"
        + LATEX_CONSTRAINTS + "\n\n"
        "COURSE OUTLINE (context only — do not reproduce):\n"
        + build_outline() + "\n\n"
        "TASK\n"
        "Expand the section below into a complete, self-contained textbook-quality section.\n"
        "Preserve the \\section{...} header exactly. Fill in full proofs, motivate definitions,\n"
        "add transitional prose. Do not invent theorems not implied by the existing content.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Expand a LaTeX section using an LLM.")
    parser.add_argument("query", help="Section title to search for (fuzzy)")
    parser.add_argument("--model", "-m", required=True,
                        help=f"Model ID. Available: {', '.join(MODEL_REGISTRY)}")
    args = parser.parse_args()

    if args.model not in MODEL_REGISTRY:
        print(f"Unknown model '{args.model}'. Available: {', '.join(MODEL_REGISTRY)}",
              file=sys.stderr)
        sys.exit(1)

    candidates = collect_sections()
    if not candidates:
        print(f"No sections found in IR database ({DB_PATH}). Run the extractor first.",
              file=sys.stderr)
        sys.exit(1)

    matches = fuzzy_match(args.query, candidates)

    if not matches:
        print(f"No sections found matching '{args.query}'.", file=sys.stderr)
        sys.exit(1)

    if len(matches) == 1:
        chosen = matches[0]
    else:
        print("Multiple matches found:")
        for i, m in enumerate(matches, 1):
            print(f"  {i}. [{m['tex_path'].parent.name}/{m['tex_path'].stem}] "
                  f"{m['type']}: {m['title']} (line {m['line']})")
        while True:
            raw = input(f"Pick [1-{len(matches)}]: ").strip()
            if raw.isdigit() and 1 <= int(raw) <= len(matches):
                chosen = matches[int(raw) - 1]
                break
            print("Invalid choice.")

    start, end, all_lines = extract_block(chosen["tex_path"], chosen["line"])
    block = all_lines[start:end]

    print(f"Expanding \"{chosen['title']}\" ({len(block)} lines) with {args.model}…")

    client = MODEL_REGISTRY[args.model]()
    expanded = client.send_prompt(args.model,
                                  build_system_prompt() + "\n\n" + "\n".join(block),
                                  [])

    new_lines = all_lines[:start] + expanded.splitlines() + all_lines[end:]
    chosen["tex_path"].write_text("\n".join(new_lines), encoding="utf-8")

    print(f"Done. {len(block)} → {len(expanded.splitlines())} lines "
          f"in {chosen['tex_path']}")


if __name__ == "__main__":
    load_dotenv()
    main()
