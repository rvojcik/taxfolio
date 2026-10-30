"""Write a report document to the format implied by the file extension."""

from __future__ import annotations

from pathlib import Path

from taxfolio.i18n import _
from taxfolio.reports.document import Document


def export(doc: Document, path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        from taxfolio.reports.xlsx import write_xlsx

        write_xlsx(doc, path)
    elif suffix == ".pdf":
        from taxfolio.reports.pdf import write_pdf

        write_pdf(doc, path)
    else:
        raise ValueError(
            _("Nepodporovaný formát exportu: {suffix} (použijte .xlsx nebo .pdf)").format(suffix=suffix)
        )
