import email as email_lib
from email.utils import getaddresses
from pathlib import Path

from watchdog_logging import email_log


def process_email(source_path: Path, context: dict) -> bool:
    """Redirect delivery to a specific catchall when the recipient matches."""
    redirects = context.get("redirects")
    if not isinstance(redirects, dict):
        return True

    msg = email_lib.message_from_bytes(source_path.read_bytes())
    recipients = {
        address.strip().lower()
        for _, address in getaddresses(msg.get_all("To", []))
        if address.strip()
    }

    for redirect_to, redirect_from_list in redirects.items():
        if not isinstance(redirect_to, str) or not isinstance(redirect_from_list, list):
            continue
        redirect_from = {
            address.strip().lower()
            for address in redirect_from_list
            if isinstance(address, str) and address.strip()
        }
        email_log.debug(
            "Redirection detector: checking %s recipients=%s against redirect_to=%s redirect_from=%s",
            source_path.name,
            sorted(recipients),
            redirect_to,
            sorted(redirect_from),
        )
        if recipients & redirect_from:
            context["catchall_email"] = redirect_to
            email_log.info(
                "Redirection detector: %s matched %s -> %s",
                source_path.name,
                sorted(recipients & redirect_from),
                redirect_to,
            )
            break

    return True
