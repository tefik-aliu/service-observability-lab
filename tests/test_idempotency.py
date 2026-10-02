import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.main import create_app
from app.models import Job, JobRequest


@pytest.fixture
def database_url(tmp_path):
    postgres = os.getenv("TEST_POSTGRES_URL")
    if not postgres:
        yield f"sqlite:///{tmp_path / 'jobs.db'}"
        return
    # A fresh schema per test: never clear an existing database's tables.
    schema = "test_" + uuid4().hex
    engine = create_engine(postgres)
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    url = make_url(postgres).update_query_dict({"options": f"-csearch_path={schema}"})
    try:
        yield url.render_as_string(hide_password=False)
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


@pytest.fixture
def client(database_url):
    with TestClient(create_app(database_url)) as client:
        yield client


def post(client, title="Generate report", key="request-1"):
    return client.post("/api/jobs", json={"title": title}, headers={"Idempotency-Key": key})


def test_replay_survives_update_delete_and_restart(client, database_url):
    first = post(client)
    assert first.status_code == 201
    assert first.headers["Idempotency-Replayed"] == "false"
    job_id = first.json()["id"]
    client.patch(f"/api/jobs/{job_id}", json={"status": "completed"})
    replay = post(client)
    assert replay.status_code == 201
    assert replay.json() == first.json()  # Creation receipt, not current job state.
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert client.get("/api/jobs").json()[0]["status"] == "completed"
    client.delete(f"/api/jobs/{job_id}")
    with TestClient(create_app(database_url)) as restarted:
        assert post(restarted).json() == first.json()
        assert restarted.get("/api/jobs").json() == []  # Never resurrect a deleted job.


def test_conflicting_payload_and_independent_keys(client):
    original = post(client)
    assert post(client, "Different report").status_code == 409
    assert len(client.get("/api/jobs").json()) == 1
    assert post(client, "  Generate report  ").json() == original.json()
    assert post(client, key="request-2").json()["id"] != original.json()["id"]


@pytest.mark.parametrize("key", ["", "with spaces", "x" * 129, "comma,key"])
def test_invalid_key_never_creates_job(client, key):
    assert post(client, key=key).status_code == 422
    assert client.get("/api/jobs").json() == []


def test_invalid_body_does_not_reserve_key(client):
    assert post(client, title="   ").status_code == 422
    assert post(client).status_code == 201


def test_old_clients_can_still_create_distinct_jobs(client):
    first = client.post("/api/jobs", json={"title": "Legacy client"})
    second = client.post("/api/jobs", json={"title": "Legacy client"})
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


def test_existing_jobs_survive_additive_table_creation(database_url):
    engine = create_engine(database_url)
    Job.__table__.create(engine)
    with Session(engine) as db:
        db.add(Job(title="Existing job", status="completed"))
        db.commit()
    engine.dispose()
    with TestClient(create_app(database_url)) as client:
        assert client.get("/api/jobs").json()[0]["title"] == "Existing job"
        assert post(client).status_code == 201
        assert len(client.get("/api/jobs").json()) == 2


def test_failed_commit_rolls_back_both_job_and_receipt(client, monkeypatch):
    def fail(_):
        raise RuntimeError("Simulated storage failure")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail)
        with pytest.raises(RuntimeError, match="Simulated storage failure"):
            post(client)
    with client.app.state.SessionLocal() as db:
        assert db.scalars(select(Job)).all() == []
        assert db.scalars(select(JobRequest)).all() == []
    assert post(client).status_code == 201


@pytest.mark.parametrize("different_title", [False, True])
def test_simultaneous_requests_create_exactly_one_job(client, different_title):
    gate = Barrier(2)
    before = REGISTRY.get_sample_value("service_lab_jobs_created_total")

    def send(title):
        with TestClient(client.app) as other:
            gate.wait(timeout=10)
            return post(other, title)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(send, "Generate report")
        b = pool.submit(send, "Different report" if different_title else "Generate report")
        results = [a.result(), b.result()]
    assert sorted(r.status_code for r in results) == ([201, 409] if different_title else [201, 201])
    if not different_title:
        assert results[0].json() == results[1].json()
        assert sorted(r.headers["Idempotency-Replayed"] for r in results) == ["false", "true"]
    assert len(client.get("/api/jobs").json()) == 1
    assert REGISTRY.get_sample_value("service_lab_jobs_created_total") == before + 1
