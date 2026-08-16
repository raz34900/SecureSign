"""Book 10.2.5: concurrent verification load.

The book specifies 10 parallel clients for 5 minutes. That duration does not belong in
a suite that runs on every change, so this holds the concurrency and the p95 criterion
and shortens the run to a fixed request count. State that deviation in the book rather
than claiming the original test was executed.

Runs against the test embedder, so it measures the request path — routing, session
resolution, database access, decision and persistence — not model inference time.
"""
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.app.db import Base, make_engine, make_session_factory
from conftest import login
from test_enrolment import do_full_enrolment
from test_signature_core import make_signature
from test_verify import png

CLIENTS = 10
REQUESTS_PER_CLIENT = 10
P95_LIMIT_SECONDS = 2.0

pytestmark = pytest.mark.slow


@pytest.fixture
def session_factory(tmp_path):
    """File-backed database for this module only: the shared in-memory StaticPool
    fixture funnels every thread through one connection, which would serialise the
    load and interleave transactions instead of exercising real concurrency."""
    engine = make_engine(f"sqlite:///{tmp_path / 'load.db'}",
                         connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


@pytest.fixture
def enrolled(client, seeded):
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456880")
    client.cookies.clear()
    return png(make_signature())


def test_ten_concurrent_clients_stay_under_the_latency_budget(app, enrolled, seeded):
    from fastapi.testclient import TestClient

    def one_client(index: int) -> list[float]:
        session = TestClient(app)
        login(session, "SB44", "rep1")
        timings = []
        for _ in range(REQUESTS_PER_CLIENT):
            started = time.perf_counter()
            response = session.post("/verify", data={"national_id": "123456880"},
                                    files={"file": ("s.png", enrolled, "image/png")})
            timings.append(time.perf_counter() - started)
            assert response.status_code == 200, response.text
        return timings

    with ThreadPoolExecutor(max_workers=CLIENTS) as pool:
        results = list(pool.map(one_client, range(CLIENTS)))

    timings = sorted(t for batch in results for t in batch)
    assert len(timings) == CLIENTS * REQUESTS_PER_CLIENT

    p95 = timings[int(len(timings) * 0.95) - 1]
    print(f"\nconcurrency p95={p95:.3f}s median={statistics.median(timings):.3f}s "
          f"max={timings[-1]:.3f}s over {len(timings)} requests")
    assert p95 < P95_LIMIT_SECONDS, (
        f"p95 {p95:.3f}s exceeds {P95_LIMIT_SECONDS}s "
        f"(median {statistics.median(timings):.3f}s, max {timings[-1]:.3f}s)")


def test_concurrent_verifications_are_all_recorded(app, enrolled, seeded):
    """No lost writes: every request that returned 200 has a row behind it."""
    from fastapi.testclient import TestClient

    def one_client(index: int) -> int:
        session = TestClient(app)
        login(session, "SB44", "rep1")
        ok = 0
        for _ in range(REQUESTS_PER_CLIENT):
            if session.post("/verify", data={"national_id": "123456880"},
                            files={"file": ("s.png", enrolled, "image/png")}).status_code == 200:
                ok += 1
        return ok

    with ThreadPoolExecutor(max_workers=CLIENTS) as pool:
        succeeded = sum(pool.map(one_client, range(CLIENTS)))

    assert succeeded == CLIENTS * REQUESTS_PER_CLIENT

    reader = TestClient(app)
    login(reader, "SB44", "rep1")
    rows = reader.get("/verifications").json()["verifications"]
    assert len(rows) >= min(succeeded, 100)
