from dumbbot.storage import HistoryStore


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def test_append_and_recent(tmp_path):
    store = HistoryStore(str(tmp_path / "h.db"))
    store.append_turn("+1", "hi", "hello")
    store.append_turn("+1", "how are you", "fine")
    assert store.recent("+1", 10) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "how are you"},
        {"role": "assistant", "content": "fine"},
    ]


def test_recent_limits_to_last_n_turns(tmp_path):
    store = HistoryStore(str(tmp_path / "h.db"))
    for i in range(15):
        store.append_turn("+1", f"q{i}", f"a{i}")
    history = store.recent("+1", 3)
    assert [m["content"] for m in history] == ["q12", "a12", "q13", "a13", "q14", "a14"]
    assert history[0]["role"] == "user"


def test_numbers_are_isolated(tmp_path):
    store = HistoryStore(str(tmp_path / "h.db"))
    store.append_turn("+1", "mine", "ok")
    store.append_turn("+2", "theirs", "ok")
    assert [m["content"] for m in store.recent("+1", 10)] == ["mine", "ok"]
    store.clear("+1")
    assert store.recent("+1", 10) == []
    assert len(store.recent("+2", 10)) == 2


def test_history_expires_after_ttl(tmp_path):
    clock = Clock()
    store = HistoryStore(str(tmp_path / "h.db"), ttl_hours=12, clock=clock)
    store.append_turn("+1", "hi", "hello")
    clock.now += 11 * 3600
    assert len(store.recent("+1", 10)) == 2
    clock.now += 2 * 3600  # 13h since last activity
    assert store.recent("+1", 10) == []


def test_activity_extends_ttl(tmp_path):
    clock = Clock()
    store = HistoryStore(str(tmp_path / "h.db"), ttl_hours=12, clock=clock)
    store.append_turn("+1", "first", "a")
    clock.now += 10 * 3600
    store.append_turn("+1", "second", "b")
    clock.now += 10 * 3600  # 20h since first, 10h since last
    assert [m["content"] for m in store.recent("+1", 10)] == ["first", "a", "second", "b"]


def test_append_prunes_other_stale_conversations(tmp_path):
    clock = Clock()
    path = str(tmp_path / "h.db")
    store = HistoryStore(path, ttl_hours=1, clock=clock)
    store.append_turn("+old", "x", "y")
    clock.now += 2 * 3600
    store.append_turn("+new", "x", "y")

    import sqlite3

    with sqlite3.connect(path) as conn:
        numbers = {r[0] for r in conn.execute("SELECT from_number FROM messages")}
    assert numbers == {"+new"}
