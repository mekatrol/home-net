import asyncio
import datetime
import email as email_lib
import functools
import json
import poplib
import smtplib
from email.utils import getaddresses
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from processors import metadata_path_for, process_email
from watchdog_logging import email_log
from watchdog_models import EmailConfig, normalize_email_path
from watchdog_redirects import load_redirects_config

INBOX_SCAN_INTERVAL = 10
PROCESSING_SCAN_INTERVAL = 10
PROCESSED_SCAN_INTERVAL = 10
SENT_CLEAN_INTERVAL = 3600
DROPPED_CLEAN_INTERVAL = 3600
RECIPIENT_HEADERS = ("To", "Cc", "Bcc")


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


def _write_email_atomic(target_dir: Path, name: str, raw: bytes) -> Path:
    tmp_path = target_dir / f"{name}.tmp"
    eml_path = target_dir / name
    tmp_path.write_bytes(raw)
    tmp_path.rename(eml_path)
    return eml_path


def _read_processed_context(
    eml_path: Path, default_catchall_to: str
) -> tuple[str, Path | None]:
    metadata_path = metadata_path_for(eml_path)
    if not metadata_path.exists():
        return default_catchall_to, None

    try:
        context = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:
        email_log.warning(
            "Processed sender: failed to read metadata for %s; using default catchall: %s",
            eml_path.name,
            exc,
        )
        return default_catchall_to, metadata_path

    catchall_to = context.get("catchall_email") or default_catchall_to
    return catchall_to, metadata_path


def _extract_message_recipients(raw: bytes) -> list[str]:
    msg = email_lib.message_from_bytes(raw)
    return [
        address.strip().lower()
        for _, address in getaddresses(msg.get_all("To", []))
        if address.strip()
    ]


def _extract_all_message_recipients(raw: bytes) -> list[str]:
    msg = email_lib.message_from_bytes(raw)
    recipients = {
        address.strip().lower()
        for _, address in getaddresses(
            [value for header in RECIPIENT_HEADERS for value in msg.get_all(header, [])]
        )
        if address.strip()
    }
    return sorted(recipients)


def _extract_message_sender(raw: bytes) -> str:
    msg = email_lib.message_from_bytes(raw)
    senders = [
        address.strip().lower()
        for _, address in getaddresses(msg.get_all("From", []))
        if address.strip()
    ]
    return senders[0] if senders else ""


def _received_at_from_name_or_stat(eml_path: Path) -> str:
    stem = eml_path.stem
    try:
        parsed = datetime.datetime.strptime(stem, "%Y%m%d_%H%M%S_%f")
        return parsed.replace(tzinfo=datetime.timezone.utc).isoformat()
    except ValueError:
        return datetime.datetime.fromtimestamp(
            eml_path.stat().st_mtime,
            tz=datetime.timezone.utc,
        ).isoformat()


def delete_email_with_metadata(eml_path: Path) -> bool:
    if not eml_path.exists():
        return False

    try:
        eml_path.unlink()
    except FileNotFoundError:
        return False
    metadata_path = metadata_path_for(eml_path)
    if metadata_path.exists():
        metadata_path.unlink()
    return True


def list_dropped_emails(cfg: EmailConfig) -> list[dict[str, str]]:
    dropped_dir = Path(cfg.store_dir) / normalize_email_path(cfg.username) / "dropped"
    dropped_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, str]] = []
    for eml_path in dropped_dir.glob("*.eml"):
        metadata_path = metadata_path_for(eml_path)
        metadata: dict[str, object] = {}
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception as exc:
                email_log.warning(
                    "Dropped listing: failed to read metadata for %s: %s",
                    eml_path.name,
                    exc,
                )

        raw = b""
        if not metadata.get("sender") or not metadata.get("recipients"):
            try:
                raw = eml_path.read_bytes()
            except Exception as exc:
                email_log.warning(
                    "Dropped listing: failed to read %s for fallback metadata: %s",
                    eml_path.name,
                    exc,
                )

        recipients = metadata.get("recipients")
        recipient_list = (
            [str(item).strip() for item in recipients if str(item).strip()]
            if isinstance(recipients, list)
            else []
        )
        if not recipient_list and raw:
            recipient_list = _extract_all_message_recipients(raw)

        sender = str(metadata.get("sender", "")).strip()
        if not sender and raw:
            sender = _extract_message_sender(raw)

        received_at = str(metadata.get("received_at", "")).strip()
        if not received_at:
            received_at = _received_at_from_name_or_stat(eml_path)

        entries.append(
            {
                "filename": eml_path.name,
                "recipient": ", ".join(recipient_list),
                "sender": sender,
                "received_at": received_at,
            }
        )

    entries.sort(
        key=lambda entry: (entry["received_at"], entry["filename"]),
        reverse=True,
    )
    return entries


async def email_poller(cfg: EmailConfig) -> None:
    loop = asyncio.get_running_loop()
    inbox_dir = Path(cfg.store_dir) / normalize_email_path(cfg.username) / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    email_log.info(
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
                eml_path = _write_email_atomic(inbox_dir, f"{timestamp}.eml", raw)
                email_log.info(
                    "Email received from %s: %s → inbox/%s",
                    sender,
                    subject,
                    eml_path.name,
                )
        except Exception as exc:
            email_log.warning("Email poll error: %s", exc)
        await asyncio.sleep(cfg.poll_interval)


async def inbox_processor(cfg: EmailConfig) -> None:
    base_dir = Path(cfg.store_dir) / normalize_email_path(cfg.username)
    inbox_dir = base_dir / "inbox"
    processing_dir = base_dir / "processing"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    processing_dir.mkdir(parents=True, exist_ok=True)

    email_log.info(
        "Inbox processor started — moving inbox/ → processing/ every %ds",
        INBOX_SCAN_INTERVAL,
    )

    while True:
        try:
            for eml_path in sorted(inbox_dir.glob("*.eml")):
                target_path = processing_dir / eml_path.name
                eml_path.rename(target_path)
                email_log.info(
                    "Inbox processor: moved inbox/%s → processing/%s",
                    eml_path.name,
                    target_path.name,
                )
        except Exception as exc:
            email_log.warning("Inbox processor error: %s", exc)
        await asyncio.sleep(INBOX_SCAN_INTERVAL)


async def processing_processor(cfg: EmailConfig) -> None:
    base_dir = Path(cfg.store_dir) / normalize_email_path(cfg.username)
    processing_dir = base_dir / "processing"
    processed_dir = base_dir / "processed"
    dropped_dir = base_dir / "dropped"
    domain = cfg.username.split("@")[1] if "@" in cfg.username else ""
    default_catchall_to = cfg.catchall.get(domain, "") if cfg.catchall else ""
    processing_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    dropped_dir.mkdir(parents=True, exist_ok=True)

    email_log.info(
        "Processing processor started — placeholder AI moving processing/ → processed/ every %ds",
        PROCESSING_SCAN_INTERVAL,
    )

    while True:
        try:
            redirects = cfg.redirects
            if cfg.config_path:
                redirects = load_redirects_config(Path(cfg.config_path))
                cfg.redirects = redirects
            for eml_path in sorted(processing_dir.glob("*.eml")):
                processed_path = process_email(
                    eml_path,
                    processed_dir,
                    {
                        "catchall_email": default_catchall_to,
                        "redirects": redirects,
                        "drop_rules": cfg.drop,
                        "allowed_domains": cfg.allowed_domains,
                        "dropped_dir": dropped_dir,
                    },
                )
                if processed_path is None:
                    continue
                email_log.info(
                    "Processing processor: ran subprocessor chain for processing/%s → %s/%s",
                    eml_path.name,
                    processed_path.parent.name,
                    processed_path.name,
                )
        except Exception as exc:
            email_log.warning("Processing processor error: %s", exc)
        await asyncio.sleep(PROCESSING_SCAN_INTERVAL)


async def processed_sender(cfg: EmailConfig) -> None:
    loop = asyncio.get_running_loop()
    base_dir = Path(cfg.store_dir) / normalize_email_path(cfg.username)
    processed_dir = base_dir / "processed"
    sent_dir = base_dir / "sent"
    processed_dir.mkdir(parents=True, exist_ok=True)
    sent_dir.mkdir(parents=True, exist_ok=True)

    domain = cfg.username.split("@")[1] if "@" in cfg.username else ""
    catchall_to = cfg.catchall.get(domain) if cfg.catchall else None

    if catchall_to:
        email_log.info(
            "Processed sender started — forwarding %s → %s from processed/ every %ds",
            domain,
            catchall_to,
            PROCESSED_SCAN_INTERVAL,
        )
    else:
        email_log.info(
            "Processed sender: no catchall for '%s' — processed/ scanning disabled",
            domain,
        )
        return

    while True:
        try:
            for eml_path in sorted(processed_dir.glob("*.eml")):
                raw = eml_path.read_bytes()
                original_recipients = _extract_message_recipients(raw)
                delivery_to, metadata_path = _read_processed_context(eml_path, catchall_to)
                try:
                    await loop.run_in_executor(
                        None,
                        functools.partial(_forward_email_sync, cfg, delivery_to, raw),
                    )
                    sent_eml_path = sent_dir / eml_path.name
                    eml_path.rename(sent_eml_path)
                    if metadata_path and metadata_path.exists():
                        metadata_path.rename(metadata_path_for(sent_eml_path))
                    email_log.info(
                        "Processed sender: forwarded recipients=%s to %s → sent/%s",
                        original_recipients or ["(unknown)"],
                        delivery_to,
                        eml_path.name,
                    )
                except Exception as fwd_exc:
                    email_log.warning(
                        "Processed sender: forward to %s failed — %s will retry: %s",
                        delivery_to,
                        eml_path.name,
                        fwd_exc,
                    )
        except Exception as exc:
            email_log.warning("Processed sender error: %s", exc)
        await asyncio.sleep(PROCESSED_SCAN_INTERVAL)


async def sent_cleaner(cfg: EmailConfig) -> None:
    if cfg.sent_retention_days <= 0:
        email_log.info("Sent cleaner: retention disabled (sent_retention_days=0)")
        return

    sent_dir = Path(cfg.store_dir) / normalize_email_path(cfg.username) / "sent"
    sent_dir.mkdir(parents=True, exist_ok=True)
    email_log.info(
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
                    delete_email_with_metadata(eml_path)
                    email_log.info(
                        "Sent cleaner: deleted %s (older than %d days)",
                        eml_path.name,
                        cfg.sent_retention_days,
                    )
        except Exception as exc:
            email_log.warning("Sent cleaner error: %s", exc)
        await asyncio.sleep(SENT_CLEAN_INTERVAL)


async def dropped_cleaner(cfg: EmailConfig) -> None:
    if cfg.dropped_retention_days <= 0:
        email_log.info("Dropped cleaner: retention disabled (dropped_retention_days=0)")
        return

    dropped_dir = Path(cfg.store_dir) / normalize_email_path(cfg.username) / "dropped"
    dropped_dir.mkdir(parents=True, exist_ok=True)
    email_log.info(
        "Dropped cleaner started — deleting dropped/ files older than %d days, checking every %ds",
        cfg.dropped_retention_days,
        DROPPED_CLEAN_INTERVAL,
    )

    while True:
        try:
            cutoff = (
                datetime.datetime.now().timestamp() - cfg.dropped_retention_days * 86400
            )
            for eml_path in dropped_dir.glob("*.eml"):
                if eml_path.stat().st_mtime < cutoff:
                    delete_email_with_metadata(eml_path)
                    email_log.info(
                        "Dropped cleaner: deleted %s (older than %d days)",
                        eml_path.name,
                        cfg.dropped_retention_days,
                    )
        except Exception as exc:
            email_log.warning("Dropped cleaner error: %s", exc)
        await asyncio.sleep(DROPPED_CLEAN_INTERVAL)


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
        email_log.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as exc:
        email_log.warning("Failed to send email to %s: %s", to, exc)
        return False
