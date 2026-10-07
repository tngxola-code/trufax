"""Generate examples/budget/general-fund-revenue.pdf (a fictional two-page budget table).

Run: python scripts/make_example_pdf.py   (needs reportlab: pip install -e '.[dev]')
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).resolve().parents[1] / "examples" / "budget" / "general-fund-revenue.pdf"
HEADER = ["Revenue Source", "FY2025 Actual", "FY2026 Proposed"]

TAX = [
    ("Personal Income Tax", "4,812,300", "5,010,900"),
    ("Corporate Income Tax", "1,204,750", "1,187,400"),
    ("General Sales Tax", "3,966,120", "4,102,880"),
    ("Fuel Levy", "612,400", "598,250"),
    ("Tobacco Products Tax", "88,930", "84,100"),
    ("Total Tax Revenue", "10,684,500", "10,983,530"),
]
NONTAX = [
    ("Licences and Permits", "215,600", "221,900"),
    ("Interest and Investment Income", "142,380", "131,000"),
    ("Fines and Forfeitures", "57,210", "60,000"),
    ("Transfers from Reserves", "300,000", "250,000"),
    ("Refunds of Prior-Year Revenue", "(12,400)", "(10,000)"),
    ("Total Non-Tax Revenue", "702,790", "652,900"),
    ("Total General Fund Revenue", "11,387,290", "11,636,430"),
]


def table(rows):
    t = Table([HEADER] + [list(r) for r in rows], colWidths=[250, 110, 110])
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    )
    return t


def main():
    ss = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(OUT), pagesize=A4)
    doc.build(
        [
            Paragraph("Province of Example: Governor's Proposed Budget FY2026", ss["Title"]),
            Paragraph(
                "Schedule 1. General Fund revenue by source (thousands of dollars)", ss["Normal"]
            ),
            Spacer(1, 12),
            table(TAX),
            PageBreak(),
            Paragraph("Schedule 1 (continued)", ss["Normal"]),
            Spacer(1, 12),
            table(NONTAX),
            Spacer(1, 12),
            Paragraph("Source: fictional data for demonstration only.", ss["Italic"]),
        ]
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
