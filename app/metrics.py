from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "service_lab_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
HTTP_DURATION = Histogram(
    "service_lab_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)
JOBS_CREATED = Counter(
    "service_lab_jobs_created_total",
    "Total jobs created",
)
JOBS_BY_STATUS = Gauge(
    "service_lab_jobs_by_status",
    "Current jobs grouped by status",
    ["status"],
)


async def metrics_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    started = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
    HTTP_DURATION.labels(request.method, path).observe(time.perf_counter() - started)
    return response
