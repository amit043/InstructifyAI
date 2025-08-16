import json
from datetime import datetime

import pytest
from fastapi import HTTPException

from exporters.templates import compile_template

fake_chunk = {
    "content": {"type": "text", "text": "hello"},
    "source": {"section_path": ["A", "B"]},
    "metadata": {},
}

fake_doc = {"doc_id": "d1", "created": datetime(2023, 1, 1)}


def test_template_renders_helpers():
    template = (
        '{{ {"path": join_section_path(chunk.source), '
        '"created": iso8601(doc.created), '
        '"text": chunk.content.text} | tojson }}'
    )
    tmpl = compile_template(template)
    rendered = tmpl.render(chunk=fake_chunk, doc=fake_doc)
    data = json.loads(rendered)
    assert data == {
        "path": "A / B",
        "created": "2023-01-01T00:00:00",
        "text": "hello",
    }


def test_invalid_template_raises_400():
    with pytest.raises(HTTPException) as exc:
        compile_template("{{ bad ::")
    assert exc.value.status_code == 400
