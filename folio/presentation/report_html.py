"""A report as HTML, for the preview and for the PDF. Always drawn on white, like paper."""
from __future__ import annotations

from html import escape

from ..application.records import ReportView
from ..application.types import FieldType
from .datasheet_format import format_cell
from .i18n import _, plural

CSS = """
body { font-family: sans-serif; color: #16181d; font-size: 10pt; }
h1 { font-size: 20pt; margin: 0 0 4px 0; }
.sub { color: #636a75; margin-bottom: 14px; }
h2 { font-size: 12pt; margin: 18px 0 4px 0; color: #4c4cc4; }
table { border-collapse: collapse; width: 100%; }
th { text-align: left; color: #636a75; font-size: 8pt; border-bottom: 1px solid #c9ccd3;
     padding: 4px 6px; }
td { padding: 4px 6px; border-bottom: 1px solid #ececf0; }
.num { text-align: right; }
.sum td { font-weight: bold; border-top: 1px solid #16181d; border-bottom: none; }
.grand td { font-weight: bold; border-top: 2px solid #16181d; border-bottom: none;
            background: #f0f1f4; }
"""


def report_html(title: str, view: ReportView, types: dict[str, FieldType | None]) -> str:
    cols = view.columns
    numeric = [types.get(c) is not None and types[c].is_numeric for c in cols]

    def head() -> str:
        return "<tr>" + "".join(f"<th{' class=num' if n else ''}>{escape(c)}</th>"
                                for c, n in zip(cols, numeric)) + "</tr>"

    def cells(row, bold=False) -> str:
        out = []
        for value, c, n in zip(row, cols, numeric):
            text = "" if value is None else format_cell(value, types.get(c))
            out.append(f"<td{' class=num' if n else ''}>{escape(text)}</td>")
        return "<tr>" + "".join(out) + "</tr>"

    def sums(row, label) -> str:
        out = []
        for i, (value, c, n) in enumerate(zip(row, cols, numeric)):
            text = label if i == 0 and value is None else ("" if value is None else format_cell(value, types.get(c)))
            out.append(f"<td{' class=num' if n and i else ''}>{escape(text)}</td>")
        return "".join(out)

    body = [f"<h1>{escape(title)}</h1>",
            f"<div class=sub>{escape(plural(view.row_count, 'row'))}</div>"]
    has_sums = any(s is not None for s in view.totals)
    for group in view.groups:
        if view.group_by:
            key = _("(empty)") if group.key is None else format_cell(group.key, types.get(view.group_by))
            body.append(f"<h2>{escape(view.group_by)}: {escape(key)}</h2>")
        body.append("<table width='100%'>" + head() + "".join(cells(r) for r in group.rows))
        if has_sums and (view.group_by):
            body.append(f"<tr class=sum>{sums(group.sums, _('Total'))}</tr>")
        body.append("</table>")
    if has_sums:
        body.append("<table width='100%'><tr class=grand>" + sums(view.totals, _("Grand total")) + "</tr></table>")
    return f"<html><head><style>{CSS}</style></head><body>{''.join(body)}</body></html>"
