from pathlib import Path


def process_email(source_path: Path, context: dict[str, str]) -> bool:
    """Placeholder redirection detector that allows mail to continue unchanged."""
    # Later this step can rewrite context["catchall_email"] before delivery.
    _ = source_path
    _ = context
    return True
