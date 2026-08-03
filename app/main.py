from __future__ import annotations

import os
from collections import Counter
from collections.abc import Generator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import build_database
from app.metrics import JOBS_BY_STATUS, JOBS_CREATED, metrics_middleware
from app.models import Base, Job
from app.schemas import JobCreate, JobRead, JobUpdate
from app.telemetry import configure_telemetry

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(database_url: str | None = None) -> FastAPI:
    resolved_url = database_url or os.getenv("DATABASE_URL", "sqlite:///./service_lab.db")
    engine, session_factory = build_database(resolved_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Base.metadata.create_all(engine)
        refresh_job_gauges(session_factory())
        yield
        engine.dispose()

    app = FastAPI(
        title="Service Observability Lab",
        version="1.0.0",
        description=(
            "A production-style FastAPI service with metrics, tracing and deployment assets."
        ),
        lifespan=lifespan,
    )
    app.state.SessionLocal = session_factory
    app.middleware("http")(metrics_middleware)
    configure_telemetry(app)

    def get_db(request: Request) -> Generator[Session]:
        db = request.app.state.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    db_dependency = Depends(get_db)

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "service-observability-lab"}

    @app.get("/ready")
    def readiness(db: Session = db_dependency) -> dict[str, str]:
        db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/jobs", response_model=list[JobRead])
    def list_jobs(db: Session = db_dependency) -> list[Job]:
        return list(db.scalars(select(Job).order_by(Job.id.desc())).all())

    @app.post("/api/jobs", response_model=JobRead, status_code=status.HTTP_201_CREATED)
    def create_job(payload: JobCreate, db: Session = db_dependency) -> Job:
        job = Job(title=payload.title, status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        JOBS_CREATED.inc()
        refresh_job_gauges(db)
        return job

    @app.patch("/api/jobs/{job_id}", response_model=JobRead)
    def update_job(
        job_id: int,
        payload: JobUpdate,
        db: Session = db_dependency,
    ) -> Job:
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        job.status = payload.status
        db.commit()
        db.refresh(job)
        refresh_job_gauges(db)
        return job

    @app.delete("/api/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_job(job_id: int, db: Session = db_dependency) -> Response:
        job = db.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        db.delete(job)
        db.commit()
        refresh_job_gauges(db)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


def refresh_job_gauges(db: Session) -> None:
    try:
        rows = db.execute(select(Job.status, func.count(Job.id)).group_by(Job.status)).all()
        counts = Counter({status: count for status, count in rows})
        for status_name in ("queued", "running", "completed", "failed"):
            JOBS_BY_STATUS.labels(status_name).set(counts.get(status_name, 0))
    finally:
        db.close()


app = create_app()
