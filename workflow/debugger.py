"""Debugger worker: uses an AI model to fix LaTeX compilation errors."""
import json
import re
from pathlib import Path
from typing import Callable

from config.paths import OUTPUT_DIR
from .base import Worker, setup_logging
from .parsing import MODEL_REGISTRY

log = setup_logging("debugger")

_SNIPPET_CONTEXT = 20  # lines before/after error location

_DEBUG_SYSTEM_PROMPT = """
You are a LaTeX debugging assistant. You will be given a snippet from a body-only \
LaTeX file (no \\documentclass) that failed to compile with tectonic, along with \
the compiler error message.

Your task: return the corrected snippet — the exact same region, with only the \
minimum changes needed to fix the error.

Rules:
- Return only the corrected lines. No explanations, no markdown fences.
- Do not add \\documentclass, \\begin{document}, or any preamble content.
- Preserve every line that does not need to change.
- Available custom commands: \\N \\Z \\Q \\R \\C \\bbk \\eps \\abs{} and \
environments: theorem, proposition, lemma, corollary, conjecture, theorem*, \
conjecture*, definition, example, remark, exercise, proof.
""".strip()


def _extract_snippet(tex_lines: list[str], error_msg: str) -> tuple[int, int]:
    """Return (start, end) 0-indexed slice bounds for the relevant snippet."""
    line_nums = [int(m) for m in re.findall(r'\.tex:(\d+):', error_msg)]
    if not line_nums:
        return 0, len(tex_lines)
    center = min(line_nums) - 1  # convert to 0-indexed
    start = max(0, center - _SNIPPET_CONTEXT)
    end = min(len(tex_lines), max(line_nums) + _SNIPPET_CONTEXT)
    return start, end


def make_process(output_dir: Path) -> Callable[[Path], None]:
    def process(job_path: Path) -> None:
        bug_data = json.loads(job_path.read_text(encoding="utf-8"))
        tex_rel = Path(bug_data["tex_path"])
        error_msg = bug_data["error"]
        debug_model = bug_data.get("debug_model", "")
        debug_iters = bug_data.get("debug_iters", 0)

        if debug_iters <= 0:
            log.info("no debug iterations left for %s, leaving bug", tex_rel)
            return

        if debug_model not in MODEL_REGISTRY:
            log.error("unknown debug_model '%s' for %s, skipping", debug_model, tex_rel)
            return

        tex_path = output_dir / tex_rel
        if not tex_path.exists():
            log.warning("tex file not found: %s, removing bug", tex_path)
            job_path.unlink(missing_ok=True)
            return

        tex_lines = tex_path.read_text(encoding="utf-8").splitlines()
        start, end = _extract_snippet(tex_lines, error_msg)
        snippet = "\n".join(tex_lines[start:end])

        user_text = (
            f"COMPILER ERROR:\n{error_msg}\n\n"
            f"SNIPPET (lines {start + 1}–{end}):\n{snippet}"
        )

        client = MODEL_REGISTRY[debug_model](model=debug_model)
        try:
            fixed_snippet = client.complete_text(_DEBUG_SYSTEM_PROMPT, user_text)
        except Exception as exc:
            log.error("AI call failed for %s: %s", tex_rel, exc)
            return

        tex_lines[start:end] = fixed_snippet.splitlines()
        tex_path.write_text("\n".join(tex_lines), encoding="utf-8")

        # Re-signal compiler with one fewer iteration remaining.
        tex_job = json.dumps({"debug_model": debug_model, "debug_iters": debug_iters - 1})
        tex_path.with_suffix(".tex.job").write_text(tex_job, encoding="utf-8")
        job_path.unlink(missing_ok=True)
        log.info("fixed and re-queued %s (%d iter(s) left)", tex_rel, debug_iters - 1)

    return process


def main() -> None:
    Worker(
        name="debugger",
        job_dir=OUTPUT_DIR / "bugs",
        output_dir=OUTPUT_DIR,
        process=make_process(OUTPUT_DIR),
        glob_pattern="*.bug",
    ).run()


if __name__ == "__main__":
    main()
