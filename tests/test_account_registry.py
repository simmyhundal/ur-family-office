import json
import stat

import pytest

from ufo.accounts.registry import RegistryError, load_registry, missing_files, registry_path
from ufo.setup import accounts as wiz


class Script:
    def __init__(self, **a):
        self.a, self.said = a, []

    def say(self, text=""):
        self.said.append(text)

    def ask(self, key, text, default=None):
        v = self.a.get(key, default)
        return str(v.pop(0) if isinstance(v, list) else v)

    def choose(self, key, text, options):
        v = self.a.get(key, 0)
        return v.pop(0) if isinstance(v, list) else v


def test_example_file_loads():
    from pathlib import Path
    reg = load_registry(Path("docs/accounts.example.json"))
    assert [a.id for a in reg.accounts] == ["brokerage-a-taxable", "example-roth"]


def test_wizard_adds_an_invented_account_end_to_end(tmp_path):
    s = Script(action=[1, 0], label="Test brokerage", id="test-1", brokerage=0, wrapper=2, digits="9999", owner="partner",
               opened="2020-02-02", closed="-", history_glob="exports/t/History*.csv", end_kind=0, end_value="$1,234.50",
               end_as_of="2026-10-31")
    wiz.run(s, tmp_path)
    path = registry_path(tmp_path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    reg = load_registry(path)
    a = reg.accounts[0]
    assert (a.id, a.wrapper.value, a.owner, a.ending_value.value) == ("test-1", "roth_ira", "partner", 1234.5)
    assert a.last_digits == "9999" and a.is_closed is False


def test_wizard_rejects_a_duplicate_id_and_caps_retries(tmp_path):
    s = Script(action=[1, 0], label="X", id="dup", brokerage=0, wrapper=0, history_glob="g", end_kind=0, end_value="1", end_as_of="2026-01-01")
    wiz.run(s, tmp_path)
    s2 = Script(action=[1, 0], label="X", id="dup", brokerage=0, wrapper=0, history_glob="g", end_kind=0, end_value="1", end_as_of="2026-01-01")
    wiz.run(s2, tmp_path)  # second add: id is taken on every try, so the cap stops it
    assert any("already used" in t for t in s2.said)
    assert len(load_registry(registry_path(tmp_path)).accounts) == 1


@pytest.mark.parametrize("text,expect", [
    ("{not json", "not valid JSON"),
    ('{"accounts": [{"id": "a", "label": "A", "brokerage": "nowhere", "source": {"importer": "x", "history_glob": "g"}}]}', "unknown brokerage"),
    ('{"accounts": [{"id": "a", "label": "A", "brokerage": "fidelity", "source": {"importer": "fidelity", "history_glob": "g"}},'
     ' {"id": "a", "label": "B", "brokerage": "fidelity", "source": {"importer": "fidelity", "history_glob": "g"}}]}', "duplicate"),
])
def test_bad_file_gives_a_plain_message(tmp_path, text, expect):
    p = registry_path(tmp_path)
    p.parent.mkdir()
    p.write_text(text)
    with pytest.raises(RegistryError, match=expect):
        load_registry(p)
    s = Script(action=0)
    wiz.run(s, tmp_path)  # the wizard reports it instead of crashing
    assert any(expect in t for t in s.said)


def test_missing_registry_is_empty_and_missing_files_are_reported(tmp_path):
    assert load_registry(registry_path(tmp_path)).accounts == []
    p = registry_path(tmp_path)
    p.parent.mkdir()
    p.write_text(json.dumps({"accounts": [{"id": "a", "label": "A", "brokerage": "fidelity",
                                          "source": {"importer": "fidelity", "history_glob": "nope/*.csv"}}]}))
    a = load_registry(p).accounts[0]
    assert "no history files match" in missing_files(a, tmp_path)[0]
