"""Extractor worker: parses compiled .tex files and writes structured metadata."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from config.paths import OUTPUT_DIR
from .base import Worker, setup_logging

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

RE_SECTION   = re.compile(r'^\s*\\(chapter|section|subsection)\{([^}]*)\}')
RE_ENV_BEGIN = re.compile(r'^\s*\\begin\{([^}]+)\}(?:\[([^\]]*)\])?')
RE_ENV_END   = re.compile(r'^\s*\\end\{([^}]+)\}')
RE_LABEL     = re.compile(r'\\label\{([^}]+)\}')


def stale_tex_finder(output_dir: Path) -> Callable[[], Path | None]:
    """Return a job-finder that yields the first .tex whose .meta.json is missing or stale."""
    def find() -> Path | None:
        if not output_dir.exists():
            return None
        for tex_path in sorted(output_dir.rglob("*.tex")):
            meta_path = tex_path.parent / f"{tex_path.stem}.meta.json"
            if not meta_path.exists() or meta_path.stat().st_mtime < tex_path.stat().st_mtime:
                return tex_path
        return None
    return find


def parse_tex(tex_path: Path) -> dict:
    lines = tex_path.read_text(encoding="utf-8").splitlines()
    sections: list[dict] = []
    environments: list[dict] = []
    stack: list[dict] = []  # frames: {env, begin_line, title, label}

    i = 0
    while i < len(lines):
        line = lines[i]
        line_no = i + 1  # 1-indexed

        # Sectioning
        m = RE_SECTION.match(line)
        if m:
            sections.append({"type": m.group(1), "title": m.group(2), "line": line_no})
            i += 1
            continue

        # Environment begin
        m = RE_ENV_BEGIN.match(line)
        if m:
            env_name = m.group(1)
            opt_title = m.group(2)  # None if no [...] on same line

            if env_name in TRACKED_ENVS:
                stack.append({
                    "env": env_name,
                    "begin_line": line_no,
                    "title": opt_title,
                    "label": None,
                })
            i += 1

        # Environment end
        m = RE_ENV_END.match(line)
        if m:
            env_name = m.group(1)
            if env_name in TRACKED_ENVS:
                for j in range(len(stack) - 1, -1, -1):
                    if stack[j]["env"] == env_name:
                        frame = stack.pop(j)
                        environments.append({
                            "type": frame["env"],
                            "title": frame["title"],
                            "label": frame["label"],
                            "begin_line": frame["begin_line"],
                            "end_line": line_no,
                        })
                        break

        # Label — assign to innermost open environment
        lm = RE_LABEL.search(line)
        if lm and stack:
            frame = stack[-1]
            if frame["label"] is None:
                frame["label"] = lm.group(1)

        i += 1

    return {"sections": sections, "environments": environments}


def make_process(output_dir: Path) -> Callable[[Path], None]:
    def process(tex_path: Path) -> None:
        stem = tex_path.stem
        rel = tex_path.relative_to(output_dir)
        meta_path = tex_path.parent / f"{stem}.meta.json"

        parsed = parse_tex(tex_path)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        meta = {
            "file": rel.as_posix(),
            "tex_mtime": tex_path.stat().st_mtime,
            "extracted_at": now,
            "sections": parsed["sections"],
            "environments": parsed["environments"],
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("extracted %s (%d envs, %d sections)",
                 rel, len(parsed["environments"]), len(parsed["sections"]))

        # Rebuild course-level index.json atomically
        course_dir = tex_path.parent
        index_files: dict[str, dict] = {}
        for mf in sorted(course_dir.glob("*.meta.json")):
            file_stem = mf.name[: -len(".meta.json")]
            try:
                index_files[file_stem] = json.loads(mf.read_text(encoding="utf-8"))
            except Exception as exc:
                log.warning("could not read %s: %s", mf.name, exc)

        index = {"updated_at": now, "files": index_files}
        tmp_path = course_dir / "index.json.tmp"
        tmp_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.rename(course_dir / "index.json")
        log.info("rebuilt index for %s (%d files)", course_dir.name, len(index_files))

    return process


def main() -> None:
    Worker(
        name="extractor",
        find_job=stale_tex_finder(OUTPUT_DIR),
        process=make_process(OUTPUT_DIR),
    ).run()


if __name__ == "__main__":
    main()
