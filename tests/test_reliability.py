"""Book 10.2.6: the service degrades with a clear message rather than crashing."""
import numpy as np
import pytest

from conftest import login
from test_enrolment import do_full_enrolment
from test_signature_core import make_signature
from test_verify import png, verify


def corrupt_one_reference(session_factory, customer_id: str) -> None:
    from backend.app.models_db import ReferenceSignature
    with session_factory() as db:
        ref = db.query(ReferenceSignature).filter_by(customer_id=customer_id).first()
        ref.embedding = b"\x00\x01\x02"  # not 128 float32 values
        db.commit()


def corrupt_every_reference(session_factory, customer_id: str) -> None:
    from backend.app.models_db import ReferenceSignature
    with session_factory() as db:
        for ref in db.query(ReferenceSignature).filter_by(customer_id=customer_id).all():
            ref.embedding = b"\x00\x01\x02"
        db.commit()


def test_one_corrupt_reference_does_not_break_verification(client, seeded, session_factory):
    login(client, "BA11", "clerk1")
    customer_id = do_full_enrolment(client, "123456860")
    corrupt_one_reference(session_factory, customer_id)

    response = verify(client, "123456860", png(make_signature()))
    assert response.status_code == 200, response.text
    assert response.json()["verdict"] in {"VALID", "FRAUD"}


def test_all_references_corrupt_gives_a_clear_error(client, seeded, session_factory):
    login(client, "BA11", "clerk1")
    customer_id = do_full_enrolment(client, "123456861")
    corrupt_every_reference(session_factory, customer_id)

    response = verify(client, "123456861", png(make_signature()))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "REFERENCES_UNREADABLE"
    assert "123456861" not in response.text


def test_decode_embedding_rejects_wrong_lengths():
    from backend.app.repositories import references

    assert references.decode_embedding(b"") is None
    assert references.decode_embedding(b"\x00" * 511) is None
    assert references.decode_embedding(b"\x00" * 513) is None
    good = np.zeros(128, dtype=np.float32).tobytes()
    assert references.decode_embedding(good).shape == (128,)


def test_a_missing_model_file_fails_loudly():
    """Startup must not half-succeed with no model."""
    from signature_core.embed import Embedder

    with pytest.raises((FileNotFoundError, OSError, RuntimeError)):
        Embedder.load("models/does-not-exist.pth")
