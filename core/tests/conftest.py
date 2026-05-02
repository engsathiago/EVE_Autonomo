import pytest

from agent.observability.logger import configure_logging
from agent.tools.registry import ToolRegistry

# Configura logger antes de qualquer teste
configure_logging("WARNING")


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()
