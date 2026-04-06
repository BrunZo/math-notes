"""Debugger worker: uses an AI model to fix LaTeX compilation errors."""
import json
import os
import re
from pathlib import Path
from typing import Callable

from .base import Worker, setup_logging
from .parsing import MODEL_REGISTRY

log = setup_logging("debugger")

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
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
        # No specific line — return the whole file
        return 0, len(tex_lines)
    center = min(line_nums) - 1  # convert to 0-indexed
    start = max(0, center - _SNIPPET_CONTEXT)
    end = min(len(tex_lines), max(line_nums) + _SNIPPET_CONTEXT)
    return start, end


def make_process(output_dir: Path, model: str) -> Callable[[Path], None]:
    client = MODEL_REGISTRY[model](model=model)

    def process(job_path: Path) -> None:
        bug_data = json.loads(job_path.read_text(encoding="utf-8"))
        tex_rel = Path(bug_data["tex_path"])
        error_msg = bug_data["error"]

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

        try:
            fixed_snippet = client.complete_text(_DEBUG_SYSTEM_PROMPT, user_text)
        except Exception as exc:
            log.error("AI call failed for %s: %s", tex_rel, exc)
            return

        tex_lines[start:end] = fixed_snippet.splitlines()
        tex_path.write_text("\n".join(tex_lines), encoding="utf-8")
        # Re-signal compiler.
        tex_path.with_suffix(".tex.job").write_text("{}", encoding="utf-8")
        job_path.unlink(missing_ok=True)
        log.info("fixed and re-queued %s", tex_rel)

    return process


def main() -> None:
    output_dir = Path(os.environ["OUTPUT_DIR"])
    model = os.environ.get("DEBUGGER_MODEL", _DEFAULT_MODEL)
    if model not in MODEL_REGISTRY:
        raise ValueError(f"Unknown DEBUGGER_MODEL '{model}'. Available: {list(MODEL_REGISTRY)}")
    bugs_dir = output_dir / "bugs"
    Worker(
        name="debugger",
        job_dir=bugs_dir,
        output_dir=output_dir,
        process=make_process(output_dir, model),
        glob_pattern="*.bug",
    ).run()


if __name__ == "__main__":
    main()
