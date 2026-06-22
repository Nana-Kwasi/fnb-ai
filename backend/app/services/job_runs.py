from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.database import AsyncSessionLocal
from app.models.job_run import JobRun
from app.observability import get_request_id


async def run_tracked_job(
    *,
    job_name: str,
    trigger_source: str,
    actor_id: str | None,
    runner: Callable[[], Awaitable[Any]],
) -> Any:
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    request_id = get_request_id()
    async with AsyncSessionLocal() as db:
        jr = JobRun(
            job_name=job_name,
            trigger_source=trigger_source,
            actor_id=actor_id,
            request_id=request_id,
            status="started",
            started_at=started,
        )
        db.add(jr)
        await db.flush()
        run_id = jr.id
        await db.commit()

    try:
        result = await runner()
        status = "success"
        err = None
    except Exception as exc:
        result = None
        status = "failed"
        err = str(exc)[:2000]
        raise
    finally:
        finished = datetime.now(timezone.utc)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        async with AsyncSessionLocal() as db:
            row = await db.get(JobRun, run_id)
            if row:
                row.status = status
                row.finished_at = finished
                row.duration_ms = duration_ms
                row.error_summary = err
                if isinstance(result, dict):
                    row.result_json = result
                elif result is None:
                    row.result_json = None
                else:
                    row.result_json = {"result": str(result)}
                await db.commit()

    return result

