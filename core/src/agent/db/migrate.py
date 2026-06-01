"""Aplica migrations SQL em ordem crescente, idempotente.

Cada migration tem a forma NNN_*.sql onde NNN é o número de versão.
A tabela `schema_migrations` rastreia as versões já aplicadas.

Uso:
    from agent.db.migrate import apply_migrations
    applied = await apply_migrations(dsn)

    # CLI:
    agent db migrate [--dry-run]
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import asyncpg

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent.parent.parent / "migrations"

_CREATE_TRACKING = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     VARCHAR(20) PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checksum    VARCHAR(64)  NOT NULL
);
"""


def _version_from_filename(stem: str) -> str:
    """Extrai prefixo numérico do nome do arquivo (ex: '011_deploy' → '011')."""
    return stem.split("_")[0]


async def apply_migrations(dsn: str, *, dry_run: bool = False) -> list[str]:
    """Aplica migrations pendentes. Retorna lista de versões aplicadas.

    Parâmetros:
        dsn      -- string de conexão asyncpg
        dry_run  -- se True, apenas lista as pendentes sem aplicar
    """
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(_CREATE_TRACKING)

        applied: set[str] = {
            r["version"]
            for r in await conn.fetch("SELECT version FROM schema_migrations ORDER BY version")
        }

        files = sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda f: f.stem)
        newly_applied: list[str] = []

        for f in files:
            version = _version_from_filename(f.stem)
            if version in applied:
                continue

            sql = f.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()

            if dry_run:
                log.info("[dry-run] pendente: %s (%s)", f.name, version)
                newly_applied.append(version)
                continue

            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version, checksum) VALUES ($1, $2)",
                    version,
                    checksum,
                )
            log.info("migration aplicada: %s", f.name)
            newly_applied.append(version)

        return newly_applied
    finally:
        await conn.close()


async def stamp_all(dsn: str) -> list[str]:
    """Registra todas as migrations como aplicadas SEM executar o SQL.

    Útil para bootstrapping: quando o schema já existe mas não há tabela de
    rastreamento (banco criado manualmente antes de migrate existir).

    Retorna lista de versões registradas nesta chamada.
    """
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(_CREATE_TRACKING)

        already: set[str] = {
            r["version"]
            for r in await conn.fetch("SELECT version FROM schema_migrations")
        }

        files = sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda f: f.stem)
        stamped: list[str] = []

        for f in files:
            version = _version_from_filename(f.stem)
            if version in already:
                continue
            sql = f.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            await conn.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES ($1, $2)"
                " ON CONFLICT (version) DO NOTHING",
                version,
                checksum,
            )
            log.info("migration carimbada (stamp): %s", f.name)
            stamped.append(version)

        return stamped
    finally:
        await conn.close()
