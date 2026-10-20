import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from folio.application.workspace import Source
from folio.demo import build_library
from folio.presentation.qt_app import create_application


@pytest.fixture(scope="module")
def app():
    return create_application(["test"])


@pytest.fixture
def window(app, services):
    from folio.presentation.main_window import MainWindow
    w = MainWindow(services)
    w.resize(1320, 840)
    w.show()
    yield w
    w.close()
    app.processEvents()


def open_sample(window, tmp_path):
    window.ws.create(str(tmp_path / "lib.folio"))
    build_library(window.ws)
    window.tables.refresh("Books")
    window.queries.refresh()
    window.forms.refresh()
    window.reports.refresh()


# first: every window leaves theme connections behind, and switching themes visits them all
def test_dark_theme_renders(window, tmp_path, app):
    from folio.presentation import theme
    open_sample(window, tmp_path)
    theme.manager().set_mode("dark")
    try:
        for page in range(len(window.PAGES)):
            window.show_page(page)
            app.processEvents()
    finally:
        theme.manager().set_mode("system")


def test_pages_are_locked_until_a_database_is_open(window, tmp_path):
    assert not window.sidebar.group.button(window.TABLES).isEnabled()
    window.show_page(window.TABLES)
    assert window.stack.currentIndex() == window.HOME
    open_sample(window, tmp_path)
    assert window.sidebar.group.button(window.TABLES).isEnabled()
    assert "lib" in window.windowTitle()


def test_every_page_shows_the_sample(window, tmp_path, app):
    open_sample(window, tmp_path)
    for page in range(len(window.PAGES)):
        window.show_page(page)
        app.processEvents()
    assert window.tables.items.list.count() == 4
    assert window.queries.items.list.count() == 2
    assert window.forms.items.list.count() == 2
    assert window.reports.items.list.count() == 2


def test_datasheet_edits_and_new_rows(window, tmp_path, app):
    open_sample(window, tmp_path)
    window.tables.open_table("Authors")
    model = window.tables.sheet.model
    assert model.rowCount() == 6  # five authors and the empty row for a new one
    name = model.index(0, 1)
    assert model.setData(name, "Italo C.")
    app.processEvents()
    assert window.ws.page(Source("table", "Authors")).rows[0].values[1] == "Italo C."
    assert not model.setData(model.index(0, 2), "x") is False  # text field accepts anything
    # a new row: the country alone can't make a row (name is required) …
    new = model.rowCount() - 1
    model.setData(model.index(new, 2), "Spain")
    assert model.pending == {"country": "Spain"}
    assert window.ws.table("Authors").row_count == 5
    # … until the name is filled in too
    model.setData(model.index(new, 1), "Cervantes")
    assert model.pending == {} and window.ws.table("Authors").row_count == 6


def test_a_bad_value_is_refused_with_a_message(window, tmp_path, app):
    open_sample(window, tmp_path)
    window.tables.open_table("Books")
    model = window.tables.sheet.model
    seen = []
    model.problem.connect(seen.append)
    assert model.setData(model.index(0, 3), "nineteen") is False
    assert seen and window.ws.page(Source("table", "Books")).rows[0].values[3] == 1972


def test_checkbox_and_lookup_columns(window, tmp_path, app):
    open_sample(window, tmp_path)
    window.tables.open_table("Books")
    model = window.tables.sheet.model
    assert model.data(model.index(0, 5), Qt.CheckStateRole) == Qt.Checked
    model.setData(model.index(0, 5), Qt.Unchecked, Qt.CheckStateRole)
    app.processEvents()
    assert model.data(model.index(0, 5), Qt.CheckStateRole) == Qt.Unchecked
    assert model.data(model.index(0, 2), Qt.DisplayRole) == "Italo Calvino"  # a name, not an id


def test_search_sort_and_undo_through_the_sheet(window, tmp_path, app):
    open_sample(window, tmp_path)
    window.tables.open_table("Books")
    sheet = window.tables.sheet
    sheet.model.set_search("Earthsea")
    assert sheet.model.total == 1
    sheet.model.set_search("")
    sheet.model.sort(3, Qt.DescendingOrder)
    assert sheet.model.rows[0].values[3] == 2011
    sheet.model.setData(sheet.model.index(0, 1), "Changed")
    app.processEvents()
    assert window.ws.can_undo
    sheet.undo()
    app.processEvents()
    assert sheet.model.rows[0].values[1] == "My Brilliant Friend"


def test_the_designer_adds_a_field_and_a_table(window, tmp_path, app):
    open_sample(window, tmp_path)
    window.tables.open_table("Authors")
    designer = window.tables.designer
    designer.add_field()
    row = designer.grid.rowCount() - 1
    designer.grid.item(row, 0).setText("born")
    designer.apply()
    assert [f.name for f in window.ws.table("Authors").fields][-1] == "born"
    window.tables.new_table()
    designer.name.setText("Notes")
    designer.grid.item(1, 0).setText("body")
    designer.apply()
    assert "Notes" in window.ws.table_names()
    assert window.tables.items.current() == "Notes"


def test_designer_reports_a_mistake_instead_of_crashing(window, tmp_path, app):
    open_sample(window, tmp_path)
    window.tables.open_table("Authors")
    designer = window.tables.designer
    designer.name.setText("")
    designer.apply()
    assert designer.message.text() and not designer.message.isHidden()


def test_query_designer_runs_and_saves(window, tmp_path, app):
    open_sample(window, tmp_path)
    window.queries.items.list.setCurrentRow(0)
    editor = window.queries.editor
    assert "WHERE" in editor.sql.toPlainText()
    assert editor.result.model.total == 5
    editor.grid.item(2, 4).setText("> 1975")
    editor.run()
    assert editor.result.model.total == 3
    window.queries.save()
    assert ">" in window.ws.query("Books since 1970").sql


def test_new_query_from_scratch_and_sql_mode(window, tmp_path, app):
    open_sample(window, tmp_path)
    q = window.queries
    q.new_query()
    editor = q.editor
    editor.tables = ["Authors"]
    editor._refresh_pickers()
    item = editor.fields.topLevelItem(0).child(2)  # Authors.name
    editor._field_double_clicked(item, 0)
    editor.run()
    assert editor.result.model.total == 5
    editor.mode.set_value("sql")
    editor._mode_changed("sql")
    editor.sql.setPlainText("SELECT COUNT(*) AS n FROM Books")
    editor.run()
    assert editor.raw and editor.result.model.rows[0].values == (7,)
    q.name.setText("Count")
    q.save()
    assert "Count" in window.ws.queries() and window.ws.query("Count").design is None


def test_a_bad_query_shows_its_error(window, tmp_path, app):
    open_sample(window, tmp_path)
    window.queries.new_query()
    editor = window.queries.editor
    editor.mode.set_value("sql")
    editor._mode_changed("sql")
    editor.sql.setPlainText("SELECT nope FROM Books")
    editor.run()
    assert not editor.error.isHidden()


def test_form_navigation_and_editing(window, tmp_path, app):
    open_sample(window, tmp_path)
    forms = window.forms
    forms.items.list.setCurrentRow(0)
    view = forms.view
    assert view.total == 7 and view.index == 0
    view.go(2)
    assert view.editors["title"].text() == "My Brilliant Friend"
    view.editors["title"].setText("Brilliant")
    view._commit_field("title")
    assert window.ws.page(Source("table", "Books")).rows[2].values[1] == "Brilliant"
    view.start_adding()
    view.editors["pages"].setText("12")
    view.commit_new()  # the title is required
    assert not view.message.isHidden() and view.adding
    view.editors["title"].setText("New book")
    view.commit_new()
    assert not view.adding and view.total == 8 and view.editors["title"].text() == "New book"


def test_form_design_changes_the_fields(window, tmp_path, app):
    open_sample(window, tmp_path)
    forms = window.forms
    forms.items.list.setCurrentRow(0)
    forms.mode.set_value("design")
    forms._mode("design")
    tree = forms.designer.tree
    tree.topLevelItem(0).setCheckState(0, Qt.Unchecked)
    tree.topLevelItem(1).setText(2, "Name of the book")
    forms.save_design()
    assert [f.name for f in window.ws.form("Book").fields][0] == "title"
    assert window.ws.form("Book").fields[0].label == "Name of the book"
    assert "title" in forms.view.editors and "id" not in forms.view.editors


def test_report_preview_and_pdf(window, tmp_path, app):
    open_sample(window, tmp_path)
    reports = window.reports
    reports.items.list.setCurrentRow(0)
    assert "Italo Calvino" in reports.html and "Grand total" in reports.html
    out = tmp_path / "r.pdf"
    from folio.presentation.views.reports import write_pdf
    write_pdf(str(out), reports.html, False)
    assert out.read_bytes().startswith(b"%PDF")
    reports.mode.set_value("design")
    reports._mode("design")
    reports.designer.group.setCurrentIndex(0)
    reports.save_design()
    assert window.ws.report("Books by author").group_by == ""


def test_relationships_page_draws_every_table_and_link(window, tmp_path, app):
    open_sample(window, tmp_path)
    window.show_page(window.RELATIONS)
    page = window.relations
    assert set(page.items) == {"Authors", "Books", "Members", "Loans"}
    assert len([i for i in page.scene.items() if i.__class__.__name__ == "LinkItem"]) == 3
    page.items["Books"].setPos(500, 40)
    page.save_positions()
    assert window.ws.layout()["Books"] == [500, 40]
    page._set_link("Loans", "member", "", "", "NO ACTION")  # remove one link
    assert len(window.ws.relationships()) == 2


def test_csv_dialog_imports(window, tmp_path, app):
    open_sample(window, tmp_path)
    src = tmp_path / "x.csv"
    src.write_text("a,b\n1,hello\n2,world\n", encoding="utf-8")
    from folio.presentation.views.tables import ImportDialog
    dialog = ImportDialog(window.ws, str(src), None, window)
    dialog._import()
    assert dialog.result_name == "x" and window.ws.table("x").row_count == 2


def test_access_files_are_converted_from_the_window(window, tmp_path, access, monkeypatch):
    import datetime as dt
    from folio.application.ports import AccessColumn, AccessDatabase, AccessTable
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    access.database = AccessDatabase((AccessTable(
        "Clients", (AccessColumn("Name", "text"), AccessColumn("Since", "date")),
        (("Ada", "2020-01-01"),)),))
    target = tmp_path / "converted.folio"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a[2]))
    window.open_file(str(tmp_path / "old.accdb"))
    assert window.ws.path == str(target) and window.ws.table("Clients").row_count == 1
    assert shown and "1 table" in shown[0]


def test_a_database_is_exported_to_access_from_the_window(window, tmp_path, access, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    open_sample(window, tmp_path)
    target = tmp_path / "lib.accdb"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append(a[2]))
    window.export_access()
    assert access.written and access.written[0][0] == str(target)
    assert "4 tables" in shown[0] and "queries" in shown[0]  # it says what doesn't travel
