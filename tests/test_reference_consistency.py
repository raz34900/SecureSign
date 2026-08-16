"""DEF-06: a specimen that does not match its own siblings must not be stored.

The registry compares a query against every reference a customer has, so one crop of
something that is not their signature drags every future score.
"""
import io

from PIL import Image

from conftest import login
from test_enrolment import enrol_body
from test_signature_core import make_signature


def card(seeds: list[int]) -> bytes:
    canvas = Image.new("L", (800, 60 + len(seeds) * 180 + 160), 255)
    for row, seed in enumerate(seeds):
        canvas.paste(make_signature(seed=seed, size=(500, 150)), (150, 60 + row * 180))
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def stage_and_upload(client, national_id: str, image: bytes) -> list[str]:
    enrolment_id = client.post("/customers", json=enrol_body(national_id)).json()["enrolment_id"]
    crops = client.post(f"/customers/{enrolment_id}/card",
                        files={"file": ("card.png", image, "image/png")}).json()["crops"]
    return enrolment_id, [crop["crop_id"] for crop in crops]


def test_a_consistent_card_is_accepted(client, seeded):
    login(client, "BA11", "clerk1")
    enrolment_id, crop_ids = stage_and_upload(client, "123456870", card([5] * 9))
    response = client.post(f"/customers/{enrolment_id}/references", json={"crop_ids": crop_ids})
    assert response.status_code == 200, response.text


def test_one_foreign_specimen_is_rejected(client, seeded, session_factory):
    """Eight signatures by one writer and one by another: the odd one out is caught."""
    login(client, "BA11", "clerk1")
    enrolment_id, crop_ids = stage_and_upload(client, "123456871", card([5] * 8 + [41]))

    response = client.post(f"/customers/{enrolment_id}/references", json={"crop_ids": crop_ids})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "INCONSISTENT_REFERENCES"

    from backend.app.models_db import Customer
    with session_factory() as db:
        assert db.query(Customer).count() == 0  # nothing partially stored


def test_the_message_says_which_specimen_to_drop(client, seeded):
    login(client, "BA11", "clerk1")
    enrolment_id, crop_ids = stage_and_upload(client, "123456872", card([5] * 8 + [41]))
    message = client.post(f"/customers/{enrolment_id}/references",
                          json={"crop_ids": crop_ids}).json()["error"]["message"]
    assert "9" in message  # the position of the offending specimen, 1-based


def test_appending_still_checks_against_the_existing_set(client, seeded):
    """Append mode already had this guard; it must keep working."""
    login(client, "BA11", "clerk1")
    enrolment_id, crop_ids = stage_and_upload(client, "123456873", card([5] * 9))
    assert client.post(f"/customers/{enrolment_id}/references",
                       json={"crop_ids": crop_ids}).status_code == 200

    enrolment_id, crop_ids = stage_and_upload(client, "123456873", card([41] * 2))
    response = client.post(f"/customers/{enrolment_id}/references",
                           json={"crop_ids": crop_ids[:1]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SIGNATURE_MISMATCH"
