from enum import Enum


class TriggerType(str, Enum):
    CRON = "cron"  # ex: "0 9 * * 1"
    INTERVAL = "interval"  # ex: "*/30 * * * *"
    ONESHOT = "oneshot"  # dispara uma vez em data/hora específica
