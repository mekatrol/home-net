import asyncio
import datetime
import email as email_lib
import functools
import poplib
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from watchdog_logging import log
from watchdog_models import EmailConfig, normalize_email_path

INBOX_SCAN_INTERVAL = 10
SENT_CLEAN_INTERVAL = 3600


def _fetch_emails_sync(
    cfg: EmailConfig,
) -> list[tuple[email_lib.message.Message, bytes]]:
    results: list[tuple[email_lib.message.Message, bytes]] = []
    conn = poplib.POP3_SSL(cfg.host, cfg.pop3_port)
    try:
        conn.user(cfg.username)
        conn.pass_(cfg.password)
        count, _ = conn.stat()
        for i in range(1, count + 1):
            raw_lines = conn.retr(i)[1]
            raw = b"\r\n".join(raw_lines)
            results.append((email_lib.message_from_bytes(raw), raw))
            conn.dele(i)
    finally:
        conn.quit()
    return results


def _forward_email_sync(cfg: EmailConfig, to: str, raw: bytes) -> None:
    with smtplib.SMTP(cfg.host, cfg.smtp_port) as smtp:
        smtp.starttls()
        smtp.login(cfg.username, cfg.password)
        smtp.sendmail(cfg.username, to, raw)


async def email_poller(cfg: EmailConfig) -> None:
    loop = asyncio.get_running_loop()
    inbox_dir = Path(cfg.store_dir) / normalize_email_path(cfg.username) / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    log.info(
        "Email poller started — polling %s:%d every %ds, inbox: %s",
        cfg.host,
        cfg.pop3_port,
        cfg.poll_interval,
        inbox_dir,
    )
    while True:
        try:
            results = await loop.run_in_executor(
                None,
                functools.partial(_fetch_emails_sync, cfg),
            )
            for msg, raw in results:
                subject = msg.get("Subject", "(no subject)")
                sender = msg.get("From", "(unknown)")
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                tmp_path = inbox_dir / f"{timestamp}.eml.tmp"
                eml_path = inbox_dir / f"{timestamp}.eml"
                tmp_path.write_bytes(raw)
                tmp_path.rename(eml_path)
                log.info(
                    "Email received from %s: %s → inbox/%s",
                    sender,
                    subject,
                    eml_path.name,
                )
        except Exception as exc:
            log.warning("Email poll error: %s", exc)
        await asyncio.sleep(cfg.poll_interval)


async def inbox_processor(cfg: EmailConfig) -> None:
    loop = asyncio.get_running_loop()
    base_dir = Path(cfg.store_dir) / normalize_email_path(cfg.username)
    inbox_dir = base_dir / "inbox"
    sent_dir = base_dir / "sent"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    sent_dir.mkdir(parents=True, exist_ok=True)

    domain = cfg.username.split("@")[1] if "@" in cfg.username else ""
    catchall_to = cfg.catchall.get(domain) if cfg.catchall else None

    if catchall_to:
        log.info(
            "Inbox processor started — forwarding %s → %s, scanning every %ds",
            domain,
            catchall_to,
            INBOX_SCAN_INTERVAL,
        )
    else:
        log.info(
            "Inbox processor: no catchall for '%s' — inbox scanning disabled",
            domain,
        )
        return

    while True:
        try:
            for eml_path in sorted(inbox_dir.glob("*.eml")):
                raw = eml_path.read_bytes()
                try:
                    await loop.run_in_executor(
                        None,
                        functools.partial(_forward_email_sync, cfg, catchall_to, raw),
                    )
                    eml_path.rename(sent_dir / eml_path.name)
                    log.info(
                        "Inbox processor: forwarded to %s → sent/%s",
                        catchall_to,
                        eml_path.name,
                    )
                except Exception as fwd_exc:
                    log.warning(
                        "Inbox processor: forward to %s failed — %s will retry: %s",
                        catchall_to,
                        eml_path.name,
                        fwd_exc,
                    )
        except Exception as exc:
            log.warning("Inbox processor error: %s", exc)
        await asyncio.sleep(INBOX_SCAN_INTERVAL)


async def sent_cleaner(cfg: EmailConfig) -> None:
    if cfg.sent_retention_days <= 0:
        log.info("Sent cleaner: retention disabled (sent_retention_days=0)")
        return

    sent_dir = Path(cfg.store_dir) / normalize_email_path(cfg.username) / "sent"
    sent_dir.mkdir(parents=True, exist_ok=True)
    log.info(
        "Sent cleaner started — deleting sent/ files older than %d days, checking every %ds",
        cfg.sent_retention_days,
        SENT_CLEAN_INTERVAL,
    )

    while True:
        try:
            cutoff = (
                datetime.datetime.now().timestamp() - cfg.sent_retention_days * 86400
            )
            for eml_path in sent_dir.glob("*.eml"):
                if eml_path.stat().st_mtime < cutoff:
                    eml_path.unlink()
                    log.info(
                        "Sent cleaner: deleted %s (older than %d days)",
                        eml_path.name,
                        cfg.sent_retention_days,
                    )
        except Exception as exc:
            log.warning("Sent cleaner error: %s", exc)
        await asyncio.sleep(SENT_CLEAN_INTERVAL)


def _send_email_sync(cfg: EmailConfig, to: str, subject: str, body: str) -> None:
    msg = MIMEMultipart()
    msg["From"] = cfg.username
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP(cfg.host, cfg.smtp_port) as smtp:
        smtp.starttls()
        smtp.login(cfg.username, cfg.password)
        smtp.send_message(msg)


async def send_email(cfg: EmailConfig, to: str, subject: str, body: str) -> bool:
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            None,
            functools.partial(_send_email_sync, cfg, to, subject, body),
        )
        log.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as exc:
        log.warning("Failed to send email to %s: %s", to, exc)
        return False
