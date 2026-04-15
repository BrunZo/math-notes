"""Debugger worker: compiles .tex files from PENDING_DIR, optionally AI-fixes errors.

Flow per file:
1. Compile the .tex via compile_single
2. If success → move to TEX_DIR
3. If failure → AI debug loop (up to debug_iters attempts)
4. If fix found → move to TEX_DIR
5. If all attempts fail → move to MANUAL_REVIEW_DIR
"""

import os
import shutil
from pathlib import Path
from typing import Callable

from config.paths import MANUAL_REVIEW_DIR, PENDING_DIR, TEX_DIR
from latex.compile import compile_single
from llm import MODEL_REGISTRY
from workflow.base import Worker, setup_logging
from workflow.testing.config import DEBUG_SYSTEM_PROMPT
from workflow.testing.log_parser import parse_errors
from workflow.utils import glob_finder

log = setup_logging("debugger")


def main() -> None:
    debug_model = os.environ.get("DEBUG_MODEL", "")
    debug_iters = int(os.environ.get("DEBUG_ITERS", "3"))

    Worker(
        name="debugger",
        find_job=lambda: glob_finder(PENDING_DIR, "*.tex"),
        process=debugger_process(
            PENDING_DIR, TEX_DIR, MANUAL_REVIEW_DIR, debug_model, debug_iters
        ),
    ).run()


def _move_tex(tex_path: Path, src_dir: Path, dest_dir: Path) -> None:
    """Move a .tex file from src_dir to dest_dir, preserving subdirectory structure."""
    rel = tex_path.relative_to(src_dir)
    dest = dest_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tex_path), str(dest))

    # Remove empty subdirectories up to src root
    d = tex_path.parent
    while d != src_dir:
        try:
            d.rmdir()
        except OSError:
            break
        d = d.parent


def debugger_process(
    pending_dir: Path,
    tex_dir: Path,
    review_dir: Path,
    debug_model: str,
    debug_iters: int,
) -> Callable[[Path], None]:
    def process(tex_path: Path) -> None:
        rel = tex_path.relative_to(pending_dir)

        result = compile_single(tex_path)
        if result.success:
            _move_tex(tex_path, pending_dir, tex_dir)
            log.info("compiled and moved %s", rel)
            return

        errors = parse_errors(result.stderr, line_offset=result.line_offset)
        log.warning("compile failed for %s: %d error(s)", rel, len(errors))

        if not debug_model or debug_model not in MODEL_REGISTRY:
            _move_tex(tex_path, pending_dir, review_dir)
            log.info("no debug model configured, moved %s to review", rel)
            return

        tex_lines = tex_path.read_text(encoding="utf-8").splitlines()
        min_line = min(e.line for e in errors)
        max_line = max(e.line for e in errors)
        start = max(0, min_line - 16)
        end = min(len(tex_lines), max_line + 15)

        error_list = "\n".join(f"ERROR (line {e.line}): {e.message}" for e in errors)
        snippet = "\n".join(f"{i + 1:4d}  {tex_lines[i]}" for i in range(start, end))
        prompt = (
            DEBUG_SYSTEM_PROMPT
            + "\n\n" + error_list
            + f"\n\nSNIPPET (lines {start + 1}-{end}):\n" + snippet
        )

        client = MODEL_REGISTRY[debug_model]()

        for attempt in range(1, debug_iters + 1):
            try:
                fixed_snippet = client.send_prompt(debug_model, prompt, [])
            except Exception as exc:
                log.error("AI call failed for %s (attempt %d): %s", rel, attempt, exc)
                continue

            patched_lines = tex_lines[:start] + fixed_snippet.splitlines() + tex_lines[end:]
            patched_text = "\n".join(patched_lines)

            tex_path.write_text(patched_text, encoding="utf-8")
            if compile_single(tex_path).success:
                _move_tex(tex_path, pending_dir, tex_dir)
                log.info("fix applied for %s (attempt %d/%d), moved to tex", rel, attempt, debug_iters)
                return

            log.warning("attempt %d for %s still fails to compile", attempt, rel)

        _move_tex(tex_path, pending_dir, review_dir)
        log.info("exhausted %d attempts for %s, moved to review", debug_iters, rel)

    return process


if __name__ == "__main__":
    main()
