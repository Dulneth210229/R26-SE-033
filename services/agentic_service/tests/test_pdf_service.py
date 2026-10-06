"""
Tests for app.services.pdf_service.render_html_to_pdf -- confirms it produces
real, non-empty PDF bytes from a trivial self-contained HTML string. Checked
via the standard %PDF- magic-byte header, not a full visual diff.
"""

import io

import pypdf

from app.services import pdf_service


def test_render_html_to_pdf_produces_real_pdf_bytes():
    html = "<html><body><h1>Hello PDF</h1></body></html>"

    pdf_bytes = pdf_service.render_html_to_pdf(html)

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 500


def test_render_html_to_pdf_handles_a_larger_styled_document():
    html = """
    <html>
    <head><style>body { font-family: sans-serif; } table { border-collapse: collapse; }</style></head>
    <body>
      <h1>Document Title</h1>
      <table><tr><th>ID</th><th>Description</th></tr><tr><td>FR-001</td><td>Do a thing</td></tr></table>
    </body>
    </html>
    """

    pdf_bytes = pdf_service.render_html_to_pdf(html)

    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 500


def test_render_html_to_pdf_adds_a_real_page_number_footer_across_multiple_pages():
    # A page-break per section forces several real pages, so this also confirms the
    # header/footer templates don't break rendering on a multi-page document.
    sections = "".join(
        f'<section style="page-break-after: always;"><h2>Section {i}</h2><p>Content {i}</p></section>'
        for i in range(3)
    )
    html = f"<html><body>{sections}</body></html>"

    pdf_bytes = pdf_service.render_html_to_pdf(html)

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) >= 2

    full_text = "".join(page.extract_text() or "" for page in reader.pages)
    assert "Page 1 of" in full_text
