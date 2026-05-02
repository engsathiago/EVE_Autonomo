from collections.abc import Callable

from agent.transports.base import BaseTransport

_TRANSPORTS: dict[str, Callable[[], BaseTransport]] = {}


def register(name: str, factory: Callable[[], BaseTransport]) -> None:
    _TRANSPORTS[name] = factory


def get(name: str) -> BaseTransport:
    if name not in _TRANSPORTS:
        raise KeyError(f"Transport '{name}' não registrado. Disponíveis: {list(_TRANSPORTS)}")
    return _TRANSPORTS[name]()


def available() -> list[str]:
    return list(_TRANSPORTS)
