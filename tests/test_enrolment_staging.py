"""Two things the staging store has to get right once photographs accumulate.

Duplicates: a photograph attached twice yields byte-identical crops, because everything
between the upload and the staging store is deterministic. Keeping them would put one
signature on file several times, and the verification evidence view would then show one
reference agreeing with itself as though several had.

Recovery: the candidate images live only in the browser, while the staging entry behind
them survives fifteen minutes on the server. A refresh used to throw away the client's
half and force the card to be rephotographed. It can be read back instead.
"""
from conftest import login
from test_enrolment import enrol_body
from test_signature_core import make_specimen_card


def start(client, nid: str = "123456800") -> str:
    login(client, "BA11", "clerk1")
    return client.post("/customers", json=enrol_body(nid)).json()["enrolment_id"]


def attach(client, enrolment_id: str, card: bytes):
    return client.post(f"/customers/{enrolment_id}/card",
                       files={"file": ("card.jpg", card, "image/jpeg")})


# --- duplicates ---------------------------------------------------------------


def test_the_same_photograph_twice_adds_nothing(client, seeded):
    enrolment_id = start(client)
    card = make_specimen_card(9)
    assert len(attach(client, enrolment_id, card).json()["crops"]) == 9

    again = attach(client, enrolment_id, card)
    assert again.status_code == 422
    assert again.json()["error"]["code"] == "DUPLICATE_SIGNATURES"

    kept = attach(client, enrolment_id, make_specimen_card(1, variant=1))
    assert len(kept.json()["crops"]) == 10, "the refusal discarded what was collected"


def test_a_second_photograph_of_the_same_writer_still_counts(client, seeded):
    """Only byte-identical crops are dropped. A real re-shoot differs pixel for pixel,
    and refusing it would put the clerk back in the loop this whole flow removed."""
    enrolment_id = start(client, "123456801")
    assert len(attach(client, enrolment_id, make_specimen_card(4)).json()["crops"]) == 4
    assert len(attach(client, enrolment_id,
                      make_specimen_card(4, variant=1)).json()["crops"]) == 8


def test_the_same_crop_selected_twice_is_one_reference(client, seeded):
    """The count returned is what was stored, not what was asked for. Counting the
    request told the clerk they had eight references when the customer held fewer, and
    eight is the floor the enrolment is built on."""
    enrolment_id = start(client, "123456802")
    crops = attach(client, enrolment_id, make_specimen_card(9)).json()["crops"]
    crop_ids = [c["crop_id"] for c in crops][:8]

    approved = client.post(f"/customers/{enrolment_id}/references",
                           json={"crop_ids": crop_ids + crop_ids[:2]})
    assert approved.status_code == 200, approved.text
    assert approved.json()["reference_count"] == 8

    customer_id = approved.json()["customer_id"]
    stored = client.get(f"/customers/{customer_id}/references").json()["references"]
    assert len(stored) == 8


def test_selecting_only_duplicates_cannot_beat_the_floor(client, seeded):
    """Eight ids that name two signatures is not eight signatures."""
    enrolment_id = start(client, "123456803")
    crops = attach(client, enrolment_id, make_specimen_card(9)).json()["crops"]
    pair = [c["crop_id"] for c in crops][:2]

    refused = client.post(f"/customers/{enrolment_id}/references",
                          json={"crop_ids": pair * 4})
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "INSUFFICIENT_SIGNATURES"


# --- picking a wizard back up --------------------------------------------------


def test_staged_crops_can_be_read_back_without_reattaching(client, seeded):
    enrolment_id = start(client, "123456804")
    attached = attach(client, enrolment_id, make_specimen_card(9)).json()["crops"]

    read_back = client.get(f"/customers/{enrolment_id}/card")
    assert read_back.status_code == 200, read_back.text
    assert read_back.json()["crops"] == attached, "same ids, same images, same order"


def test_reading_back_before_any_photograph_is_empty_not_an_error(client, seeded):
    """The wizard reloads at step two as legitimately as at step three."""
    enrolment_id = start(client, "123456805")
    assert client.get(f"/customers/{enrolment_id}/card").json()["crops"] == []


def test_another_organisation_cannot_read_staged_crops(client, seeded):
    """404, like every other staging call: a 403 would confirm the enrolment exists."""
    enrolment_id = start(client, "123456806")
    attach(client, enrolment_id, make_specimen_card(9))
    client.cookies.clear()

    login(client, "BB22", "clerk2")
    assert client.get(f"/customers/{enrolment_id}/card").status_code == 404


def test_an_expired_enrolment_reads_back_as_gone(client, seeded, monkeypatch):
    enrolment_id = start(client, "123456807")
    attach(client, enrolment_id, make_specimen_card(9))

    from backend.app.services import enrolment
    monkeypatch.setattr(enrolment, "_TTL_SECONDS", -1)
    assert client.get(f"/customers/{enrolment_id}/card").status_code == 404


def test_a_verifier_cannot_read_staged_crops(client, seeded):
    enrolment_id = start(client, "123456808")
    client.cookies.clear()
    login(client, "SB44", "rep1")
    assert client.get(f"/customers/{enrolment_id}/card").status_code == 403
