"""Tab widget hosting one CodeEditor per open file."""

from PySide6.QtWidgets import QTabWidget


class EditorTabs(QTabWidget):
    """Closable, movable tabs. Title text carries the modified indicator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.setTabBarAutoHide(False)

    def add_editor(self, editor, title, tooltip=""):
        index = self.addTab(editor, title)
        if tooltip:
            self.setTabToolTip(index, tooltip)
        return index

    def set_tab_title(self, index, title):
        self.setTabText(index, title)

    def editor_at(self, index):
        return self.widget(index)
