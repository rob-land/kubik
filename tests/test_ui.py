"""End-to-end: build the real window and drive it.

Not a screenshot test — it exercises the code paths a user hits (switch pages,
walk every lesson card, scramble, solve, play a solution back, record a solve)
and fails on any exception or GTK criticality along the way.
"""

import os
import tempfile
from pathlib import Path

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from conftest import gresource_available  # noqa: E402

if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
    pytest.skip("needs a display", allow_module_level=True)
if not gresource_available():
    pytest.skip("UI bundle not built; run meson compile first",
                allow_module_level=True)

Adw.init()

from kubik.cube import Cube  # noqa: E402
from kubik.store import Store  # noqa: E402
from kubik.views.learn import LessonPage  # noqa: E402
from kubik.window import KubikWindow  # noqa: E402


def _memory_settings() -> Gio.Settings:
    """A throwaway GSettings so tests do not leak state through dconf.

    The window persists the selected puzzle, so a real backend would let one
    test decide which cube the next one starts on.
    """
    source = Gio.SettingsSchemaSource.get_default()
    schema = source.lookup("land.rob.kubik", True)
    assert schema is not None, "schema not compiled; see conftest"
    return Gio.Settings.new_full(schema, Gio.memory_settings_backend_new(),
                                 None)


@pytest.fixture(scope="session")
def app():
    """One registered application for the whole run — the id is a bus name."""
    from gi.repository import Gio

    application = Adw.Application(
        application_id="io.github.kubik.Kubik.Test",
        flags=Gio.ApplicationFlags.NON_UNIQUE)
    application.register()  # windows may only be added after startup
    return application


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr("kubik.window.Store",
                        lambda: Store(tmp_path / "solves.db"))
    win = KubikWindow(application=app, settings=_memory_settings())
    yield win
    win.destroy()


def pump(iterations=60):
    context = GLib.MainContext.default()
    for _ in range(iterations):
        while context.pending():
            context.iteration(False)


def test_window_builds_with_all_pages(window):
    names = [p.get_name() for p in window.view_stack.get_pages()]
    assert names == ["learn", "play", "solve", "timer", "cubes"]


def test_switching_pages(window):
    for name in ("play", "solve", "timer", "cubes", "learn"):
        window.view_stack.set_visible_child_name(name)
        pump(5)
        assert window.view_stack.get_visible_child_name() == name


def test_narrow_and_wide_layouts(window):
    window._on_wide(None, False)
    assert window.header.get_title_widget() is window.window_title
    window._on_wide(None, True)
    assert window.header.get_title_widget() is window.switcher


def test_play_scramble_and_solve(window):
    play = window.view_stack.get_child_by_name("play")
    play._scramble(None)
    # Playback is timer-driven; drain the queue synchronously instead.
    while play._queue:
        play._advance()
    assert not window.session.cube.is_solved()

    play._solve(None)
    assert play.solution.get_visible()
    rows = []
    child = play.solution.get_first_child()
    while child is not None:
        rows.append(child)
        child = child.get_next_sibling()
    assert rows, "the solver produced no steps"

    for row in rows:
        play._play(row.get_title())
    while play._queue:
        play._advance()
    assert window.session.cube.is_solved()


def test_play_move_pad_drives_the_session(window):
    play = window.view_stack.get_child_by_name("play")
    play._reset(None)
    play._on_pad("R")
    assert window.session.cube == Cube().apply("R")
    play._reset(None)
    assert window.session.cube.is_solved()


def test_every_lesson_card_renders(window):
    learn = window.view_stack.get_child_by_name("learn")
    for lesson in learn.lessons:
        page = LessonPage(lesson, window.session, window.store, lambda: None)
        for index in range(len(lesson.cards)):
            page.index = index
            page._render()
            pump(2)
            assert page.content.get_first_child() is not None
        page._unwatch()


def test_quiz_gates_the_next_button(window):
    learn = window.view_stack.get_child_by_name("learn")
    lesson = next(l for l in learn.lessons
                  if any(c.kind == "quiz" for c in l.cards))
    page = LessonPage(lesson, window.session, window.store, lambda: None)
    index = next(i for i, c in enumerate(lesson.cards) if c.kind == "quiz")
    page.index = index
    page._render()
    card = lesson.cards[index]
    assert not page.next.get_sensitive()

    group = page.content.get_last_child().get_prev_sibling()
    buttons = []
    child = group.get_first_child()
    while child is not None:
        buttons.append(child)
        child = child.get_next_sibling()

    wrong = next(i for i in range(len(card.options)) if i != card.answer)
    buttons[wrong].emit("clicked")
    assert not page.next.get_sensitive()
    buttons[card.answer].emit("clicked")
    assert page.next.get_sensitive()
    page._unwatch()


def test_do_card_unlocks_when_the_goal_is_reached(window):
    learn = window.view_stack.get_child_by_name("learn")
    lesson = next(l for l in learn.lessons if l.id == "daisy")
    page = LessonPage(lesson, window.session, window.store, lambda: None)
    page.index = next(i for i, c in enumerate(lesson.cards) if c.kind == "do")
    window.session.reset()
    page._render()
    assert not page.next.get_sensitive(), "a solved cube is not a daisy"

    window.session.reset(Cube().apply("F2 R2 B2 L2"))
    pump(2)
    assert page.next.get_sensitive()
    page._unwatch()


def test_hint_names_a_step(window):
    learn = window.view_stack.get_child_by_name("learn")
    lesson = next(l for l in learn.lessons if l.id == "white-cross")
    page = LessonPage(lesson, window.session, window.store, lambda: None)
    page.index = next(i for i, c in enumerate(lesson.cards) if c.kind == "do")
    window.session.reset(Cube().apply("R U R' F2 L D B'"))
    page._render()
    page._hint(lesson.cards[page.index])
    assert page.hint_label.get_text().strip()
    page._unwatch()


def test_finishing_a_lesson_records_progress(window):
    learn = window.view_stack.get_child_by_name("learn")
    lesson = learn.lessons[0]
    page = LessonPage(lesson, window.session, window.store, learn.refresh)
    page.index = len(lesson.cards) - 1
    page._go(1)
    assert lesson.id in window.store.completed()
    learn.refresh()
    assert learn._rows[lesson.id].get_visible()


def test_timer_records_and_averages(window):
    timer = window.view_stack.get_child_by_name("timer")
    for millis in (12000, 11000, 13000, 10000, 14000):
        window.store.add_solve(millis, "R U R'", 40)
    timer.refresh()
    assert window.store.count() == 5
    assert timer.stat_rows["best"].get_text() == "10.000"
    assert timer.stat_rows["ao5"].get_text() == "12.000"
    assert timer.stat_rows["ao12"].get_text() == "—"


def test_timer_arms_on_the_scramble_not_during_it(window):
    """A connected cube must not start the clock while you are scrambling."""
    timer = window.view_stack.get_child_by_name("timer")
    window.session.connected = True
    timer.new_scramble()
    window.session.reset()

    for move in timer.scramble[:-1]:
        window.session.apply_move(move)
        assert not timer.armed
        assert timer.state != 2  # RUNNING

    window.session.apply_move(timer.scramble[-1])
    assert timer.armed, "should arm once the cube matches the scramble"
    assert timer.state != 2, "arming is not starting"

    window.session.apply_move("R")
    assert timer.state == 2, "the first solving turn starts the clock"

    window.session.reset()  # pretend the solve finished
    window.session.apply_move("U")
    window.session.apply_move("U'")
    assert timer.state != 2, "a solved cube stops the clock"
    assert window.store.count() >= 1


def _switch(window, puzzle):
    from gi.repository import GLib

    window.puzzle_action.activate(GLib.Variant("s", puzzle))
    pump(5)


def test_switching_puzzle_updates_everything(window):
    from kubik.cube import Cube2

    _switch(window, "2x2")
    assert window.session.cube_type == "2x2"
    assert isinstance(window.session.cube, Cube2)
    assert window.puzzle_action.get_state().get_string() == "2x2"

    learn = window.view_stack.get_child_by_name("learn")
    assert learn.lessons
    assert all(l.cube == "2x2" for l in learn.lessons)
    assert window.view_stack.get_child_by_name("timer").target.size == 2

    _switch(window, "3x3")
    assert window.session.cube_type == "3x3"
    assert all(l.cube == "3x3" for l in learn.lessons)


def test_play_scramble_and_solve_a_2x2(window):
    _switch(window, "2x2")
    play = window.view_stack.get_child_by_name("play")
    play._scramble(None)
    while play._queue:
        play._advance()
    assert not window.session.cube.is_solved()
    play._solve(None)
    rows, child = [], play.solution.get_first_child()
    while child is not None:
        rows.append(child)
        child = child.get_next_sibling()
    assert rows
    for row in rows:
        play._play(row.get_title())
    while play._queue:
        play._advance()
    assert window.session.cube.is_solved()


def test_every_2x2_lesson_card_renders(window):
    _switch(window, "2x2")
    learn = window.view_stack.get_child_by_name("learn")
    for lesson in learn.lessons:
        page = LessonPage(lesson, window.session, window.store, lambda: None)
        for index in range(len(lesson.cards)):
            page.index = index
            page._render()
            pump(2)
            assert page.content.get_first_child() is not None
        page._unwatch()


def test_2x2_do_card_unlocks_on_its_goal(window):
    _switch(window, "2x2")
    learn = window.view_stack.get_child_by_name("learn")
    lesson = next(l for l in learn.lessons if l.id == "2x2-yellow-face")
    page = LessonPage(lesson, window.session, window.store, lambda: None)
    page.index = next(i for i, c in enumerate(lesson.cards) if c.kind == "do")
    window.session.reset()
    window.session.apply_sequence("R U R' U R U2 R'")  # breaks the yellow face
    page._render()
    assert not page.next.get_sensitive()
    window.session.reset()
    pump(2)
    assert page.next.get_sensitive()
    page._unwatch()


def test_timer_keeps_separate_statistics_per_puzzle(window):
    timer = window.view_stack.get_child_by_name("timer")
    for millis in (12000, 11000, 13000):
        window.store.add_solve(millis, "R U", 40, "3x3")
    window.store.add_solve(4000, "R U", 10, "2x2")

    timer.refresh()
    assert timer.stat_rows["best"].get_text() == "11.000"
    assert timer.stat_rows["count"].get_text() == "3"

    _switch(window, "2x2")
    assert timer.stat_rows["best"].get_text() == "4.000"
    assert timer.stat_rows["count"].get_text() == "1"


def test_2x2_scramble_is_shorter_and_uses_three_faces(window):
    timer = window.view_stack.get_child_by_name("timer")
    _switch(window, "2x2")
    assert len(timer.scramble) == 11
    assert {m[0] for m in timer.scramble} <= set("URF")


def test_devices_lists_every_driver(window):
    from kubik.ble.driver import drivers

    devices = window.view_stack.get_child_by_name("cubes")
    assert devices is not None
    assert len(drivers()) >= 6


# --- Solve: entering a cube by hand -------------------------------------------

def _solve_view(window):
    return window.view_stack.get_child_by_name("solve")


def test_solve_view_starts_with_centres_only(window):
    view = _solve_view(window)
    assert view.partial.entered == 0
    assert not view.solve_button.get_sensitive()
    assert "48 to go" in view.status.get_text()


def test_painting_a_sticker_updates_the_model_and_status(window):
    view = _solve_view(window)
    view._brush = 1
    view._on_sticker(view.editor, 8)
    assert view.partial.facelets[8] == 1
    assert view.partial.is_user_set(8)
    assert "47 to go" in view.status.get_text()


def test_the_eraser_clears_a_sticker(window):
    view = _solve_view(window)
    view._brush = 1
    view._on_sticker(view.editor, 8)
    view._brush = None
    view._on_sticker(view.editor, 8)
    assert view.partial.facelets[8] is None


def test_entering_a_whole_cube_enables_solving(window):
    from kubik.cube import Cube
    from kubik.facelets import CENTRES

    view = _solve_view(window)
    target = Cube().apply("R U R' U' F2 L D B'").to_facelets()
    for index in range(54):
        if index in CENTRES or view.partial.facelets[index] is not None:
            continue
        view._brush = target[index]
        view._on_sticker(view.editor, index)
    assert view.partial.complete
    assert view.solve_button.get_sensitive()

    view._on_solve(view.solve_button)
    assert view.solution.get_visible()
    rows = []
    child = view.solution.get_first_child()
    while child is not None:
        rows.append(child.get_title())
        child = child.get_next_sibling()
    assert rows
    # The solution has to actually solve the cube that was entered.
    moves = [m for row in rows for m in row.split()]
    assert Cube.from_facelets(target).apply(moves).is_solved()
    # ... and the rest of the app now holds that cube.
    assert window.session.cube == Cube.from_facelets(target)


def test_seeding_from_the_connected_cube(window):
    from kubik.cube import Cube

    window.session.reset(Cube().apply("R U F"))
    view = _solve_view(window)
    view._on_from_cube(None)
    assert view.partial.complete
    assert view.partial.to_cube() == Cube().apply("R U F")


def test_clear_resets_to_centres(window):
    view = _solve_view(window)
    view._brush = 2
    view._on_sticker(view.editor, 8)
    view._on_clear(None)
    assert view.partial.entered == 0
    assert not view.solve_button.get_sensitive()


def test_an_impossible_sticker_is_reported_not_swallowed(window):
    view = _solve_view(window)
    view._brush = 0
    view._on_sticker(view.editor, 8)
    view._on_sticker(view.editor, 9)      # two whites on one corner
    assert not view.solve_button.get_sensitive()
    assert "URF" in view.status.get_text()


def test_exhausted_colours_are_disabled_in_the_palette(window):
    view = _solve_view(window)
    view._brush = 3
    for index in (0, 1, 2, 3, 5, 6, 7, 8):
        view._on_sticker(view.editor, index)
    # Eight yellows plus the yellow centre is all nine.
    assert view.partial.remaining(3) == 0
    view._brush = 0
    view._refresh()
    assert not view._swatches[3].get_sensitive()
