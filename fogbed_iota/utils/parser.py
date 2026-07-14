import json
import re
from typing import Any, Dict, List, Optional

def strip_ansi(text: str) -> str:
    if not text:
        return ""
    ansi_pattern = r"\x1B\[[0-?]*[ -/]*[@-~]"
    return re.sub(ansi_pattern, "", text)


def extract_json_from_output(output: str) -> Dict[str, Any]:
    output_clean = strip_ansi(output)

    clean_lines: List[str] = []
    for line in output_clean.splitlines():
        stripped = line.strip()

        if re.match(r"^\d{4}-\d{2}-\d{2}T", stripped):
            continue
        if stripped.startswith(("[note]", "FETCHING", "Cloning", "Updating", "Compiling")):
            continue
        if stripped.startswith(("DEBUG", "INFO", "WARNING", "ERROR")):
            continue

        clean_lines.append(line)

    output_clean = "\n".join(clean_lines).strip()

    if output_clean.startswith("{") or output_clean.startswith("["):
        try:
            data = json.loads(output_clean)
            if isinstance(data, dict):
                return data
            raise ValueError(f"Expected JSON object, got {type(data).__name__}")
        except json.JSONDecodeError:
            pass

    decoder = json.JSONDecoder()
    for pos, ch in enumerate(output_clean):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(output_clean, pos)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    raise ValueError(
        "No JSON object found in CLI output.\n"
        f"Output preview: {output_clean[:800]}"
    )


def tx_digest(tx: Dict[str, Any]) -> str:
    effects = tx.get("effects") or {}
    return tx.get("digest") or effects.get("transactionDigest") or "unknown"


def tx_error(tx: Dict[str, Any]) -> Optional[str]:
    if not isinstance(tx, dict):
        return str(tx)

    if tx.get("error"):
        return str(tx["error"])

    effects = tx.get("effects") or {}
    status = effects.get("status") or {}

    if isinstance(status, dict) and status.get("error"):
        return str(status["error"])

    return None


def tx_looks_successful(tx: Dict[str, Any]) -> bool:
    if not isinstance(tx, dict) or not tx:
        return False

    effects = tx.get("effects") or {}
    status = effects.get("status") or {}
    top_status = tx.get("status")
    error_msg = tx_error(tx)

    if isinstance(status, dict):
        effects_status = status.get("status")
    else:
        effects_status = str(status) if status else ""

    digest = tx.get("digest") or effects.get("transactionDigest")

    return any(
        [
            top_status == "success",
            effects_status == "success",
            bool(tx.get("confirmedLocalExecution")),
            "objectChanges" in tx,
            "balanceChanges" in tx,
            bool(digest) and not error_msg,
        ]
    )
