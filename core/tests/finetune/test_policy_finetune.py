"""Tests for POLICY_FINETUNE sandbox profile — C14."""
from __future__ import annotations

from agent.sandbox.base import NetworkPolicy
from agent.sandbox.policy import get_policy


class TestPolicyFinetune:
    def test_policy_finetune_is_registered(self):
        """C14: profile FINETUNE existe no registry."""
        policy = get_policy("finetune")
        assert policy.name == "finetune"

    def test_policy_finetune_has_sufficient_wall_time(self):
        """LoRA training + merge pode levar até 2h."""
        policy = get_policy("finetune")
        assert policy.config.wall_time_seconds >= 3600  # at least 1h

    def test_policy_finetune_has_sufficient_memory(self):
        """Merge-and-quantize pode precisar de até 32 GiB de RAM."""
        policy = get_policy("finetune")
        assert policy.config.memory_limit_mb >= 16384  # at least 16 GiB

    def test_policy_finetune_does_not_require_critic_approval(self):
        """Treino não passa pelo Crítico — processo determinístico."""
        policy = get_policy("finetune")
        assert policy.require_critic_approval is False

    def test_policy_finetune_is_not_open_network(self):
        """FINETUNE não tem rede aberta — só allowlist com HuggingFace."""
        policy = get_policy("finetune")
        assert policy.allow_open_network is False

    def test_policy_finetune_network_is_allowlist(self):
        policy = get_policy("finetune")
        assert policy.config.network == NetworkPolicy.ALLOWLIST

    def test_policy_finetune_allows_huggingface(self):
        """HuggingFace necessário para download de tokenizers/configs."""
        policy = get_policy("finetune")
        allowed = policy.config.allowed_domains or []
        assert any("huggingface" in d for d in allowed)
