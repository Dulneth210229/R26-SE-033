"""
Unit tests for functional_checker.py -- the payload-synthesis and endpoint-discovery halves are
pure, tmp_path-only, no LLM/Docker/network (mirrors every sibling checker's own idiom); the real
HTTP POST/GET half is exercised via a stubbed urllib.request.urlopen so no real server is needed
either.
"""

import urllib.error
from unittest.mock import patch

from app.agents.coder_agent.functional_checker import (
    check_crud_functionality,
    discover_post_endpoints,
    synthesize_payload_from_form,
)

POST_ROUTE = """\
import { NextResponse } from "next/server";

export async function POST(request) {
  const body = await request.json();
  return NextResponse.json(body, { status: 201 });
}
"""

GET_ONLY_ROUTE = """\
import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json([]);
}
"""

REAL_FORM = """\
export default function ItemListingPage() {
  const [formData, setFormData] = useState({
    name: "",
    price: 0,
    quantity: 0,
    inStock: false,
  });

  return <form></form>;
}
"""

UNCONFIDENT_FORM = """\
export default function Page() {
  const [config, setConfig] = useState({ ref: someExternalDefault() });
  const [open, setOpen] = useState(false);
  return null;
}
"""


def _write(tmp_path, rel_path, content):
    file_path = tmp_path / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


class _FakeBody:
    """Minimal file-like object for urllib.error.HTTPError's own `fp` -- HTTPError.read()
    delegates to it."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def close(self):
        pass


def test_discover_post_endpoints_finds_a_real_post_route(tmp_path):
    _write(tmp_path, "app/api/items/route.ts", POST_ROUTE)
    plan = {"files": [{"path": "app/api/items/route.ts", "action": "create", "maps_to": []}]}

    results = discover_post_endpoints(tmp_path, plan)

    assert results == [{"endpoint": "/api/items", "file": "app/api/items/route.ts"}]


def test_discover_post_endpoints_ignores_get_only_routes(tmp_path):
    _write(tmp_path, "app/api/items/route.ts", GET_ONLY_ROUTE)
    plan = {"files": [{"path": "app/api/items/route.ts", "action": "create", "maps_to": []}]}

    assert discover_post_endpoints(tmp_path, plan) == []


def test_discover_post_endpoints_ignores_parameterized_routes(tmp_path):
    _write(tmp_path, "app/api/items/[id]/route.ts", POST_ROUTE)
    plan = {"files": [{"path": "app/api/items/[id]/route.ts", "action": "create", "maps_to": []}]}

    assert discover_post_endpoints(tmp_path, plan) == []


def test_discover_post_endpoints_ignores_deleted_files(tmp_path):
    _write(tmp_path, "app/api/items/route.ts", POST_ROUTE)
    plan = {"files": [{"path": "app/api/items/route.ts", "action": "delete", "maps_to": []}]}

    assert discover_post_endpoints(tmp_path, plan) == []


def test_synthesize_payload_from_real_form_shape():
    payload = synthesize_payload_from_form([REAL_FORM])

    assert payload is not None
    assert payload["name"] == "AutoForgeCrudCheck"  # first string field gets the distinctive marker
    assert payload["price"] == 1
    assert payload["quantity"] == 1
    assert payload["inStock"] is True


def test_synthesize_payload_returns_none_when_no_confident_state_object():
    assert synthesize_payload_from_form([UNCONFIDENT_FORM]) is None


def test_synthesize_payload_skips_unconfident_fields_but_keeps_confident_ones():
    form = """\
export default function Page() {
  const [formData, setFormData] = useState({
    name: "",
    createdAt: Date.now(),
    price: 5,
  });
  return null;
}
"""
    payload = synthesize_payload_from_form([form])

    assert payload is not None
    assert "createdAt" not in payload
    assert payload["name"] == "AutoForgeCrudCheck"
    assert payload["price"] == 1


def test_synthesize_payload_returns_none_for_empty_frontend_list():
    assert synthesize_payload_from_form([]) is None


def test_check_crud_functionality_skips_when_no_post_endpoint(tmp_path):
    plan = {"files": []}
    results = check_crud_functionality(tmp_path, plan, "http://localhost:1")

    assert len(results) == 1
    assert results[0]["status"] == "skipped"


def test_check_crud_functionality_skips_when_no_payload_synthesizable(tmp_path):
    _write(tmp_path, "app/api/items/route.ts", POST_ROUTE)
    _write(tmp_path, "app/item-listing/page.tsx", UNCONFIDENT_FORM)
    plan = {
        "files": [
            {"path": "app/api/items/route.ts", "action": "create", "maps_to": []},
            {"path": "app/item-listing/page.tsx", "action": "create", "maps_to": []},
        ]
    }

    results = check_crud_functionality(tmp_path, plan, "http://localhost:1")

    assert len(results) == 1
    assert results[0]["status"] == "skipped"


def _fake_urlopen_factory(post_status, post_body, get_body):
    class _FakeResponse:
        def __init__(self, status, body):
            self.status = status
            self._body = body.encode("utf-8")

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _fake_urlopen(request, timeout=None):
        if request.get_method() == "POST":
            return _FakeResponse(post_status, post_body)
        return _FakeResponse(200, get_body)

    return _fake_urlopen


def test_check_crud_functionality_passes_on_real_create_then_confirmed_readback(tmp_path):
    _write(tmp_path, "app/api/items/route.ts", POST_ROUTE)
    _write(tmp_path, "app/item-listing/page.tsx", REAL_FORM)
    plan = {
        "files": [
            {"path": "app/api/items/route.ts", "action": "create", "maps_to": []},
            {"path": "app/item-listing/page.tsx", "action": "create", "maps_to": []},
        ]
    }

    fake_urlopen = _fake_urlopen_factory(201, '{"name":"AutoForgeCrudCheck"}', '[{"name":"AutoForgeCrudCheck"}]')
    with patch("app.agents.coder_agent.functional_checker.urllib.request.urlopen", side_effect=fake_urlopen):
        results = check_crud_functionality(tmp_path, plan, "http://localhost:12345")

    assert len(results) == 1
    assert results[0]["status"] == "passed"
    assert results[0]["endpoint"] == "/api/items"


def test_check_crud_functionality_fails_on_non_2xx_post(tmp_path):
    _write(tmp_path, "app/api/items/route.ts", POST_ROUTE)
    _write(tmp_path, "app/item-listing/page.tsx", REAL_FORM)
    plan = {
        "files": [
            {"path": "app/api/items/route.ts", "action": "create", "maps_to": []},
            {"path": "app/item-listing/page.tsx", "action": "create", "maps_to": []},
        ]
    }

    def _raise_http_error(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 500, "Internal Server Error", None,
            fp=_FakeBody(b'{"error":"Failed to create item"}'),
        )

    with patch("app.agents.coder_agent.functional_checker.urllib.request.urlopen", side_effect=_raise_http_error):
        results = check_crud_functionality(tmp_path, plan, "http://localhost:12345")

    assert results[0]["status"] == "failed"
    assert results[0]["reason"] == "post_rejected"
    assert "Failed to create item" in results[0]["output"]


def test_check_crud_functionality_fails_when_created_item_never_shows_up_on_readback(tmp_path):
    _write(tmp_path, "app/api/items/route.ts", POST_ROUTE)
    _write(tmp_path, "app/item-listing/page.tsx", REAL_FORM)
    plan = {
        "files": [
            {"path": "app/api/items/route.ts", "action": "create", "maps_to": []},
            {"path": "app/item-listing/page.tsx", "action": "create", "maps_to": []},
        ]
    }

    fake_urlopen = _fake_urlopen_factory(201, '{"name":"AutoForgeCrudCheck"}', "[]")
    with patch("app.agents.coder_agent.functional_checker.urllib.request.urlopen", side_effect=fake_urlopen):
        results = check_crud_functionality(tmp_path, plan, "http://localhost:12345")

    assert results[0]["status"] == "failed"
    assert results[0]["reason"] == "not_persisted"
    assert "never appeared" in results[0]["output"]
