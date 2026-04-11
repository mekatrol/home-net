import json
from pathlib import Path
from typing import Any, Callable, Optional

from watchdog_logging import email_log

from .drop_detector import process_email as run_drop_detector
from .redirection_detector import process_email as run_redirection_detector
from .spam_detector import process_email as run_spam_detector

ProcessorContext = dict[str, Any]
Subprocessor = Callable[[Path, ProcessorContext], bool]

SUBPROCESSORS: tuple[tuple[str, Subprocessor], ...] = (
    ("drop detector", run_drop_detector),
    ("spam detector", run_spam_detector),
    ("redirection detector", run_redirection_detector),
)


def metadata_path_for(email_path: Path) -> Path:
    return email_path.with_suffix(f"{email_path.suffix}.meta.json")


def process_email(
    source_path: Path, destination_dir: Path, context: ProcessorContext
) -> Optional[Path]:
    """Claim a staged email, run the subprocessor chain, and persist the result."""
    destination_dir.mkdir(parents=True, exist_ok=True)

    locked_path = source_path.with_suffix(f"{source_path.suffix}.locked")
    try:
        source_path.rename(locked_path)
    except FileNotFoundError:
        return None

    for processor_name, processor in SUBPROCESSORS:
        try:
            should_continue = processor(locked_path, context)
        except Exception as exc:
            email_log.warning(
                "Processor '%s' failed for %s; continuing: %s",
                processor_name,
                locked_path.name,
                exc,
            )
            should_continue = True

        if not should_continue:
            break

    final_destination_dir = context.get("destination_dir", destination_dir)
    if not isinstance(final_destination_dir, Path):
        final_destination_dir = destination_dir
    final_destination_dir.mkdir(parents=True, exist_ok=True)

    destination_path = final_destination_dir / source_path.name
    tmp_path = final_destination_dir / f"{source_path.name}.tmp"
    metadata_path = metadata_path_for(destination_path)
    tmp_metadata_path = metadata_path_for(tmp_path)
    try:
        tmp_path.write_bytes(locked_path.read_bytes())
        tmp_path.rename(destination_path)

        metadata_context = {
            key: value
            for key, value in context.items()
            if key not in {"destination_dir", "dropped_dir"}
        }
        tmp_metadata_path.write_text(
            json.dumps(metadata_context),
            encoding="utf-8",
        )
        tmp_metadata_path.rename(metadata_path)

        locked_path.unlink()
        return destination_path
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        if tmp_metadata_path.exists():
            tmp_metadata_path.unlink()
        if metadata_path.exists():
            metadata_path.unlink()
        try:
            locked_path.rename(source_path)
        except FileNotFoundError:
            pass
        raise


__all__ = ["metadata_path_for", "process_email"]
