import email as email_lib
import re
from email.utils import getaddresses
from pathlib import Path

from watchdog_logging import email_log

RECIPIENT_HEADERS = ("To", "Cc", "Bcc")
REGEX_PREFIX = "regex:"


def _extract_recipients(source_path: Path) -> set[str]:
    msg = email_lib.message_from_bytes(source_path.read_bytes())
    return {
        address.strip().lower()
        for _, address in getaddresses(
            [value for header in RECIPIENT_HEADERS for value in msg.get_all(header, [])]
        )
        if address.strip()
    }


def _has_disallowed_domain(recipients: set[str], allowed_domains: set[str]) -> list[str]:
    if not allowed_domains:
        email_log.debug(
            "Drop detector: allowed_domains empty; skipping domain gate for recipients=%s",
            sorted(recipients),
        )
        return []

    disallowed_domains: set[str] = set()
    for recipient in recipients:
        if "@" not in recipient:
            email_log.debug(
                "Drop detector: recipient '%s' missing domain while checking allowed domains=%s",
                recipient,
                sorted(allowed_domains),
            )
            disallowed_domains.add("(missing-domain)")
            continue
        _, domain = recipient.rsplit("@", 1)
        email_log.debug(
            "Drop detector: checking recipient '%s' domain '%s' against allowed domains=%s",
            recipient,
            domain,
            sorted(allowed_domains),
        )
        if domain not in allowed_domains:
            disallowed_domains.add(domain)

    return sorted(disallowed_domains)


def _match_drop_rule(recipients: set[str], raw_rule: str) -> list[str]:
    rule = raw_rule.strip()
    if not rule:
        return []

    if rule.lower().startswith(REGEX_PREFIX):
        pattern = rule[len(REGEX_PREFIX) :].strip()
        if not pattern:
            email_log.debug("Drop detector: regex rule '%s' ignored because it is empty", raw_rule)
            return []
        email_log.debug(
            "Drop detector: checking recipients=%s against regex rule='%s'",
            sorted(recipients),
            pattern,
        )
        try:
            matched = sorted(
                recipient for recipient in recipients if re.fullmatch(pattern, recipient)
            )
            email_log.debug(
                "Drop detector: regex rule='%s' matched recipients=%s",
                pattern,
                matched,
            )
            return matched
        except re.error as exc:
            email_log.warning(
                "Drop detector: invalid regex rule '%s': %s",
                raw_rule,
                exc,
            )
            return []

    if "@" not in rule:
        email_log.warning(
            "Drop detector: exact rule '%s' ignored because it is missing a domain suffix",
            raw_rule,
        )
        return []

    candidate = rule.lower()
    matched = [candidate] if candidate in recipients else []
    email_log.debug(
        "Drop detector: checking recipients=%s against exact rule='%s' matched=%s",
        sorted(recipients),
        candidate,
        matched,
    )
    return matched


def process_email(source_path: Path, context: dict) -> bool:
    if context.get("skip_drop_detector"):
        email_log.info(
            "Drop detector: skipping %s because skip_drop_detector=true",
            source_path.name,
        )
        return True

    recipients = _extract_recipients(source_path)
    email_log.debug(
        "Drop detector: evaluating %s recipients=%s",
        source_path.name,
        sorted(recipients),
    )
    allowed_domains = {
        domain.strip().lower()
        for domain in context.get("allowed_domains", [])
        if isinstance(domain, str) and domain.strip()
    }
    email_log.debug(
        "Drop detector: %s allowed_domains=%s",
        source_path.name,
        sorted(allowed_domains),
    )

    disallowed_domains = _has_disallowed_domain(recipients, allowed_domains)
    if disallowed_domains:
        context["drop_reason"] = {
            "type": "disallowed_domain",
            "domains": disallowed_domains,
            "recipients": sorted(recipients),
        }
        context["destination_dir"] = context.get("dropped_dir")
        email_log.info(
            "Drop detector: %s dropped for recipients=%s due to disallowed domains=%s",
            source_path.name,
            sorted(recipients),
            disallowed_domains,
        )
        return False

    drop_rules = context.get("drop_rules", [])
    email_log.debug(
        "Drop detector: %s checking %d drop rules",
        source_path.name,
        len(drop_rules) if isinstance(drop_rules, list) else 0,
    )
    for raw_rule in drop_rules:
        if not isinstance(raw_rule, str):
            email_log.debug(
                "Drop detector: skipping non-string drop rule for %s: %r",
                source_path.name,
                raw_rule,
            )
            continue
        matched_recipients = _match_drop_rule(recipients, raw_rule)
        if matched_recipients:
            context["drop_reason"] = {
                "type": "recipient_match",
                "rule": raw_rule,
                "recipients": matched_recipients,
            }
            context["destination_dir"] = context.get("dropped_dir")
            email_log.info(
                "Drop detector: %s dropped for recipients=%s by rule=%s",
                source_path.name,
                matched_recipients,
                raw_rule,
            )
            return False

    email_log.debug("Drop detector: %s passed all drop checks", source_path.name)
    return True
