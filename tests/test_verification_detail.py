"""Looking back at a past result, and how long the picture behind it survives.

History used to be a list of numbers nobody could act on. Opening a row now shows the
image the model compared, which is what lets a clerk say "that signature looks wrong"
about a decision taken weeks ago.

Storing that image is the only new class of retained personal data in the product, so
what is kept, for how long, and who may read it are all pinned here.
"""
import base64
import io
import os
from datetime import UTC, datetime, timedelta

from PIL import Image

from conftest import login
from test_enrolment import do_full_enrolment
from test_signature_core import make_signature
from test_verify import png, verify


def run_one(client, national_id: str = "123456660") -> dict:
    """Enrol, verify once as the enrolling bank, and return the history row."""
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, national_id)
    verify(client, national_id, png(make_signature()))
    return client.get("/verifications").json()["verifications"][0]


def test_a_row_can_be_opened_and_carries_the_compared_image(client, seeded):
    row = run_one(client)
    assert row["has_image"] is True

    detail = client.get(f"/verifications/{row['request_id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()

    assert body["verdict"] == row["verdict"]
    assert body["distance"] == row["distance"]
    image = Image.open(io.BytesIO(base64.b64decode(body["compared_png_base64"])))
    assert image.size == (224, 224), "the stored image is the one the model compared"
    assert body["retention_days"] == 90


def test_the_list_never_carries_images_only_a_flag(client, seeded):
    """One row at a time, through an audited endpoint - not a page that ships every
    signature the organisation has ever queried."""
    run_one(client)
    row = client.get("/verifications").json()["verifications"][0]
    assert row["has_image"] is True
    assert "compared_png_base64" not in row
    assert "query_image_path" not in row


def test_opening_a_row_is_audited(client, seeded, session_factory):
    row = run_one(client)
    client.get(f"/verifications/{row['request_id']}")

    from backend.app.models_db import AuditLog
    with session_factory() as db:
        assert db.query(AuditLog).filter_by(
            action="view_verification", resource_id=row["request_id"]).count() == 1


def test_another_organisation_cannot_open_the_row(client, seeded):
    """404, not 403: a verification belonging to someone else must look nonexistent."""
    row = run_one(client)
    client.cookies.clear()
    login(client, "SB44", "rep1")
    assert client.get(f"/verifications/{row['request_id']}").status_code == 404


def test_the_detail_never_returns_a_full_national_id(client, seeded):
    row = run_one(client, "123456661")
    body = client.get(f"/verifications/{row['request_id']}").json()
    assert body["national_id_masked"] == "•••••6661"
    assert "123456661" not in str(body)


def test_what_comes_back_depends_on_the_role(client, seeded):
    """A clerk works for the institution holding the references and already sees them.
    A verifier at a shop never does, live or in history."""
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456662")
    client.cookies.clear()

    login(client, "SB44", "rep1")
    verify(client, "123456662", png(make_signature()))
    shop_row = client.get("/verifications").json()["verifications"][0]
    assert "references" not in client.get(f"/verifications/{shop_row['request_id']}").json()

    client.cookies.clear()
    login(client, "BA11", "clerk1")
    verify(client, "123456662", png(make_signature()))
    bank_row = client.get("/verifications").json()["verifications"][0]
    body = client.get(f"/verifications/{bank_row['request_id']}").json()
    assert body["references"], "a clerk sees the reference set"
    assert all(view["image_png_base64"] for view in body["references"])


def test_an_unknown_row_is_not_found(client, seeded):
    login(client, "BA11", "clerk1")
    assert client.get("/verifications/00000000-0000-0000-0000-000000000000").status_code == 404


# --- retention ---------------------------------------------------------------


def test_the_verdict_outlives_the_picture(client, seeded, session_factory):
    """Ninety days is a review window, not an archive. The row and its verdict are
    permanent; the signature image behind it is not."""
    from backend.app.models_db import Verification
    from backend.app.services import verification as service

    row = run_one(client, "123456663")
    with session_factory() as db:
        stored = db.get(Verification, row["request_id"])
        path = stored.query_image_path
        assert path and os.path.exists(path)
        # Age the row past the window.
        stored.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=91)
        db.commit()

        assert service.purge_expired_query_images(db) == 1
        refreshed = db.get(Verification, row["request_id"])
        assert refreshed.query_image_path is None
        assert refreshed.decision == row["verdict"], "the verdict survives"
    assert not os.path.exists(path), "the file is gone from disk, not just unlinked in the row"

    detail = client.get(f"/verifications/{row['request_id']}")
    assert detail.status_code == 200
    assert detail.json()["compared_png_base64"] is None
    assert client.get("/verifications").json()["verifications"][0]["has_image"] is False


def test_a_fresh_row_is_not_purged(client, seeded, session_factory):
    from backend.app.services import verification as service

    run_one(client, "123456664")
    with session_factory() as db:
        assert service.purge_expired_query_images(db) == 0


def test_a_missing_file_does_not_break_reading_history(client, seeded, session_factory):
    """The image is stored best-effort and may be gone - a disk wiped, a restore, a
    purge half-done. History must still open."""
    from backend.app.models_db import Verification

    row = run_one(client, "123456665")
    with session_factory() as db:
        os.remove(db.get(Verification, row["request_id"]).query_image_path)

    detail = client.get(f"/verifications/{row['request_id']}")
    assert detail.status_code == 200
    assert detail.json()["compared_png_base64"] is None


# --- paging ------------------------------------------------------------------


def test_history_pages_and_reports_a_total(client, seeded):
    """The old fixed limit of a hundred returned no count, so an organisation with more
    saw the newest hundred and had no way to know the rest existed."""
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123456666")
    for _ in range(7):
        verify(client, "123456666", png(make_signature()))

    first = client.get("/verifications?limit=3").json()
    assert len(first["verifications"]) == 3
    assert first["total"] == 7
    assert first["limit"] == 3 and first["offset"] == 0

    second = client.get("/verifications?limit=3&offset=3").json()
    assert len(second["verifications"]) == 3
    ids = {r["request_id"] for r in first["verifications"]}
    assert ids.isdisjoint({r["request_id"] for r in second["verifications"]})

    last = client.get("/verifications?limit=3&offset=6").json()
    assert len(last["verifications"]) == 1

    everything = client.get("/verifications?limit=200").json()
    assert len({r["request_id"] for r in everything["verifications"]}) == 7


def test_a_page_size_beyond_the_cap_is_refused(client, seeded):
    login(client, "BA11", "clerk1")
    assert client.get("/verifications?limit=5000").status_code == 422
    assert client.get("/verifications?offset=-1").status_code == 422
