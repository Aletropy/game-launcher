"""The Journal: what you have been playing, drawn from your own history.

Replaces the old card grid. The library already lists every game; this
view is about time instead - what to pick up again, how much you have
played, and when.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from launcher.domain import journal
from launcher.domain.journal import Day, Session
from launcher.domain.models import Game, format_last_played
from launcher.services.artwork import GRID, ICON, ArtworkService
from launcher.ui.theme import palette
from launcher.ui.widgets.art_source import ArtSource
from launcher.ui.widgets.hero_banner import HeroBanner

_WEEKS = 26
_CELL = 14
_GAP = 3
_SHELF_LIMIT = 10
_TOP_LIMIT = 5


def _heat_colours() -> list[QColor]:
    """Five steps from an empty cell to the accent colour."""
    empty = QColor(palette().raised)
    accent = QColor(palette().accent_hover)
    steps = [empty]
    for i in range(1, 5):
        t = 0.28 + 0.18 * i
        steps.append(
            QColor(
                round(empty.red() + (accent.red() - empty.red()) * t),
                round(empty.green() + (accent.green() - empty.green()) * t),
                round(empty.blue() + (accent.blue() - empty.blue()) * t),
            )
        )
    return steps


def _section(title: str) -> QLabel:
    label = QLabel(title.upper())
    label.setObjectName("journalSection")
    return label


class StatTile(QFrame):
    """One headline number with a caption."""

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statTile")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        self._value = QLabel("—")
        self._value.setObjectName("statValue")
        self._detail = QLabel("")
        self._detail.setObjectName("hintLabel")
        caption_label = QLabel(caption)
        caption_label.setObjectName("statCaption")
        layout.addWidget(caption_label)
        layout.addWidget(self._value)
        layout.addWidget(self._detail)

    def set(self, value: str, detail: str = "") -> None:
        self._value.setText(value)
        self._detail.setText(detail)
        self._detail.setVisible(bool(detail))


class Heatmap(QWidget):
    """A calendar of how much was played each day, GitHub style."""

    day_clicked = Signal(object)

    _LEFT = 30
    _TOP = 18

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid: list[list[Day | None]] = []
        self._peak = 0
        self.setMouseTracking(True)
        width = self._LEFT + _WEEKS * (_CELL + _GAP)
        height = self._TOP + 7 * (_CELL + _GAP) + 26
        self.setMinimumSize(width, height)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def set_sessions(self, sessions: list[Session], today: date | None = None) -> None:
        self._grid = journal.heatmap(sessions, weeks=_WEEKS, today=today)
        self._peak = max(
            (d.seconds for col in self._grid for d in col if d is not None),
            default=0,
        )
        self.update()

    def _cell_rect(self, week: int, weekday: int) -> QRect:
        return QRect(
            self._LEFT + week * (_CELL + _GAP),
            self._TOP + weekday * (_CELL + _GAP),
            _CELL,
            _CELL,
        )

    def _day_at(self, point: QPoint) -> Day | None:
        for week, column in enumerate(self._grid):
            for weekday, day in enumerate(column):
                if day is not None and self._cell_rect(week, weekday).contains(point):
                    return day
        return None

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() * 0.8))
        painter.setFont(small)
        painter.setPen(QColor(palette().fg_muted))
        colours = _heat_colours()

        for weekday, label in ((0, "Mon"), (2, "Wed"), (4, "Fri")):
            rect = self._cell_rect(0, weekday)
            painter.drawText(
                QRect(0, rect.top() - 1, self._LEFT - 6, _CELL + 2),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                label,
            )

        last_month = None
        last_label = -3
        for week, column in enumerate(self._grid):
            first = next((d for d in column if d is not None), None)
            if first is not None and first.day.month != last_month:
                last_month = first.day.month
                # Skip a label that would run into the previous one.
                if week - last_label >= 3 and week < len(self._grid) - 1:
                    last_label = week
                    painter.drawText(
                        self._cell_rect(week, 0).left(),
                        self._TOP - 5,
                        first.day.strftime("%b"),
                    )
            for weekday, day in enumerate(column):
                if day is None:
                    continue
                level = journal.intensity(day.seconds, self._peak)
                path = QPainterPath()
                path.addRoundedRect(QRectF(self._cell_rect(week, weekday)), 3, 3)
                painter.fillPath(path, colours[level])

        # Legend.
        y = self._TOP + 7 * (_CELL + _GAP) + 8
        x = self.width() - 5 * (_CELL + 2) - 70
        painter.setPen(QColor(palette().fg_muted))
        painter.drawText(x - 34, y + _CELL - 3, "Less")
        for level, colour in enumerate(colours):
            path = QPainterPath()
            path.addRoundedRect(QRectF(x + level * (_CELL + 2), y, _CELL, _CELL), 3, 3)
            painter.fillPath(path, colour)
        painter.drawText(x + 5 * (_CELL + 2) + 6, y + _CELL - 3, "More")

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        day = self._day_at(event.position().toPoint())
        if day is None:
            QToolTip.hideText()
            return
        heading = day.day.strftime("%A, %d %B")
        if not day.seconds:
            text = f"{heading}\nNothing played"
        else:
            games = sorted(day.games.items(), key=lambda kv: kv[1], reverse=True)
            lines = [f"{heading} — {journal.format_duration(day.seconds)}"]
            lines += [f"  {name}  {journal.format_duration(s)}" for name, s in games[:4]]
            if day.approximate:
                lines.append("Includes earlier playtime; date approximate.")
            text = "\n".join(lines)
        QToolTip.showText(event.globalPosition().toPoint(), text, self)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        day = self._day_at(event.position().toPoint())
        if day is not None and day.top_game:
            self.day_clicked.emit(day)


class CoverTile(QWidget):
    """A game's cover on the shelf. Click to open, double-click to play."""

    open_requested = Signal(str)
    play_requested = Signal(str)

    _COVER = QSize(116, 174)

    def __init__(
        self,
        game: Game,
        artwork: ArtSource,
        caption: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._game = game
        self._artwork = artwork
        self._caption = caption
        self._hover = False
        self.setFixedSize(self._COVER.width(), self._COVER.height() + 44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{game.name}\nClick to open · double-click to play")

    def enterEvent(self, event: object) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, event: object) -> None:
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit(self._game.name)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.play_requested.emit(self._game.name)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(0, 0, self._COVER.width(), self._COVER.height())

        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        cover = self._artwork.pixmap(
            self._game.name,
            GRID.name,
            self._COVER,
            expand=True,
            dpr=self.devicePixelRatioF(),
        )
        painter.save()
        painter.setClipPath(path)
        if cover is not None:
            # Centre the expanded pixmap in the tile.
            logical_w = cover.width() / cover.devicePixelRatio()
            logical_h = cover.height() / cover.devicePixelRatio()
            painter.drawPixmap(
                QRectF(
                    (rect.width() - logical_w) / 2,
                    (rect.height() - logical_h) / 2,
                    logical_w,
                    logical_h,
                ),
                cover,
                QRectF(cover.rect()),
            )
        else:
            gradient = QLinearGradient(0, 0, 0, rect.height())
            gradient.setColorAt(0, QColor(palette().placeholder_top))
            gradient.setColorAt(1, QColor(palette().placeholder_bottom))
            painter.fillRect(rect, gradient)
            initials = "".join(w[0] for w in self._game.name.split()[:2]).upper()
            font = QFont(self.font())
            font.setPointSize(22)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(palette().link))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), initials)
        painter.restore()

        border = QColor(palette().link if self._hover else palette().border)
        painter.setPen(border)
        painter.drawPath(path)

        metrics = painter.fontMetrics()
        name = metrics.elidedText(
            self._game.name, Qt.TextElideMode.ElideRight, self.width()
        )
        painter.setPen(QColor(palette().fg_bright))
        painter.drawText(0, int(rect.height()) + 18, name)
        painter.setPen(QColor(palette().fg_muted))
        painter.drawText(0, int(rect.height()) + 36, self._caption)


class TopGames(QWidget):
    """Horizontal bars for the most played games."""

    open_requested = Signal(str)

    _ROW = 40

    def __init__(self, artwork: ArtworkService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._artwork = artwork
        self._rows: list[tuple[str, int]] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_rows(self, rows: list[tuple[str, int]]) -> None:
        self._rows = rows
        self.setFixedHeight(max(1, len(rows)) * self._ROW)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        index = int(event.position().y() // self._ROW)
        if 0 <= index < len(self._rows):
            self.open_requested.emit(self._rows[index][0])

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._rows:
            return
        peak = max(seconds for _, seconds in self._rows) or 1
        icon = QSize(28, 28)
        label_w = 190
        value_w = 70
        bar_x = 40 + label_w
        bar_max = max(40, self.width() - bar_x - value_w)
        metrics = painter.fontMetrics()

        for i, (name, seconds) in enumerate(self._rows):
            y = i * self._ROW
            pix = self._artwork.pixmap(
                name, ICON.name, icon, dpr=self.devicePixelRatioF()
            ) or self._artwork.pixmap(
                name, GRID.name, icon, expand=True, dpr=self.devicePixelRatioF()
            )
            box = QRectF(0, y + 6, 28, 28)
            clip = QPainterPath()
            clip.addRoundedRect(box, 6, 6)
            painter.save()
            painter.setClipPath(clip)
            if pix is not None:
                painter.drawPixmap(box, pix, QRectF(pix.rect()))
            else:
                painter.fillPath(clip, QColor(palette().raised))
            painter.restore()

            painter.setPen(QColor(palette().fg_bright))
            painter.drawText(
                QRect(40, y, label_w - 10, self._ROW),
                int(Qt.AlignmentFlag.AlignVCenter),
                metrics.elidedText(name, Qt.TextElideMode.ElideRight, label_w - 12),
            )

            track = QPainterPath()
            track.addRoundedRect(QRectF(bar_x, y + 15, bar_max, 10), 5, 5)
            painter.fillPath(track, QColor(palette().raised))
            fill = QPainterPath()
            fill.addRoundedRect(
                QRectF(bar_x, y + 15, max(10, bar_max * seconds / peak), 10), 5, 5
            )
            gradient = QLinearGradient(bar_x, 0, bar_x + bar_max, 0)
            gradient.setColorAt(0, QColor(palette().accent))
            gradient.setColorAt(1, QColor(palette().accent_hover))
            painter.fillPath(fill, gradient)

            painter.setPen(QColor(palette().fg_muted))
            painter.drawText(
                QRect(bar_x + bar_max + 8, y, value_w, self._ROW),
                int(Qt.AlignmentFlag.AlignVCenter),
                journal.format_duration(seconds),
            )


class JournalView(QScrollArea):
    """The Journal page."""

    play_requested = Signal(str)
    open_requested = Signal(str)

    def __init__(self, artwork: ArtworkService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._artwork = artwork
        self._continue_name: str | None = None
        self.setObjectName("journal")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._build()

    def _build(self) -> None:
        body = QWidget()
        body.setObjectName("journalBody")
        self.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(12)

        # Continue playing: the banner with a play button over its corner.
        self._continue_label = _section("Continue playing")
        layout.addWidget(self._continue_label)
        hero_box = QWidget()
        hero_grid = QGridLayout(hero_box)
        hero_grid.setContentsMargins(0, 0, 0, 0)
        self._banner = HeroBanner(self._artwork, height=240)
        hero_grid.addWidget(self._banner, 0, 0)
        self._continue_btn = QPushButton("▶  Continue")
        self._continue_btn.setObjectName("playButton")
        self._continue_btn.setFixedHeight(40)
        self._continue_btn.setMinimumWidth(150)
        self._continue_btn.clicked.connect(self._continue)
        hero_grid.addWidget(
            self._continue_btn,
            0,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
        )
        hero_grid.setContentsMargins(0, 0, 0, 0)
        self._continue_btn.setContentsMargins(0, 0, 20, 20)
        self._hero_box = hero_box
        layout.addWidget(hero_box)
        layout.addSpacing(10)

        # Headline numbers.
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self._total_tile = StatTile("Total played")
        self._week_tile = StatTile("This week")
        self._streak_tile = StatTile("Day streak")
        self._longest_tile = StatTile("Longest session")
        for tile in (
            self._total_tile,
            self._week_tile,
            self._streak_tile,
            self._longest_tile,
        ):
            tiles.addWidget(tile)
        layout.addLayout(tiles)
        layout.addSpacing(10)

        # Activity.
        layout.addWidget(_section("Activity — last six months"))
        activity = QFrame()
        activity.setObjectName("journalCard")
        activity_layout = QVBoxLayout(activity)
        activity_layout.setContentsMargins(16, 14, 16, 10)
        self._heatmap = Heatmap()
        self._heatmap.day_clicked.connect(self._open_day)
        activity_layout.addWidget(self._heatmap)
        layout.addWidget(activity)
        layout.addSpacing(10)

        # Recently played shelf.
        layout.addWidget(_section("Recently played"))
        shelf_scroll = QScrollArea()
        shelf_scroll.setObjectName("shelf")
        shelf_scroll.setWidgetResizable(True)
        shelf_scroll.setFrameShape(QFrame.Shape.NoFrame)
        shelf_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        shelf_scroll.setFixedHeight(CoverTile._COVER.height() + 44 + 18)
        self._shelf = QWidget()
        self._shelf_layout = QHBoxLayout(self._shelf)
        self._shelf_layout.setContentsMargins(0, 0, 0, 0)
        self._shelf_layout.setSpacing(16)
        shelf_scroll.setWidget(self._shelf)
        layout.addWidget(shelf_scroll)
        layout.addSpacing(10)

        # Most played.
        top_card = QFrame()
        top_card.setObjectName("journalCard")
        top_layout = QVBoxLayout(top_card)
        top_layout.setContentsMargins(16, 10, 16, 10)
        self._top = TopGames(self._artwork)
        self._top.open_requested.connect(self.open_requested)
        top_layout.addWidget(self._top)
        self._top_label = _section("Most played")
        self._top_card = top_card
        layout.addWidget(self._top_label)
        layout.addWidget(top_card)

        self._empty = QLabel(
            "Your journal fills in as you play.\n"
            "Launch a game from the library and it will start here."
        )
        self._empty.setObjectName("emptyLabel")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty)
        layout.addStretch()

    # -- data ----------------------------------------------------------

    def refresh(
        self,
        games: list[Game],
        sessions: list[Session],
        today: date | None = None,
    ) -> None:
        today = today or date.today()
        played = [g for g in games if g.last_played is not None]
        played.sort(key=lambda g: g.last_played or datetime.min, reverse=True)
        has_history = bool(played) or bool(sessions)

        self._empty.setVisible(not has_history)
        for widget in (self._continue_label, self._hero_box):
            widget.setVisible(bool(played))

        # Continue playing.
        if played:
            latest = played[0]
            self._continue_name = latest.name
            when = format_last_played(latest.last_played)
            self._banner.set_game(
                latest.name,
                latest.name,
                f"Last played {when}  ·  "
                f"{journal.format_duration(latest.playtime_seconds)} in total",
            )
            self._continue_btn.setEnabled(latest.executable_exists)
        else:
            self._continue_name = None

        # Numbers. Totals come from the per-game counters, which include
        # playtime from before sessions were recorded.
        total = sum(g.playtime_seconds for g in games)
        self._total_tile.set(
            journal.format_duration(total),
            f"across {sum(1 for g in games if g.playtime_seconds)} games",
        )
        this_week = journal.total_since(sessions, journal.week_start(today))
        last_week = journal.total_since(
            sessions, journal.week_start(today) - timedelta(days=7)
        ) - this_week
        self._week_tile.set(
            journal.format_duration(this_week),
            f"last week {journal.format_duration(last_week)}" if last_week else "",
        )
        streak = journal.streak(sessions, today)
        self._streak_tile.set(
            f"{streak} day{'s' if streak != 1 else ''}",
            "keep it going" if streak else "",
        )
        longest = journal.longest(sessions)
        self._longest_tile.set(
            journal.format_duration(longest.seconds) if longest else "—",
            longest.name if longest else "",
        )

        self._heatmap.set_sessions(sessions, today)
        self._fill_shelf(played[:_SHELF_LIMIT])

        ranked = sorted(
            ((g.name, g.playtime_seconds) for g in games if g.playtime_seconds),
            key=lambda row: row[1],
            reverse=True,
        )
        self._top.set_rows(ranked[:_TOP_LIMIT])
        self._top_label.setVisible(bool(ranked))
        self._top_card.setVisible(bool(ranked))

    def _fill_shelf(self, games: list[Game]) -> None:
        while self._shelf_layout.count():
            item = self._shelf_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for game in games:
            caption = format_last_played(game.last_played) or "never"
            tile = CoverTile(game, self._artwork, caption)
            tile.open_requested.connect(self.open_requested)
            tile.play_requested.connect(self.play_requested)
            self._shelf_layout.addWidget(tile)
        self._shelf_layout.addStretch()

    def refresh_artwork(self) -> None:
        self._banner.refresh()
        self._shelf.update()
        self._top.update()

    # -- actions -------------------------------------------------------

    def _continue(self) -> None:
        if self._continue_name:
            self.play_requested.emit(self._continue_name)

    def _open_day(self, day: Day) -> None:
        if day.top_game:
            self.open_requested.emit(day.top_game)
