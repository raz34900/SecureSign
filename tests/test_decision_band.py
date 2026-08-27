"""The three-way band is decided once, on the server.

It used to be computed on both sides of the wire: the API sent a two-way verdict and the
browser re-derived valid/fraud/borderline from its own copy of the margin, with a strict
`<` where the engineering panel used `<=`. Two copies of one rule that already disagreed
at the boundary, and the verify screen could count a reference as matched while painting
the tile beside it borderline.
"""
from conftest import login
from signature_core.decision import BORDERLINE_MARGIN, THRESHOLD, band, decide
from test_enrolment import do_full_enrolment
from test_signature_core import make_signature
from test_verify import png, verify

BANDS = ("valid", "fraud", "borderline")


def test_the_band_follows_the_distance():
    assert band(0.10, THRESHOLD) == "valid"
    assert band(0.90, THRESHOLD) == "fraud"
    assert band(THRESHOLD, THRESHOLD) == "borderline"
    assert band(THRESHOLD - BORDERLINE_MARGIN / 2, THRESHOLD) == "borderline"
    assert band(THRESHOLD + BORDERLINE_MARGIN / 2, THRESHOLD) == "borderline"


def test_a_borderline_distance_still_carries_a_verdict():
    """Borderline describes confidence, not the decision. The stored verdict stays
    two-way, because a record of what the system decided cannot be "unsure"."""
    result = decide([THRESHOLD - 0.001], THRESHOLD)
    assert result.band == "borderline"
    assert result.verdict == "VALID"


def test_the_verify_response_carries_the_band(client, seeded):
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123458000")
    body = verify(client, "123458000", png(make_signature())).json()

    assert body["band"] in BANDS
    assert body["band"] == band(body["distance"], body["threshold"])
    for reference in body["references"]:
        assert reference["band"] == band(reference["distance"], body["threshold"])


def test_history_carries_the_band_on_the_row_and_the_detail(client, seeded):
    """A stored row is banded from the threshold it was judged against, not today's."""
    login(client, "BA11", "clerk1")
    do_full_enrolment(client, "123458001")
    verify(client, "123458001", png(make_signature()))

    row = client.get("/verifications").json()["verifications"][0]
    assert row["band"] == band(row["distance"], row["threshold_used"])

    detail = client.get(f"/verifications/{row['request_id']}").json()
    assert detail["band"] == row["band"]


def test_the_client_is_never_asked_to_recompute_the_band():
    """The frontend holds no margin of its own. If this fails, the two rules have
    started drifting apart again."""
    from pathlib import Path

    src = Path("frontend/src")
    for path in list(src.rglob("*.vue")) + list(src.rglob("*.js")):
        text = path.read_text()
        assert "BORDERLINE_MARGIN" not in text, f"{path} recomputes the band"
        assert "classifyDecision" not in text, f"{path} recomputes the band"
