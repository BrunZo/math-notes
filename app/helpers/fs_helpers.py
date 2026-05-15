from pathlib import Path


def relative_paths_with_suffix(root: Path, suffix: str) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        f.relative_to(root).with_suffix("").as_posix()
        for f in root.rglob(f"*{suffix}")
    )
