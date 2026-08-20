from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QInputDialog, QColorDialog, QLabel, QMessageBox,
)
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtCore import Qt, pyqtSignal

from app.core.annotation_store import ClassDef, load_classes, save_classes


class ClassPanel(QWidget):
    class_selected = pyqtSignal(int)  # class_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._classes: list[ClassDef] = []
        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addWidget(QLabel("클래스"))

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._btn_add = QPushButton("+")
        self._btn_add.setToolTip("클래스 추가")
        self._btn_add.setFixedWidth(28)
        self._btn_del = QPushButton("−")
        self._btn_del.setToolTip("선택 클래스 삭제")
        self._btn_del.setFixedWidth(28)
        self._btn_color = QPushButton("색상")
        self._btn_color.setToolTip("색상 변경")
        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(self._btn_del)
        btn_row.addWidget(self._btn_color)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._btn_add.clicked.connect(self._on_add)
        self._btn_del.clicked.connect(self._on_delete)
        self._btn_color.clicked.connect(self._on_change_color)

    # ── 공개 ──────────────────────────────────────────────────────────────────

    def reload(self) -> None:
        self._classes = load_classes()
        self._refresh_list()
        if self._list.count() > 1:
            self._list.setCurrentRow(1)

    @property
    def active_class_id(self) -> int:
        row = self._list.currentRow()
        if 0 <= row < len(self._classes):
            return self._classes[row].class_id
        return 1

    def classes(self) -> list[ClassDef]:
        return list(self._classes)

    # ── 슬롯 ─────────────────────────────────────────────────────────────────

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._classes):
            self.class_selected.emit(self._classes[row].class_id)

    def _on_add(self) -> None:
        name, ok = QInputDialog.getText(self, "클래스 추가", "클래스 이름:")
        if not ok or not name.strip():
            return
        new_id = max((c.class_id for c in self._classes), default=-1) + 1
        from app.core.annotation_store import DEFAULT_PALETTE
        color = DEFAULT_PALETTE[new_id % len(DEFAULT_PALETTE)]
        self._classes.append(ClassDef(new_id, name.strip(), color))
        save_classes(self._classes)
        self._refresh_list()
        self._list.setCurrentRow(len(self._classes) - 1)

    def _on_delete(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        cls = self._classes[row]
        if cls.class_id == 0:
            QMessageBox.warning(self, "삭제 불가", "background 클래스는 삭제할 수 없습니다.")
            return
        self._classes.pop(row)
        save_classes(self._classes)
        self._refresh_list()

    def _on_change_color(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        cls = self._classes[row]
        initial = QColor(*cls.color)
        color = QColorDialog.getColor(initial, self, "색상 선택")
        if not color.isValid():
            return
        self._classes[row].color = (color.red(), color.green(), color.blue())
        save_classes(self._classes)
        self._refresh_list()
        self._list.setCurrentRow(row)

    # ── 내부 ─────────────────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        current_row = self._list.currentRow()
        self._list.clear()
        for cls in self._classes:
            icon = _make_color_icon(cls.color)
            item = QListWidgetItem(icon, f"[{cls.class_id}] {cls.name}")
            self._list.addItem(item)
        if 0 <= current_row < self._list.count():
            self._list.setCurrentRow(current_row)


def _make_color_icon(color: tuple[int, int, int]) -> QIcon:
    px = QPixmap(16, 16)
    px.fill(QColor(*color))
    return QIcon(px)
