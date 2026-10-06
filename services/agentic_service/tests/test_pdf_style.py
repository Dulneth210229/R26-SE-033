"""
Tests for app.agents._shared.pdf_style -- html_document_shell's "Downloaded On"
line and signature_block_html()'s sign-off fields.
"""

from datetime import datetime

from app.agents._shared.pdf_style import html_document_shell, signature_block_html


def test_html_document_shell_renders_downloaded_on_with_an_injected_timestamp():
    fixed = datetime(2026, 3, 5, 14, 30)

    html = html_document_shell("Title", "Subtitle", "<p>body</p>", generated_at=fixed)

    assert "Downloaded On: March 05, 2026 at 02:30 PM" in html


def test_html_document_shell_defaults_to_the_real_current_time_when_omitted():
    html = html_document_shell("Title", "Subtitle", "<p>body</p>")

    assert "Downloaded On:" in html
    assert str(datetime.now().year) in html


def test_html_document_shell_still_renders_title_subtitle_and_body():
    html = html_document_shell("My Title", "My Subtitle", "<p>real body content</p>")

    assert "My Title" in html
    assert "My Subtitle" in html
    assert "real body content" in html
    assert html.startswith("<!DOCTYPE html>")


def test_signature_block_html_contains_both_rows_and_blank_fields():
    html = signature_block_html()

    assert "Prepared By" in html
    assert "Reviewed / Approved By" in html
    assert html.count("Name") == 2
    assert html.count("Signature") == 2
    assert html.count("Date") == 2
    assert "signoff-line" in html
