"""Render a report Document to PDF via Qt's rich-text engine (no extra dependencies)."""

from __future__ import annotations

import html
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import QApplication

from taxfolio.i18n import _
from taxfolio.reports.document import Document, text

_app: QApplication | None = None  # kept alive for the whole process once created here


def to_html(doc: Document) -> str:
    parts = [
        "<html><head><style>"
        "body{font-family:sans-serif;font-size:8pt} h1{font-size:14pt} h2{font-size:10pt;margin-top:14px}"
        "table{border-collapse:collapse} th,td{border:1px solid #999;padding:2px 4px}"
        "th{background:#eee} td.n{text-align:right} .note{color:#7a4b00}"
        "</style></head><body>",
        f"<h1>{html.escape(doc.title)}</h1>",
    ]
    if doc.subtitle:
        parts.append(f"<p>{html.escape(doc.subtitle)}</p>")
    generated = _("Vygenerováno {when}").format(when=f"{doc.generated_at:%d.%m.%Y %H:%M}")
    parts.append(f"<p>{html.escape(generated)}</p>")
    parts.extend(f"<p>{html.escape(p)}</p>" for p in doc.summary)
    for table in doc.tables:
        parts.append(f"<h2>{html.escape(table.title)}</h2><table width='100%'><tr>")
        parts.extend(f"<th>{html.escape(h)}</th>" for h in table.headers)
        parts.append("</tr>")
        for row in table.rows:
            parts.append("<tr>")
            for value in row:
                cls = " class='n'" if isinstance(value, (Decimal, int)) else ""
                parts.append(f"<td{cls}>{html.escape(text(value))}</td>")
            parts.append("</tr>")
        parts.append("</table>")
    if doc.notes:
        parts.append(f"<h2>{html.escape(_('Upozornění'))}</h2>")
        parts.extend(f"<p class='note'>{html.escape(n)}</p>" for n in doc.notes)
    parts.append("</body></html>")
    return "".join(parts)


def write_pdf(doc: Document, path: Path) -> None:
    # QTextDocument needs an application object; the CLI runs without one. Create a full
    # QApplication (not QGuiApplication) so a widget UI started later in the process still works.
    global _app
    if QApplication.instance() is None:
        _app = QApplication(["taxfolio", "-platform", "offscreen"])
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = QPdfWriter(str(path))
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Landscape, QMarginsF(12, 12, 12, 12)
        )
    )
    writer.setResolution(150)
    writer.setTitle(doc.title)
    text_doc = QTextDocument()
    text_doc.setHtml(to_html(doc))
    rect = writer.pageLayout().paintRectPixels(writer.resolution())
    text_doc.setPageSize(QSizeF(rect.width(), rect.height()))
    text_doc.print_(writer)
