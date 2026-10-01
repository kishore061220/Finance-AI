"""Report generation for CSV, Excel and PDF.

Every generator is pure: it takes already-computed rows and returns bytes plus
a row count. The route layer owns the data access, so the formats are
testable without a database.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Sequence, Tuple

REPORT_DATE_FORMAT = "%Y-%m-%d %H:%M"


def _cell(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.strftime(REPORT_DATE_FORMAT)
    if hasattr(value, "value"):
        return value.value
    return value


def _to_csv(columns: Sequence[str], rows: Sequence[Dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(c)) for c in columns])
    return buffer.getvalue().encode("utf-8")


def _to_excel(columns: Sequence[str], rows: Sequence[Dict], title: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31] or "Report"

    ws.append([f"Finance-AI {title} Report"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Generated: {datetime.utcnow().strftime(REPORT_DATE_FORMAT)} UTC"])
    ws.append([])

    header_row = ws.max_row + 1
    ws.append(list(columns))
    for cell in ws[header_row]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDEEFF")
        cell.alignment = Alignment(horizontal="center")

    for row in rows:
        ws.append([_cell(row.get(c)) for c in columns])

    widths = {}
    for r in rows:
        for c in columns:
            widths[c] = max(widths.get(c, len(str(c))), len(str(_cell(r.get(c)) or "")))
    for idx, c in enumerate(columns, start=1):
        ws.column_dimensions[ws.cell(row=header_row, column=idx).column_letter].width = min(
            max(12, widths.get(c, 12) + 2), 45
        )

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _to_pdf(columns: Sequence[str], rows: Sequence[Dict], title: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        title=f"Finance-AI {title} Report",
        author="Finance-AI",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Finance-AI {title} Report", styles["Title"]),
        Spacer(1, 4 * mm),
        Paragraph(
            f"Generated {datetime.utcnow().strftime(REPORT_DATE_FORMAT)} UTC"
            f" &middot; {len(rows)} row(s)",
            styles["Normal"],
        ),
        Spacer(1, 6 * mm),
    ]

    table_data = [list(columns)] + [[_cell(r.get(c)) for c in columns] for r in rows]
    # A landscape A4 fits roughly this many columns legibly.
    max_cols = 9
    if len(columns) > max_cols:
        table_data = [row[:max_cols] for row in table_data]

    table = Table(table_data, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b57")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("FONTSIZE", (0, 1), (-1, -1), 7.5),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#bbbbbb")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7fa")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    return buffer.getvalue()


def generate(
    report_format: str,
    columns: Sequence[str],
    rows: Sequence[Dict],
    title: str = "Financial",
) -> Tuple[bytes, int, str]:
    """Render a report.

    Returns ``(bytes, row_count, media_type)``.
    """
    fmt = (report_format or "CSV").upper()
    row_count = len(rows)
    if fmt == "CSV":
        return _to_csv(columns, rows), row_count, "text/csv"
    if fmt == "EXCEL":
        return (
            _to_excel(columns, rows, title),
            row_count,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if fmt == "PDF":
        return _to_pdf(columns, rows, title), row_count, "application/pdf"
    raise ValueError(f"Unsupported report format: {report_format}")


# ---------------------------------------------------------------------------
# Column contracts per report type
# ---------------------------------------------------------------------------
TRANSACTION_COLUMNS = (
    "id", "transaction_date", "transaction_type", "amount", "category",
    "emi_type", "merchant", "description", "source", "fraud_score", "is_flagged",
)
BUDGET_COLUMNS = ("id", "category", "amount", "month", "year")
FRAUD_COLUMNS = (
    "id", "created_at", "risk_score", "risk_level", "is_fraud",
    "detection_layer", "merchant_snapshot", "amount_snapshot", "reasons",
)
LOAN_COLUMNS = (
    "id", "name", "lender", "loan_type", "principal", "interest_rate",
    "tenure_months", "monthly_emi", "total_payable", "start_date", "status",
)


def transaction_row(t) -> Dict:
    return {
        "id": t.id,
        "transaction_date": t.transaction_date,
        "transaction_type": t.transaction_type,
        "amount": t.amount,
        "category": t.category,
        "emi_type": t.emi_type,
        "merchant": t.merchant,
        "description": t.description,
        "source": getattr(t, "source", None),
        "fraud_score": getattr(t, "fraud_score", None),
        "is_flagged": getattr(t, "is_flagged", None),
    }


def budget_row(b) -> Dict:
    return {
        "id": b.id,
        "category": b.category,
        "amount": b.amount,
        "month": b.month,
        "year": b.year,
    }


def fraud_row(a) -> Dict:
    return {
        "id": a.id,
        "created_at": a.created_at,
        "risk_score": a.risk_score,
        "risk_level": a.risk_level,
        "is_fraud": a.is_fraud,
        "detection_layer": a.detection_layer,
        "merchant_snapshot": a.merchant_snapshot,
        "amount_snapshot": a.amount_snapshot,
        "reasons": ", ".join(a.reasons) if a.reasons else None,
    }


def loan_row(loan) -> Dict:
    return {
        "id": loan.id,
        "name": loan.name,
        "lender": loan.lender,
        "loan_type": loan.loan_type,
        "principal": loan.principal,
        "interest_rate": loan.interest_rate,
        "tenure_months": loan.tenure_months,
        "monthly_emi": loan.monthly_emi,
        "total_payable": loan.total_payable,
        "start_date": loan.start_date,
        "status": loan.status,
    }


def category_rows(transactions, analytics_totals) -> List[Dict]:
    from app.services.analytics import category_breakdown

    rows = category_breakdown(transactions)
    return [
        {
            "category": r["category"],
            "amount": r["amount"],
            "percent": r["percent"],
            "total_expense": analytics_totals["expense"],
        }
        for r in rows
    ]


CATEGORY_COLUMNS = ("category", "amount", "percent", "total_expense")


def spending_trend_rows(transactions) -> List[Dict]:
    from app.services.analytics import monthly_series

    return [
        {
            "period": m["label"],
            "income": m["income"],
            "expense": m["expense"],
            "net": m["net"],
        }
        for m in monthly_series(transactions)
    ]


TREND_COLUMNS = ("period", "income", "expense", "net")
