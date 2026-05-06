"""
Registry lazy de transports. Instancia cada provider apenas quando necessário.
"""
from __future__ import annotations

from agent.models.base import HealthStatus, Transport
from agent.observability.logger import get_logger

log = get_logger(__name__)


class TransportRegistry:
    def __init__(self) -> None:
        self._instances: dict[str, Transport] = {}
        self._factories: dict[str, object] = {}

    def register(self, name: str, factory: object) -> None:
        self._factories[name] = factory

    def get(self, name: str) -> Transport:
        if name not in self._instances:
            if name not in self._factories:
                available = list(self._factories)
                raise KeyError(
                    f"Provider '{name}' não registrado. Disponíveis: {available}"
                )
            factory = self._factories[name]
            self._instances[name] = factory()  # type: ignore[operator]
            log.debug("transport.registry.instantiated", provider=name)
        return self._instances[name]

    def available(self) -> list[str]:
        return list(self._factories)

    async def health_all(self) -> dict[str, HealthStatus]:
        results: dict[str, HealthStatus] = {}
        for name in self._factories:
            try:
                transport = self.get(name)
                results[name] = await transport.health()
            except Exception as exc:
                results[name] = HealthStatus(ok=False, message=str(exc))
        return results
