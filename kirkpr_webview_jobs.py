# -*- coding: utf-8 -*-
"""Ena dolgotrajna naloga hkrati, z možnostjo poizvedovanja stanja."""
from __future__ import annotations

import logging
import threading
import traceback
import uuid
from typing import Any, Callable

log = logging.getLogger("kirkpr.jobs")


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._active: str | None = None

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._active is not None

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(str(job_id or ""))
            return dict(job) if job else None

    def start(self, label: str, fn: Callable[..., Any], payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._active is not None:
                raise RuntimeError("Druga naloga v ozadju še teče — počakaj na zaključek.")
            job_id = uuid.uuid4().hex
            job = {
                "id": job_id,
                "label": label,
                "state": "running",
                "result": None,
                "error": "",
                "msg": label,
            }
            self._jobs[job_id] = job
            self._active = job_id

        def worker() -> None:
            try:
                result = fn(payload)
                with self._lock:
                    job["state"] = "done"
                    job["result"] = result
                    job["msg"] = str((result or {}).get("msg") or "Končano.")
            except Exception as exc:
                log.error("Naloga %s spodletela: %s\n%s", label, exc, traceback.format_exc())
                with self._lock:
                    job["state"] = "error"
                    job["error"] = str(exc)
                    job["msg"] = str(exc)
            finally:
                with self._lock:
                    if self._active == job_id:
                        self._active = None

        threading.Thread(target=worker, name=f"kirkpr-job-{job_id[:8]}", daemon=True).start()
        return {"ok": True, "job": job_id, "id": job_id, "state": "running", "label": label, "msg": label}