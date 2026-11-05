import builtins

from ufo.setup.prompts import TerminalPrompter


def feed(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(it))


def test_ask_uses_the_default_on_enter_and_reprompts_without_one(monkeypatch):
    feed(monkeypatch, ["", "x"])
    p = TerminalPrompter()
    assert p.ask("k", "Day", "14") == "14"
    assert p.ask("k", "Name") == "x"  # an empty answer is not accepted when there is no default


def test_confirm_defaults_and_yes_no(monkeypatch):
    feed(monkeypatch, ["", "n", "Yes", "", "y"])
    p = TerminalPrompter()
    assert p.confirm("k", "?", True) is True
    assert p.confirm("k", "?", True) is False
    assert p.confirm("k", "?", False) is True
    assert p.confirm("k", "?", False) is False
    assert p.confirm("k", "?", False) is True


def test_choose_rejects_bad_numbers_and_returns_a_zero_based_index(monkeypatch):
    feed(monkeypatch, ["0", "9", "abc", "2"])
    assert TerminalPrompter().choose("k", "Pick", ["a", "b", "c"]) == 1


def test_choose_many_parses_lists_and_allows_none(monkeypatch):
    feed(monkeypatch, ["", "1, 3", "2,x", "7", "3,1"])
    p = TerminalPrompter()
    assert p.choose_many("k", "Pick", ["a", "b", "c"]) == []
    assert p.choose_many("k", "Pick", ["a", "b", "c"]) == [0, 2]
    assert p.choose_many("k", "Pick", ["a", "b", "c"]) == [0, 2]  # "2,x" and "7" are rejected, then "3,1" is accepted


def test_secret_is_read_hidden(monkeypatch):
    import getpass

    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "  tok  ")
    assert TerminalPrompter().secret("k", "Token") == "tok"
