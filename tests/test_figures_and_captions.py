import base64
import io

import pytest

pytest.importorskip("fitz")
pytest.importorskip("pytesseract")

import fitz  # type: ignore[import-not-found, import-untyped]
import pytesseract  # type: ignore[import-untyped]

from parsers.html_figures import extract_figures as extract_html_figures
from parsers.pdf_figures import extract_figures as extract_pdf_figures
from storage.object_store import ObjectStore
from worker.ocr.image_block import ocr_image_block


class FakeS3Client:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def put_object(self, Bucket: str, Key: str, Body: bytes) -> None:  # noqa: N803
        self.store[Key] = Body

    def get_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803
        return {"Body": io.BytesIO(self.store[Key])}

    def list_objects_v2(self, Bucket: str, Prefix: str) -> dict:  # noqa: N803
        keys = [k for k in self.store if k.startswith(Prefix)]
        return {"Contents": [{"Key": k} for k in keys]}

    def generate_presigned_url(
        self, operation: str, Params: dict, ExpiresIn: int
    ) -> str:  # noqa: N803
        return f"https://example.com/{Params['Key']}?X-Amz-Expires={ExpiresIn}"


HTML_SNIPPET = """
<figure>
  <img src="img.png" />
  <figcaption>An example figure</figcaption>
</figure>
"""

IMAGE_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAGQAAAAoCAIAAACHGsgUAAAB+UlEQVR4nO3Yv6uyUBjA8YyXgpYg"
    "qMH2gqJFpziDmuLSFASNTY3N/SVNDdUS/QVhP4YarE1CCILG2m3KMPLcQa5c3vcle6Dw3svzmfR0i"
    "sO3ziFkKKUR9Jxo2Av4STAWAMYCwFgAGAsAYwFgLACMBYCxADAWAMYCCI7V7/d5ni+XyzzPD4dDb7DX63Ec"
    "JwhCtVo9Ho/eYCKREEVREASO41ar1RtXHRb6kKZphBDLsiillmURQubz+Ww2kyTpcrlQSieTSaVS8SYnk0nvwjTNUqn0+JN/ooBYsiyv12v/Vtd1RVFUVd1sNv5gq9Vy"
    "HId+ieW6biqVev1iwxYQi2VZ27b9W9u2WZbNZrPX6/XfyX4sTdPq9frrFvld/IHuWYZh7vf7f191HEcUxdvttt/vd7vdKw6J7yXggC8UCoZh+LeGYRSLxVwut91uvRFK"
    "abPZ9K5jsdhyudR1vdPpDAaDt6w3XI9/eNPplBByPp/p5wG/WCzG47GiKN5OHI1GjUbDm+xvQ8MwarXa23ZDaAK2oaqqp9NJkqR4PO44TrvdlmU5EokcDgee59PpdCaT"
    "6Xa7f70rn8+bpum6bjT6q/7HMRSfwT/tV33z74axADAWAMYCwFgAGAsAYwFgLACMBYCxADAWAMYCwFgAGAsAYwFgLACMBYCxADAWwAeEQLqnJKe0wQAAAABJRU5ErkJggg=="
)


def test_html_figure_extraction() -> None:
    figs = extract_html_figures(HTML_SNIPPET)
    assert len(figs) == 1
    assert figs[0].src == "img.png"
    assert figs[0].caption == "An example figure"


def _tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _tesseract_available(), reason="tesseract not installed")
def test_pdf_figures_and_ocr() -> None:
    client = FakeS3Client()
    store = ObjectStore(client=client, bucket="test")
    doc = fitz.open()
    page = doc.new_page()
    image_bytes = base64.b64decode(IMAGE_PNG_BASE64)
    page.insert_image(fitz.Rect(0, 0, 100, 40), stream=image_bytes)
    page.insert_text((0, 50), "Figure: Greeting")
    pdf_bytes = doc.tobytes()
    doc.close()

    figures = extract_pdf_figures(pdf_bytes, store=store, doc_id="doc1")
    assert figures
    fig = figures[0]
    assert fig.caption == "Figure: Greeting"
    assert fig.image_key in client.store
    ocr_text, conf = ocr_image_block(client.store[fig.image_key])
    assert "HELLO" in ocr_text
    assert conf > 0
