"""Extractor worker: parses compiled .tex files into the SQLite IR via pylatexenc."""
import hashlib
import re
from pathlib import Path
from typing import Callable

from pylatexenc.latexwalker import (
    LatexWalker,
    LatexCharsNode,
    LatexEnvironmentNode,
    LatexMacroNode,
)

from config.paths import DB_PATH, OUTPUT_DIR
from models.helpers import (
    FileParseResult,
    ObjectInfo,
    RefInfo,
    SectionInfo,
    rebuild_file,
)
from models.schema import init_db
from workflow.base import Worker, setup_logging

log = setup_logging("extractor")

TRACKED_ENVS = frozenset({
    "theorem",     "theorem*",
    "proposition", "proposition*",
    "lemma",       "lemma*",
    "corollary",   "corollary*",
    "conjecture",  "conjecture*",
    "definition",  "definition*",
    "example",     "example*",
    "remark",      "remark*",
    "exercise",    "exercise*",
    "proof",
})

SECTION_MACROS = {"chapter": 0, "section": 1, "subsection": 2}
REF_MACROS = {"ref", "eqref", "cref", "cite"}
RE_PROVENANCE = re.compile(r"^%\s*source:\s*(\S+).*?sha256:([a-f0-9]+)", re.MULTILINE)


def _offset_to_line(source: str, offset: int) -> int:
    """Convert a character offset to a 1-indexed line number."""
    return source[:offset].count("\n") + 1


def _extract_macro_arg(node: LatexMacroNode) -> str | None:
    """Get the first brace-group argument text from a macro node."""
    if not node.nodeargd or not node.nodeargd.argnlist:
        return None
    for arg in node.nodeargd.argnlist:
        if arg is None:
            continue
        if hasattr(arg, "nodelist") and arg.nodelist:
            parts = []
            for child in arg.nodelist:
                if hasattr(child, "chars"):
                    parts.append(child.chars)
                elif hasattr(child, "latex_verbatim"):
                    parts.append(child.latex_verbatim())
            if parts:
                return "".join(parts)
        if hasattr(arg, "chars"):
            return arg.chars
    return None


def _extract_optional_arg(node: LatexEnvironmentNode | LatexMacroNode) -> str | None:
    """Get the first bracket-delimited optional argument text."""
    if not node.nodeargd or not node.nodeargd.argnlist:
        return None
    for arg in node.nodeargd.argnlist:
        if arg is None:
            continue
        # Optional args have is_whitespace_node or come from [] delimiters
        if hasattr(arg, "delimiters") and arg.delimiters == ("[", "]"):
            if hasattr(arg, "nodelist") and arg.nodelist:
                return "".join(
                    c.chars for c in arg.nodelist if hasattr(c, "chars")
                )
    return None


def _count_words(source: str, start_line: int, end_line: int) -> int:
    """Count words in the given line range, stripping LaTeX commands."""
    lines = source.splitlines()
    block = " ".join(lines[start_line - 1 : end_line])
    # Strip commands but keep text
    text = re.sub(r"\\[a-zA-Z]+\*?(\{[^}]*\})*(\[[^\]]*\])*", " ", block)
    text = re.sub(r"[{}\\$%&_^~]", " ", text)
    return len(text.split())


def _status_from_words(word_count: int) -> str:
    if word_count < 50:
        return "stub"
    if word_count < 200:
        return "draft"
    return "complete"


def _walk_nodes(nodes, source: str, result: FileParseResult,
                current_section_idx: int | None,
                section_stack: list[tuple[int, int]]):
    """Recursively walk AST nodes, populating result."""
    for node in nodes:
        if isinstance(node, LatexMacroNode):
            name = node.macroname

            # Sectioning macro
            if name in SECTION_MACROS:
                level_rank = SECTION_MACROS[name]
                title = _extract_macro_arg(node) or ""
                line = _offset_to_line(source, node.pos)

                # Pop stack until parent is a higher level
                while section_stack and section_stack[-1][0] >= level_rank:
                    section_stack.pop()

                parent_idx = section_stack[-1][1] if section_stack else None
                idx = len(result.sections)
                result.sections.append(SectionInfo(
                    level=name,
                    title=title,
                    line_start=line,
                    parent_index=parent_idx,
                ))
                section_stack.append((level_rank, idx))

            # Label macro
            elif name == "label":
                label = _extract_macro_arg(node)
                if label:
                    # Assign to innermost open object if any, else to current section
                    # (objects are assigned during environment processing below)
                    # For section labels, assign to current section
                    if result.sections:
                        last_sec = result.sections[-1]
                        if last_sec.label is None:
                            last_sec.label = label

            # Reference macros
            elif name in REF_MACROS:
                to_label = _extract_macro_arg(node)
                if to_label:
                    line = _offset_to_line(source, node.pos)
                    result.refs.append(RefInfo(
                        from_object_index=None,  # patched later if inside an env
                        to_label=to_label,
                        line=line,
                        kind=name,
                    ))

        elif isinstance(node, LatexEnvironmentNode):
            env_name = node.environmentname
            if env_name in TRACKED_ENVS:
                line_start = _offset_to_line(source, node.pos)
                line_end = _offset_to_line(source, node.pos + node.len - 1)
                opt_title = _extract_optional_arg(node)

                # Body hash
                body_start = node.nodelist[0].pos if node.nodelist else node.pos
                body_end = node.pos + node.len
                body_text = source[body_start:body_end]
                body_hash = hashlib.sha256(body_text.encode()).hexdigest()

                # Find current section for this object
                sec_idx = section_stack[-1][1] if section_stack else None

                obj_idx = len(result.objects)
                obj = ObjectInfo(
                    kind=env_name.rstrip("*"),
                    title=opt_title,
                    line_start=line_start,
                    line_end=line_end,
                    body_hash=body_hash,
                    section_index=sec_idx,
                )
                result.objects.append(obj)

                # Walk body to find labels and refs inside this environment
                if node.nodelist:
                    refs_before = len(result.refs)
                    for child in node.nodelist:
                        if isinstance(child, LatexMacroNode):
                            if child.macroname == "label":
                                label = _extract_macro_arg(child)
                                if label and obj.label is None:
                                    obj.label = label
                            elif child.macroname in REF_MACROS:
                                to_label = _extract_macro_arg(child)
                                if to_label:
                                    result.refs.append(RefInfo(
                                        from_object_index=obj_idx,
                                        to_label=to_label,
                                        line=_offset_to_line(source, child.pos),
                                        kind=child.macroname,
                                    ))
                    # Patch any refs added by recursive walk to point to this object
                    for r in result.refs[refs_before:]:
                        if r.from_object_index is None:
                            r.from_object_index = obj_idx
                # Don't recurse further into tracked envs
                continue

        # Recurse into child nodes
        if hasattr(node, "nodelist") and node.nodelist:
            sec_idx = section_stack[-1][1] if section_stack else None
            _walk_nodes(node.nodelist, source, result, sec_idx, section_stack)


def _backfill_section_ends(result: FileParseResult, total_lines: int) -> None:
    """Set line_end for each section (line before next same-or-higher-level section, or EOF)."""
    sections = result.sections
    for i, sec in enumerate(sections):
        level_rank = SECTION_MACROS.get(sec.level, 99)
        end = total_lines
        for j in range(i + 1, len(sections)):
            next_rank = SECTION_MACROS.get(sections[j].level, 99)
            if next_rank <= level_rank:
                end = sections[j].line_start - 1
                break
        sec.line_end = end


def parse_tex_ast(tex_path: Path) -> FileParseResult:
    """Parse a .tex file into a FileParseResult using pylatexenc."""
    source = tex_path.read_text(encoding="utf-8")
    total_lines = source.count("\n") + 1

    result = FileParseResult()

    try:
        walker = LatexWalker(source)
        nodes, _, _ = walker.get_latex_nodes()
    except Exception as exc:
        log.warning("pylatexenc failed on %s: %s — skipping", tex_path.name, exc)
        return result

    section_stack: list[tuple[int, int]] = []  # (level_rank, section_index)
    _walk_nodes(nodes, source, result, None, section_stack)

    _backfill_section_ends(result, total_lines)

    # Compute word counts and status for each section
    for sec in result.sections:
        sec.word_count = _count_words(source, sec.line_start, sec.line_end)
        sec.status = _status_from_words(sec.word_count)

    return result


def stale_tex_finder(output_dir: Path) -> Callable[[], Path | None]:
    """Return a job-finder that yields the first .tex whose IR entry is missing or stale."""
    def find() -> Path | None:
        if not output_dir.exists():
            return None
        conn = init_db(DB_PATH)
        try:
            for tex_path in sorted(output_dir.rglob("*.tex")):
                rel = tex_path.relative_to(output_dir).as_posix()
                row = conn.execute(
                    "SELECT last_built_at FROM files WHERE path = ?", (rel,)
                ).fetchone()
                if row is None:
                    return tex_path
                # Compare file mtime against last_built_at
                from datetime import datetime, timezone
                built = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                mtime = datetime.fromtimestamp(tex_path.stat().st_mtime, tz=timezone.utc)
                if mtime > built:
                    return tex_path
        finally:
            conn.close()
        return None
    return find


def make_process(output_dir: Path) -> Callable[[Path], None]:
    def process(tex_path: Path) -> None:
        rel = tex_path.relative_to(output_dir).as_posix()

        result = parse_tex_ast(tex_path)

        # Compute file hash
        file_bytes = tex_path.read_bytes()
        file_sha = hashlib.sha256(file_bytes).hexdigest()

        conn = init_db(DB_PATH)
        try:
            rebuild_file(conn, rel, result, file_sha)
            log.info(
                "extracted %s (%d sections, %d objects, %d refs)",
                rel,
                len(result.sections),
                len(result.objects),
                len(result.refs),
            )
        finally:
            conn.close()

    return process


def main() -> None:
    Worker(
        name="extractor",
        find_job=stale_tex_finder(OUTPUT_DIR),
        process=make_process(OUTPUT_DIR),
    ).run()


if __name__ == "__main__":
    main()
