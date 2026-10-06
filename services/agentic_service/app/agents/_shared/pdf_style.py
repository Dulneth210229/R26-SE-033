"""
Shared CSS for the PDF document templates (Requirement/Domain/Architecture
Agent). One small stylesheet reused by every pdf_builder.py so the three
generated documents share one clean, print-friendly visual language instead
of each hand-rolling its own.
"""

from __future__ import annotations

from datetime import datetime

PDF_DOCUMENT_STYLE = """
<style>
  @page { size: A4; margin: 0; }
  * { box-sizing: border-box; }
  body {
    font-family: "Segoe UI", Helvetica, Arial, sans-serif;
    color: #1f2933;
    font-size: 11px;
    line-height: 1.5;
  }
  .doc-title {
    font-size: 22px;
    font-weight: 700;
    color: #111827;
    margin: 0 0 4px 0;
    border-top: 4px solid #4f46e5;
    padding-top: 10px;
  }
  .doc-subtitle {
    font-size: 12px;
    color: #4b5563;
    margin: 0 0 18px 0;
  }
  .meta-table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 20px;
  }
  .meta-table td {
    border: 1px solid #d1d5db;
    padding: 5px 8px;
    vertical-align: top;
  }
  .meta-table td.meta-label {
    background: #f3f4f6;
    font-weight: 600;
    width: 32%;
    color: #374151;
  }
  section.doc-section {
    margin: 0 0 18px 0;
    page-break-inside: avoid;
  }
  h2.section-title {
    font-size: 15px;
    font-weight: 700;
    color: #111827;
    border-bottom: 2px solid #4f46e5;
    padding-bottom: 4px;
    margin: 0 0 10px 0;
  }
  h3.subsection-title {
    font-size: 12.5px;
    font-weight: 700;
    color: #1f2937;
    margin: 14px 0 6px 0;
  }
  p.section-body {
    margin: 0 0 8px 0;
  }
  ul.plain-list {
    margin: 0 0 8px 0;
    padding-left: 20px;
  }
  ul.plain-list li {
    margin-bottom: 4px;
  }
  table.data-table {
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0 14px 0;
    font-size: 10.5px;
  }
  table.data-table thead {
    /* Repeats the colored header row on every page a long table spans across. */
    display: table-header-group;
  }
  table.data-table th {
    background: #4f46e5;
    color: #ffffff;
    text-align: left;
    padding: 6px 8px;
    font-weight: 600;
  }
  table.data-table td {
    border: 1px solid #e5e7eb;
    padding: 6px 8px;
    vertical-align: top;
  }
  table.data-table tr:nth-child(even) td {
    background: #f9fafb;
  }
  table.data-table tr {
    page-break-inside: avoid;
  }
  .card {
    border: 1px solid #e5e7eb;
    border-left: 4px solid #4f46e5;
    border-radius: 4px;
    padding: 8px 10px;
    margin-bottom: 8px;
    background: #f8fafc;
    page-break-inside: avoid;
  }
  .card.domain-added {
    border-left-color: #16a34a;
    background: #f0fdf4;
  }
  .card .card-title {
    font-weight: 700;
    margin-bottom: 3px;
    color: #1f2937;
  }
  .badge {
    display: inline-block;
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    padding: 1px 6px;
    border-radius: 3px;
    background: #16a34a;
    color: #ffffff;
    margin-left: 6px;
  }
  .empty-note {
    color: #6b7280;
    font-style: italic;
  }
  .doc-footer {
    margin-top: 24px;
    padding-top: 10px;
    border-top: 1px solid #d1d5db;
    font-size: 9.5px;
    color: #6b7280;
  }
  .signoff-block {
    margin-top: 6px;
  }
  .signoff-row {
    display: flex;
    gap: 24px;
    margin-top: 10px;
    page-break-inside: avoid;
  }
  .signoff-field {
    flex: 1;
  }
  .signoff-field .signoff-label {
    display: block;
    font-size: 9.5px;
    color: #6b7280;
    margin-bottom: 22px;
  }
  .signoff-field .signoff-line {
    display: block;
    border-bottom: 1px solid #1f2933;
    height: 1px;
  }
</style>
"""


def html_document_shell(
    title: str, subtitle: str, body_html: str, generated_at: datetime | None = None
) -> str:
    """
    Wrap a document's own section HTML in a complete, self-contained
    <html> document with the shared style block inlined.

    generated_at defaults to the real current time (this PDF is always rendered
    fresh on every download, so "generated at" == "downloaded at") -- the
    optional override exists purely so a test can assert an exact, deterministic
    "Downloaded On" string instead of loosely pattern-matching a wall-clock value.
    """
    when = generated_at or datetime.now()
    downloaded_line = f"Downloaded On: {when.strftime('%B %d, %Y at %I:%M %p')}"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>{title}</title>
{PDF_DOCUMENT_STYLE}
</head>
<body>
  <div class="doc-title">{title}</div>
  <div class="doc-subtitle">{subtitle}</div>
  <div class="doc-subtitle">{downloaded_line}</div>
  {body_html}
</body>
</html>"""


def signature_block_html() -> str:
    """
    A static, non-interactive "Document Sign-Off" block -- blank, underlined
    Name/Signature/Date fields for a human to fill in by hand on a printed (or
    annotated) copy. Appended by every pdf_builder.py as the final section of
    its document.
    """

    def _row(label: str) -> str:
        return f"""
        <div class="signoff-row">
          <div class="signoff-field">
            <span class="signoff-label">{label} -- Name</span>
            <span class="signoff-line"></span>
          </div>
          <div class="signoff-field">
            <span class="signoff-label">Signature</span>
            <span class="signoff-line"></span>
          </div>
          <div class="signoff-field">
            <span class="signoff-label">Date</span>
            <span class="signoff-line"></span>
          </div>
        </div>"""

    return f'<div class="signoff-block">{_row("Prepared By")}{_row("Reviewed / Approved By")}</div>'
