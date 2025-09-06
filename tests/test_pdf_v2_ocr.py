import base64

import pytest

pytest.importorskip("fitz")
pytest.importorskip("pytesseract")

import fitz  # type: ignore[import-not-found, import-untyped]
import pytesseract  # type: ignore[import-untyped]

from parsers.pdf_v2 import PDFParserV2

IMAGE_PNG_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAGQAAAAoCAIAAACHGsgUAAAB+UlEQVR4nO3Yv6uyUBjA8YyXgpYgqMH2gqJFpziDmuLSFASNTY3N/SVNDdUS/QVhP4YarE1CCILG2m3KMPLcQa5c3vcle6Dw3svzmfR0isO3ziFkKKUR9Jxo2Av4STAWAMYCwFgAGAsAYwFgLACMBYCxADAWAMYCCI7V7/d5ni+XyzzPD4dDb7DX63EcJwhCtVo9Ho/eYCKREEVREASO41ar1RtXHRb6kKZphBDLsiillmURQubz+Ww2kyTpcrlQSieTSaVS8SYnk0nvwjTNUqn0+JN/ooBYsiyv12v/Vtd1RVFUVd1sNv5gq9VyHId+ieW6biqVev1iwxYQi2VZ27b9W9u2WZbNZrPX6/XfyX4sTdPq9frrFvld/IHuWYZh7vf7f191HEcUxdvttt/vd7vdKw6J7yXggC8UCoZh+LeGYRSLxVwut91uvRFKabPZ9K5jsdhyudR1vdPpDAaDt6w3XI9/eNPplBByPp/p5wG/WCzG47GiKN5OHI1GjUbDm+xvQ8MwarXa23ZDaAK2oaqqp9NJkqR4PO44TrvdlmU5EokcDgee59PpdCaT6Xa7f70rn8+bpum6bjT6q/7HMRSfwT/tV33z74axADAWAMYCwFgAGAsAYwFgLACMBYCxADAWAMYCwFgAGAsAYwFgLACMBYCxADAWwAeEQLqnJKe0wQAAAABJRU5ErkJggg=="


def _tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _tesseract_available(), reason="tesseract not installed")
def test_pdf_v2_ocr() -> None:
    doc = fitz.open()

    # Page 1: regular text
    page1 = doc.new_page()
    page1.insert_text((72, 72), "HELLO\nworld")

    # Page 2: image with text
    page2 = doc.new_page()
    image_bytes = base64.b64decode(IMAGE_PNG_BASE64)
    page2.insert_image(fitz.Rect(0, 0, 100, 40), stream=image_bytes)

    pdf_bytes = doc.tobytes()
    doc.close()

    parser = PDFParserV2(langs=["eng"])
    blocks = list(parser.parse(pdf_bytes))

    assert any(b.meta["source_stage"] == "pdf_text" for b in blocks)
    assert any(b.meta["source_stage"] == "pdf_ocr" for b in blocks)

    assert parser.page_metrics[0].ocr_used is False
    assert parser.page_metrics[1].ocr_used is True
    assert parser.page_metrics[1].ocr_conf_mean is not None
