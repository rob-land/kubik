"""Learn: the course.

Each lesson is a stack of cards. A "do" card watches the live cube and only
lets you move on once the goal is genuinely reached — the same
condition-against-live-state idea as GoCube's `Particula.Learn`, rather than a
next button you can mash through.
"""

from __future__ import annotations

from gi.repository import Adw, GLib, Gtk

from kubik import curriculum
from kubik.cube import random_scramble, random_scramble_2x2, tokenize
from kubik.solver import Unsolvable, solve, stage_title
from kubik.widgets.cube3d import CubeView, NetView


class LearnView(Adw.Bin):
    __gtype_name__ = "KubikLearnView"

    def __init__(self, session, store):
        super().__init__()
        self.session = session
        self.store = store
        self.lessons = curriculum.load(session.cube_type)
        self.navigation = Adw.NavigationView()
        self.navigation.add(self._index_page())
        self.set_child(self.navigation)

    # -- lesson list --------------------------------------------------------

    def _index_page(self) -> Adw.NavigationPage:
        self.group = Adw.PreferencesGroup(
            title="Layer by layer",
            description="Everything works with or without a smart cube. "
                        "Switch puzzle from the main menu.")
        self._rows = {}
        self._lesson_rows = []
        for lesson in self.lessons:
            self.group.add(self._lesson_row(lesson))

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        body.set_margin_top(18)
        body.set_margin_bottom(18)
        body.set_margin_start(12)
        body.set_margin_end(12)
        body.append(self.group)

        scroller = Gtk.ScrolledWindow(
            hexpand=True, vexpand=True,
            child=Adw.Clamp(maximum_size=620, child=body))
        toolbar = Adw.ToolbarView(content=scroller)
        toolbar.add_top_bar(Adw.HeaderBar())
        page = Adw.NavigationPage(title="Course", child=toolbar)
        page.set_tag("index")
        self.refresh()
        return page

    def _lesson_row(self, lesson) -> Adw.ActionRow:
        row = Adw.ActionRow(title=lesson.title, subtitle=lesson.summary,
                            activatable=True)
        icon = Gtk.Image(icon_name="object-select-symbolic")
        icon.add_css_class("success")
        row.add_suffix(icon)
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        row.connect("activated", lambda _r, l=lesson: self._open(l))
        self._rows[lesson.id] = icon
        self._lesson_rows.append(row)
        return row

    def refresh(self):
        done = self.store.completed()
        for lesson_id, icon in self._rows.items():
            icon.set_visible(lesson_id in done)

    def on_puzzle_changed(self):
        """Rebuild the list for the other puzzle, dropping any open lesson."""
        self.navigation.pop_to_tag("index")
        self.lessons = curriculum.load(self.session.cube_type)
        for row in list(self._lesson_rows):
            self.group.remove(row)
        self._lesson_rows = []
        self._rows = {}
        for lesson in self.lessons:
            self.group.add(self._lesson_row(lesson))
        self.refresh()

    def _open(self, lesson):
        self.navigation.push(LessonPage(lesson, self.session, self.store,
                                        self.refresh))


class LessonPage(Adw.NavigationPage):
    """One lesson, card by card."""

    __gtype_name__ = "KubikLessonPage"

    def __init__(self, lesson, session, store, on_done):
        super().__init__(title=lesson.title)
        self.lesson = lesson
        self.session = session
        self.store = store
        self.on_done = on_done
        self.index = 0
        self._queue: list[str] = []
        self._playing = False
        self._watch = None
        self._alg_view = None
        self.live = None

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                               spacing=14)
        self.content.set_margin_top(18)
        self.content.set_margin_bottom(18)
        self.content.set_margin_start(12)
        self.content.set_margin_end(12)

        self.progress = Gtk.ProgressBar(show_text=False)
        self.progress.add_css_class("osd")

        self.back = Gtk.Button(label="Back")
        self.back.connect("clicked", lambda _b: self._go(-1))
        self.next = Gtk.Button(label="Next")
        self.next.add_css_class("suggested-action")
        self.next.connect("clicked", lambda _b: self._go(1))
        nav = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        nav.append(self.back)
        nav.append(self.next)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.append(self.progress)
        scroller = Gtk.ScrolledWindow(
            hexpand=True, vexpand=True,
            child=Adw.Clamp(maximum_size=620, child=self.content))
        outer.append(scroller)
        nav.set_margin_bottom(12)
        nav.set_margin_end(12)
        outer.append(nav)

        toolbar = Adw.ToolbarView(content=outer)
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_child(toolbar)
        self.connect("hidden", lambda _p: self._unwatch())
        self._render()

    # -- navigation ----------------------------------------------------------

    def _go(self, delta):
        new = self.index + delta
        if new < 0:
            return
        if new >= len(self.lesson.cards):
            self.store.mark_done(self.lesson.id)
            self.on_done()
            parent = self.get_parent()
            while parent is not None and not isinstance(parent,
                                                        Adw.NavigationView):
                parent = parent.get_parent()
            if parent is not None:
                parent.pop()
            return
        self.index = new
        self._render()

    def _clear(self):
        while (child := self.content.get_first_child()) is not None:
            self.content.remove(child)

    def _render(self):
        self._unwatch()
        self._alg_view = None
        self._clear()
        card = self.lesson.cards[self.index]
        self.progress.set_fraction((self.index + 1) / len(self.lesson.cards))
        self.back.set_sensitive(self.index > 0)
        self.next.set_label(
            "Finish" if self.index == len(self.lesson.cards) - 1 else "Next")
        builder = {"text": self._text_card, "alg": self._alg_card,
                   "quiz": self._quiz_card, "do": self._do_card}
        builder[card.kind](card)

    # -- card kinds -----------------------------------------------------------

    def _heading(self, text):
        label = Gtk.Label(label=text, xalign=0, wrap=True)
        label.add_css_class("title-2")
        return label

    def _body(self, text):
        label = Gtk.Label(label=text, xalign=0, wrap=True)
        label.add_css_class("body")
        return label

    def _text_card(self, card):
        if card.title:
            self.content.append(self._heading(card.title))
        self.content.append(self._body(card.text))
        self.next.set_sensitive(True)

    def _alg_card(self, card):
        self.content.append(self._heading(card.alg_name))
        view = CubeView(self.session.cube.copy())
        view.set_size_request(-1, 200)
        self.content.append(view)
        self._alg_view = view

        moves = Gtk.Label(label=card.moves, xalign=0.5)
        moves.add_css_class("algorithm-display")
        moves.add_css_class("title-1")
        self.content.append(moves)

        row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        play = Gtk.Button(label="Play on the cube",
                          icon_name="media-playback-start-symbolic")
        play.add_css_class("pill")
        play.add_css_class("suggested-action")
        play.connect("clicked", lambda _b, m=card.moves: self._play(m))
        row.append(play)
        reset = Gtk.Button(label="Reset")
        reset.add_css_class("pill")
        reset.connect("clicked", lambda _b: self._reset_demo())
        row.append(reset)
        self.content.append(row)

        if card.text:
            self.content.append(self._body(card.text))
        self.next.set_sensitive(True)

    def _quiz_card(self, card):
        self.content.append(self._heading("Quick check"))
        self.content.append(self._body(card.question))
        feedback = Gtk.Label(xalign=0, wrap=True)
        feedback.add_css_class("body")
        group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for i, option in enumerate(card.options):
            button = Gtk.Button(label=option)
            button.add_css_class("pill")
            button.connect("clicked", self._answer, card, i, feedback, group)
            group.append(button)
        self.content.append(group)
        self.content.append(feedback)
        self.next.set_sensitive(False)

    def _answer(self, button, card, index, feedback, group):
        if index == card.answer:
            button.add_css_class("suggested-action")
            feedback.set_text("Correct.")
            feedback.remove_css_class("error")
            feedback.add_css_class("success")
            child = group.get_first_child()
            while child is not None:
                child.set_sensitive(child is button)
                child = child.get_next_sibling()
            self.next.set_sensitive(True)
        else:
            button.add_css_class("destructive-action")
            button.set_sensitive(False)
            correction = ""
            if index < len(card.corrections):
                correction = card.corrections[index]
            feedback.remove_css_class("success")
            feedback.add_css_class("error")
            feedback.set_text(correction or "Not quite — try again.")

    def _do_card(self, card):
        self.content.append(self._heading("Your turn"))
        self.content.append(self._body(card.call))

        goal_box = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        net = NetView(self.session.size)
        net.set_mask(curriculum.goal_mask(card.goal, self.session.size))
        goal_label = Gtk.Label(label="Goal", xalign=0.5)
        goal_label.add_css_class("dim-label")
        goal_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        goal_column.append(net)
        goal_column.append(goal_label)
        goal_box.append(goal_column)
        self.content.append(goal_box)

        self.live = CubeView(self.session.cube.copy())
        self.live.set_size_request(-1, 220)
        if card.hold == "bottom":
            self.live.pitch = -0.85
        self.content.append(self.live)

        if card.text:
            self.content.append(self._body(card.text))

        self.verdict = Gtk.Label(xalign=0.5, wrap=True)
        self.verdict.add_css_class("title-4")
        self.content.append(self.verdict)

        tools = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        scramble = Gtk.Button(label="Scramble")
        scramble.add_css_class("pill")
        scramble.connect("clicked", lambda _b: self._scramble())
        tools.append(scramble)
        hint = Gtk.Button(label="Show me the next move")
        hint.add_css_class("pill")
        hint.connect("clicked", lambda _b, c=card: self._hint(c))
        tools.append(hint)
        self.content.append(tools)

        self.hint_label = Gtk.Label(xalign=0.5, wrap=True)
        self.hint_label.add_css_class("dim-label")
        self.content.append(self.hint_label)

        self._predicate = curriculum.goal_predicate(card.goal,
                                                    self.session.size)
        self._watch = self.session.connect("changed", self._check)
        self._check(self.session)

    # -- live checking ---------------------------------------------------------

    def _check(self, session):
        if self.live is None:
            return
        if not self.live.is_animating():
            self.live.set_cube(session.cube.copy())
        if self._predicate(session.cube):
            self.verdict.set_text("Done — that is the goal state.")
            self.verdict.remove_css_class("dim-label")
            self.verdict.add_css_class("success")
            self.next.set_sensitive(True)
        else:
            self.verdict.set_text("Not there yet.")
            self.verdict.remove_css_class("success")
            self.verdict.add_css_class("dim-label")
            self.next.set_sensitive(False)

    def _unwatch(self):
        if self._watch is not None:
            self.session.disconnect(self._watch)
            self._watch = None
        self.live = None

    def _hint(self, card):
        try:
            steps = solve(self.session.cube)
        except Unsolvable:
            self.hint_label.set_text("This cube state does not look solvable.")
            return
        if not steps:
            self.hint_label.set_text("The cube is already solved.")
            return
        step = steps[0]
        self.hint_label.set_text(
            f"{stage_title(step.stage, self.session.size)}: "
            f"{step.label} — {step.text}")

    def _scramble(self):
        self.session.reset()
        self._play(random_scramble_2x2(11) if self.session.size == 2
                   else random_scramble(22))

    def _reset_demo(self):
        self.session.reset()
        if self._alg_view is not None:
            self._alg_view.set_cube(self.session.cube.copy())

    def _play(self, moves):
        self._queue.extend(tokenize(moves))
        if not self._playing:
            self._playing = True
            GLib.timeout_add(140, self._advance)

    def _advance(self):
        if not self._queue:
            self._playing = False
            return False
        move = self._queue.pop(0)
        before = self.session.cube.copy()
        self.session.apply_move(move)
        face, rest = move[0], move[1:]
        quarters = 2 if rest == "2" else (3 if rest == "'" else 1)
        for view in (self._alg_view, self.live):
            if view is not None:
                view.set_cube(before)
                view.animate(face, quarters, self.session.cube.copy())
        return True
