"""Region isolation for the verify path.

Verification embeds whatever ink it is handed. Without this step a genuine signature
photographed on a printed form embeds the form, and comes back FRAUD.
"""
import base64
import io

from PIL import Image, ImageDraw

from conftest import login
from test_signature_core import make_signature, make_specimen_card
from test_verify import png


def make_printed_document() -> bytes:
    """A signature on a form, which is what a clerk actually photographs.

    Printed lines are drawn as bars rather than with PIL's default font: at scan
    resolution real print is tall enough to survive the extractor's height filter,
    and the tiny default font is not, which would make this fixture unrealistically
    easy.
    """
    doc = Image.new("L", (1000, 760), 255)
    draw = ImageDraw.Draw(doc)
    y = 50
    for width in (600, 480, 540, 420):
        draw.rectangle([(60, y), (60 + width, y + 28)], fill=40)
        y += 80
    doc.paste(make_signature(seed=4).resize((420, 150)), (300, y + 60))
    buffer = io.BytesIO()
    doc.convert("RGB").save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def post_regions(client, image_bytes: bytes, filename: str = "doc.jpg"):
    return client.post("/verify/regions",
                       files={"file": (filename, image_bytes, "image/jpeg")})


def make_phone_photograph() -> bytes:
    """One signature filling a frame the size a phone actually produces."""
    photo = Image.new("L", (4032, 3024), 250)
    photo.paste(make_signature(seed=6).resize((3000, 1400)), (500, 800))
    buffer = io.BytesIO()
    photo.convert("RGB").save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def test_the_browser_is_shown_a_thumbnail_and_submits_the_full_region(client, seeded):
    """Two images per region, and the difference is not cosmetic.

    A decoded bitmap costs four bytes a pixel in the tab regardless of what the PNG
    weighs, so displaying full-resolution regions from a phone photograph cost ~23 MB
    each. A phone reclaims memory by discarding the page, which reloads it and empties
    the form mid-verification. The submitted image stays full resolution because
    preparing a downscaled region moves the embedding distance by up to 0.47.
    """
    from backend.app.routers.verify import PREVIEW_EDGE

    login(client, "SB44", "rep1")
    regions = post_regions(client, make_phone_photograph(), "photo.jpg").json()["regions"]
    assert regions

    for region in regions:
        shown = Image.open(io.BytesIO(base64.b64decode(region["preview_png_base64"])))
        submitted = Image.open(io.BytesIO(base64.b64decode(region["image_png_base64"])))
        assert max(shown.size) <= PREVIEW_EDGE
        assert submitted.size >= shown.size

    biggest = max(regions, key=lambda r: len(r["image_png_base64"]))
    full = Image.open(io.BytesIO(base64.b64decode(biggest["image_png_base64"])))
    assert max(full.size) > PREVIEW_EDGE, "fixture too small to prove anything"


def test_document_yields_multiple_candidate_regions(client, seeded):
    login(client, "SB44", "rep1")
    response = post_regions(client, make_printed_document())
    assert response.status_code == 200, response.text
    regions = response.json()["regions"]
    assert len(regions) > 1, "a printed form should offer the clerk a choice"
    assert [r["index"] for r in regions] == list(range(len(regions)))
    for region in regions:
        assert region["preview_png_base64"]


def test_specimen_card_yields_one_region_per_signature(client, seeded):
    login(client, "BA11", "clerk1")
    response = post_regions(client, make_specimen_card(9), filename="card.jpg")
    assert response.status_code == 200
    assert len(response.json()["regions"]) >= 5


def test_cropped_signature_needs_no_selection(client, seeded):
    """An already-tight signature has no distinct sub-region, so the caller just
    submits the original image. This is the path that preserves today's behaviour."""
    login(client, "SB44", "rep1")
    response = post_regions(client, png(make_signature()), filename="sig.png")
    assert response.status_code == 200
    assert len(response.json()["regions"]) == 1


def test_regions_rejects_blank_image(client, seeded):
    login(client, "SB44", "rep1")
    blank = png(Image.new("L", (400, 300), 255))
    response = post_regions(client, blank, filename="blank.png")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_IMAGE"


def test_regions_requires_auth(client, seeded):
    assert post_regions(client, make_printed_document()).status_code == 401


def test_regions_forbidden_for_engineer(client, seeded):
    login(client, "SS00", "eng1")
    assert post_regions(client, make_printed_document()).status_code == 403


def test_regions_are_capped(client, seeded):
    """A dense scan must not return a wall of thumbnails."""
    from backend.app.routers.verify import MAX_REGIONS

    login(client, "SB44", "rep1")
    dense = Image.new("L", (900, 2400), 255)
    draw = ImageDraw.Draw(dense)
    for row in range(30):
        draw.text((60, 40 + row * 78), f"Line item {row} of the statement", fill=0)
    buffer = io.BytesIO()
    dense.convert("RGB").save(buffer, format="JPEG", quality=95)

    regions = post_regions(client, buffer.getvalue()).json()["regions"]
    assert len(regions) <= MAX_REGIONS


def test_a_tight_close_up_still_gets_a_prepared_region(client, seeded):
    """The bug this guards: a close-up yields no sub-region, and the caller used to fall
    back to submitting the raw original - unprepared, while every reference was
    prepared. Same photo, different preparation, unusable comparison."""
    login(client, "SB44", "rep1")
    response = post_regions(client, png(make_signature()), filename="closeup.png")
    assert response.status_code == 200
    regions = response.json()["regions"]
    assert len(regions) == 1, "a close-up must still offer exactly one prepared region"
    assert regions[0]["preview_png_base64"]
