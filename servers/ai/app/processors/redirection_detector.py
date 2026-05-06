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
    senders = {
        address.strip().lower()
        for _, address in getaddresses(msg.get_all("From", []))
        if address.strip()
    }

    for redirect_to, redirect_rules in redirects.items():
        if not isinstance(redirect_to, str) or not isinstance(redirect_rules, list):
            continue
        redirect_domain = (
            redirect_to.rsplit("@", 1)[1].lower() if "@" in redirect_to else ""
        )
        email_log.debug(
            "Redirection detector: checking %s recipients=%s senders=%s against redirect_to=%s",
            source_path.name,
            sorted(recipients),
            sorted(senders),
            redirect_to,
        )

        matched_addresses = _match_redirect_rules(
            redirect_to, redirect_domain, redirect_rules, recipients, senders
        )
        if matched_addresses:
            context["catchall_email"] = redirect_to
            email_log.info(
                "Redirection detector: %s matched %s -> %s",
                source_path.name,
                matched_addresses,
                redirect_to,
            )
            break

    return True


def _match_redirect_rules(
    redirect_to: str,
    redirect_domain: str,
    redirect_rules: list,
    recipients: set[str],
    senders: set[str],
) -> list[str]:
    for rule in redirect_rules:
        if not isinstance(rule, dict):
            continue
        rule_type = rule.get("type")
        direction = rule.get("direction", "to")
        value = rule.get("value")
        if rule_type not in {"exact", "regex"} or direction not in {"from", "to"}:
            continue
        if not isinstance(value, str) or not value.strip():
            continue

        candidates = senders if direction == "from" else recipients
        if rule_type == "exact":
            matched = sorted(candidates & {value.strip().lower()})
            if matched:
                return matched
            continue

        matched = _match_regex_rule(
            redirect_to,
            redirect_domain,
            value.strip(),
            direction,
            candidates,
        )
        if matched:
            return matched

    return []


def _match_regex_rule(
    redirect_to: str,
    redirect_domain: str,
    pattern: str,
    direction: str,
    candidates: set[str],
) -> list[str]:
    for address in candidates:
        if direction == "to":
            if "@" not in address or not redirect_domain:
                continue
            local_part, domain = address.rsplit("@", 1)
            if domain.lower() != redirect_domain:
                continue
            value = local_part
        else:
            value = address

        try:
            if re.fullmatch(pattern, value):
                return [address]
        except re.error as exc:
            email_log.warning(
                "Redirection detector: invalid regex for %s (%s): %s",
                redirect_to,
                pattern,
                exc,
            )
            return []

    return []
