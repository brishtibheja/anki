# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from concurrent.futures import Future
from operator import itemgetter
from typing import Any, List, Optional, Sequence

import aqt.clayout
from anki import stdmodels
from anki.lang import without_unicode_isolation
from anki.models import NoteType, NoteTypeID, NoteTypeNameIDUseCount
from anki.notes import Note
from aqt import AnkiQt, gui_hooks
from aqt.qt import *
from aqt.utils import (
    HelpPage,
    askUser,
    disable_help_button,
    getText,
    maybeHideClose,
    openHelp,
    restoreGeom,
    saveGeom,
    showInfo,
    tr,
)


class Models(QDialog):
    def __init__(
        self,
        mw: AnkiQt,
        parent: Optional[QWidget] = None,
        fromMain: bool = False,
        selected_notetype_id: Optional[NoteTypeID] = None,
    ):
        self.mw = mw
        parent = parent or mw
        self.fromMain = fromMain
        self.selected_notetype_id = selected_notetype_id
        QDialog.__init__(self, parent, Qt.Window)
        self.col = mw.col.weakref()
        assert self.col
        self.mm = self.col.models
        self.mw.checkpoint(tr.notetypes_note_types())
        self.form = aqt.forms.models.Ui_Dialog()
        self.form.setupUi(self)
        qconnect(
            self.form.buttonBox.helpRequested,
            lambda: openHelp(HelpPage.ADDING_A_NOTE_TYPE),
        )
        self.models: List[NoteTypeNameIDUseCount] = []
        self.setupModels()
        restoreGeom(self, "models")
        self.exec_()

    # Models
    ##########################################################################

    def maybe_select_provided_notetype(self) -> None:
        if not self.selected_notetype_id:
            self.form.modelsList.setCurrentRow(0)
            return
        for i, m in enumerate(self.models):
            if m.id == self.selected_notetype_id:
                self.form.modelsList.setCurrentRow(i)
                break

    def setupModels(self) -> None:
        self.model = None
        f = self.form
        box = f.buttonBox

        default_buttons = [
            (tr.actions_add(), self.onAdd),
            (tr.actions_rename(), self.onRename),
            (tr.actions_delete(), self.onDelete),
        ]

        if self.fromMain:
            default_buttons.extend(
                [
                    (tr.notetypes_fields(), self.onFields),
                    (tr.notetypes_cards(), self.onCards),
                ]
            )

        default_buttons.append((tr.notetypes_options(), self.onAdvanced))

        for label, func in gui_hooks.models_did_init_buttons(default_buttons, self):
            button = box.addButton(label, QDialogButtonBox.ActionRole)
            qconnect(button.clicked, func)

        qconnect(f.modelsList.itemDoubleClicked, self.onRename)

        def on_done(fut: Future) -> None:
            self.updateModelsList(fut.result())
            self.maybe_select_provided_notetype()

        self.mw.taskman.with_progress(self.col.models.all_use_counts, on_done, self)
        maybeHideClose(box)

    def onRename(self) -> None:
        nt = self.current_notetype()
        txt = getText(tr.actions_new_name(), default=nt["name"])
        name = txt[0].replace('"', "")
        if txt[1] and name:
            nt["name"] = name
            self.saveAndRefresh(nt)

    def saveAndRefresh(self, nt: NoteType) -> None:
        def save() -> Sequence[NoteTypeNameIDUseCount]:
            self.mm.save(nt)
            return self.col.models.all_use_counts()

        def on_done(fut: Future) -> None:
            self.updateModelsList(fut.result())

        self.mw.taskman.with_progress(save, on_done, self)

    def updateModelsList(self, notetypes: List[NoteTypeNameIDUseCount]) -> None:
        row = self.form.modelsList.currentRow()
        if row == -1:
            row = 0
        self.form.modelsList.clear()

        self.models = notetypes
        for m in self.models:
            mUse = tr.browsing_note_count(count=m.use_count)
            item = QListWidgetItem(f"{m.name} [{mUse}]")
            self.form.modelsList.addItem(item)
        self.form.modelsList.setCurrentRow(row)

    def current_notetype(self) -> NoteType:
        row = self.form.modelsList.currentRow()
        return self.mm.get(self.models[row].id)

    def onAdd(self) -> None:
        m = AddModel(self.mw, self).get()
        if m:
            txt = getText(tr.actions_name(), default=m["name"])[0].replace('"', "")
            if txt:
                m["name"] = txt
            self.saveAndRefresh(m)

    def onDelete(self) -> None:
        if len(self.models) < 2:
            showInfo(tr.notetypes_please_add_another_note_type_first(), parent=self)
            return
        idx = self.form.modelsList.currentRow()
        if self.models[idx].use_count:
            msg = tr.notetypes_delete_this_note_type_and_all()
        else:
            msg = tr.notetypes_delete_this_unused_note_type()
        if not askUser(msg, parent=self):
            return

        self.col.modSchema(check=True)

        nt = self.current_notetype()

        def save() -> Sequence[NoteTypeNameIDUseCount]:
            self.mm.rem(nt)
            return self.col.models.all_use_counts()

        def on_done(fut: Future) -> None:
            self.updateModelsList(fut.result())

        self.mw.taskman.with_progress(save, on_done, self)

    def onAdvanced(self) -> None:
        nt = self.current_notetype()
        d = QDialog(self)
        disable_help_button(d)
        frm = aqt.forms.modelopts.Ui_Dialog()
        frm.setupUi(d)
        frm.latexsvg.setChecked(nt.get("latexsvg", False))
        frm.latexHeader.setText(nt["latexPre"])
        frm.latexFooter.setText(nt["latexPost"])
        d.setWindowTitle(
            without_unicode_isolation(tr.actions_options_for(val=nt["name"]))
        )
        qconnect(frm.buttonBox.helpRequested, lambda: openHelp(HelpPage.LATEX))
        restoreGeom(d, "modelopts")
        gui_hooks.models_advanced_will_show(d)
        d.exec_()
        saveGeom(d, "modelopts")
        nt["latexsvg"] = frm.latexsvg.isChecked()
        nt["latexPre"] = str(frm.latexHeader.toPlainText())
        nt["latexPost"] = str(frm.latexFooter.toPlainText())
        self.saveAndRefresh(nt)

    def _tmpNote(self) -> Note:
        nt = self.current_notetype()
        return Note(self.col, nt)

    def onFields(self) -> None:
        from aqt.fields import FieldDialog

        FieldDialog(self.mw, self.current_notetype(), parent=self)

    def onCards(self) -> None:
        from aqt.clayout import CardLayout

        n = self._tmpNote()
        CardLayout(self.mw, n, ord=0, parent=self, fill_empty=True)

    # Cleanup
    ##########################################################################

    # need to flush model on change or reject

    def reject(self) -> None:
        self.mw.reset()
        saveGeom(self, "models")
        QDialog.reject(self)


class AddModel(QDialog):
    model: Optional[NoteType]

    def __init__(self, mw: AnkiQt, parent: Optional[QWidget] = None) -> None:
        self.parent_ = parent or mw
        self.mw = mw
        self.col = mw.col
        QDialog.__init__(self, self.parent_, Qt.Window)
        self.model = None
        self.dialog = aqt.forms.addmodel.Ui_Dialog()
        self.dialog.setupUi(self)
        disable_help_button(self)
        # standard models
        self.models = []
        for (name, func) in stdmodels.get_stock_notetypes(self.col):
            item = QListWidgetItem(tr.notetypes_add(val=name))
            self.dialog.models.addItem(item)
            self.models.append((True, func))
        # add copies
        for m in sorted(self.col.models.all(), key=itemgetter("name")):
            item = QListWidgetItem(tr.notetypes_clone(val=m["name"]))
            self.dialog.models.addItem(item)
            self.models.append((False, m))  # type: ignore
        self.dialog.models.setCurrentRow(0)
        # the list widget will swallow the enter key
        s = QShortcut(QKeySequence("Return"), self)
        qconnect(s.activated, self.accept)
        # help
        qconnect(self.dialog.buttonBox.helpRequested, self.onHelp)

    def get(self) -> Any:
        self.exec_()
        return self.model

    def reject(self) -> None:
        QDialog.reject(self)

    def accept(self) -> None:
        (isStd, model) = self.models[self.dialog.models.currentRow()]
        if isStd:
            # create
            self.model = model(self.col)
        else:
            # add copy to deck
            self.model = self.mw.col.models.copy(model)
            self.mw.col.models.setCurrent(self.model)
        QDialog.accept(self)

    def onHelp(self) -> None:
        openHelp(HelpPage.ADDING_A_NOTE_TYPE)
