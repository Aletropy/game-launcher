"""The Friends tab: what friends are playing, what they play most, and who
has played most this week.

Read-only by design: there is nothing to send a friend but a request.
In Offline Mode this page explains the feature and does nothing else.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from launcher.domain import journal
from launcher.domain.friends import (
    BoardPeriod,
    CommonGame,
    Friend,
    FriendRequest,
    FriendsSnapshot,
    FriendsState,
    LeaderboardRow,
    common_games,
    format_code,
    format_seen,
    format_since,
    game_key,
    is_valid_code,
)
from launcher.domain.models import Game
from launcher.services.artwork import GRID, ArtworkService
from launcher.services.friends import FriendsService
from launcher.ui.dialogs.confirm import Answer, ask
from launcher.ui.theme import palette
from launcher.ui.widgets.journal import StatTile, TopGames

_OFFLINE, _UNREGISTERED, _CONNECTING, _MAIN = range(4)
_FRIEND_TOP = 3


def _section(title: str) -> QLabel:
    label = QLabel(title.upper())
    label.setObjectName("journalSection")
    return label


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hintLabel")
    label.setWordWrap(True)
    return label


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("journalCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    return frame, layout


def _clear(layout: QVBoxLayout | QHBoxLayout | QGridLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget() if item is not None else None
        if widget is not None:
            widget.deleteLater()


class _LocalGames:
    """Friends' games matched to the user's own, for artwork and links."""

    def __init__(self) -> None:
        self._by_key: dict[str, str] = {}
        self._seconds: dict[str, int] = {}

    def update(self, games: list[Game]) -> None:
        self._by_key = {game_key(g.config): g.name for g in games}
        self._seconds = {game_key(g.config): g.playtime_seconds for g in games}

    def name(self, key: str) -> str | None:
        """The user's own name for a game, or None if they don't have it."""
        return self._by_key.get(key)

    def seconds(self, key: str) -> int:
        """The user's playtime for a game key, or 0."""
        return self._seconds.get(key, 0)

    def owns(self, name: str) -> bool:
        return name in self._by_key.values()


# --------------------------------------------------------------------------
# pieces
# --------------------------------------------------------------------------


class PresenceTile(QWidget):
    """A friend playing something now: the cover, who, and for how long."""

    open_requested = Signal(str)

    _COVER = QSize(116, 174)

    def __init__(
        self,
        friend: Friend,
        local_name: str | None,
        artwork: ArtworkService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        assert friend.presence is not None
        self._friend = friend
        self._game = friend.presence.name
        self._local = local_name
        self._artwork = artwork
        self.setFixedSize(self._COVER.width(), self._COVER.height() + 62)
        tip = f"{friend.name} is playing {self._game}"
        if local_name:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            tip += "\nYou have it too · click to open"
        self.setToolTip(tip)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._local and event.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit(self._local)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(0, 0, self._COVER.width(), self._COVER.height())
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        cover = (
            self._artwork.pixmap(
                self._local, GRID.name, self._COVER, expand=True, dpr=self.devicePixelRatioF()
            )
            if self._local
            else None
        )
        painter.save()
        painter.setClipPath(path)
        if cover is not None:
            w = cover.width() / cover.devicePixelRatio()
            h = cover.height() / cover.devicePixelRatio()
            painter.drawPixmap(
                QRectF((rect.width() - w) / 2, (rect.height() - h) / 2, w, h),
                cover,
                QRectF(cover.rect()),
            )
        else:
            gradient = QLinearGradient(0, 0, 0, rect.height())
            gradient.setColorAt(0, QColor(palette().placeholder_top))
            gradient.setColorAt(1, QColor(palette().placeholder_bottom))
            painter.fillRect(rect, gradient)
            painter.setPen(QColor(palette().link))
            font = QFont(self.font())
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                rect.adjusted(10, 10, -10, -10),
                int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                self._game,
            )
        painter.restore()
        painter.setPen(QColor(palette().accent_hover))
        painter.drawPath(path)

        painter.setFont(self.font())
        metrics = painter.fontMetrics()
        y = int(rect.height())
        painter.setPen(QColor(palette().fg_bright))
        elide = Qt.TextElideMode.ElideRight
        painter.drawText(0, y + 18, metrics.elidedText(self._friend.name, elide, self.width()))
        painter.setPen(QColor(palette().fg))
        painter.drawText(0, y + 36, metrics.elidedText(self._game, elide, self.width()))
        painter.setPen(QColor(palette().fg_muted))
        since = self._friend.presence.since if self._friend.presence else None
        painter.drawText(0, y + 54, format_since(since))


class Leaderboard(QWidget):
    """Ranked rows with bars; your own row stands out."""

    _ROW = 38

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[LeaderboardRow] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_rows(self, rows: list[LeaderboardRow]) -> None:
        self._rows = rows
        self.setFixedHeight(max(1, len(rows)) * self._ROW)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        metrics = painter.fontMetrics()
        if not self._rows:
            painter.setPen(QColor(palette().fg_muted))
            painter.drawText(
                self.rect(), int(Qt.AlignmentFlag.AlignVCenter), "Nobody has played yet."
            )
            return
        peak = max(r.seconds for r in self._rows) or 1
        rank_w, name_w, value_w = 36, 170, 76
        bar_x = rank_w + name_w
        bar_max = max(40, self.width() - bar_x - value_w)
        medals = {1: palette().favorite, 2: palette().fg_bright, 3: palette().link}

        for i, row in enumerate(self._rows):
            y = i * self._ROW
            if row.is_me:
                band = QPainterPath()
                band.addRoundedRect(QRectF(0, y + 2, self.width(), self._ROW - 4), 6, 6)
                painter.fillPath(band, QColor(palette().raised))

            bold = QFont(self.font())
            bold.setBold(row.rank <= 3 or row.is_me)
            painter.setFont(bold)
            painter.setPen(QColor(medals.get(row.rank, palette().fg_muted)))
            painter.drawText(
                QRect(0, y, rank_w - 8, self._ROW),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"{row.rank}",
            )
            painter.setPen(QColor(palette().fg_bright))
            label = f"{row.name} (you)" if row.is_me else row.name
            painter.drawText(
                QRect(rank_w + 4, y, name_w - 12, self._ROW),
                int(Qt.AlignmentFlag.AlignVCenter),
                metrics.elidedText(label, Qt.TextElideMode.ElideRight, name_w - 14),
            )
            painter.setFont(self.font())

            track = QPainterPath()
            track.addRoundedRect(QRectF(bar_x, y + 14, bar_max, 10), 5, 5)
            painter.fillPath(track, QColor(palette().raised if not row.is_me else palette().bg))
            if row.seconds:
                fill = QPainterPath()
                fill.addRoundedRect(
                    QRectF(bar_x, y + 14, max(10, bar_max * row.seconds / peak), 10), 5, 5
                )
                gradient = QLinearGradient(bar_x, 0, bar_x + bar_max, 0)
                gradient.setColorAt(0, QColor(palette().accent))
                gradient.setColorAt(1, QColor(palette().accent_hover))
                painter.fillPath(fill, gradient)

            painter.setPen(QColor(palette().fg_muted))
            painter.drawText(
                QRect(bar_x + bar_max + 8, y, value_w, self._ROW),
                int(Qt.AlignmentFlag.AlignVCenter),
                journal.format_duration(row.seconds),
            )


class StatusDot(QWidget):
    """Green while playing, the accent while online, grey otherwise."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colour = QColor(palette().fg_disabled)
        self.setFixedSize(10, 10)

    def set_colour(self, colour: str) -> None:
        self._colour = QColor(colour)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._colour)
        painter.drawEllipse(QRectF(0, 0, 10, 10))


class FriendCard(QFrame):
    """One friend: status, time this week and in total, and top games."""

    open_requested = Signal(str)
    remove_requested = Signal(int, str)

    def __init__(
        self,
        friend: Friend,
        local: _LocalGames,
        artwork: ArtworkService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("journalCard")
        self._friend = friend
        self._local = local
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 12, 12)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        dot = StatusDot()
        top.addWidget(dot, alignment=Qt.AlignmentFlag.AlignVCenter)
        name = QLabel(friend.name)
        name.setObjectName("friendName")
        top.addWidget(name, stretch=1)
        more = QToolButton()
        more.setObjectName("friendMenu")
        more.setText("⋯")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction(
            "Remove friend…", lambda: self.remove_requested.emit(friend.user_id, friend.name)
        )
        more.setMenu(menu)
        top.addWidget(more)
        layout.addLayout(top)

        if friend.presence is not None:
            dot.set_colour(palette().accent_hover)
            status = f"Playing {friend.presence.name} {format_since(friend.presence.since)}"
        else:
            seen = format_seen(friend.last_seen)
            if seen == "Online now":
                dot.set_colour(palette().link)
            status = seen
        status_label = QLabel(status)
        status_label.setObjectName("infoValue" if friend.presence else "hintLabel")
        status_label.setWordWrap(True)
        layout.addWidget(status_label)

        numbers = _hint(
            f"This week {journal.format_duration(friend.week_seconds)}"
            f"  ·  All time {journal.format_duration(friend.total_seconds)}"
        )
        layout.addWidget(numbers)

        if friend.top_games:
            top_games = TopGames(artwork)
            # The user's own name for a game they both have finds its art
            # and opens it; otherwise the friend's name is shown as-is.
            top_games.set_rows(
                [
                    (self._local.name(g.key) or g.name, g.seconds)
                    for g in friend.top_games[:_FRIEND_TOP]
                ]
            )
            top_games.open_requested.connect(self._open)
            layout.addWidget(top_games)
        else:
            layout.addWidget(_hint("Nothing played yet."))

    def _open(self, name: str) -> None:
        # Only games the user has; the rest are just names.
        if self._local.owns(name):
            self.open_requested.emit(name)


# --------------------------------------------------------------------------
# the view
# --------------------------------------------------------------------------


class FriendsView(QScrollArea):
    """The Friends page."""

    #: Open one of the user's own games in the library.
    open_requested = Signal(str)
    #: Open Settings on a page.
    settings_requested = Signal(str)

    def __init__(
        self,
        service: FriendsService,
        artwork: ArtworkService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._artwork = artwork
        self._local = _LocalGames()
        self.setObjectName("friends")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._build()

        service.state_changed.connect(self._on_state)
        service.snapshot_changed.connect(self._render)
        service.notice.connect(self._show_notice)
        self._on_state(service.state)
        if service.snapshot is not None:
            self._render(service.snapshot)

    # -- construction --------------------------------------------------

    def _build(self) -> None:
        body = QWidget()
        body.setObjectName("friendsBody")
        self.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(12)

        self._banner = QLabel()
        self._banner.setObjectName("friendsBanner")
        self._banner.setWordWrap(True)
        self._banner.hide()
        layout.addWidget(self._banner)
        self._notice = QLabel()
        self._notice.setObjectName("friendsNotice")
        self._notice.setWordWrap(True)
        self._notice.hide()
        layout.addWidget(self._notice)
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.setInterval(8000)
        self._notice_timer.timeout.connect(self._notice.hide)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_offline())
        self._pages.addWidget(self._build_unregistered())
        self._pages.addWidget(self._build_connecting())
        self._pages.addWidget(self._build_main())
        layout.addWidget(self._pages)
        layout.addStretch()

    @staticmethod
    def _centred(card: QFrame) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 40, 0, 0)
        row = QHBoxLayout()
        row.addStretch()
        card.setMaximumWidth(560)
        row.addWidget(card, stretch=3)
        row.addStretch()
        column.addLayout(row)
        column.addStretch()
        return page

    def _show_page(self, index: int) -> None:
        """Switch page, sized to that page alone.

        A stack is as tall as its tallest page; ignoring the hidden ones
        keeps the short offline card from scrolling like the full tab.
        """
        for i in range(self._pages.count()):
            page = self._pages.widget(i)
            if page is None:
                continue
            policy = QSizePolicy.Policy.Preferred if i == index else QSizePolicy.Policy.Ignored
            page.setSizePolicy(policy, policy)
        self._pages.setCurrentIndex(index)
        self._pages.adjustSize()

    def _build_offline(self) -> QWidget:
        card, layout = _card()
        title = QLabel("Friends")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(
            _hint(
                "See what your friends are playing right now, what they play most, "
                "and who has played the most this week. There's no chat and nothing "
                "to reply to: just play time."
            )
        )
        layout.addSpacing(6)
        layout.addWidget(QLabel("You're in Offline Mode."))
        layout.addWidget(
            _hint(
                "Nothing is sent anywhere. Going online shares your display name, "
                "your play history (which games, and for how long) and, if you "
                "want, the game you're playing now, with friends you accept."
            )
        )
        layout.addSpacing(6)
        row = QHBoxLayout()
        go = QPushButton("Go online…")
        go.setObjectName("playButton")
        go.clicked.connect(lambda: self.settings_requested.emit("friends"))
        row.addWidget(go)
        row.addStretch()
        layout.addLayout(row)
        return self._centred(card)

    def _build_unregistered(self) -> QWidget:
        card, layout = _card()
        title = QLabel("Create your profile")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(
            _hint("Friends see this name. You get a friend code to share with them.")
        )
        row = QHBoxLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Display name")
        self._name_edit.setMaxLength(32)
        self._name_edit.returnPressed.connect(self._register)
        row.addWidget(self._name_edit, stretch=1)
        self._register_btn = QPushButton("Create profile")
        self._register_btn.setObjectName("playButton")
        self._register_btn.clicked.connect(self._register)
        row.addWidget(self._register_btn)
        layout.addLayout(row)
        self._server_hint = _hint("")
        layout.addWidget(self._server_hint)
        stay = QPushButton("Stay offline")
        stay.setFlat(True)
        stay.clicked.connect(lambda: self.settings_requested.emit("friends"))
        layout.addWidget(stay, alignment=Qt.AlignmentFlag.AlignLeft)
        return self._centred(card)

    def _build_connecting(self) -> QWidget:
        card, layout = _card()
        self._connecting_label = QLabel("Connecting…")
        layout.addWidget(self._connecting_label)
        return self._centred(card)

    def _build_main(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # You: your code, and adding someone by theirs.
        header = QHBoxLayout()
        header.setSpacing(12)
        self._me_tile = StatTile("Your friend code")
        copy = QPushButton("Copy")
        copy.clicked.connect(self._copy_code)
        header.addWidget(self._me_tile, stretch=1)
        me_actions = QVBoxLayout()
        me_actions.addStretch()
        me_actions.addWidget(copy)
        header.addLayout(me_actions)

        add_card, add_layout = _card()
        add_layout.addWidget(QLabel("Add a friend"))
        add_row = QHBoxLayout()
        self._code_edit = QLineEdit()
        self._code_edit.setPlaceholderText("Their code, e.g. K7QX-29MB")
        self._code_edit.setMaxLength(12)
        self._code_edit.returnPressed.connect(self._send_request)
        add_row.addWidget(self._code_edit, stretch=1)
        send = QPushButton("Send request")
        send.clicked.connect(self._send_request)
        add_row.addWidget(send)
        add_layout.addLayout(add_row)
        header.addWidget(add_card, stretch=2)
        layout.addLayout(header)

        self._week_tile = StatTile("You this week")
        self._total_tile = StatTile("You all time")
        self._friends_tile = StatTile("Friends")
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        for tile in (self._week_tile, self._total_tile, self._friends_tile):
            tiles.addWidget(tile)
        layout.addLayout(tiles)

        # Requests.
        self._requests_label = _section("Requests")
        layout.addWidget(self._requests_label)
        self._requests_card, requests_layout = _card()
        self._requests_rows = QVBoxLayout()
        self._requests_rows.setSpacing(6)
        requests_layout.addLayout(self._requests_rows)
        layout.addWidget(self._requests_card)

        # Playing now.
        self._playing_label = _section("Playing now")
        layout.addWidget(self._playing_label)
        shelf_scroll = QScrollArea()
        shelf_scroll.setObjectName("shelf")
        shelf_scroll.setWidgetResizable(True)
        shelf_scroll.setFrameShape(QFrame.Shape.NoFrame)
        shelf_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        shelf_scroll.setFixedHeight(PresenceTile._COVER.height() + 62 + 18)
        self._shelf = QWidget()
        self._shelf_layout = QHBoxLayout(self._shelf)
        self._shelf_layout.setContentsMargins(0, 0, 0, 0)
        self._shelf_layout.setSpacing(16)
        shelf_scroll.setWidget(self._shelf)
        self._shelf_scroll = shelf_scroll
        layout.addWidget(shelf_scroll)

        # In common: games you own that friends play too.
        self._common_label = _section("In common")
        layout.addWidget(self._common_label)
        self._common_card, common_layout = _card()
        self._common_rows = QVBoxLayout()
        self._common_rows.setSpacing(6)
        common_layout.addLayout(self._common_rows)
        layout.addWidget(self._common_card)

        # Leaderboard.
        board_head = QHBoxLayout()
        board_head.addWidget(_section("Leaderboard"))
        board_head.addStretch()
        self._period_group = QButtonGroup(self)
        self._period_group.setExclusive(True)
        for index, period in enumerate(BoardPeriod):
            button = QPushButton(period.label)
            button.setObjectName("viewToggle")
            button.setCheckable(True)
            button.setFixedHeight(28)
            button.setChecked(period is BoardPeriod.WEEK)
            self._period_group.addButton(button, index)
            board_head.addWidget(button)
        self._period_group.idClicked.connect(lambda _i: self._board_changed())
        self._game_combo = QComboBox()
        self._game_combo.setMinimumWidth(200)
        self._game_combo.addItem("All games", "")
        self._game_combo.activated.connect(lambda _i: self._board_changed())
        board_head.addWidget(self._game_combo)
        layout.addLayout(board_head)
        board_card, board_layout = _card()
        self._board = Leaderboard()
        board_layout.addWidget(self._board)
        layout.addWidget(board_card)

        # Friends.
        layout.addWidget(_section("Friends"))
        self._grid_box = QWidget()
        self._grid = QGridLayout(self._grid_box)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(12)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        layout.addWidget(self._grid_box)
        self._no_friends = QLabel(
            "No friends yet.\nShare your code, or enter a friend's code above."
        )
        self._no_friends.setObjectName("emptyLabel")
        self._no_friends.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._no_friends)
        return page

    # -- state ---------------------------------------------------------

    def set_local_games(self, games: list[Game]) -> None:
        """The user's library, to match friends' games against."""
        self._local.update(games)
        if self._service.snapshot is not None and self._pages.currentIndex() == _MAIN:
            self._render(self._service.snapshot)

    def _on_state(self, state: FriendsState) -> None:
        self._banner.hide()
        if state is FriendsState.OFFLINE:
            self._show_page(_OFFLINE)
        elif state is FriendsState.UNREGISTERED:
            self._register_btn.setEnabled(True)
            self._name_edit.setEnabled(True)
            self._server_hint.setText(f"Server: {self._service.server_url}")
            self._show_page(_UNREGISTERED)
        elif state is FriendsState.RECOVERY:
            self._banner.setText(
                "This profile isn't recognised by the server — nothing was deleted here."
                " Restore a profile backup (milso-launcher --import-profile FILE)"
                " or reclaim with your friend code + recovery key, then restart."
                " Your local play history is untouched."
            )
            self._banner.show()
            self._register_btn.setEnabled(True)
            self._name_edit.setEnabled(True)
            self._server_hint.setText(f"Server: {self._service.server_url}")
            self._show_page(_UNREGISTERED)
        elif state is FriendsState.CONNECTING:
            self._connecting_label.setText(f"Connecting to {self._service.server_url}…")
            self._show_page(_CONNECTING)
        elif state is FriendsState.ONLINE:
            self._show_page(_MAIN)
        elif state is FriendsState.UNREACHABLE:
            self._banner.setText(
                f"Can't reach the friends server at {self._service.server_url}. "
                "Retrying; everything else works as normal."
            )
            self._banner.show()
            if self._service.snapshot is None:
                self._connecting_label.setText("Waiting for the friends server…")
                self._show_page(_CONNECTING)
            else:
                # Keep showing what was last known.
                self._show_page(_MAIN)

    def _show_notice(self, text: str) -> None:
        self._notice.setText(text)
        self._notice.setVisible(bool(text))
        self._notice_timer.start()

    def _render(self, snap: FriendsSnapshot) -> None:
        self._me_tile.set(snap.friend_code or "—", snap.me.name)
        self._week_tile.set(journal.format_duration(snap.me.week_seconds))
        self._total_tile.set(journal.format_duration(snap.me.total_seconds))
        playing = len(snap.playing_now)
        self._friends_tile.set(
            str(len(snap.friends)), f"{playing} playing now" if playing else ""
        )
        self._render_requests(snap)
        self._render_playing(snap)
        self._render_common(snap)
        self._render_board(snap)
        self._render_friends(snap)

    def _render_requests(self, snap: FriendsSnapshot) -> None:
        _clear(self._requests_rows)
        for request in (*snap.incoming, *snap.outgoing):
            self._requests_rows.addWidget(self._request_row(request))
        visible = bool(snap.requests)
        self._requests_label.setVisible(visible)
        self._requests_card.setVisible(visible)

    def _request_row(self, request: FriendRequest) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        if request.incoming:
            layout.addWidget(QLabel(f"{request.name} wants to be friends"), stretch=1)
            accept = QPushButton("Accept")
            accept.setObjectName("playButton")
            accept.clicked.connect(lambda: self._service.answer(request.id, True))
            decline = QPushButton("Decline")
            decline.clicked.connect(lambda: self._service.answer(request.id, False))
            layout.addWidget(accept)
            layout.addWidget(decline)
        else:
            label = _hint(f"Waiting for {request.name} to accept")
            layout.addWidget(label, stretch=1)
            cancel = QPushButton("Withdraw")
            cancel.clicked.connect(lambda: self._service.cancel_request(request.id))
            layout.addWidget(cancel)
        return row

    def _render_playing(self, snap: FriendsSnapshot) -> None:
        _clear(self._shelf_layout)
        for friend in snap.playing_now:
            assert friend.presence is not None
            tile = PresenceTile(friend, self._local.name(friend.presence.key), self._artwork)
            tile.open_requested.connect(self.open_requested)
            self._shelf_layout.addWidget(tile)
        self._shelf_layout.addStretch()
        visible = bool(snap.playing_now)
        self._playing_label.setVisible(visible)
        self._shelf_scroll.setVisible(visible)

    def _render_common(self, snap: FriendsSnapshot) -> None:
        _clear(self._common_rows)
        common = common_games(
            snap.friends,
            local_name=self._local.name,
            local_seconds=self._local.seconds,
        )[:6]
        for game in common:
            self._common_rows.addWidget(self._common_row(game))
        visible = bool(common)
        self._common_label.setVisible(visible)
        self._common_card.setVisible(visible)

    def _common_row(self, game: CommonGame) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        names = ", ".join(game.friend_names[:3])
        if len(game.friend_names) > 3:
            names += f" and {len(game.friend_names) - 3} more"
        detail = f"{names} · {journal.format_duration(game.friends_seconds)}"
        if game.mine_seconds:
            detail += f" · you: {journal.format_duration(game.mine_seconds)}"
        text = QLabel(f"<b>{game.name}</b><br>{detail}")
        text.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(text, stretch=1)
        open_btn = QPushButton("Open")
        open_btn.clicked.connect(lambda: self.open_requested.emit(game.name))
        layout.addWidget(open_btn)
        return row

    def _render_board(self, snap: FriendsSnapshot) -> None:
        # Refill the game list without losing the choice.
        self._game_combo.blockSignals(True)
        self._game_combo.clear()
        self._game_combo.addItem("All games", "")
        for game in snap.games:
            label = self._local.name(game.key) or game.name
            suffix = f"  ({game.players})" if game.players > 1 else ""
            self._game_combo.addItem(label + suffix, game.key)
        index = self._game_combo.findData(snap.board_game)
        self._game_combo.setCurrentIndex(max(0, index))
        self._game_combo.blockSignals(False)
        button = self._period_group.button(list(BoardPeriod).index(snap.board_period))
        if button is not None:
            button.setChecked(True)
        self._board.set_rows(list(snap.board))

    def _render_friends(self, snap: FriendsSnapshot) -> None:
        _clear(self._grid)
        for i, friend in enumerate(snap.friends):
            card = FriendCard(friend, self._local, self._artwork)
            card.open_requested.connect(self.open_requested)
            card.remove_requested.connect(self._remove_friend)
            self._grid.addWidget(card, i // 2, i % 2)
        self._no_friends.setVisible(not snap.friends)
        self._grid_box.setVisible(bool(snap.friends))

    def refresh_artwork(self) -> None:
        self._shelf.update()
        self._grid_box.update()

    # -- actions -------------------------------------------------------

    def _register(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            self._name_edit.setFocus()
            return
        self._register_btn.setEnabled(False)
        self._name_edit.setEnabled(False)
        self._service.register(name)

    def _send_request(self) -> None:
        code = self._code_edit.text()
        if not is_valid_code(code):
            self._show_notice("A friend code has eight letters and numbers, like K7QX-29MB.")
            return
        self._service.send_request(format_code(code))
        self._code_edit.clear()

    def _copy_code(self) -> None:
        snap = self._service.snapshot
        if snap is not None and snap.friend_code:
            QGuiApplication.clipboard().setText(snap.friend_code)
            self._show_notice(f"Copied {snap.friend_code}.")

    def _board_changed(self) -> None:
        period = list(BoardPeriod)[max(0, self._period_group.checkedId())]
        self._service.set_board(period, str(self._game_combo.currentData() or ""))

    def _remove_friend(self, user_id: int, name: str) -> None:
        answer = ask(
            self,
            "Remove Friend",
            f"Remove {name}?\n\nYou stop seeing each other's play time. "
            "You can add each other again with your codes.",
            default=Answer.NO,
        )
        if answer is Answer.YES:
            self._service.unfriend(user_id)
