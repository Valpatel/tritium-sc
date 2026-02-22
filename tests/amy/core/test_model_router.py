"""Unit tests for ModelRouter — task-aware model selection with fleet fallback.

Tests TaskType classification, ModelProfile, model selection chains,
fallback behavior, and fleet integration. Written TDD-first — these tests
define the contract before implementation.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ===========================================================================
# TaskType Enum
# ===========================================================================

@pytest.mark.unit
class TestTaskType:
    """TaskType — inference task classification."""

    def test_simple_think_exists(self):
        from amy.inference.model_router import TaskType
        assert TaskType.SIMPLE_THINK is not None

    def test_complex_reason_exists(self):
        from amy.inference.model_router import TaskType
        assert TaskType.COMPLEX_REASON is not None

    def test_vision_exists(self):
        from amy.inference.model_router import TaskType
        assert TaskType.VISION is not None

    def test_code_gen_exists(self):
        from amy.inference.model_router import TaskType
        assert TaskType.CODE_GEN is not None

    def test_chat_exists(self):
        from amy.inference.model_router import TaskType
        assert TaskType.CHAT is not None

    def test_all_values_unique(self):
        from amy.inference.model_router import TaskType
        values = [t.value for t in TaskType]
        assert len(values) == len(set(values))


# ===========================================================================
# ModelProfile Dataclass
# ===========================================================================

@pytest.mark.unit
class TestModelProfile:
    """ModelProfile — model capability metadata."""

    def test_construction(self):
        from amy.inference.model_router import ModelProfile
        p = ModelProfile(
            name="gemma3:4b",
            capabilities={"text"},
            speed="fast",
            context_length=8192,
            priority=1,
        )
        assert p.name == "gemma3:4b"
        assert "text" in p.capabilities

    def test_has_capability(self):
        from amy.inference.model_router import ModelProfile
        p = ModelProfile(
            name="llava:7b",
            capabilities={"text", "vision"},
            speed="medium",
            context_length=4096,
            priority=2,
        )
        assert p.has_capability("vision")
        assert p.has_capability("text")
        assert not p.has_capability("code")

    def test_defaults(self):
        from amy.inference.model_router import ModelProfile
        p = ModelProfile(name="test:1b")
        assert p.capabilities == {"text"}
        assert p.speed == "fast"
        assert p.context_length == 4096
        assert p.priority == 10

    def test_to_dict(self):
        from amy.inference.model_router import ModelProfile
        p = ModelProfile(name="gemma3:4b", capabilities={"text", "code"})
        d = p.to_dict()
        assert d["name"] == "gemma3:4b"
        assert "text" in d["capabilities"]
        assert "code" in d["capabilities"]
        assert isinstance(d, dict)


# ===========================================================================
# ModelRouter — Construction
# ===========================================================================

@pytest.mark.unit
class TestModelRouterInit:
    """ModelRouter — initialization and profile registration."""

    def test_construction_no_fleet(self):
        from amy.inference.model_router import ModelRouter
        router = ModelRouter()
        assert router is not None

    def test_construction_with_profiles(self):
        from amy.inference.model_router import ModelRouter, ModelProfile
        profiles = [
            ModelProfile(name="gemma3:4b", capabilities={"text"}, priority=1),
            ModelProfile(name="llava:7b", capabilities={"text", "vision"}, priority=2),
        ]
        router = ModelRouter(profiles=profiles)
        assert len(router.profiles) == 2

    def test_register_profile(self):
        from amy.inference.model_router import ModelRouter, ModelProfile
        router = ModelRouter()
        router.register(ModelProfile(name="test:1b"))
        assert len(router.profiles) == 1

    def test_register_replaces_existing(self):
        from amy.inference.model_router import ModelRouter, ModelProfile
        router = ModelRouter()
        router.register(ModelProfile(name="test:1b", priority=10))
        router.register(ModelProfile(name="test:1b", priority=1))
        assert len(router.profiles) == 1
        assert router.profiles[0].priority == 1

    def test_unregister(self):
        from amy.inference.model_router import ModelRouter, ModelProfile
        router = ModelRouter()
        router.register(ModelProfile(name="test:1b"))
        router.unregister("test:1b")
        assert len(router.profiles) == 0

    def test_unregister_missing_no_error(self):
        from amy.inference.model_router import ModelRouter
        router = ModelRouter()
        router.unregister("nonexistent")  # Should not raise

    def test_get_profile(self):
        from amy.inference.model_router import ModelRouter, ModelProfile
        router = ModelRouter()
        router.register(ModelProfile(name="gemma3:4b"))
        p = router.get_profile("gemma3:4b")
        assert p is not None
        assert p.name == "gemma3:4b"

    def test_get_profile_missing(self):
        from amy.inference.model_router import ModelRouter
        router = ModelRouter()
        assert router.get_profile("nonexistent") is None


# ===========================================================================
# ModelRouter — Task Classification
# ===========================================================================

@pytest.mark.unit
class TestModelRouterClassify:
    """ModelRouter.classify_task — infer TaskType from context."""

    def test_classify_simple_think(self):
        from amy.inference.model_router import ModelRouter, TaskType
        router = ModelRouter()
        tt = router.classify_task(messages=[
            {"role": "user", "content": "What do you do next?"},
        ], context={"battlespace_empty": True, "people_present": False})
        assert tt == TaskType.SIMPLE_THINK

    def test_classify_complex_reason_battlespace(self):
        from amy.inference.model_router import ModelRouter, TaskType
        router = ModelRouter()
        tt = router.classify_task(messages=[
            {"role": "user", "content": "What do you do next?"},
        ], context={"hostile_count": 3, "active_threats": 2})
        assert tt == TaskType.COMPLEX_REASON

    def test_classify_vision_with_images(self):
        from amy.inference.model_router import ModelRouter, TaskType
        router = ModelRouter()
        tt = router.classify_task(messages=[
            {"role": "user", "content": "Describe what you see."},
        ], has_images=True)
        assert tt == TaskType.VISION

    def test_classify_chat_with_transcript(self):
        from amy.inference.model_router import ModelRouter, TaskType
        router = ModelRouter()
        tt = router.classify_task(messages=[
            {"role": "user", "content": "Hey Amy, how are you?"},
        ], context={"is_chat": True})
        assert tt == TaskType.CHAT

    def test_classify_code_gen(self):
        from amy.inference.model_router import ModelRouter, TaskType
        router = ModelRouter()
        tt = router.classify_task(messages=[
            {"role": "user", "content": "Generate a patrol routine"},
        ], context={"code_gen_requested": True})
        assert tt == TaskType.CODE_GEN

    def test_classify_defaults_simple(self):
        from amy.inference.model_router import ModelRouter, TaskType
        router = ModelRouter()
        tt = router.classify_task(messages=[
            {"role": "user", "content": "What do you do next?"},
        ])
        assert tt == TaskType.SIMPLE_THINK


# ===========================================================================
# ModelRouter — Model Selection
# ===========================================================================

@pytest.mark.unit
class TestModelRouterSelect:
    """ModelRouter.select_chain — ordered model/host fallback chain."""

    def _router_with_profiles(self):
        from amy.inference.model_router import ModelRouter, ModelProfile
        profiles = [
            ModelProfile(name="orca-mini:3b", capabilities={"text"}, speed="fast", priority=1),
            ModelProfile(name="gemma3:4b", capabilities={"text", "code"}, speed="fast", priority=2),
            ModelProfile(name="llava:7b", capabilities={"text", "vision"}, speed="medium", priority=3),
            ModelProfile(name="llava:13b", capabilities={"text", "vision", "code"}, speed="slow", priority=4),
        ]
        return ModelRouter(profiles=profiles)

    def test_select_simple_prefers_fast(self):
        from amy.inference.model_router import TaskType
        router = self._router_with_profiles()
        chain = router.select_chain(TaskType.SIMPLE_THINK)
        assert len(chain) >= 1
        # First model should be the fastest text-capable
        assert chain[0].name == "orca-mini:3b"

    def test_select_vision_requires_vision(self):
        from amy.inference.model_router import TaskType
        router = self._router_with_profiles()
        chain = router.select_chain(TaskType.VISION)
        for profile in chain:
            assert "vision" in profile.capabilities

    def test_select_code_gen_requires_code(self):
        from amy.inference.model_router import TaskType
        router = self._router_with_profiles()
        chain = router.select_chain(TaskType.CODE_GEN)
        for profile in chain:
            assert "code" in profile.capabilities

    def test_select_complex_prefers_larger(self):
        from amy.inference.model_router import TaskType
        router = self._router_with_profiles()
        chain = router.select_chain(TaskType.COMPLEX_REASON)
        # Complex reasoning should prefer quality over speed
        assert len(chain) >= 1
        # The first model for complex should NOT be the smallest
        assert chain[0].name != "orca-mini:3b"

    def test_select_chat_returns_text_capable(self):
        from amy.inference.model_router import TaskType
        router = self._router_with_profiles()
        chain = router.select_chain(TaskType.CHAT)
        assert len(chain) >= 1
        for profile in chain:
            assert "text" in profile.capabilities

    def test_select_empty_profiles_returns_empty(self):
        from amy.inference.model_router import ModelRouter, TaskType
        router = ModelRouter()
        chain = router.select_chain(TaskType.SIMPLE_THINK)
        assert chain == []

    def test_select_no_matching_capability(self):
        from amy.inference.model_router import ModelRouter, ModelProfile, TaskType
        router = ModelRouter(profiles=[
            ModelProfile(name="text-only:1b", capabilities={"text"}),
        ])
        chain = router.select_chain(TaskType.VISION)
        assert chain == []


# ===========================================================================
# ModelRouter — Inference with Fallback
# ===========================================================================

@pytest.mark.unit
class TestModelRouterInfer:
    """ModelRouter.infer — call LLM with automatic fallback."""

    def _router_with_mock_fleet(self):
        from amy.inference.model_router import ModelRouter, ModelProfile
        profiles = [
            ModelProfile(name="gemma3:4b", capabilities={"text"}, priority=1),
            ModelProfile(name="llava:7b", capabilities={"text", "vision"}, priority=2),
        ]
        router = ModelRouter(profiles=profiles)
        # Mock fleet
        mock_fleet = MagicMock()
        mock_host = MagicMock()
        mock_host.url = "http://localhost:11434"
        mock_host.name = "localhost"
        mock_host.has_model.return_value = True
        mock_fleet.hosts_with_model.return_value = [mock_host]
        router._fleet = mock_fleet
        return router

    def test_infer_success(self):
        from amy.inference.model_router import TaskType
        router = self._router_with_mock_fleet()
        messages = [{"role": "user", "content": "Hello"}]

        with patch("amy.inference.model_router.ollama_chat") as mock_chat:
            mock_chat.return_value = {
                "message": {"content": "Hi there!"},
            }
            result = router.infer(TaskType.SIMPLE_THINK, messages)
            assert result["message"]["content"] == "Hi there!"
            mock_chat.assert_called_once()

    def test_infer_fallback_on_failure(self):
        from amy.inference.model_router import TaskType
        router = self._router_with_mock_fleet()
        messages = [{"role": "user", "content": "Hello"}]

        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Host down")
            return {"message": {"content": "Fallback response"}}

        with patch("amy.inference.model_router.ollama_chat", side_effect=side_effect):
            result = router.infer(TaskType.CHAT, messages)
            assert result["message"]["content"] == "Fallback response"
            assert call_count == 2

    def test_infer_all_fail_raises(self):
        from amy.inference.model_router import TaskType, AllHostsFailedError
        router = self._router_with_mock_fleet()
        messages = [{"role": "user", "content": "Hello"}]

        with patch("amy.inference.model_router.ollama_chat", side_effect=ConnectionError("Down")):
            with pytest.raises(AllHostsFailedError):
                router.infer(TaskType.SIMPLE_THINK, messages)

    def test_infer_no_fleet_uses_direct(self):
        """Without a fleet, infer() uses the first profile's model directly."""
        from amy.inference.model_router import ModelRouter, ModelProfile, TaskType
        router = ModelRouter(profiles=[
            ModelProfile(name="gemma3:4b", capabilities={"text"}, priority=1),
        ])
        messages = [{"role": "user", "content": "Hello"}]

        with patch("amy.inference.model_router.ollama_chat") as mock_chat:
            mock_chat.return_value = {"message": {"content": "OK"}}
            result = router.infer(TaskType.SIMPLE_THINK, messages)
            assert result["message"]["content"] == "OK"
            # Should be called with the model name
            call_args = mock_chat.call_args
            assert call_args[1].get("model") == "gemma3:4b" or call_args[0][0] == "gemma3:4b"

    def test_infer_vision_passes_images(self):
        from amy.inference.model_router import TaskType
        router = self._router_with_mock_fleet()
        messages = [{"role": "user", "content": "What do you see?", "images": ["base64data"]}]

        with patch("amy.inference.model_router.ollama_chat") as mock_chat:
            mock_chat.return_value = {"message": {"content": "I see a room"}}
            result = router.infer(TaskType.VISION, messages)
            assert result["message"]["content"] == "I see a room"

    def test_infer_records_model_used(self):
        from amy.inference.model_router import TaskType
        router = self._router_with_mock_fleet()
        messages = [{"role": "user", "content": "Hello"}]

        with patch("amy.inference.model_router.ollama_chat") as mock_chat:
            mock_chat.return_value = {"message": {"content": "OK"}}
            result = router.infer(TaskType.SIMPLE_THINK, messages)
            # Result should include metadata about which model was used
            assert "model_used" in result or "model" in result.get("_routing", {})


# ===========================================================================
# ModelRouter — Static Fallback (no fleet)
# ===========================================================================

@pytest.mark.unit
class TestModelRouterStaticFallback:
    """ModelRouter with static config — backwards compatible with current Amy."""

    def test_static_config(self):
        from amy.inference.model_router import ModelRouter
        router = ModelRouter.from_static(
            chat_model="gemma3:4b",
            deep_model="llava:7b",
            ollama_host="http://localhost:11434",
        )
        assert len(router.profiles) >= 2

    def test_static_infer_uses_host(self):
        from amy.inference.model_router import ModelRouter, TaskType
        router = ModelRouter.from_static(
            chat_model="gemma3:4b",
            deep_model="llava:7b",
            ollama_host="http://localhost:11434",
        )
        messages = [{"role": "user", "content": "Hello"}]

        with patch("amy.inference.model_router.ollama_chat") as mock_chat:
            mock_chat.return_value = {"message": {"content": "OK"}}
            router.infer(TaskType.CHAT, messages)
            call_kwargs = mock_chat.call_args[1] if mock_chat.call_args[1] else {}
            call_args = mock_chat.call_args[0] if mock_chat.call_args[0] else ()
            # Should use the specified host
            assert "localhost" in str(call_kwargs) or "localhost" in str(call_args)


# ===========================================================================
# ModelRouter — Fleet-Aware Host Selection
# ===========================================================================

@pytest.mark.unit
class TestModelRouterFleetHosts:
    """ModelRouter with fleet — host rotation on failure."""

    def test_tries_multiple_hosts(self):
        from amy.inference.model_router import ModelRouter, ModelProfile, TaskType
        profiles = [
            ModelProfile(name="gemma3:4b", capabilities={"text"}, priority=1),
        ]
        router = ModelRouter(profiles=profiles)

        mock_fleet = MagicMock()
        host1 = MagicMock()
        host1.url = "http://host1:11434"
        host1.name = "host1"
        host1.has_model.return_value = True
        host2 = MagicMock()
        host2.url = "http://host2:11434"
        host2.name = "host2"
        host2.has_model.return_value = True
        mock_fleet.hosts_with_model.return_value = [host1, host2]
        router._fleet = mock_fleet

        messages = [{"role": "user", "content": "Hello"}]
        hosts_tried = []

        def track_calls(*args, **kwargs):
            base_url = kwargs.get("base_url", "")
            hosts_tried.append(base_url)
            if len(hosts_tried) == 1:
                raise ConnectionError("Host 1 down")
            return {"message": {"content": "From host 2"}}

        with patch("amy.inference.model_router.ollama_chat", side_effect=track_calls):
            result = router.infer(TaskType.SIMPLE_THINK, messages)
            assert len(hosts_tried) == 2
            assert result["message"]["content"] == "From host 2"
