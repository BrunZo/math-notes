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
from workflow.testing.log_parser import attach_context, parse_errors
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


def debugger_process(
    pending_dir: Path,
    tex_dir: Path,
    review_dir: Path,
    debug_model: str,
    debug_iters: int,
) -> Callable[[Path], None]:
    def process(tex_path: Path) -> None:
        rel = tex_path.relative_to(pending_dir)

        # Step 1: compile.
        result = compile_single(tex_path)
        if result.success:
            _move_tex(tex_path, pending_dir, tex_dir)
            log.info("compiled and moved %s", rel)
            return

        # Step 2: parse errors.
        errors = parse_errors(result.stderr)
        tex_lines = tex_path.read_text(encoding="utf-8").splitlines()
        attach_context(errors, tex_lines)
        log.warning("compile failed for %s: %d error(s)", rel, len(errors))

        # Step 3: AI debug loop.
        if not debug_model or debug_model not in MODEL_REGISTRY:
            _move_tex(tex_path, pending_dir, review_dir)
            log.info("no debug model configured, moved %s to review", rel)
            return

        error_text = "\n".join(
            f"ERROR (line {e.line}): {e.message}"
            + (f"\n{e.context}" if e.context else "")
            for e in errors
        )
        prompt = DEBUG_SYSTEM_PROMPT + "\n\n" + error_text

        min_line = min(e.line for e in errors)
        max_line = max(e.line for e in errors)
        start = max(0, min_line - 16)
        end = min(len(tex_lines), max_line + 15)

        client = MODEL_REGISTRY[debug_model]()

        for attempt in range(1, debug_iters + 1):
            try:
                fixed_snippet = client.send_prompt(debug_model, prompt, [])
            except Exception as exc:
                log.error("AI call failed for %s (attempt %d): %s", rel, attempt, exc)
                continue

            patched_lines = (
                tex_lines[:start] + fixed_snippet.splitlines() + tex_lines[end:]
            )
            patched_text = "\n".join(patched_lines)

            # Guard: patched version compiles.
            tmp_tex = tex_path.with_suffix(".debug.tex")
            tmp_tex.write_text(patched_text, encoding="utf-8")
            check = compile_single(tmp_tex)
            tmp_tex.unlink(missing_ok=True)

            if not check.success:
                log.warning("attempt %d for %s still fails to compile", attempt, rel)
                continue

            # Fix verified — apply and move.
            tex_path.write_text(patched_text, encoding="utf-8")
            _move_tex(tex_path, pending_dir, tex_dir)
            log.info(
                "fix applied for %s (attempt %d/%d), moved to tex",
                rel,
                attempt,
                debug_iters,
            )
            return

        # All attempts exhausted.
        _move_tex(tex_path, pending_dir, review_dir)
        log.info("exhausted %d attempts for %s, moved to review", debug_iters, rel)

    return process


def _move_tex(tex_path: Path, src_dir: Path, dest_dir: Path) -> None:
    """Move a .tex file from src_dir to dest_dir, preserving subdirectory structure."""
    rel = tex_path.relative_to(src_dir)
    dest = dest_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tex_path), str(dest))


if __name__ == "__main__":
    main()
