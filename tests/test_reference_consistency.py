"""DEF-06, and the line it now draws.

The registry compares a query against every reference a customer has, so one crop of
something that is not their signature drags every future score. That guard applies where
there is an established identity to protect: appending to a customer already on file.

A first enrolment is not that case. The card being photographed *is* the identity being
defined, so a specimen that differs from its neighbours is handwriting variation, not
evidence of a second writer — and scoring siblings against the verification threshold
refused real cards constantly, because a person's signature drifts down a page.
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


# Eight of one writer and one of another: the shape the old first-enrolment check refused.
MIXED_CARD = card([5] * 8 + [41])


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


def test_a_card_whose_specimens_differ_is_still_accepted(client, seeded, session_factory):
    """First enrolment defines the identity, so there is nothing yet to impersonate.

    This used to be refused: every specimen was scored against its siblings and the card
    rejected if one crossed the verification threshold. On real cards it fired constantly
    — a person's own signature drifts down a page, and this project's own genuine data
    already reaches 0.3303 against a 0.3999 threshold. A clerk photographing a real card
    could not get past it. The guard that matters runs on append, below, where there is
    an established set to compare against.
    """
    login(client, "BA11", "clerk1")
    eid = client.post("/customers", json=enrol_body("123456790")).json()["enrolment_id"]
    crops = client.post(f"/customers/{eid}/card",
                        files={"file": ("card.png", MIXED_CARD, "image/png")}).json()["crops"]

    approved = client.post(f"/customers/{eid}/references",
                           json={"crop_ids": [c["crop_id"] for c in crops][:8]})
    assert approved.status_code == 200, approved.text
    assert approved.json()["reference_count"] == 8


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
