from fastapi.testclient import TestClient

from app.main import create_app


def make_client() -> TestClient:
    return TestClient(create_app("sqlite+pysqlite:///:memory:"))


def test_health_and_readiness() -> None:
    with make_client() as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/ready").json() == {"status": "ready", "database": "connected"}


def test_job_lifecycle() -> None:
    with make_client() as client:
        created = client.post("/api/jobs", json={"title": "Generate KPI report"})
        assert created.status_code == 201
        job_id = created.json()["id"]
        assert created.json()["status"] == "queued"

        updated = client.patch(f"/api/jobs/{job_id}", json={"status": "completed"})
        assert updated.status_code == 200
        assert updated.json()["status"] == "completed"

        jobs = client.get("/api/jobs").json()
        assert len(jobs) == 1
        assert jobs[0]["title"] == "Generate KPI report"

        deleted = client.delete(f"/api/jobs/{job_id}")
        assert deleted.status_code == 204
        assert client.get("/api/jobs").json() == []


def test_validation_and_missing_job() -> None:
    with make_client() as client:
        assert client.post("/api/jobs", json={"title": "x"}).status_code == 422
        assert client.patch("/api/jobs/999", json={"status": "failed"}).status_code == 404


def test_prometheus_metrics_are_exposed() -> None:
    with make_client() as client:
        client.get("/health")
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "service_lab_http_requests_total" in metrics.text
        assert "service_lab_jobs_by_status" in metrics.text
