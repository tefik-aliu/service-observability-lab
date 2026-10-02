from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Job, JobRequest
from app.schemas import JobRead


def create_once(db: Session, title: str, key: str | None) -> tuple[dict, bool]:
    """Commit a job and its receipt together; the unique key arbitrates races."""
    receipt = JobRequest(key=key, title=title, response={}) if key else None
    try:
        if receipt is not None:
            db.add(receipt)
            db.flush()  # Reserve the key before creating the job.
        job = Job(title=title, status="queued")
        db.add(job)
        db.flush()
        body = JobRead.model_validate(job).model_dump(mode="json")
        if receipt is not None:
            receipt.response = body
        db.commit()
        return body, False
    except IntegrityError:
        db.rollback()
        existing = db.get(JobRequest, key) if key else None
        if existing is None:
            raise  # Do not misreport unrelated database failures as duplicates.
        if existing.title != title:
            raise HTTPException(409, "Idempotency-Key already used for a different title") from None
        return existing.response, True
    except Exception:
        db.rollback()
        raise
