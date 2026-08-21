"""민원카드 저장소 (계약서 5절 스키마).

``data/complaints/<id>.json`` 으로 떨어뜨린다. 대시보드(P8)와 HTTP API(P6)가
같은 디렉터리를 읽는다. DB 없이 파일 하나 = 민원 하나로 두어, 경북도청 담당자가
그대로 열어 볼 수 있게 했다.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from voisso.routing.dataaccess import data_dir
from voisso.routing.privacy import scrub

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

REQUIRED_ASSIGNED = ("department_id", "full_name", "evidence")


def complaints_dir() -> Path:
    path = Path(os.environ.get("VOISSO_COMPLAINTS_DIR") or (data_dir() / "complaints"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _next_id(directory: Path) -> str:
    used = set()
    for entry in directory.glob("*.json"):
        if entry.stem.isdigit():
            used.add(int(entry.stem))
    return f"{(max(used) + 1) if used else 1:04d}"


class ComplaintError(ValueError):
    """민원카드가 계약서 5절 스키마를 만족하지 못할 때."""


def submit_complaint(complaint: dict[str, Any]) -> dict[str, Any]:
    """민원카드를 검증 후 저장하고 {"id", "path", "complaint"} 를 돌려준다."""
    if not isinstance(complaint, dict):
        raise ComplaintError("민원카드는 JSON 객체여야 합니다.")

    card = dict(complaint)
    directory = complaints_dir()

    card_id = str(card.get("id") or "").strip() or _next_id(directory)
    if not _ID_RE.match(card_id):
        raise ComplaintError(f"허용되지 않는 id 형식입니다: {card_id!r}")
    card["id"] = card_id

    card.setdefault("created_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    card.setdefault("duration_sec", 0)
    card.setdefault("summary", "")
    card.setdefault("category", "")
    card.setdefault("alternatives", [])
    card.setdefault("caller", {})
    card.setdefault("transcript", [])

    assigned = card.get("assigned")
    if not isinstance(assigned, dict):
        raise ComplaintError("assigned 는 객체여야 합니다 (계약서 5절).")
    for key in REQUIRED_ASSIGNED:
        if not str(assigned.get(key) or "").strip():
            raise ComplaintError(
                f"assigned.{key} 가 비어 있습니다. "
                "특히 evidence 는 담당자에게 배정 근거를 보여주는 값이라 필수입니다."
            )
    assigned.setdefault("phone_token", "")
    # 원문에 섞여 들어온 전화번호는 저장 단계에서 한 번 더 막는다.
    assigned["evidence"] = scrub(str(assigned["evidence"]))
    card["assigned"] = assigned

    alts = []
    for alt in card.get("alternatives") or []:
        if not isinstance(alt, dict):
            continue
        alts.append(
            {
                "full_name": alt.get("full_name", ""),
                "score": float(alt.get("score") or 0.0),
                "evidence": scrub(str(alt.get("evidence") or "")),
                **({"department_id": alt["department_id"]} if alt.get("department_id") else {}),
            }
        )
    card["alternatives"] = alts

    path = directory / f"{card_id}.json"
    # 대시보드가 읽는 중에 반쪽짜리 파일을 보지 않도록 원자적으로 쓴다.
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
    ) as tmp:
        json.dump(card, tmp, ensure_ascii=False, indent=2)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)

    return {"id": card_id, "path": str(path), "complaint": card}


def list_complaints() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in sorted(complaints_dir().glob("*.json")):
        try:
            with entry.open(encoding="utf-8") as fh:
                out.append(json.load(fh))
        except Exception:
            continue
    return out


def get_complaint(complaint_id: str) -> dict[str, Any]:
    path = complaints_dir() / f"{complaint_id}.json"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)
