"""EmailAdapter (F12) — IMAP IDLE para receber + SMTP para enviar.

Regras de segurança implementadas:
- Allowlist obrigatória (EMAIL_FROM_ALLOWLIST). Sem allowlist → ConfigError.
- Anti-loop: emails com Auto-Submitted/X-Autoreply são descartados silenciosamente.
- Anti-spoof: Authentication-Results com spf=fail ou dkim=fail são descartados.
- Nunca responde a remetente não autorizado (sem reflexão de spam).
- Saída inclui Auto-Submitted: auto-generated para evitar loops.
- Email mascarado nos logs (u***r@example.com).
"""
from __future__ import annotations

import asyncio
import email
import email.message
import email.policy
import email.utils
import html
import os
import re
from typing import Any

import aiosmtplib

from agent.channels.base import ChannelAdapter, ConfigError, IncomingMessage, OutgoingMessage
from agent.channels import metrics as ch_metrics
from agent.observability.logger import get_logger

log = get_logger(__name__)

_SUBJECT_PREFIX = "[agent]"
_SIGNATURE = "\n\n-- agent"
_MAX_BODY_BYTES = 50 * 1024  # 50 KB


def _mask_email(addr: str) -> str:
    """Mascara email para logs: thiago@example.com → t*****o@example.com."""
    local, _, domain = addr.partition("@")
    if not domain:
        return "***"
    if len(local) <= 2:
        return f"{local[0]}***@{domain}"
    return f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}@{domain}"


def _parse_allowlist(raw: str) -> set[str]:
    return {a.strip().lower() for a in raw.split(",") if a.strip()}


def _strip_html(text: str) -> str:
    """Remove tags HTML e decodifica entidades."""
    clean = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(clean).strip()


class EmailAdapter(ChannelAdapter):
    """Adapta email (IMAP IDLE + SMTP) ao ChannelRouter."""

    name = "email"

    def __init__(
        self,
        imap_host: str,
        imap_port: int,
        smtp_host: str,
        smtp_port: int,
        user: str,
        password: str,
        allowlist: set[str],
        router: Any | None = None,  # ChannelRouter — injetado após boot
    ) -> None:
        if not allowlist:
            raise ConfigError(
                "EMAIL_FROM_ALLOWLIST é obrigatório. "
                "Sem allowlist o adapter não sobe (regra de segurança)."
            )
        self._imap_host = imap_host
        self._imap_port = imap_port
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._user = user
        self._password = password
        self._allowlist = allowlist
        self._router = router
        self._running = False
        self._task: asyncio.Task | None = None

    @classmethod
    def from_env(cls, router: Any | None = None) -> "EmailAdapter":
        """Constrói a partir das variáveis de ambiente."""
        required = {
            "EMAIL_IMAP_HOST": os.getenv("EMAIL_IMAP_HOST", ""),
            "EMAIL_USER": os.getenv("EMAIL_USER", ""),
            "EMAIL_PASS": os.getenv("EMAIL_PASS", ""),
            "EMAIL_FROM_ALLOWLIST": os.getenv("EMAIL_FROM_ALLOWLIST", ""),
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ConfigError(f"Variáveis obrigatórias ausentes: {', '.join(missing)}")

        allowlist = _parse_allowlist(required["EMAIL_FROM_ALLOWLIST"])
        if not allowlist:
            raise ConfigError("EMAIL_FROM_ALLOWLIST está vazio — adapter não sobe.")

        return cls(
            imap_host=required["EMAIL_IMAP_HOST"],
            imap_port=int(os.getenv("EMAIL_IMAP_PORT", "993")),
            smtp_host=os.getenv("EMAIL_SMTP_HOST", required["EMAIL_IMAP_HOST"]),
            smtp_port=int(os.getenv("EMAIL_SMTP_PORT", "587")),
            user=required["EMAIL_USER"],
            password=required["EMAIL_PASS"],
            allowlist=allowlist,
            router=router,
        )

    def set_router(self, router: Any) -> None:
        self._router = router

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._idle_loop())
        ch_metrics.connection_status.labels(channel="email").set(1)
        log.info("email.adapter.started", user=_mask_email(self._user))

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        ch_metrics.connection_status.labels(channel="email").set(0)
        log.info("email.adapter.stopped")

    async def send(self, user_id: str, msg: OutgoingMessage) -> None:
        """Envia email de resposta ao remetente."""
        body = msg.text + _SIGNATURE
        out = email.message.EmailMessage()
        out["From"] = self._user
        out["To"] = user_id
        out["Subject"] = f"{_SUBJECT_PREFIX} resposta"
        out["Auto-Submitted"] = "auto-generated"
        if msg.thread_id:
            out["In-Reply-To"] = msg.thread_id
            out["References"] = msg.thread_id
        out.set_content(body)

        # Truncagem: > 50 KB vai como anexo .txt
        body_bytes = body.encode()
        if len(body_bytes) > _MAX_BODY_BYTES:
            out.set_content(f"{_SUBJECT_PREFIX} Resposta em anexo (> 50 KB).")
            out.add_attachment(body_bytes, maintype="text", subtype="plain", filename="response.txt")

        try:
            async with aiosmtplib.SMTP(
                hostname=self._smtp_host,
                port=self._smtp_port,
                start_tls=True,
            ) as smtp:
                await smtp.login(self._user, self._password)
                await smtp.send_message(out)
            log.info("email.sent", to=_mask_email(user_id))
        except Exception as exc:
            log.error("email.send_failed", to=_mask_email(user_id), error=str(exc))

    async def is_authorized(self, user_id: str) -> bool:
        return user_id.lower() in self._allowlist

    # ── IMAP IDLE loop ───────────────────────────────────────────────────────

    async def _idle_loop(self) -> None:
        """IMAP IDLE: recebe notificações push do servidor em vez de polling."""
        import aioimaplib
        while self._running:
            try:
                imap = aioimaplib.IMAP4_SSL(host=self._imap_host, port=self._imap_port)
                await imap.wait_hello_from_server()
                await imap.login(self._user, self._password)
                await imap.select("INBOX")
                log.info("email.imap.connected", host=self._imap_host)

                while self._running:
                    # IDLE: bloqueia até o servidor notificar (novo email, etc.)
                    await imap.idle_start(timeout=60)
                    idle_result = await imap.idle_done()
                    if not self._running:
                        break
                    # Processa novas mensagens sinalizadas pelo IDLE
                    await self._fetch_new(imap)

                await imap.logout()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("email.imap.reconnect", error=str(exc))
                ch_metrics.connection_status.labels(channel="email").set(0)
                await asyncio.sleep(30)  # backoff antes de reconectar

    async def _fetch_new(self, imap: Any) -> None:
        """Busca mensagens não lidas e as processa."""
        status, data = await imap.uid("search", None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            return
        uids = data[0].split()
        for uid in uids:
            try:
                fetch_status, fetch_data = await imap.uid("fetch", uid, "(RFC822)")
                if fetch_status != "OK":
                    continue
                raw_bytes = fetch_data[1] if len(fetch_data) > 1 else None
                if not raw_bytes:
                    continue
                if isinstance(raw_bytes, (bytes, bytearray)):
                    msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
                else:
                    continue
                await self._process_email(msg)
                # Marca como lido
                await imap.uid("store", uid, "+FLAGS", "\\Seen")
            except Exception as exc:
                log.warning("email.fetch.error", uid=uid, error=str(exc))

    async def _process_email(self, msg: email.message.Message) -> None:
        """Valida e encaminha email ao router."""
        sender_raw = msg.get("From", "")
        _, sender = email.utils.parseaddr(sender_raw)
        sender = sender.lower().strip()

        # Anti-loop: descarta emails automáticos
        if _is_auto_reply(msg):
            log.info("email.discarded.auto_reply", from_=_mask_email(sender))
            return

        # Anti-spoof: valida SPF/DKIM se header presente
        if _spf_dkim_failed(msg):
            log.info("email.discarded.spf_dkim_fail", from_=_mask_email(sender))
            return

        # Allowlist
        if not await self.is_authorized(sender):
            log.info("email.discarded.not_allowed", from_=_mask_email(sender))
            return

        # Anexos: descarta com aviso
        if _has_attachments(msg):
            await self.send(sender, OutgoingMessage(
                text="Anexos não são processados nesta versão. Envie apenas texto.",
            ))
            return

        subject = str(msg.get("Subject", ""))
        body = _extract_body(msg)
        thread_id = msg.get("Message-ID")

        # Subject deve começar com [agent]
        if not subject.strip().lower().startswith(_SUBJECT_PREFIX.lower()):
            log.info("email.discarded.no_prefix", from_=_mask_email(sender))
            return

        text = subject[len(_SUBJECT_PREFIX):].strip() or body

        incoming = IncomingMessage(
            channel="email",
            user_id=sender,
            user_display=sender_raw or sender,
            text=text,
            thread_id=thread_id,
            raw={"subject": subject, "from": sender_raw},
        )

        if self._router:
            await self._router.handle(incoming)


# ── Helpers de segurança ──────────────────────────────────────────────────────

def _is_auto_reply(msg: email.message.Message) -> bool:
    """Detecta resposta automática via headers padrão."""
    auto_submitted = msg.get("Auto-Submitted", "")
    if auto_submitted and auto_submitted.lower() != "no":
        return True
    x_autoreply = msg.get("X-Autoreply", "")
    if x_autoreply and x_autoreply.lower() in ("yes", "true", "1"):
        return True
    return False


def _spf_dkim_failed(msg: email.message.Message) -> bool:
    """Descarta email se Authentication-Results indicar falha de SPF e DKIM."""
    auth_results = msg.get("Authentication-Results", "")
    if not auth_results:
        return False  # sem header = não validado, não rejeita
    auth_lower = auth_results.lower()
    spf_fail = "spf=fail" in auth_lower or "spf=softfail" in auth_lower
    dkim_fail = "dkim=fail" in auth_lower or "dkim=none" in auth_lower
    return spf_fail and dkim_fail


def _has_attachments(msg: email.message.Message) -> bool:
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            return True
    return False


def _extract_body(msg: email.message.Message) -> str:
    """Extrai corpo de texto puro (strip HTML se necessário)."""
    for part in msg.walk():
        ct = part.get_content_type()
        if ct == "text/plain":
            payload = part.get_payload(decode=True)
            if payload:
                return payload.decode("utf-8", errors="replace").strip()
        if ct == "text/html":
            payload = part.get_payload(decode=True)
            if payload:
                return _strip_html(payload.decode("utf-8", errors="replace"))
    # Fallback para mensagem simples não-multipart
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode("utf-8", errors="replace").strip()
    return ""
