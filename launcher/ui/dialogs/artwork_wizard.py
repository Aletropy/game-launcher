"""Choosing a game's artwork, with a live preview of the result.

Steps: find the game on SteamGridDB, then pick a cover, banner, logo and
icon (or a local file, or keep what is there, or remove it), then review.
The right-hand side is the real library row, banner and Journal cover,
drawn from the choices so far; nothing is saved until Apply.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QIcon, QImage, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from launcher.app.context import AppContext
from launcher.domain.models import Game, GameConfig, format_last_played, format_playtime
from launcher.services.artwork import GRID, HERO, ICON, LOGO
from launcher.services.sgdb import STYLES, ArtQuery, ArtResult, GameMatch
from launcher.services.tasks import TaskGroup
from launcher.ui.dialogs.confirm import warn
from launcher.ui.theme import palette
from launcher.ui.widgets.art_source import PreviewArt, scaled_pixmap
from launcher.ui.widgets.hero_banner import HeroBanner
from launcher.ui.widgets.journal import CoverTile
from launcher.ui.widgets.sidebar import letter_tile

_IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp)"


class ArtClient(Protocol):
    """What the wizard needs from SteamGridDB; tests pass a fake."""

    @property
    def configured(self) -> bool: ...

    def find_games(self, query: str) -> list[GameMatch]: ...

    def find_art(self, game_id: int, query: ArtQuery) -> list[ArtResult]: ...

    def download(self, url: str) -> bytes: ...


@dataclass(frozen=True)
class ArtStep:
    art: str
    title: str
    description: str
    #: Thumbnail box in the results grid.
    thumb: QSize


ART_STEPS: tuple[ArtStep, ...] = (
    ArtStep(
        GRID.name,
        "Cover",
        "Portrait art for the Journal shelf, and the library icon when there is no icon.",
        QSize(112, 168),
    ),
    ArtStep(
        HERO.name,
        "Banner",
        "The wide image across the top of the game's page.",
        QSize(256, 83),
    ),
    ArtStep(
        LOGO.name,
        "Logo",
        "Transparent title art drawn over the banner in place of the name.",
        QSize(200, 80),
    ),
    ArtStep(
        ICON.name,
        "Icon",
        "The small square beside the name in the library.",
        QSize(72, 72),
    ),
)
_STEP_TITLES = ("Find game", *(s.title for s in ART_STEPS), "Review")
_STYLE_LABELS = {
    "alternate": "Alternate",
    "blurred": "Blurred",
    "white_logo": "White logo",
    "material": "Material",
    "no_logo": "No logo",
    "official": "Official",
    "white": "White",
    "black": "Black",
    "custom": "Custom",
}


@dataclass
class Choice:
    """What will happen to one art type."""

    kind: str = "keep"  # keep | remove | remote | local
    result: ArtResult | None = None
    path: Path | None = None
    #: The best image so far: a thumbnail until the full one arrives.
    image: QImage | None = None
    #: The full image, ready to store.
    data: bytes | None = None

    @property
    def changes(self) -> bool:
        return self.kind != "keep"

    @property
    def ready(self) -> bool:
        return self.kind in ("keep", "remove") or self.data is not None

    def describe(self) -> str:
        if self.kind == "keep":
            return "Unchanged"
        if self.kind == "remove":
            return "Removed"
        if self.kind == "local" and self.path is not None:
            return f"From {self.path.name}"
        if self.result is not None:
            by = f" by {self.result.author}" if self.result.author else ""
            state = "" if self.data is not None else " — downloading…"
            return f"SteamGridDB, {self.result.size_label}{by}{state}"
        return ""


def decode(data: bytes) -> QImage:
    image = QImage()
    image.loadFromData(data)
    if image.isNull():
        raise ValueError("not an image")
    return image


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------


class FindPage(QWidget):
    """Search SteamGridDB for the game."""

    search_requested = Signal(str)
    game_chosen = Signal(object)
    advance = Signal()

    def __init__(self, name: str, configured: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = QLabel("Which game is it?")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        hint = QLabel(
            "Artwork comes from SteamGridDB. Pick the matching game; the "
            "next steps show everything it has."
            if configured
            else "Add a SteamGridDB API key in Settings → Artwork to search "
            "online. You can still use image files on every step."
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        self.query = QLineEdit(name)
        self.query.setPlaceholderText("Game name")
        self.query.returnPressed.connect(self._search)
        row.addWidget(self.query, stretch=1)
        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self._search)
        row.addWidget(self.search_btn)
        layout.addLayout(row)
        self.query.setEnabled(configured)
        self.search_btn.setEnabled(configured)

        self.results = QListWidget()
        self.results.setObjectName("matchList")
        self.results.currentItemChanged.connect(self._chosen)
        self.results.itemDoubleClicked.connect(lambda _item: self.advance.emit())
        layout.addWidget(self.results, stretch=1)

        self.status = QLabel()
        self.status.setObjectName("hintLabel")
        layout.addWidget(self.status)

    def _search(self) -> None:
        text = self.query.text().strip()
        if text:
            self.search_requested.emit(text)

    def _chosen(self, item: QListWidgetItem | None) -> None:
        if item is not None:
            self.game_chosen.emit(item.data(Qt.ItemDataRole.UserRole))

    def set_matches(self, matches: list[GameMatch], wanted: str) -> None:
        self.results.clear()
        best = None
        for match in matches:
            text = match.label + ("   ✓ verified" if match.verified else "")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, match)
            self.results.addItem(item)
            if best is None and match.name.casefold() == wanted.casefold():
                best = item
        self.status.setText(
            f"{len(matches)} match(es)." if matches else "Nothing found; try another name."
        )
        if best is not None or self.results.count():
            self.results.setCurrentItem(best or self.results.item(0))


class ArtPage(QWidget):
    """Every image SteamGridDB has for one art type, and the other options."""

    query_changed = Signal(object)
    result_chosen = Signal(object)
    file_chosen = Signal(str)
    keep_chosen = Signal()
    remove_chosen = Signal()

    def __init__(self, step: ArtStep, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.step = step
        self._query = ArtQuery(step.art)
        self._items: dict[int, QListWidgetItem] = {}
        #: The game the results belong to, so switching games refetches.
        self.loaded_for: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel(step.title)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        hint = QLabel(step.description)
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.style_combo = QComboBox()
        self.style_combo.addItem("Any style", "")
        for style in STYLES.get(step.art, ()):
            self.style_combo.addItem(_STYLE_LABELS.get(style, style.title()), style)
        self.style_combo.currentIndexChanged.connect(lambda _: self._filters_changed())
        filters.addWidget(self.style_combo)
        self.portrait = QCheckBox("Portrait only")
        self.portrait.setChecked(True)
        self.portrait.setVisible(step.art == GRID.name)
        self.portrait.toggled.connect(lambda _: self._filters_changed())
        filters.addWidget(self.portrait)
        self.nsfw = QCheckBox("Adult")
        self.nsfw.setToolTip("Include images marked not safe for work")
        self.nsfw.toggled.connect(lambda _: self._filters_changed())
        filters.addWidget(self.nsfw)
        self.humor = QCheckBox("Humour")
        self.humor.setToolTip("Include joke images")
        self.humor.toggled.connect(lambda _: self._filters_changed())
        filters.addWidget(self.humor)
        filters.addStretch()
        layout.addLayout(filters)

        self.grid = QListWidget()
        self.grid.setObjectName("artGrid")
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setSpacing(6)
        self.grid.setIconSize(step.thumb)
        # Room for two caption lines under each thumbnail.
        caption_h = self.fontMetrics().lineSpacing() * 2 + 14
        self.grid.setGridSize(
            QSize(max(step.thumb.width(), 120) + 18, step.thumb.height() + caption_h)
        )
        self.grid.setWordWrap(True)
        self.grid.itemClicked.connect(self._clicked)
        layout.addWidget(self.grid, stretch=1)

        actions = QHBoxLayout()
        file_btn = QPushButton("Use a file…")
        file_btn.clicked.connect(self._pick_file)
        actions.addWidget(file_btn)
        keep_btn = QPushButton("Keep current")
        keep_btn.clicked.connect(self._keep)
        actions.addWidget(keep_btn)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._remove)
        actions.addWidget(remove_btn)
        actions.addStretch()
        self.status = QLabel()
        self.status.setObjectName("hintLabel")
        actions.addWidget(self.status)
        self.more_btn = QPushButton("Load more")
        self.more_btn.setVisible(False)
        self.more_btn.clicked.connect(self._more)
        actions.addWidget(self.more_btn)
        layout.addLayout(actions)

    @property
    def query(self) -> ArtQuery:
        return self._query

    def _filters_changed(self) -> None:
        self._query = ArtQuery(
            self.step.art,
            style=str(self.style_combo.currentData() or ""),
            portrait_only=self.portrait.isChecked(),
            nsfw=self.nsfw.isChecked(),
            humor=self.humor.isChecked(),
        )
        self.query_changed.emit(self._query)

    def _more(self) -> None:
        self._query = replace(self._query, page=self._query.page + 1)
        self.more_btn.setEnabled(False)
        self.query_changed.emit(self._query)

    def clear(self, message: str = "") -> None:
        self.grid.clear()
        self._items.clear()
        self.more_btn.setVisible(False)
        self.status.setText(message)

    def add_results(self, results: list[ArtResult], *, first_page: bool) -> None:
        if first_page:
            self.grid.clear()
            self._items.clear()
        placeholder = QPixmap(self.step.thumb)
        placeholder.fill(QColor(palette().raised))
        for result in results:
            if result.id in self._items:
                continue
            caption = result.size_label + (f"\n{result.author}" if result.author else "")
            item = QListWidgetItem(QIcon(placeholder), caption)
            item.setData(Qt.ItemDataRole.UserRole, result)
            tip = [result.size_label]
            if result.style:
                tip.append(f"Style: {_STYLE_LABELS.get(result.style, result.style)}")
            if result.author:
                tip.append(f"By {result.author}")
            tip.append(f"Score {result.score}")
            item.setToolTip("\n".join(t for t in tip if t))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.grid.addItem(item)
            self._items[result.id] = item
        count = len(self._items)
        self.status.setText(
            f"{count} image(s)" if count else "SteamGridDB has none with these filters."
        )
        # A full page suggests there is more; SteamGridDB pages hold 50.
        self.more_btn.setVisible(len(results) >= 50)
        self.more_btn.setEnabled(True)

    def set_thumb(self, result_id: int, image: QImage) -> None:
        item = self._items.get(result_id)
        if item is not None:
            pixmap = scaled_pixmap(
                image, self.step.thumb, expand=False, dpr=self.devicePixelRatioF()
            )
            item.setIcon(QIcon(pixmap))

    def _clicked(self, item: QListWidgetItem) -> None:
        self.result_chosen.emit(item.data(Qt.ItemDataRole.UserRole))

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, f"Choose a {self.step.title.lower()}", "", _IMAGE_FILTER
        )
        if path:
            self.grid.clearSelection()
            self.file_chosen.emit(path)

    def _keep(self) -> None:
        self.grid.clearSelection()
        self.keep_chosen.emit()

    def _remove(self) -> None:
        self.grid.clearSelection()
        self.remove_chosen.emit()


class ReviewPage(QWidget):
    """What Apply will do, one line per art type."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        title = QLabel("Review")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        hint = QLabel(
            "Nothing has been saved yet. Apply stores each image at the size "
            "the library shows it, replacing what was there."
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(10)
        self._rows: dict[str, tuple[QLabel, QLabel]] = {}
        for index, step in enumerate(ART_STEPS):
            thumb = QLabel()
            thumb.setFixedSize(QSize(96, 64))
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setObjectName("reviewThumb")
            name = QLabel(step.title)
            name.setObjectName("gameNameLabel")
            text = QLabel()
            text.setWordWrap(True)
            self._grid.addWidget(thumb, index, 0)
            self._grid.addWidget(name, index, 1)
            self._grid.addWidget(text, index, 2)
            self._rows[step.art] = (thumb, text)
        self._grid.setColumnStretch(2, 1)
        layout.addLayout(self._grid)
        layout.addStretch()

    def show_choices(self, choices: dict[str, Choice], preview: PreviewArt) -> None:
        for art, (thumb, text) in self._rows.items():
            choice = choices[art]
            text.setText(choice.describe())
            image = preview.image(preview.key, art)
            if image is None:
                thumb.setPixmap(QPixmap())
                thumb.setText("none")
            else:
                thumb.setText("")
                thumb.setPixmap(
                    scaled_pixmap(image, QSize(96, 64), expand=False, dpr=self.devicePixelRatioF())
                )


# --------------------------------------------------------------------------
# preview
# --------------------------------------------------------------------------


class RowPreview(QWidget):
    """The game's row in the library list, as the sidebar draws it."""

    def __init__(self, game: Game, art: PreviewArt, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._game = game
        self._art = art
        self.setFixedHeight(58)

    def paintEvent(self, event: QPaintEvent) -> None:
        colours = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(colours.surface))
        row = self.rect().adjusted(8, 6, -8, -6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colours.selection or colours.raised))
        painter.drawRoundedRect(row, 6, 6)

        size = QSize(34, 34)
        dpr = self.devicePixelRatioF()
        name = self._game.name
        icon = (
            self._art.pixmap(name, ICON.name, size, dpr=dpr)
            or self._art.pixmap(name, GRID.name, size, expand=True, dpr=dpr)
            or letter_tile(name, size, dpr)
        )
        top = row.top() + (row.height() - size.height()) // 2
        # Draw the centre of an expanded crop, as the list's icon does.
        logical_w = icon.width() / icon.devicePixelRatio()
        logical_h = icon.height() / icon.devicePixelRatio()
        painter.save()
        painter.setClipRect(row.left() + 8, top, size.width(), size.height())
        painter.drawPixmap(
            round(row.left() + 8 - (logical_w - size.width()) / 2),
            round(top - (logical_h - size.height()) / 2),
            icon,
        )
        painter.restore()

        text_x = row.left() + 8 + size.width() + 10
        painter.setPen(QColor(colours.fg_bright))
        painter.drawText(text_x, row.top() + 19, name)
        painter.setPen(QColor(colours.fg_muted))
        detail = "  ·  ".join(
            p
            for p in (
                format_playtime(self._game.playtime_seconds),
                format_last_played(self._game.last_played),
            )
            if p
        )
        painter.drawText(text_x, row.top() + 37, detail or "never played")


class IconSizes(QWidget):
    """The icon at the sizes the launcher uses it, to judge sharpness."""

    _SIZES = (64, 44, 34, 26)

    def __init__(self, game: Game, art: PreviewArt, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._game = game
        self._art = art
        self.setFixedHeight(76)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dpr = self.devicePixelRatioF()
        x = 0
        for side in self._SIZES:
            size = QSize(side, side)
            name = self._game.name
            pixmap = (
                self._art.pixmap(name, ICON.name, size, dpr=dpr)
                or self._art.pixmap(name, GRID.name, size, expand=True, dpr=dpr)
                or letter_tile(name, size, dpr)
            )
            logical_w = pixmap.width() / pixmap.devicePixelRatio()
            logical_h = pixmap.height() / pixmap.devicePixelRatio()
            y = (self._SIZES[0] - side) // 2 + 4
            painter.save()
            painter.setClipRect(x, y, side, side)
            painter.drawPixmap(
                round(x - (logical_w - side) / 2), round(y - (logical_h - side) / 2), pixmap
            )
            painter.restore()
            x += side + 14


class PreviewPanel(QFrame):
    """The library, banner and Journal, drawn from the choices so far."""

    def __init__(self, game: Game, art: PreviewArt, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("previewPanel")
        self.setFixedWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        def section(text: str) -> None:
            label = QLabel(text.upper())
            label.setObjectName("journalSection")
            layout.addWidget(label)

        section("In the library")
        self._row = RowPreview(game, art)
        layout.addWidget(self._row)
        self._banner = HeroBanner(art, height=150)
        subtitle = "  ·  ".join(
            p
            for p in (
                format_playtime(game.playtime_seconds),
                format_last_played(game.last_played),
            )
            if p
        )
        self._banner.set_game(game.name, game.name, subtitle)
        layout.addWidget(self._banner)

        section("In the Journal")
        journal_row = QHBoxLayout()
        self._cover = CoverTile(
            game, art, format_last_played(game.last_played) or "never played"
        )
        journal_row.addWidget(self._cover)
        icon_box = QVBoxLayout()
        icon_label = QLabel("Icon at 64, 44, 34 and 26 px")
        icon_label.setObjectName("hintLabel")
        icon_box.addWidget(icon_label)
        self._icons = IconSizes(game, art)
        icon_box.addWidget(self._icons)
        icon_box.addStretch()
        journal_row.addLayout(icon_box, stretch=1)
        layout.addLayout(journal_row)
        layout.addStretch()

    def refresh(self) -> None:
        self._banner.refresh()
        for widget in (self._row, self._cover, self._icons):
            widget.update()


# --------------------------------------------------------------------------
# the wizard
# --------------------------------------------------------------------------


@dataclass
class _Pending:
    """What an outstanding task was for."""

    kind: str  # games | art | thumb | full
    art: str = ""
    result_id: int = 0
    first_page: bool = True
    extra: dict = field(default_factory=dict)


class ArtworkWizard(QDialog):
    """Find, choose and preview a game's artwork, then apply it."""

    #: Emitted after Apply stored something; carries the game name.
    applied = Signal(str)

    def __init__(
        self,
        context: AppContext,
        game_name: str,
        parent: QWidget | None = None,
        *,
        client: ArtClient | None = None,
    ) -> None:
        super().__init__(parent)
        self._ctx = context
        self._name = game_name
        self._client: ArtClient = client or context.sgdb
        self._game = context.games.get(game_name) or Game(
            config=GameConfig(name=game_name), conf_path=Path()
        )
        self._art = PreviewArt(context.artwork, game_name)
        self._choices: dict[str, Choice] = {s.art: Choice() for s in ART_STEPS}
        self._match: GameMatch | None = None
        self._pending: dict[int, _Pending] = {}
        self._tasks = TaskGroup(self)
        self._tasks.finished.connect(self._on_done)
        self._tasks.failed.connect(self._on_failed)

        self.setWindowTitle(f"Artwork — {game_name}")
        self.resize(1220, 760)
        self._setup_ui()
        self._go(0)
        if self._client.configured:
            self._search(game_name)

    # -- layout --------------------------------------------------------

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 14)
        outer.setSpacing(12)

        steps = QHBoxLayout()
        steps.setSpacing(6)
        self._step_group = QButtonGroup(self)
        self._step_buttons: list[QPushButton] = []
        for index, title in enumerate(_STEP_TITLES):
            button = QPushButton(f"{index + 1}  {title}")
            button.setObjectName("stepPill")
            button.setCheckable(True)
            self._step_group.addButton(button, index)
            self._step_buttons.append(button)
            steps.addWidget(button)
        steps.addStretch()
        self._step_group.idClicked.connect(self._go)
        outer.addLayout(steps)

        body = QHBoxLayout()
        body.setSpacing(18)
        self._pages = QStackedWidget()
        self._find = FindPage(self._name, self._client.configured)
        self._find.search_requested.connect(self._search)
        self._find.game_chosen.connect(self._choose_game)
        self._find.advance.connect(lambda: self._go(1))
        self._pages.addWidget(self._find)

        self._art_pages: dict[str, ArtPage] = {}
        for step in ART_STEPS:
            page = ArtPage(step)
            page.query_changed.connect(lambda q, a=step.art: self._fetch_art(a, q))
            page.result_chosen.connect(lambda r, a=step.art: self._choose_result(a, r))
            page.file_chosen.connect(lambda p, a=step.art: self._choose_file(a, p))
            page.keep_chosen.connect(lambda a=step.art: self._set_choice(a, Choice()))
            page.remove_chosen.connect(
                lambda a=step.art: self._set_choice(a, Choice(kind="remove"))
            )
            self._pages.addWidget(page)
            self._art_pages[step.art] = page

        self._review = ReviewPage()
        self._pages.addWidget(self._review)
        body.addWidget(self._pages, stretch=1)

        self._preview = PreviewPanel(self._game, self._art)
        body.addWidget(self._preview)
        outer.addLayout(body, stretch=1)

        footer = QHBoxLayout()
        self._status = QLabel()
        self._status.setObjectName("hintLabel")
        footer.addWidget(self._status, stretch=1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self._back = QPushButton("Back")
        self._back.clicked.connect(lambda: self._go(self._pages.currentIndex() - 1))
        footer.addWidget(self._back)
        self._next = QPushButton("Next")
        self._next.clicked.connect(lambda: self._go(self._pages.currentIndex() + 1))
        footer.addWidget(self._next)
        self._apply = QPushButton("Apply")
        self._apply.setObjectName("playButton")
        self._apply.clicked.connect(self._apply_choices)
        footer.addWidget(self._apply)
        outer.addLayout(footer)

    # -- navigation ----------------------------------------------------

    def _go(self, index: int) -> None:
        index = max(0, min(index, self._pages.count() - 1))
        self._pages.setCurrentIndex(index)
        button = self._step_group.button(index)
        if button is not None:
            button.setChecked(True)
        widget = self._pages.currentWidget()
        if isinstance(widget, ArtPage):
            self._load_page(widget)
        if widget is self._review:
            self._review.show_choices(self._choices, self._art)
        self._update_footer()

    def _update_footer(self) -> None:
        index = self._pages.currentIndex()
        self._back.setEnabled(index > 0)
        self._next.setVisible(index < self._pages.count() - 1)
        changes = [c for c in self._choices.values() if c.changes]
        waiting = sum(1 for c in changes if not c.ready)
        self._apply.setEnabled(bool(changes) and not waiting)
        for step_index, step in enumerate(ART_STEPS, start=1):
            done = self._choices[step.art].changes
            self._step_buttons[step_index].setText(
                f"{'✓' if done else step_index + 1}  {step.title}"
            )
        if waiting:
            self._status.setText(f"Downloading {waiting} full-size image(s)…")
        elif changes:
            self._status.setText(f"{len(changes)} change(s) ready to apply.")
        elif self._match is not None:
            self._status.setText(f"SteamGridDB: {self._match.label}")
        else:
            self._status.setText("")

    # -- searching -----------------------------------------------------

    def _submit(self, pending: _Pending, fn: object, *args: object) -> None:
        token = self._tasks.submit(fn, *args)  # type: ignore[arg-type]
        self._pending[token] = pending

    def _search(self, text: str) -> None:
        self._find.status.setText("Searching…")
        self._submit(_Pending("games"), self._client.find_games, text)

    def _choose_game(self, match: GameMatch) -> None:
        if self._match is not None and match.id == self._match.id:
            return
        self._match = match
        for page in self._art_pages.values():
            page.loaded_for = None
            page.clear()
        self._update_footer()

    def _load_page(self, page: ArtPage) -> None:
        if self._match is None:
            page.clear(
                "Find the game first to see SteamGridDB's images."
                if self._client.configured
                else ""
            )
            return
        if page.loaded_for != self._match.id:
            page.loaded_for = self._match.id
            self._fetch_art(page.step.art, page.query)

    def _fetch_art(self, art: str, query: ArtQuery) -> None:
        if self._match is None:
            return
        page = self._art_pages[art]
        if query.page == 0:
            page.clear("Loading…")
        self._submit(
            _Pending("art", art=art, first_page=query.page == 0),
            self._client.find_art,
            self._match.id,
            query,
        )

    # -- choosing ------------------------------------------------------

    def _choose_result(self, art: str, result: ArtResult) -> None:
        thumb = None
        item = self._art_pages[art]._items.get(result.id)
        if item is not None:
            thumb = item.data(Qt.ItemDataRole.UserRole + 1)
        self._set_choice(art, Choice(kind="remote", result=result, image=thumb))
        self._submit(
            _Pending("full", art=art, result_id=result.id),
            self._download_full,
            result.url,
        )

    def _download_full(self, url: str) -> tuple[bytes, QImage]:
        data = self._client.download(url)
        return data, decode(data)

    def _choose_file(self, art: str, path: str) -> None:
        try:
            data = Path(path).read_bytes()
            image = decode(data)
        except (OSError, ValueError) as e:
            warn(self, "Artwork", f"Could not read that image:\n{e}")
            return
        self._set_choice(art, Choice(kind="local", path=Path(path), image=image, data=data))

    def _set_choice(self, art: str, choice: Choice) -> None:
        self._choices[art] = choice
        if choice.kind == "keep":
            self._art.reset(art)
        elif choice.kind == "remove":
            self._art.set(art, None)
        elif choice.image is not None:
            self._art.set(art, choice.image)
        self._preview.refresh()
        self._update_footer()

    # -- task results --------------------------------------------------

    def _on_done(self, token: int, result: object) -> None:
        pending = self._pending.pop(token, None)
        if pending is None:
            return
        if pending.kind == "games":
            self._find.set_matches(list(result), self._name)  # type: ignore[call-overload]
        elif pending.kind == "art":
            results: list[ArtResult] = list(result)  # type: ignore[call-overload]
            self._art_pages[pending.art].add_results(results, first_page=pending.first_page)
            for item in results:
                self._submit(
                    _Pending("thumb", art=pending.art, result_id=item.id),
                    self._thumb,
                    item.thumb,
                )
        elif pending.kind == "thumb":
            image = result
            if isinstance(image, QImage):
                page = self._art_pages[pending.art]
                page.set_thumb(pending.result_id, image)
                entry = page._items.get(pending.result_id)
                if entry is not None:
                    entry.setData(Qt.ItemDataRole.UserRole + 1, image)
                choice = self._choices[pending.art]
                if (
                    choice.kind == "remote"
                    and choice.result is not None
                    and choice.result.id == pending.result_id
                    and choice.data is None
                ):
                    choice.image = image
                    self._set_choice(pending.art, choice)
        elif pending.kind == "full" and isinstance(result, tuple):
            choice = self._choices[pending.art]
            if (
                choice.kind == "remote"
                and choice.result is not None
                and choice.result.id == pending.result_id
            ):
                data, image = result
                choice.data, choice.image = bytes(data), QImage(image)
                self._set_choice(pending.art, choice)

    def _thumb(self, url: str) -> QImage:
        return decode(self._client.download(url))

    def _on_failed(self, token: int, message: str) -> None:
        pending = self._pending.pop(token, None)
        if pending is None:
            return
        if pending.kind == "games":
            self._find.status.setText(f"Search failed: {message}")
        elif pending.kind == "art":
            self._art_pages[pending.art].clear(f"Could not load: {message}")
        elif pending.kind == "full":
            choice = self._choices[pending.art]
            if choice.result is not None and choice.result.id == pending.result_id:
                self._set_choice(pending.art, Choice())
                warn(self, "Artwork", f"Could not download that image:\n{message}")

    # -- applying ------------------------------------------------------

    def _apply_choices(self) -> None:
        artwork = self._ctx.artwork
        notes: list[str] = []
        try:
            for art, choice in self._choices.items():
                if choice.kind == "remove":
                    artwork.remove(self._name, art)
            for step in ART_STEPS:
                choice = self._choices[step.art]
                if choice.data is None or choice.kind not in ("remote", "local"):
                    continue
                stored = artwork.store(self._name, step.art, choice.data)
                if stored.parent.name != step.art:
                    notes.append(
                        f"The {step.title.lower()} is shaped like a "
                        f"{stored.parent.name}, so it was saved as one."
                    )
        except OSError as e:
            warn(self, "Artwork", f"Could not save the artwork:\n{e}")
            return
        artwork.invalidate(self._name)
        self.applied.emit(self._name)
        if notes:
            warn(self, "Artwork", "\n".join(notes))
        self.accept()

    # -- lifetime ------------------------------------------------------

    def _discard(self) -> None:
        self._tasks.cancel_all()
        self._pending.clear()

    def reject(self) -> None:
        self._discard()
        super().reject()

    def accept(self) -> None:
        self._discard()
        super().accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._discard()
        super().closeEvent(event)
