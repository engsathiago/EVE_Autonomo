class SandboxTimeout(Exception):
    """Processo não terminou dentro do wall_time_seconds."""

    def __init__(self, wall_time_s: int) -> None:
        super().__init__(f"Sandbox timeout após {wall_time_s}s")
        self.wall_time_s = wall_time_s


class SandboxOOM(Exception):
    """Processo foi morto por exceder o limite de memória."""

    def __init__(self, limit_mb: int) -> None:
        super().__init__(f"Sandbox OOM: limite {limit_mb}MB excedido")
        self.limit_mb = limit_mb


class SandboxNetworkDenied(Exception):
    """Tentativa de acesso de rede bloqueada pela política."""

    def __init__(self, domain: str) -> None:
        super().__init__(f"Rede negada para domínio: {domain}")
        self.domain = domain


class SandboxBackendUnsupported(Exception):
    """Backend não suporta a configuração solicitada."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Backend não suportado: {reason}")
        self.reason = reason


class SandboxCriticRejected(Exception):
    """Execução bloqueada pelo Crítico (política require_critic_approval)."""

    def __init__(self, reasoning: str) -> None:
        super().__init__(f"Crítico rejeitou execução: {reasoning}")
        self.reasoning = reasoning
