from __future__ import annotations

import pytest

from synapse.profiles.models import ABTestResult, UserProfile
from synapse.profiles.store import ProfileStore


class TestUserProfile:
    def test_to_dict_roundtrip(self):
        profile = UserProfile(
            name="alice",
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            preferred_volume_range=(0.2, 0.5),
            preferred_patterns=["starter-gentle"],
            notes="likes slow patterns",
        )
        d = profile.to_dict()
        assert d["name"] == "alice"
        assert d["preferred_volume_range"] == [0.2, 0.5]
        restored = UserProfile.from_dict(d)
        assert restored.name == profile.name
        assert restored.preferred_volume_range == (0.2, 0.5)
        assert restored.preferred_patterns == ["starter-gentle"]
        assert restored.notes == "likes slow patterns"

    def test_from_dict_defaults(self):
        profile = UserProfile.from_dict({
            "name": "bob",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        })
        assert profile.session_count == 0
        assert profile.total_duration_s == 0.0
        assert profile.preferred_patterns == []
        assert profile.tags == {}


class TestABTestResult:
    def test_new_generates_uuid(self):
        test = ABTestResult.new("carrier_freq", {"hz": 600}, {"hz": 800})
        assert len(test.test_id) == 36  # UUID4 format
        assert test.variable == "carrier_freq"
        assert test.winner is None

    def test_to_dict_roundtrip(self):
        test = ABTestResult.new("pattern", {"name": "gentle"}, {"name": "moderate"})
        test.winner = "a"
        test.notes = "preferred gentler"
        d = test.to_dict()
        restored = ABTestResult.from_dict(d)
        assert restored.test_id == test.test_id
        assert restored.winner == "a"
        assert restored.notes == "preferred gentler"


class TestProfileStore:
    def test_create_and_get(self, tmp_path):
        store = ProfileStore(str(tmp_path))
        profile = store.create("alice")
        assert profile.name == "alice"
        fetched = store.get("alice")
        assert fetched is not None
        assert fetched.name == "alice"

    def test_get_nonexistent(self, tmp_path):
        store = ProfileStore(str(tmp_path))
        assert store.get("nobody") is None

    def test_list(self, tmp_path):
        store = ProfileStore(str(tmp_path))
        store.create("alice")
        store.create("bob")
        profiles = store.list()
        names = [p.name for p in profiles]
        assert "alice" in names
        assert "bob" in names

    def test_save_and_reload(self, tmp_path):
        store = ProfileStore(str(tmp_path))
        profile = store.create("alice")
        profile.notes = "test notes"
        profile.session_count = 3
        store.save(profile)

        reloaded = store.get("alice")
        assert reloaded is not None
        assert reloaded.notes == "test notes"
        assert reloaded.session_count == 3

    def test_delete(self, tmp_path):
        store = ProfileStore(str(tmp_path))
        store.create("alice")
        removed = store.delete("alice")
        assert removed is True
        assert store.get("alice") is None

    def test_delete_nonexistent(self, tmp_path):
        store = ProfileStore(str(tmp_path))
        assert store.delete("nobody") is False

    def test_update_partial(self, tmp_path):
        store = ProfileStore(str(tmp_path))
        store.create("alice")
        updated = store.update("alice", notes="updated note", session_count=5)
        assert updated is not None
        assert updated.notes == "updated note"
        assert updated.session_count == 5
        # Other fields unchanged
        reloaded = store.get("alice")
        assert reloaded is not None
        assert reloaded.session_count == 5

    def test_update_nonexistent(self, tmp_path):
        store = ProfileStore(str(tmp_path))
        result = store.update("nobody", notes="test")
        assert result is None

    def test_update_sets_updated_at(self, tmp_path):
        store = ProfileStore(str(tmp_path))
        profile = store.create("alice")
        old_updated_at = profile.updated_at
        updated = store.update("alice", notes="new note")
        assert updated is not None
        # updated_at should be >= old value (might be equal in fast tests)
        assert updated.updated_at >= old_updated_at

    def test_update_preferred_volume_range(self, tmp_path):
        store = ProfileStore(str(tmp_path))
        store.create("alice")
        updated = store.update("alice", preferred_volume_range=[0.3, 0.7])
        assert updated is not None
        assert updated.preferred_volume_range == (0.3, 0.7)

    def test_ab_test_recording(self, tmp_path):
        store = ProfileStore(str(tmp_path))
        profile = store.create("alice")

        # Simulate storing an A/B test in tags
        from synapse.profiles.models import ABTestResult
        test = ABTestResult.new("carrier_freq", {"hz": 600}, {"hz": 800})
        profile.tags["ab_tests"] = [test.to_dict()]
        store.save(profile)

        reloaded = store.get("alice")
        assert reloaded is not None
        ab_tests = reloaded.tags.get("ab_tests", [])
        assert len(ab_tests) == 1
        assert ab_tests[0]["variable"] == "carrier_freq"

    def test_profile_yaml_format(self, tmp_path):
        """Profile file should be valid YAML."""
        import yaml
        store = ProfileStore(str(tmp_path))
        profile = store.create("alice")
        profile.preferred_patterns = ["starter-gentle", "starter-moderate"]
        store.save(profile)

        yaml_path = tmp_path / "alice.yaml"
        assert yaml_path.exists()
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["name"] == "alice"
        assert data["preferred_patterns"] == ["starter-gentle", "starter-moderate"]
