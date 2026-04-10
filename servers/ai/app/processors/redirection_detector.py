import email as email_lib
import re
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

    for redirect_to, redirect_rules in redirects.items():
        if not isinstance(redirect_to, str) or not isinstance(redirect_rules, list):
            continue
        redirect_domain = redirect_to.rsplit("@", 1)[1].lower() if "@" in redirect_to else ""
        exact_matches = {
            rule["value"].strip().lower()
            for rule in redirect_rules
            if isinstance(rule, dict)
            and rule.get("type") == "exact"
            and isinstance(rule.get("value"), str)
            and rule["value"].strip()
        }
        regex_patterns = [
            rule["value"]
            for rule in redirect_rules
            if isinstance(rule, dict)
            and rule.get("type") == "regex"
            and isinstance(rule.get("value"), str)
            and rule["value"].strip()
        ]
        email_log.debug(
            "Redirection detector: checking %s recipients=%s against redirect_to=%s exact=%s regex=%s",
            source_path.name,
            sorted(recipients),
            redirect_to,
            sorted(exact_matches),
            regex_patterns,
        )

        matched_recipients = sorted(recipients & exact_matches)
        if not matched_recipients:
            for recipient in recipients:
                if "@" not in recipient or not redirect_domain:
                    continue
                local_part, domain = recipient.rsplit("@", 1)
                if domain.lower() != redirect_domain:
                    continue
                for pattern in regex_patterns:
                    try:
                        if re.fullmatch(pattern, local_part):
                            matched_recipients.append(recipient)
                            break
                    except re.error as exc:
                        email_log.warning(
                            "Redirection detector: invalid regex for %s (%s): %s",
                            redirect_to,
                            pattern,
                            exc,
                        )
                if matched_recipients:
                    break

        if matched_recipients:
            context["catchall_email"] = redirect_to
            email_log.info(
                "Redirection detector: %s matched %s -> %s",
                source_path.name,
                matched_recipients,
                redirect_to,
            )
            break

    return True
