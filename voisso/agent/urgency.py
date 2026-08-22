"""긴급도 판정 — 담당자가 무엇을 먼저 볼지 정해 준다.

담당자는 하루에 수십 건을 받는다. 순서를 정해 주지 않으면 접수 순서대로
처리되고 급한 민원이 뒤에 묻힌다.

## 설계 원칙

**규칙이 먼저다.** 명백한 위험 신호(가스·불·붕괴·고립·감전·침수 진행)는
정규식으로 결정적으로 잡는다. LLM 은 규칙이 안 걸릴 때만 문맥으로 판정하고,
**규칙 결과를 올릴 수만 있지 내릴 수는 없다.** 안전 쪽으로 치우치는 것이 옳다.

**방언은 어미가 아니라 어간으로 잡는다.** "무너집니더 / 무너질라 칸다 /
무너지겠어예" 는 전부 `무너` 로 걸린다. 어미 변이를 일일이 나열하면 반드시
빠뜨린다.

## 🚨 응급은 접수하고 끝내면 안 된다

사람이 위험한 상황을 민원으로 접수하고 통화를 끝내는 것이 이 시스템의 가장 큰
위험이다. 응급으로 판정되면 **119·112 안내를 먼저** 하고, 접수는 그다음이다.
접수가 신고를 대체한다고 오해하게 만들면 안 된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 낮은 것부터. 비교는 이 순서로 한다.
LEVELS = ("낮음", "보통", "중요", "응급")
LEVEL_RANK = {level: index for index, level in enumerate(LEVELS)}

EMERGENCY = "응급"
IMPORTANT = "중요"
NORMAL = "보통"
LOW = "낮음"

# 안내할 번호. 화재·구조·응급의료는 119, 범죄·위협은 112.
REFERRAL_119 = {"number": "119", "label": "소방·구조"}
REFERRAL_112 = {"number": "112", "label": "경찰"}

# 응급 안내 문구. **표준어로 만든다** — 사투리 변환은 방언 사전이 맡는다.
SAFETY_NOTICE_119 = "지금 위험하시면 먼저 119에 전화해 주세요. 민원은 제가 접수해 두겠습니다."
SAFETY_NOTICE_112 = "지금 위험하시면 먼저 112에 전화해 주세요. 민원은 제가 접수해 두겠습니다."


# (단계, 신호 이름, 패턴). 위에서부터 검사하고 가장 높은 단계가 이긴다.
#
# 방언 어미를 나열하지 않고 어간만 쓴다:
#   무너 -> 무너진다/무너집니더/무너질라 칸다/무너지겠어예 전부 매칭
_RULES: tuple[tuple[str, str, str], ...] = (
    # ── 응급: 사람이 다칠 수 있다, 지금 ──────────────────────────────
    (EMERGENCY, "가스 누출", r"가스\s*(냄새|가\s*새|새|누출)|가스가\s*나"),
    (EMERGENCY, "화재·연기", r"불이\s*나|불\s*났|화재|연기가\s*나|타는\s*냄새|불길"),
    (EMERGENCY, "붕괴 조짐", r"무너|붕괴|내려앉|주저앉|기울어|쓰러질|넘어질\s*것"),
    (EMERGENCY, "지반 함몰", r"함몰|땅이\s*꺼|푹\s*꺼|지반\s*침하|싱크홀"),
    (EMERGENCY, "고립·갇힘", r"갇혔|갇히|고립|못\s*나가|못\s*나오|길이\s*끊"),
    (EMERGENCY, "감전 위험", r"감전|전기가\s*오|찌릿|누전.*물|전선이\s*끊|전선.*늘어"),
    (EMERGENCY, "침수 진행 중", r"차오|차올|무릎까지|허리까지|가슴까지|잠겼|잠긴다|떠내려|휩쓸"),
    (EMERGENCY, "인명 피해", r"다쳤|다치|쓰러졌|피가\s*나|숨을\s*못|의식이\s*없|사람이\s*빠"),
    (EMERGENCY, "범죄·위협", r"폭행|협박|위협|도둑|강도|맞았|때렸"),
    # ── 중요: 방치하면 피해가 커진다 ────────────────────────────────
    (IMPORTANT, "단수", r"단수|물이\s*안\s*나오|수돗물이\s*안\s*나오|수도가\s*안\s*나오"),
    (IMPORTANT, "상수도 파손", r"(상수도|수도관|수도)\s*(가\s*)?터|누수가\s*심"),
    (IMPORTANT, "하수 역류", r"역류|하수가\s*넘|오수가\s*넘|맨홀에서\s*(물|물이)\s*넘"),
    (IMPORTANT, "정전", r"정전|전기가\s*안\s*들어|전기가\s*나갔"),
    (IMPORTANT, "야간 조명 소등", r"가로등.*(안\s*들어|안\s*켜|나갔|고장)|가로등이\s*꺼"),
    (IMPORTANT, "농작물 피해 우려", r"논이\s*잠|밭이\s*잠|농작물.*(피해|잠|침수)"),
    (IMPORTANT, "통행 지장", r"길을\s*막|통행.*(불가|못)|차가\s*못\s*지나|트랙터가\s*몬\s*지나"),
    # ── 낮음: 급하지 않다 ──────────────────────────────────────────
    (LOW, "제도 문의", r"문의|여쭤|물어보|궁금|어떻게\s*하(나|는지)|신청.*(방법|하려)|알아보"),
    (LOW, "지원 사업", r"지원\s*사업|보조금|접수\s*기간|자격이\s*되"),
    (LOW, "건의·칭찬", r"건의|제안|고맙|감사|칭찬|수고"),
)

_COMPILED = tuple((level, name, re.compile(pattern)) for level, name, pattern in _RULES)

# 112 로 안내할 신호. 나머지 응급은 119.
_POLICE_SIGNALS = {"범죄·위협"}


@dataclass
class Urgency:
    """계약서 5-A 의 긴급도 블록."""

    level: str = NORMAL
    reason: str = ""
    signals: list[str] = field(default_factory=list)
    decided_by: str = "rule"
    safety_referral: dict[str, str] | None = None
    # 담당자가 수정하면 원래 판정을 여기에 남긴다(계약서: 이력으로 남긴다).
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_emergency(self) -> bool:
        return self.level == EMERGENCY

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "reason": self.reason,
            "signals": list(self.signals),
            "decided_by": self.decided_by,
            "safety_referral": self.safety_referral,
            "history": list(self.history),
        }


def _rank(level: str) -> int:
    return LEVEL_RANK.get(level, LEVEL_RANK[NORMAL])


def detect_signals(text: str) -> list[tuple[str, str]]:
    """`(단계, 신호 이름)` 목록. 걸린 규칙을 모두 돌려준다."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for level, name, pattern in _COMPILED:
        if name in seen:
            continue
        if pattern.search(cleaned):
            found.append((level, name))
            seen.add(name)
    return found


def _referral_for(signals: list[str]) -> dict[str, str]:
    return REFERRAL_112 if any(s in _POLICE_SIGNALS for s in signals) else REFERRAL_119


def assess(
    text: str,
    llm_level: str | None = None,
    llm_reason: str = "",
) -> Urgency:
    """긴급도를 판정한다.

    `text` 는 통화에서 어르신이 한 말을 이어 붙인 것이다(누적 판정).
    `llm_level` 은 LLM 의 제안이고, **규칙 결과보다 높을 때만** 채택된다.
    """
    matched = detect_signals(text)

    rule_level = NORMAL
    signals: list[str] = []
    if matched:
        # 가장 높은 단계가 이긴다.
        rule_level = max((level for level, _ in matched), key=_rank)
        # 근거로 보여줄 신호는 채택된 단계의 것만.
        signals = [name for level, name in matched if level == rule_level]

    level = rule_level
    decided_by = "rule"
    reason = ""

    if signals:
        reason = f"통화에서 '{', '.join(signals)}' 신호가 확인됐습니다."
    elif matched:
        reason = "명확한 위험 신호는 없었습니다."

    # LLM 은 올릴 수만 있다. 내리지 못한다.
    if llm_level in LEVEL_RANK and _rank(llm_level) > _rank(level):
        level = llm_level
        decided_by = "llm"
        reason = (llm_reason or "").strip() or f"통화 내용으로 보아 {llm_level} 으로 판단했습니다."

    if not reason:
        # **비어 있으면 버그다.** 담당자가 납득 못 하는 표시는 무시된다.
        reason = "위험 신호가 없어 정상 처리 일정으로 분류했습니다."

    referral = _referral_for(signals) if level == EMERGENCY else None
    return Urgency(
        level=level,
        reason=reason,
        signals=signals,
        decided_by=decided_by,
        safety_referral=referral,
    )


def safety_notice(urgency: Urgency) -> str:
    """응급일 때 슬롯 채우기보다 **먼저** 할 안내. 표준어로 만든다."""
    if not urgency.is_emergency or not urgency.safety_referral:
        return ""
    if urgency.safety_referral["number"] == "112":
        return SAFETY_NOTICE_112
    return SAFETY_NOTICE_119


def revise(current: dict[str, Any], level: str, reason: str, by: str = "officer") -> dict[str, Any]:
    """담당자가 긴급도를 고친다. **원래 판정을 이력으로 남긴다.**

    AI 판정은 제안이고 최종 판단은 사람이 한다.
    """
    if level not in LEVEL_RANK:
        raise ValueError(f"level 은 {' | '.join(LEVELS)} 중 하나여야 합니다.")

    previous = dict(current or {})
    history = list(previous.get("history") or [])
    history.append(
        {
            "level": previous.get("level", NORMAL),
            "reason": previous.get("reason", ""),
            "decided_by": previous.get("decided_by", "rule"),
        }
    )
    return {
        "level": level,
        "reason": (reason or "").strip() or f"담당자가 {level} 으로 조정했습니다.",
        "signals": list(previous.get("signals") or []),
        "decided_by": by,
        # 단계가 내려가면 안내 기록도 함께 정리한다.
        "safety_referral": previous.get("safety_referral") if level == EMERGENCY else None,
        "history": history,
    }
