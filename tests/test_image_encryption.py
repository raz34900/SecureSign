"""What the encrypted image store guarantees end to end.

The claim being tested: a copy of the database, on its own, does not yield a signature -
and a customer's images can be erased everywhere at once by destroying one short key.
"""
from conftest import login
from test_enrolment import do_full_enrolment
from test_signature_core import make_signature
from test_verify import png, verify


def enrol(client, national_id: str = "123456900") -> str:
    login(client, "BA11", "clerk1")
    return do_full_enrolment(client, national_id)


def test_no_signature_image_is_written_to_disk(client, seeded):
    """The whole point. Nothing readable is left beside the database - the directory
    enrolment used to fill is never created at all."""
    import os

    customer_id = enrol(client)
    verify(client, "123456900", png(make_signature()))
    assert not os.path.exists(os.path.join("data/enrolment_samples", customer_id))


def test_the_stored_reference_is_not_a_png(client, seeded, session_factory):
    """A dump of the table must not contain something an image viewer will open."""
    from backend.app.models_db import ReferenceSignature

    customer_id = enrol(client, "123456901")
    with session_factory() as db:
        rows = db.query(ReferenceSignature).filter_by(customer_id=customer_id).all()
        assert rows
        for ref in rows:
            assert ref.image_encrypted, "the crop is stored on the row"
            assert not ref.image_encrypted.startswith(b"\x89PNG"), "stored as ciphertext"
            assert ref.image_path == "", "and no longer as a path to a file"


def test_the_key_is_never_stored_beside_the_image_in_the_clear(client, seeded,
                                                               session_factory):
    from backend.app.config import get_settings
    from backend.app.models_db import CustomerKey
    from backend.app.security import envelope

    customer_id = enrol(client, "123456902")
    with session_factory() as db:
        row = db.get(CustomerKey, customer_id)
        assert row is not None, "a key was minted on first use"
        dek = envelope.unwrap_dek(row.wrapped_dek, get_settings().pii_enc_key)
        assert dek not in row.wrapped_dek, "the stored form is not the key"


def test_each_customer_gets_a_different_key(client, seeded, session_factory):
    """Blast radius. One recovered key must not open the next customer's images."""
    from backend.app.models_db import CustomerKey
    from backend.app.repositories import customer_keys

    first = enrol(client, "123456903")
    second = enrol(client, "123456904")
    with session_factory() as db:
        assert db.query(CustomerKey).count() >= 2
        assert customer_keys.key_for(db, first) != customer_keys.key_for(db, second)


def test_images_survive_a_restart(client, seeded):
    """Nothing depends on process state: the key is derived from the row and the
    environment every time it is needed."""
    enrol(client, "123456905")
    body = verify(client, "123456905", png(make_signature())).json()
    assert body["references"], "references decrypt on a fresh request"
    assert all(view["image_png_base64"] for view in body["references"])


def test_destroying_the_key_erases_every_image_for_that_customer(client, seeded,
                                                                 session_factory):
    """Crypto-shredding. Erasure that reaches copies nobody can edit - the ciphertext
    stays exactly where it is, in the database and in every backup ever taken, and stops
    meaning anything."""
    from backend.app.repositories import customer_keys

    customer_id = enrol(client, "123456906")
    verify(client, "123456906", png(make_signature()))
    assert client.get(f"/customers/{customer_id}/references").json()["references"]

    with session_factory() as db:
        assert customer_keys.destroy(db, customer_id) is True
        db.commit()

    assert client.get(f"/customers/{customer_id}/references").json()["references"] == []
    assert client.get("/verifications").json()["verifications"][0]["has_image"] is True, \
        "the row still says an image was kept; it is simply no longer readable"

    row = client.get("/verifications").json()["verifications"][0]
    assert client.get(f"/verifications/{row['request_id']}"
                      ).json()["compared_png_base64"] is None


def test_destroying_a_key_that_is_not_there_is_not_an_error(client, seeded, session_factory):
    from backend.app.repositories import customer_keys

    with session_factory() as db:
        assert customer_keys.destroy(db, "no-such-customer") is False


def test_a_ciphertext_moved_between_customers_is_refused(client, seeded, session_factory):
    """The reference id is authenticated, so swapping one person's signature onto
    another's record fails to decrypt rather than standing in for it."""
    from backend.app.models_db import ReferenceSignature

    first = enrol(client, "123456907")
    second = enrol(client, "123456908")
    with session_factory() as db:
        stolen = db.query(ReferenceSignature).filter_by(customer_id=first).first()
        victim = db.query(ReferenceSignature).filter_by(customer_id=second).first()
        victim.image_encrypted = stolen.image_encrypted
        db.commit()

    shown = client.get(f"/customers/{second}/references").json()["references"]
    assert all(view["reference_id"] != victim.id for view in shown), \
        "the transplanted image is refused, not rendered as this customer's"
