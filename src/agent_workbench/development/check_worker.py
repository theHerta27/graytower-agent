"""Trusted background control process; candidate code only runs in Docker."""
from pathlib import Path
import sys
from .checks import CheckJobs
from .sandbox import execute, CheckNotStarted
from .workspace import encoded


def run(root, job_id):
    jobs = CheckJobs(root)
    record = Path(root) / job_id / 'resources.json'
    try:
        payload = jobs.payload(job_id)
        outcome = execute(payload, lambda value: record.write_bytes(encoded(value)))
        jobs.complete(job_id, outcome)
    except CheckNotStarted as exc:
        jobs.mark_not_started(job_id,str(exc))
        raise
    except Exception as exc:
        jobs.mark_unknown(job_id, type(exc).__name__)
        raise


if __name__ == '__main__':
    run(sys.argv[1], sys.argv[2])
