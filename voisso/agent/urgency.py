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

# 안내 문구는 session.py 가 **질문 형태**로 만든다("119에 연결해 드릴까요?").
# 예전의 통보형("먼저 119에 전화해 주세요")은 어르신이 직접 걸어야 해서 걷어냈다.


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
    # 침수. 어르신은 "차오른다"보다 **"물이 들어온다"** 를 훨씬 자주 쓴다.
    # 부정형("물이 안 들어와요")은 단수(斷水)라 응급이 아니므로 룩어헤드로 배제한다.
    (
        EMERGENCY,
        "침수 진행 중",
        # 부사가 끼어드는 경우가 많다: "물이 **자꾸** 들어옵니더"
        r"물[이가]?\s*(?:자꾸|계속|지금|막|또|마구|한참)?\s*"
        r"(?![안못])(?:들어오|들어와|들어옵|넘어오|넘어와|밀려오|밀려와"
        r"|차오|차올|차고|차서|잠기|잠겼|불어)"
        r"|무릎까지|허리까지|가슴까지|발목까지"
        r"|잠겼|잠긴다|떠내려|휩쓸|물바다|물난리|침수",
    ),
    # "지금/계속/자꾸" 가 붙으면 진행 중이라는 뜻이다.
    (
        EMERGENCY,
        "침수 진행 중",
        r"(?:지금|계속|자꾸|막|자꾸만)\s*(?:물[이가]?\s*)?(?:들어오|들어와|차오|차올|넘어오)",
    ),
    (EMERGENCY, "인명 피해", r"다쳤|다치|쓰러졌|피가\s*나|숨을\s*못|의식이\s*없|사람이\s*빠"),
    (EMERGENCY, "범죄·위협", r"폭행|협박|위협|도둑|강도|맞았|때렸"),
    # ── 중요: 방치하면 피해가 커진다 ────────────────────────────────
    (
        IMPORTANT,
        "단수",
        r"단수|(?:물|수돗물|수도)[이가]?\s*안\s*(?:나오|나와|나옵|들어오|들어와|들어옵)",
    ),
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

# 재촉·다급함 표현. **반복이 신호다.**
# 단발 강조("큰일이라예")는 경북에서 흔한 말투라 1회로는 올리지 않는다.
_PRESSURE_PATTERNS = (
    r"빨리", r"퍼뜩", r"언능", r"어서", r"지금\s*(당장|바로)?", r"당장",
    r"우짜노", r"우짭니꺼", r"우야노", r"야단났", r"큰일났", r"큰일이",
    r"급해", r"급합니", r"급한데", r"살려", r"제발",
)
_PRESSURE_RE = re.compile("(" + "|".join(_PRESSURE_PATTERNS) + ")")
# 느낌표 반복도 다급함의 신호다. "!!!" 는 한 번으로 세지 않는다.
_BANG_RE = re.compile(r"[!！]{2,}")

# **몇 개의 발화에서** 재촉이 나왔는가로 센다. 한 문장 안의 강조가 아니라
# 턴을 넘긴 반복이 신호다 — "큰일이라예!!!" 한 번은 경북에서 흔한 말투다.
PRESSURE_THRESHOLD = 2


def has_pressure(text: str) -> bool:
    """이 발화에 재촉·다급함이 담겼는가."""
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    return bool(_PRESSURE_RE.search(cleaned) or _BANG_RE.search(cleaned))


# LLM 이 위험을 인지했을 때 답변에 나타나는 표현.
# 규칙이 못 잡은 위험을 모델이 알아채는 경우가 실제로 있었다 —
# 모델은 "안전한 곳으로 이동하시고 119에 신고하이소" 라고 답했는데
# 규칙은 "위험 신호가 없어" 라고 판정해 **둘이 어긋났다.**
# 계약서 5-A: LLM 은 규칙 결과를 **올릴 수만 있다.** 안전 쪽으로 치우친다.
_LLM_RISK_RE = re.compile(
    r"119|112|대피|안전한\s*곳|긴급\s*신고|즉시\s*신고|위험하니|위험합니다|"
    r"몸을\s*피|밖으로\s*나오|자리를\s*피"
)


def llm_signals_risk(reply: str) -> bool:
    """모델의 답변이 위험을 인지했는가."""
    return bool(_LLM_RISK_RE.search(reply or ""))


# 119 연결을 물었을 때의 대답. **부정을 먼저 본다** —
# "괜찮아예" 안에 "예" 가 들어 있어서 순서를 바꾸면 긍정으로 잘못 읽힌다.
_DECLINE_RE = re.compile(
    r"아니|아뇨|아이라|괜찮|됐어|됐습니|됐다|필요\s*없|안\s*해도|"
    r"내가\s*(하|걸|할)|직접\s*(하|걸)|제가\s*(하|걸)|하지\s*마|놔\s*두"
)
_ACCEPT_RE = re.compile(
    r"^\s*(네|예|야|응|어|음)\s*[.!]*\s*$|"
    r"그래|그러이소|그리\s*하|해\s*주|해주|부탁|연결\s*해|걸어\s*주|불러\s*주|"
    r"좋(아|습니|겠)|맞(아|습니)|얼른|빨리\s*(해|좀)|그람|그라이소|어예"
)


def confirm_intent(text: str) -> str | None:
    """119 연결 제안에 대한 대답. `"yes"` | `"no"` | None(불분명).

    **애매하면 None 이다.** 부정으로 단정하지 않는다 — 위험 쪽으로 기울이되
    강제하지 않기 위해 한 번 더 묻는 경로로 보낸다.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if _DECLINE_RE.search(cleaned):
        return "no"
    if _ACCEPT_RE.search(cleaned):
        return "yes"
    return None


def count_pressure(text: str) -> int:
    """재촉 신호의 총 개수. 강도 표시용이고 승급 판정에는 쓰지 않는다."""
    cleaned = (text or "").strip()
    if not cleaned:
        return 0
    return len(_PRESSURE_RE.findall(cleaned)) + len(_BANG_RE.findall(cleaned))


@dataclass
class Urgency:
    """계약서 5-A 의 긴급도 블록."""

    level: str = NORMAL
    reason: str = ""
    signals: list[str] = field(default_factory=list)
    decided_by: str = "rule"
    safety_referral: dict[str, str] | None = None
    # 재촉 신호가 몇 번 나왔는지. 2회 이상이면 한 단계 올린다.
    pressure_count: int = 0
    # 이미 응급인데 또 재촉이 왔다. 더 올릴 곳이 없으니
    # **안내를 다시, 더 강하게** 보여야 한다는 표시다(P7 이 버튼을 재강조).
    reemphasize: bool = False
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
            "pressure_count": self.pressure_count,
            "reemphasize": self.reemphasize,
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
    pressure_turns: int = 0,
    llm_reply: str = "",
) -> Urgency:
    """긴급도를 판정한다.

    `text` 는 통화에서 어르신이 한 말을 이어 붙인 것이다(누적 판정).
    `llm_level` 은 LLM 의 제안이고, **규칙 결과보다 높을 때만** 채택된다.
    `pressure_turns` 는 재촉이 나온 **발화 수**다. 2회 이상이면 한 단계 올린다.
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

    # 모델이 답변에서 위험을 인지했으면(119 안내·대피 권유 등) 응급으로 본다.
    # 규칙이 표현을 못 잡았을 뿐 상황은 위험할 수 있다.
    if llm_level is None and llm_signals_risk(llm_reply):
        llm_level = EMERGENCY
        llm_reason = (
            "상담 응답에서 대피·긴급신고 안내가 나왔습니다(모델이 위험을 인지). "
            "규칙 신호가 없어도 안전 쪽으로 올렸습니다."
        )

    # LLM 은 올릴 수만 있다. 내리지 못한다.
    if llm_level in LEVEL_RANK and _rank(llm_level) > _rank(level):
        level = llm_level
        decided_by = "llm"
        reason = (llm_reason or "").strip() or f"통화 내용으로 보아 {llm_level} 으로 판단했습니다."

    if not reason:
        # **비어 있으면 버그다.** 담당자가 납득 못 하는 표시는 무시된다.
        reason = "위험 신호가 없어 정상 처리 일정으로 분류했습니다."

    # 재촉 반복은 상황이 악화되고 있다는 신호다. **턴을 넘긴 반복**만 센다.
    pressure = count_pressure(text)
    reemphasize = False
    if pressure_turns >= PRESSURE_THRESHOLD:
        if level == EMERGENCY:
            # 더 올릴 곳이 없다. 대신 안내를 다시 강조한다.
            reemphasize = True
        else:
            raised = LEVELS[min(_rank(level) + 1, len(LEVELS) - 1)]
            if raised != level:
                level = raised
                decided_by = "rule"
                reason = (
                    f"{reason} 재촉 표현이 {pressure_turns}번의 발화에서 반복돼 "
                    "한 단계 올렸습니다."
                ).strip()

    referral = _referral_for(signals) if level == EMERGENCY else None
    return Urgency(
        level=level,
        reason=reason,
        signals=signals,
        decided_by=decided_by,
        safety_referral=referral,
        pressure_count=pressure,
        reemphasize=reemphasize,
    )


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
