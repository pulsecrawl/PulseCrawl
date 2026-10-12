"""A schedule tick has the same execution identity across retries."""

import hashlib


def _execution_id(job_id: str, scheduled_for: str) -> str:
    digest = hashlib.sha256(f"{job_id}\0{scheduled_for}".encode()).hexdigest()[:32]
    return f"exec_sched_{digest}"
