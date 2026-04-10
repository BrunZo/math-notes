"""Debugger worker: uses an AI model to fix LaTeX compilation errors.

Flow:
1. Read structured errors from .bug file
2. Send error context + preamble to AI, get a fix for the snippet
3. Apply fix to a copy of the .tex, compile the copy
4. If compilation succeeds and no labels were lost → apply to real file
5. If not → decrement iterations; on exhaustion move to human_review/
"""
import json
import re
import shutil
from pathlib import Path
from typing import Callable

from jinja2 import Environment, FileSystemLoader

from config.paths import OUTPUT_DIR, TEX_BUGS_DIR
from latex.compile import compile_single
from workflow.base import Worker, glob_finder, setup_logging
from workflow.ingestion.parsing import MODEL_REGISTRY

log = setup_logging("debugger")

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=False)

_RE_LABEL = re.compile(r"\\label\{([^}]+)\}")


def _load_preamble() -> str:
    """Extract the preamble (everything before \\begin{document}) from master.tex.j2."""
    template_src = _jinja_env.loader.get_source(_jinja_env, "master.tex.j2")[0]
    lines = template_src.splitlines()
    preamble_lines = []
    for line in lines:
        if r"\begin{document}" in line:
            break
        preamble_lines.append(line)
    return "\n".join(preamble_lines)


_PREAMBLE = _load_preamble()

_DEBUG_SYSTEM_PROMPT = f"""
You are a LaTeX debugging assistant. You will be given a snippet from a body-only \
LaTeX file (no \\documentclass) that failed to compile with tectonic, along with \
the compiler error message.

Your task: return the corrected snippet — the exact same region, with only the \
minimum changes needed to fix the error.

Rules:
- Return only the corrected lines. No explanations, no markdown fences.
- Do not add \\documentclass, \\begin{{document}}, or any preamble content.
- Preserve every line that does not need to change.

The document preamble (for reference — do NOT include it in your output):
{_PREAMBLE}
""".strip()

_MAX_ATTEMPTS = 3


def _extract_labels(text: str) -> set[str]:
    return set(_RE_LABEL.findall(text))


def make_process(output_dir: Path) -> Callable[[Path], None]:
    def process(job_path: Path) -> None:
        bug_data = json.loads(job_path.read_text(encoding="utf-8"))
        tex_rel = Path(bug_data["tex_path"])
        debug_model = bug_data.get("debug_model", "")
        debug_iters = bug_data.get("debug_iters", 0)

        if debug_iters <= 0:
            log.info("no debug iterations left for %s, moving to human review", tex_rel)
            _move_to_review(output_dir, tex_rel)
            job_path.unlink(missing_ok=True)
            return

        if debug_model not in MODEL_REGISTRY:
            log.error("unknown debug_model '%s' for %s, skipping", debug_model, tex_rel)
            return

        tex_path = output_dir / tex_rel
        if not tex_path.exists():
            log.warning("tex file not found: %s, removing bug", tex_path)
            job_path.unlink(missing_ok=True)
            return

        original_text = tex_path.read_text(encoding="utf-8")
        original_labels = _extract_labels(original_text)
        tex_lines = original_text.splitlines()

        # Build user prompt from structured errors — only context lines.
        errors = bug_data.get("errors", [])
        if not errors:
            log.warning("no structured errors for %s, skipping", tex_rel)
            return

        parts = []
        for err in errors:
            parts.append(f"ERROR (line {err['line']}): {err['message']}")
            if err.get("context"):
                parts.append(err["context"])
            parts.append("")
        user_text = "\n".join(parts)

        # Determine the span covered by all error contexts.
        min_line = min(e["line"] for e in errors)
        max_line = max(e["line"] for e in errors)
        start = max(0, min_line - 16)   # match log_parser context_lines=15
        end = min(len(tex_lines), max_line + 15)

        client = MODEL_REGISTRY[debug_model](model=debug_model)
        try:
            fixed_snippet = client.complete_text(_DEBUG_SYSTEM_PROMPT, user_text)
        except Exception as exc:
            log.error("AI call failed for %s: %s", tex_rel, exc)
            return

        # Apply fix to a copy and validate.
        patched_lines = tex_lines[:start] + fixed_snippet.splitlines() + tex_lines[end:]
        patched_text = "\n".join(patched_lines)

        # Guard 1: no labels lost.
        patched_labels = _extract_labels(patched_text)
        lost_labels = original_labels - patched_labels
        if lost_labels:
            log.warning("patch for %s would lose labels %s, rejecting", tex_rel, lost_labels)
            _retry_or_review(job_path, bug_data, output_dir, tex_rel)
            return

        # Guard 2: patched version compiles.
        # Write patched copy next to original, compile, then clean up.
        tmp_tex = tex_path.with_suffix(".debug.tex")
        tmp_tex.write_text(patched_text, encoding="utf-8")
        try:
            result = compile_single(tmp_tex)
        finally:
            tmp_tex.unlink(missing_ok=True)

        if not result.success:
            log.warning("patched %s still fails to compile, rejecting", tex_rel)
            _retry_or_review(job_path, bug_data, output_dir, tex_rel)
            return

        # All guards passed — apply the fix.
        tex_path.write_text(patched_text, encoding="utf-8")
        job_path.unlink(missing_ok=True)
        log.info("fix verified and applied for %s (%d iter(s) left)", tex_rel, debug_iters - 1)

    return process


def _retry_or_review(
    job_path: Path, bug_data: dict, output_dir: Path, tex_rel: Path,
) -> None:
    """Decrement iterations; if exhausted, move to human review."""
    iters_left = bug_data.get("debug_iters", 0) - 1
    if iters_left > 0:
        bug_data["debug_iters"] = iters_left
        job_path.write_text(
            json.dumps(bug_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("will retry %s (%d iter(s) left)", tex_rel, iters_left)
    else:
        _move_to_review(output_dir, tex_rel)
        job_path.unlink(missing_ok=True)
        log.info("exhausted retries for %s, moved to human review", tex_rel)


def _move_to_review(output_dir: Path, tex_rel: Path) -> None:
    """Move a .tex file to the human_review/ subdirectory."""
    src = output_dir / tex_rel
    if not src.exists():
        return
    review_dir = output_dir / "human_review" / tex_rel.parent
    review_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(review_dir / src.name))


def main() -> None:
    Worker(
        name="debugger",
        find_job=glob_finder(TEX_BUGS_DIR, "*.bug"),
        process=make_process(OUTPUT_DIR),
    ).run()


if __name__ == "__main__":
    main()
