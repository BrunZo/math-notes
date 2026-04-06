"""Generic Worker primitive for all pipeline workers."""
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


def setup_logging(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )
    return logging.getLogger(name)


@dataclass
class Worker:
    name: str
    job_dir: Path
    output_dir: Path
    process: Callable[[Path], None]
    glob_pattern: str = "*.job"
    poll_interval: int = 5

    def run(self) -> None:
        log = logging.getLogger(self.name)
        log.info("started (job_dir=%s, output_dir=%s)", self.job_dir, self.output_dir)
        try:
            while True:
                job = self._find_job()
                if job is None:
                    time.sleep(self.poll_interval)
                    continue
                log.info("processing %s", job)
                try:
                    self.process(job)
                except Exception as exc:
                    log.error("error on %s: %s", job, exc)
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("shutting down")
            sys.exit(0)

    def _find_job(self) -> Path | None:
        if not self.job_dir.exists():
            return None
        return next((f for f in sorted(self.job_dir.rglob(self.glob_pattern))), None)
