from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml


class _QuotedString(str):
    pass


class _RedirectConfigDumper(yaml.SafeDumper):
    pass


def _represent_quoted_string(
    dumper: yaml.SafeDumper, data: _QuotedString
) -> yaml.nodes.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style='"')


_RedirectConfigDumper.add_representer(_QuotedString, _represent_quoted_string)


def load_redirects_config(path: Path) -> dict[str, list[dict[str, str]]]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return normalize_redirects_config(raw)


def normalize_redirects_config(raw: Any) -> dict[str, list[dict[str, str]]]:
    redirects = raw.get("redirects", raw) if isinstance(raw, dict) else {}
    normalized: dict[str, list[dict[str, str]]] = {}
    for catchall_email, rules in redirects.items():
        if not isinstance(catchall_email, str):
            continue
        catchall_email = catchall_email.strip().lower()
        if "@" not in catchall_email:
            continue

        _, domain = catchall_email.rsplit("@", 1)
        normalized_rules: list[dict[str, str]] = []
        raw_rules = rules if isinstance(rules, list) else []
        for rule in raw_rules:
            if isinstance(rule, str):
                value = rule.strip()
                if not value:
                    continue
                if value.lower().startswith("regex:"):
                    pattern = value[6:].strip()
                    if pattern:
                        normalized_rules.append({"type": "regex", "value": pattern})
                    continue
                address = value.lower()
                if "@" not in address:
                    address = f"{address}@{domain}"
                normalized_rules.append({"type": "exact", "value": address})
                continue

            if not isinstance(rule, dict):
                continue

            rule_type = rule.get("type")
            rule_value = rule.get("value")
            if isinstance(rule_type, str) and isinstance(rule_value, str) and rule_value.strip():
                normalized_type = rule_type.strip().lower()
                normalized_value = rule_value.strip()
                if normalized_type == "exact":
                    address = normalized_value.lower()
                    if "@" not in address:
                        address = f"{address}@{domain}"
                    normalized_rules.append({"type": "exact", "value": address})
                    continue
                if normalized_type == "regex":
                    normalized_rules.append({"type": "regex", "value": normalized_value})
                    continue

            exact_value = rule.get("exact") or rule.get("address")
            if isinstance(exact_value, str) and exact_value.strip():
                address = exact_value.strip().lower()
                if "@" not in address:
                    address = f"{address}@{domain}"
                normalized_rules.append({"type": "exact", "value": address})

            regex_value = rule.get("regex")
            if isinstance(regex_value, str) and regex_value.strip():
                normalized_rules.append(
                    {"type": "regex", "value": regex_value.strip()}
                )

        normalized[catchall_email] = normalized_rules
    return normalized


def serialize_redirects_config(
    redirects: dict[str, list[dict[str, str]]],
) -> dict[str, dict[str, list[dict[str, str]]]]:
    return {"redirects": redirects}


def save_redirects_config(
    path: Path, redirects: dict[str, list[dict[str, str]]]
) -> dict[str, list[dict[str, str]]]:
    normalized = normalize_redirects_config(serialize_redirects_config(redirects))
    existing_raw: dict[str, Any] = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if isinstance(loaded, dict):
            existing_raw = loaded

    merged = dict(existing_raw)
    merged["redirects"] = normalized

    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        yaml.dump(
            _quote_all_strings(merged),
            tmp,
            Dumper=_RedirectConfigDumper,
            sort_keys=False,
            default_flow_style=False,
        )
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    return normalized


def _quote_all_strings(value: Any) -> Any:
    if isinstance(value, str):
        return _QuotedString(value)
    if isinstance(value, dict):
        return {key: _quote_all_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_quote_all_strings(item) for item in value]
    return value
