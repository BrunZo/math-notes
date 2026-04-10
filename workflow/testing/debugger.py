"""Debugger worker: compiles .tex files, and on failure runs an AI debug loop.

Flow per job:
1. Compile the .tex via compile_single
2. If success → done
3. If failure → parse errors, then for each attempt up to debug_iters:
   a. Send error context + preamble to AI, get a snippet fix
   b. Apply fix to a copy, check labels preserved, compile the copy
   c. If both pass → apply to real file, done
4. If all attempts fail → move .tex to human_review/
"""
import json
import re
import shutil
from pathlib import Path
from typing import Callable

from jinja2 import Environment, FileSystemLoader

from config.paths import OUTPUT_DIR
from latex.compile import compile_single
from workflow.base import Worker, glob_finder, setup_logging
from workflow.ingestion.parsing import MODEL_REGISTRY
from workflow.testing.log_parser import parse_errors, attach_context

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


def _extract_labels(text: str) -> set[str]:
    return set(_RE_LABEL.findall(text))


def _move_to_review(output_dir: Path, tex_rel: Path) -> None:
    """Move a .tex file to the human_review/ subdirectory."""
    src = output_dir / tex_rel
    if not src.exists():
        return
    review_dir = output_dir / "human_review" / tex_rel.parent
    review_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(review_dir / src.name))


def make_process(output_dir: Path) -> Callable[[Path], None]:
    def process(job_path: Path) -> None:
        tex_path = job_path.with_suffix("")  # strips .job → .tex
        rel = tex_path.relative_to(output_dir)

        job_meta = json.loads(job_path.read_text(encoding="utf-8"))
        debug_model = job_meta.get("debug_model", "")
        debug_iters = job_meta.get("debug_iters", 0)
        job_path.unlink(missing_ok=True)

        if not tex_path.exists():
            log.warning("no .tex found for %s, skipping", job_path)
            return

        # Step 1: compile.
        result = compile_single(tex_path)
        if result.success:
            log.info("compiled %s", rel)
            return

        # Step 2: parse errors.
        errors = parse_errors(result.stderr)
        if not errors:
            log.warning("compile failed for %s but no parseable errors, skipping debug", rel)
            return

        tex_lines = tex_path.read_text(encoding="utf-8").splitlines()
        attach_context(errors, tex_lines)
        log.warning("compile failed for %s: %d error(s)", rel, len(errors))

        # Step 3: debug loop.
        if not debug_model or debug_model not in MODEL_REGISTRY:
            if debug_model:
                log.error("unknown debug_model '%s' for %s", debug_model, rel)
            _move_to_review(output_dir, rel)
            log.info("no valid debug model for %s, moved to human review", rel)
            return

        original_text = tex_path.read_text(encoding="utf-8")
        original_labels = _extract_labels(original_text)

        parts = []
        for err in errors:
            parts.append(f"ERROR (line {err.line}): {err.message}")
            if err.context:
                parts.append(err.context)
            parts.append("")
        user_text = "\n".join(parts)

        min_line = min(e.line for e in errors)
        max_line = max(e.line for e in errors)
        start = max(0, min_line - 16)
        end = min(len(tex_lines), max_line + 15)

        client = MODEL_REGISTRY[debug_model](model=debug_model)

        for attempt in range(1, debug_iters + 1):
            try:
                fixed_snippet = client.complete_text(_DEBUG_SYSTEM_PROMPT, user_text)
            except Exception as exc:
                log.error("AI call failed for %s (attempt %d): %s", rel, attempt, exc)
                continue

            patched_lines = tex_lines[:start] + fixed_snippet.splitlines() + tex_lines[end:]
            patched_text = "\n".join(patched_lines)

            # Guard 1: no labels lost.
            lost_labels = original_labels - _extract_labels(patched_text)
            if lost_labels:
                log.warning("attempt %d for %s would lose labels %s, rejecting", attempt, rel, lost_labels)
                continue

            # Guard 2: patched version compiles.
            tmp_tex = tex_path.with_suffix(".debug.tex")
            tmp_tex.write_text(patched_text, encoding="utf-8")
            try:
                check = compile_single(tmp_tex)
            finally:
                tmp_tex.unlink(missing_ok=True)

            if not check.success:
                log.warning("attempt %d for %s still fails to compile, rejecting", attempt, rel)
                continue

            # All guards passed.
            tex_path.write_text(patched_text, encoding="utf-8")
            log.info("fix verified and applied for %s (attempt %d/%d)", rel, attempt, debug_iters)
            return

        # All attempts exhausted.
        _move_to_review(output_dir, rel)
        log.info("exhausted %d debug attempts for %s, moved to human review", debug_iters, rel)

    return process


def main() -> None:
    Worker(
        name="debugger",
        find_job=glob_finder(OUTPUT_DIR, "*.tex.job"),
        process=make_process(OUTPUT_DIR),
    ).run()


if __name__ == "__main__":
    main()
