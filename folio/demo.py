"""A small sample database, built through the use cases like any user would."""
from __future__ import annotations

from .application.inputs import FieldDesign, FormDef, QueryColumn, QueryDesign, ReportDef, TableDesign
from .application.types import FieldType
from .application.workspace import Source, Workspace

T, I, D, Y = FieldType.TEXT, FieldType.INTEGER, FieldType.DATE, FieldType.YES_NO


def key() -> FieldDesign:
    return FieldDesign("id", I, True, True)


def build_library(ws: Workspace) -> None:
    ws.save_table(None, TableDesign("Authors", (key(), FieldDesign("name", T, required=True),
                                                FieldDesign("country", T))))
    ws.save_table(None, TableDesign("Books", (
        key(), FieldDesign("title", T, required=True),
        FieldDesign("author", I, ref_table="Authors", ref_field="id"),
        FieldDesign("year", I), FieldDesign("pages", I), FieldDesign("available", Y, default="yes"))))
    ws.save_table(None, TableDesign("Members", (key(), FieldDesign("name", T, required=True),
                                                FieldDesign("joined", D, default="today"))))
    ws.save_table(None, TableDesign("Loans", (
        key(), FieldDesign("book", I, ref_table="Books", ref_field="id", required=True),
        FieldDesign("member", I, ref_table="Members", ref_field="id", required=True),
        FieldDesign("lent", D, default="today"), FieldDesign("returned", D))))
    authors = {name: ws.insert_row("Authors", {"name": name, "country": country}) for name, country in (
        ("Italo Calvino", "Italy"), ("Elena Ferrante", "Italy"), ("Ursula K. Le Guin", "USA"),
        ("Stanisław Lem", "Poland"), ("Umberto Eco", "Italy"))}
    books = {}
    for title, author, year, pages in (
            ("Invisible Cities", "Italo Calvino", 1972, 165), ("If on a winter's night a traveller", "Italo Calvino", 1979, 260),
            ("My Brilliant Friend", "Elena Ferrante", 2011, 331), ("The Dispossessed", "Ursula K. Le Guin", 1974, 387),
            ("A Wizard of Earthsea", "Ursula K. Le Guin", 1968, 183), ("Solaris", "Stanisław Lem", 1961, 204),
            ("The Name of the Rose", "Umberto Eco", 1980, 502)):
        books[title] = ws.insert_row("Books", {"title": title, "author": str(authors[author]),
                                               "year": str(year), "pages": str(pages)})
    members = [ws.insert_row("Members", {"name": n, "joined": d}) for n, d in (
        ("Giulia Rossi", "2026-01-12"), ("Marco Bianchi", "2026-03-02"), ("Anna Verdi", "2026-05-20"))]
    for book, member, lent, back in (("Solaris", 0, "2026-09-01", "2026-09-15"),
                                     ("Invisible Cities", 1, "2026-09-10", ""),
                                     ("The Dispossessed", 0, "2026-10-02", ""),
                                     ("My Brilliant Friend", 2, "2026-10-05", "2026-10-12")):
        ws.insert_row("Loans", {"book": str(books[book]), "member": str(members[member]),
                                "lent": lent, "returned": back})
    design = QueryDesign(
        ("Authors", "Books"), ws.suggest_joins(["Authors", "Books"]),
        (QueryColumn("Authors", "name", sort="asc"), QueryColumn("Books", "title"),
         QueryColumn("Books", "year", criteria=">= 1970")))
    ws.save_query("Books since 1970", None, ws.build_sql(design), design)
    totals = QueryDesign(
        ("Authors", "Books"), ws.suggest_joins(["Authors", "Books"]),
        (QueryColumn("Authors", "name"), QueryColumn("Books", "pages", total="sum", sort="desc")))
    ws.save_query("Pages per author", None, ws.build_sql(totals), totals)
    ws.save_form("Book", None, ws.default_form(Source("table", "Books")))
    ws.save_form("Member", None, ws.default_form(Source("table", "Members")))
    ws.save_report("Books by author", None, ReportDef(
        "Books", "table", "Books by author", ("title", "year", "pages"), group_by="author",
        sort_by="year", sum_columns=("pages",)))
    ws.save_report("Loans", None, ReportDef("Loans", "table", "Loans", ("book", "member", "lent", "returned"),
                                             sort_by="lent", descending=True, landscape=True))
