"""Tests for the Memory system (§18.3)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from synapse.profiles.store import ProfileStore
from synapse.profiles.models import Memory


@pytest.fixture
def profile_store(tmp_path: Path) -> ProfileStore:
    store = ProfileStore(str(tmp_path / "profiles"))
    store.create("alice")
    return store


def test_add_memory_returns_memory(profile_store: ProfileStore) -> None:
    mem = profile_store.add_memory("alice", "Prefers slow oscillation", "preference")
    assert isinstance(mem, Memory)
    assert mem.text == "Prefers slow oscillation"
    assert mem.category == "preference"
    assert mem.id  # has uuid
    assert mem.created_at  # has timestamp


def test_add_memory_with_session(profile_store: ProfileStore) -> None:
    mem = profile_store.add_memory("alice", "Spiked at 0.4", "observation", session_name="sess1")
    assert mem.session_name == "sess1"


def test_get_memories_all(profile_store: ProfileStore) -> None:
    profile_store.add_memory("alice", "Likes circular", "preference")
    profile_store.add_memory("alice", "Dislikes fast pulse", "reaction")
    memories = profile_store.get_memories("alice")
    assert len(memories) == 2


def test_get_memories_with_query(profile_store: ProfileStore) -> None:
    profile_store.add_memory("alice", "Likes circular motion", "preference")
    profile_store.add_memory("alice", "Dislikes fast pulse", "reaction")
    memories = profile_store.get_memories("alice", query="circular")
    assert len(memories) == 1
    assert "circular" in memories[0].text


def test_get_memories_case_insensitive(profile_store: ProfileStore) -> None:
    profile_store.add_memory("alice", "Likes CIRCULAR motion", "preference")
    memories = profile_store.get_memories("alice", query="circular")
    assert len(memories) == 1


def test_get_memories_empty_query_returns_all(profile_store: ProfileStore) -> None:
    profile_store.add_memory("alice", "One", "general")
    profile_store.add_memory("alice", "Two", "general")
    assert len(profile_store.get_memories("alice", query="")) == 2


def test_delete_memory(profile_store: ProfileStore) -> None:
    mem = profile_store.add_memory("alice", "Todo: try higher freq", "todo")
    result = profile_store.delete_memory("alice", mem.id)
    assert result is True
    memories = profile_store.get_memories("alice")
    assert not any(m.id == mem.id for m in memories)


def test_delete_nonexistent_memory(profile_store: ProfileStore) -> None:
    result = profile_store.delete_memory("alice", "nonexistent-id")
    assert result is False


def test_memories_survive_save_load_roundtrip(profile_store: ProfileStore) -> None:
    mem1 = profile_store.add_memory("alice", "First memory", "preference")
    mem2 = profile_store.add_memory("alice", "Second memory", "reaction")

    # Reload from disk
    store2 = ProfileStore(str(Path(profile_store._dir)))
    memories = store2.get_memories("alice")
    assert len(memories) == 2
    ids = {m.id for m in memories}
    assert mem1.id in ids
    assert mem2.id in ids


def test_memories_nonexistent_profile(profile_store: ProfileStore) -> None:
    memories = profile_store.get_memories("nobody")
    assert memories == []


def test_delete_memory_nonexistent_profile(profile_store: ProfileStore) -> None:
    result = profile_store.delete_memory("nobody", "some-id")
    assert result is False


def test_add_memory_nonexistent_profile(profile_store: ProfileStore) -> None:
    with pytest.raises(ValueError, match="not found"):
        profile_store.add_memory("nobody", "some text")
