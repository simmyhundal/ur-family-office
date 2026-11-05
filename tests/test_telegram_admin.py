from ufo.providers.telegram_admin import TelegramAdmin


class Admin(TelegramAdmin):
    def __init__(self, updates, me=None):
        super().__init__("t")
        self.updates, self._me = updates, me or {"username": "b", "can_join_groups": True}

    def _call(self, method, payload=None):
        return {"getUpdates": self.updates, "getMe": self._me, "getWebhookInfo": {"url": ""}}.get(method, {})


def test_direct_chats_and_groups_both_count_and_other_updates_are_ignored():
    ups = [
        {"message": {"chat": {"id": 1, "type": "private", "first_name": "Pat", "last_name": "Example"}, "text": "/start"}},
        {"message": {"chat": {"id": -5, "type": "group", "title": "Household"}, "text": "/start"}},
        {"my_chat_member": {"chat": {"id": -6, "type": "supergroup", "title": "Other"}}},
        {"message": {"chat": {"id": 9, "type": "channel", "title": "News"}}},
        {"edited_message": {"chat": {"id": 7, "type": "private", "first_name": "Edit"}}},
    ]
    assert Admin(ups).chats_that_messaged() == {1: "Pat Example", -5: "Household (group)", -6: "Other (group)"}


def test_hardening_warns_about_groups_only_when_no_group_is_used():
    a = Admin([])
    a._call = lambda m, p=None: {"getMe": {"username": "b", "can_join_groups": True}, "getWebhookInfo": {"url": ""}}.get(m, {})
    assert any("Allow Groups" in w for w in a.harden())
    assert a.harden(uses_group=True) == []
