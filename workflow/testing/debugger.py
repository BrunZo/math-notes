"""Debugger worker: uses an AI model to fix LaTeX compilation errors."""
import json
from pathlib import Path
from typing import Callable

from config.paths import OUTPUT_DIR, TEX_BUGS_DIR
from workflow.base import Worker, glob_finder, setup_logging
from workflow.ingestion.parsing import MODEL_REGISTRY

log = setup_logging("debugger")

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


def make_process(output_dir: Path) -> Callable[[Path], None]:
    def process(job_path: Path) -> None:
        bug_data = json.loads(job_path.read_text(encoding="utf-8"))
        tex_rel = Path(bug_data["tex_path"])
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

        # Build user prompt from structured errors with context.
        errors = bug_data.get("errors", [])
        if not errors:
            # Fallback: use raw stderr if no structured errors.
            user_text = f"COMPILER ERRORS:\n{bug_data.get('stderr', '')}"
        else:
            parts = []
            for err in errors:
                parts.append(f"ERROR (line {err['line']}): {err['message']}")
                if err.get("context"):
                    parts.append(err["context"])
                parts.append("")
            user_text = "\n".join(parts)

        tex_content = tex_path.read_text(encoding="utf-8")
        user_text += f"\n\nFULL FILE:\n{tex_content}"

        client = MODEL_REGISTRY[debug_model](model=debug_model)
        try:
            fixed = client.complete_text(_DEBUG_SYSTEM_PROMPT, user_text)
        except Exception as exc:
            log.error("AI call failed for %s: %s", tex_rel, exc)
            return

        tex_path.write_text(fixed, encoding="utf-8")

        # Re-signal compiler with one fewer iteration remaining.
        tex_job = json.dumps({"debug_model": debug_model, "debug_iters": debug_iters - 1})
        tex_path.with_suffix(".tex.job").write_text(tex_job, encoding="utf-8")
        job_path.unlink(missing_ok=True)
        log.info("fixed and re-queued %s (%d iter(s) left)", tex_rel, debug_iters - 1)

    return process


def main() -> None:
    Worker(
        name="debugger",
        find_job=glob_finder(TEX_BUGS_DIR, "*.bug"),
        process=make_process(OUTPUT_DIR),
    ).run()


if __name__ == "__main__":
    main()
