"""경북 방언 ↔ 표준어 변환 엔진.

정직성 고지 (문서·발표에서 이 표현을 유지할 것)
------------------------------------------------
이 모듈은 방언 음향 모델을 학습시킨 결과물이 **아니다.**
우리는 음성 모델을 파인튜닝하지 않았고, 48시간 해커톤에서 가능하지도 않다.
여기서 하는 일은 두 가지뿐이다.

1. 출처가 기록된 어휘·어미 사전(``lexicon.json``)에 기반한 **결정론적 문자열 변환**
2. ``VOISSO_DIALECT_LLM=1`` 일 때만 켜지는 **선택적** LLM 다듬기 (``llm.py``)

사전의 모든 항목에는 ``source`` 필드가 있다. 출처별 재배포 조건은 ``SOURCES.md`` 참조.
AI Hub 방언 코퍼스(dataSetSn=119)에서 추출한 항목은 **하나도 들어 있지 않다.**
이용정책 제5항(제3자 제공 금지)이 공개 저장소 배포를 금지하기 때문이다.
(``docs/DATA_LICENSE.md`` §1)
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

LEXICON_PATH = Path(__file__).parent / "lexicon.json"

# 재배포 가능 여부가 갈리는 출처 네임스페이스. SOURCES.md 와 짝을 이룬다.
SOURCE_PREFIXES = ("curated:", "wikipedia:", "nikl:", "aihub:")
#: 공개 저장소에 커밋하면 안 되는 출처 접두사 (docs/DATA_LICENSE.md §1).
RESTRICTED_SOURCE_PREFIXES = ("aihub:",)

STRENGTHS = ("light", "polite", "strong")
_STRENGTH_RANK = {name: i for i, name in enumerate(STRENGTHS)}

_HANGUL = "가-힣"
_HANGUL_RE = re.compile(f"[{_HANGUL}]")

# 어절 경계로 인정하는 문자들. 한국어에는 \b 가 없어서 직접 정의한다.
_BEFORE = f"(?<![{_HANGUL}])"

# 명사 뒤에 붙어도 같은 낱말로 봐야 하는 조사. 긴 것부터 (에서 < 에).
_JOSA = (
    "에서부터", "으로부터", "이라도", "이라고", "이라는", "이란", "이야", "이나",
    "에서", "에게", "한테", "께서", "으로", "이랑", "부터", "까지", "보다", "처럼",
    "마다", "밖에", "조차", "라도", "라고", "라는", "하고", "이며", "이고", "이다",
    "은", "는", "이", "가", "을", "를", "에", "의", "도", "만", "로", "와", "과",
    "랑", "요",
)
# 주의: "다"/"아"/"야"/"예"는 조사로 넣지 않는다. 어미와 겹쳐서 "가물다"→"가뭄다"
# 같은 오변환을 만든다. 조사 목록은 넓히는 것보다 좁게 유지하는 편이 안전하다.
_JOSA_RE = re.compile(f"(?:{'|'.join(_JOSA)})(?![{_HANGUL}])")


class LexiconError(RuntimeError):
    """사전 파일이 깨졌을 때. 런타임은 이 예외를 삼키고 원문을 반환한다."""


# --------------------------------------------------------------------------- #
# 사전 로딩
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def load_lexicon() -> dict[str, Any]:
    """``lexicon.json`` 을 읽어 캐시한다. 프로세스당 1회만 디스크를 친다."""
    try:
        with LEXICON_PATH.open(encoding="utf-8") as fp:
            data = json.load(fp)
    except FileNotFoundError as exc:  # pragma: no cover - 배포 사고
        raise LexiconError(f"사전 파일이 없다: {LEXICON_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise LexiconError(f"사전 JSON 파싱 실패: {exc}") from exc

    if not isinstance(data.get("entries"), list) or not isinstance(data.get("rules"), list):
        raise LexiconError("사전에 entries/rules 배열이 없다")
    return data


def entries() -> list[dict[str, Any]]:
    return load_lexicon()["entries"]


def rules() -> list[dict[str, Any]]:
    return load_lexicon()["rules"]


# --------------------------------------------------------------------------- #
# 보호 마스킹 — 변환하면 안 되는 구간
# --------------------------------------------------------------------------- #
# 전화번호·숫자·영문·URL·대괄호 토큰(PHONE_0042 등)은 손대지 않는다.
# 부서명("건설도시국 도로과")은 어미 규칙이 어절 끝에만 걸리므로 자연 보호된다.
_PROTECT_RE = re.compile(
    r"""
      \[[^\]]{0,80}\]                 # [토큰] 형태
    | https?://\S+                    # URL
    | [A-Za-z][A-Za-z0-9_.\-]*        # 영문 낱말 / PHONE_0042
    | \d+(?:[-–—.,:]\d+)*             # 숫자, 전화번호, 날짜
    """,
    re.VERBOSE,
)
_SENTINEL = "\x00{}\x00"
_SENTINEL_RE = re.compile("\x00(\\d+)\x00")


def _mask(text: str) -> tuple[str, list[str]]:
    saved: list[str] = []

    def keep(match: re.Match[str]) -> str:
        saved.append(match.group(0))
        return _SENTINEL.format(len(saved) - 1)

    return _PROTECT_RE.sub(keep, text), saved


def _unmask(text: str, saved: list[str]) -> str:
    if not saved:
        return text

    def restore(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        return saved[idx] if idx < len(saved) else match.group(0)

    return _SENTINEL_RE.sub(restore, text)


# --------------------------------------------------------------------------- #
# 어휘 치환 (최장일치)
# --------------------------------------------------------------------------- #
def _tail_kind(entry: dict[str, Any]) -> str:
    """뒤에 무엇이 와도 되는지. 오탐을 막는 가장 중요한 장치다."""
    if entry.get("stem"):
        return "stem"          # 어간 — 어미가 이어붙는다 (아푸다/아푸고/아푼)
    if entry.get("pos") == "명사":
        return "josa"          # 명사 — 조사만 이어붙을 수 있다 (질바닥에/질바닥은)
    return "word"              # 그 외 — 뒤에 한글이 오면 다른 낱말이다


def _tail_ok(kind: str, rest: str) -> bool:
    if kind == "stem":
        return True
    if not rest or not _HANGUL_RE.match(rest[0]):
        return True
    if kind == "josa":
        return _JOSA_RE.match(rest) is not None
    return False


# 어휘를 바꾸면 받침이 달라져서 조사가 어긋난다. ("차부가" → "버스터미널가")
# 반드시 **치환이 실제로 일어난 자리**에서만 손본다. 문장 전체에 돌리면
# "마을"의 끝 글자 '을'을 조사로 착각해 "마를"로 망가뜨린다.
# 이/가, 을/를만 다룬다. 은/는은 관형형 어미 "-는"과 겹쳐서 위험하다.
_JOSA_PAIRS = {"이": ("이", "가"), "가": ("이", "가"), "을": ("을", "를"), "를": ("을", "를")}


def _has_final(syllable: str) -> bool:
    """한글 음절에 받침이 있는지. 유니코드 조합 공식으로 판단한다."""
    code = ord(syllable) - 0xAC00
    return 0 <= code <= 11171 and code % 28 != 0


def _fix_josa(word: str, josa: str) -> str:
    """치환된 낱말 뒤에 붙은 조사를 새 받침에 맞춘다."""
    pair = _JOSA_PAIRS.get(josa)
    if not pair or not word:
        return josa
    with_final, without_final = pair
    return with_final if _has_final(word[-1]) else without_final


def _allowed(item: dict[str, Any], strength: str) -> bool:
    return _STRENGTH_RANK.get(item.get("strength", "polite"), 1) <= _STRENGTH_RANK[strength]


@lru_cache(maxsize=8)
def _vocab(direction: str, strength: str) -> tuple[re.Pattern[str] | None, dict[str, tuple[str, str]]]:
    """방향별 어휘 치환 규칙을 정규식 하나로 컴파일한다.

    ``to_dialect`` 는 ``reverse: true`` 인 항목만 쓴다. 표준어→사투리는
    과하게 바꾸면 희화화되므로 **정밀도 우선**이다.
    """
    mapping: dict[str, tuple[str, str]] = {}
    for entry in entries():
        src, dst = ("dialect", "standard") if direction == "to_standard" else ("standard", "dialect")
        if direction == "to_dialect":
            if not entry.get("reverse") or not _allowed(entry, strength):
                continue
        key, value = entry.get(src, ""), entry.get(dst, "")
        if not key or not value or key == value or key in mapping:
            continue
        mapping[key] = (value, _tail_kind(entry))

    if not mapping:
        return None, mapping
    # 최장일치: 긴 표제어를 먼저 시도해야 "질바닥"이 "질"에 잡아먹히지 않는다.
    alternation = "|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True))
    # 뒤따르는 조사까지 함께 잡아야 치환 후 받침에 맞춰 고칠 수 있다.
    return re.compile(f"{_BEFORE}(?:{alternation})(?P<josa>이|가|을|를)?(?![{_HANGUL}])?"), mapping


def _apply_vocab(text: str, direction: str, strength: str) -> str:
    pattern, mapping = _vocab(direction, strength)
    if pattern is None:
        return text

    def repl(match: re.Match[str]) -> str:
        josa = match.group("josa") or ""
        word = match.group(0)[: len(match.group(0)) - len(josa)]
        rest = josa + match.string[match.end():]

        # 긴 표제어의 뒤 문맥이 맞지 않으면 짧은 표제어로 되돌아간다.
        # 정규식 자체는 여기서 백트래킹하지 않으므로 직접 훑는다.
        # (예: "맥히가꼬" — "맥히가"는 뒤에 '꼬'가 와서 탈락, "맥히"가 맞다)
        for size in range(len(word), 0, -1):
            candidate = word[:size]
            found = mapping.get(candidate)
            if found is None:
                continue
            value, kind = found
            tail = word[size:] + rest
            if _tail_ok(kind, tail):
                if size == len(word) and josa:
                    return value + _fix_josa(value, josa)
                return value + word[size:] + josa
        return word + josa

    return pattern.sub(repl, text)


# --------------------------------------------------------------------------- #
# 어미·문법 규칙
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=8)
def _rules(direction: str, strength: str) -> tuple[tuple[re.Pattern[str], str, str], ...]:
    wanted = {"to_standard": ("to_standard", "both"), "to_dialect": ("to_dialect", "both")}[direction]
    picked: list[dict[str, Any]] = []
    for rule in rules():
        if rule.get("dir", "both") not in wanted:
            continue
        if direction == "to_dialect":
            # 왕복 검증에서 떨어진 규칙은 사투리 생성에 쓰지 않는다. 양보다 자연스러움이다.
            if rule.get("roundtrip") is False or not _allowed(rule, strength):
                continue
        picked.append(rule)

    # 우선순위 내림차순 → 같으면 긴 패턴 먼저. "습니다"를 "니다"보다 먼저 처리해야 한다.
    picked.sort(key=lambda r: (r.get("priority", 50), len(r.get("pattern", ""))), reverse=True)

    compiled: list[tuple[re.Pattern[str], str, str]] = []
    for rule in picked:
        try:
            compiled.append((re.compile(rule["pattern"]), rule.get("replace", ""), rule.get("desc", "")))
        except re.error as exc:  # 사전 오타가 통화를 죽이면 안 된다
            log.warning("방언 규칙 정규식 오류로 건너뜀 (%s): %s", rule.get("desc", "?"), exc)
    return tuple(compiled)


def _apply_rules(text: str, direction: str, strength: str) -> str:
    for pattern, replace, _desc in _rules(direction, strength):
        text = pattern.sub(replace, text)
    return text


# --------------------------------------------------------------------------- #
# 공개 변환 함수
# --------------------------------------------------------------------------- #
def convert(text: str, direction: str, strength: str = "polite") -> str:
    """마스킹 → 어휘 → 어미 → 복원. 실패하면 원문을 그대로 돌려준다."""
    if not text or not text.strip():
        return text
    if strength not in _STRENGTH_RANK:
        raise ValueError(f"strength 는 {STRENGTHS} 중 하나여야 한다: {strength!r}")
    try:
        masked, saved = _mask(text)
        if direction == "to_standard":
            # STT 오인식 교정이 목적 — 재현율 우선.
            # 어휘 → 어미 → 어휘 순으로 두 번 훑는다. 어미 규칙이 만들어낸 형태를
            # (맥힜다 → 맥혔다) 어휘 사전이 다시 잡을 수 있어야 하기 때문이다.
            masked = _apply_vocab(masked, direction, strength)
            masked = _apply_rules(masked, direction, strength)
            masked = _apply_vocab(masked, direction, strength)
        else:
            # TTS 입력 생성 — 정밀도 우선. 어미가 체감 차이의 대부분이다.
            masked = _apply_rules(masked, direction, strength)
            masked = _apply_vocab(masked, direction, strength)
        return _unmask(masked, saved)
    except LexiconError:
        log.exception("방언 사전을 읽지 못했다 — 원문 유지")
        return text
    except Exception:  # noqa: BLE001 - 방언 레이어가 통화를 끊게 두지 않는다
        log.exception("방언 변환 실패 — 원문 유지")
        return text


def explain(text: str, direction: str, strength: str = "polite") -> list[dict[str, str]]:
    """이 문장에 실제로 적용된 항목만 추린다. 데모 출력과 LLM few-shot에 쓴다."""
    hits: list[dict[str, str]] = []
    if not text:
        return hits
    try:
        masked, _ = _mask(text)
        pattern, mapping = _vocab(direction, strength)
        if pattern is not None:
            for match in pattern.finditer(masked):
                value, kind = mapping[match.group(0)]
                if _tail_ok(kind, match.string[match.end():]):
                    hits.append({"kind": "어휘", "from": match.group(0), "to": value, "desc": ""})
        staged = _apply_vocab(masked, direction, strength) if direction == "to_standard" else masked
        for rule_pattern, replace, desc in _rules(direction, strength):
            found = rule_pattern.search(staged)
            if found:
                hits.append({
                    "kind": "어미",
                    "from": found.group(0),
                    "to": rule_pattern.sub(replace, found.group(0)),
                    "desc": desc,
                })
            staged = rule_pattern.sub(replace, staged)
    except Exception:  # noqa: BLE001
        log.exception("방언 규칙 설명 생성 실패")
    return hits


def source_counts() -> dict[str, int]:
    """출처별 항목 수. SOURCES.md 갱신과 재배포 점검에 쓴다."""
    counts: dict[str, int] = {}
    for item in [*entries(), *rules()]:
        prefix = str(item.get("source", "")).split(":", 1)[0] + ":"
        counts[prefix] = counts.get(prefix, 0) + 1
    return dict(sorted(counts.items()))


def restricted_entries() -> list[dict[str, Any]]:
    """재배포 금지 출처에서 온 항목. **항상 비어 있어야 한다.**"""
    return [
        item
        for item in [*entries(), *rules()]
        if str(item.get("source", "")).startswith(RESTRICTED_SOURCE_PREFIXES)
    ]

def cues() -> dict[str, list[str]]:
    """통화 마무리 신호 목록. 번역쌍이 아니라 **의도 신호**다.

    ``closing_negative`` 는 "더 없다"(종료), ``closing_positive`` 는 "더 있다"(계속).
    사투리형과 표준어형을 둘 다 담고 있어서 :func:`convert` 전후 어느 쪽에 매칭해도 걸린다.
    """
    return load_lexicon().get("cues", {})


def admin_plain() -> list[dict[str, str]]:
    """행정 문체 → 쉬운 말 대응표."""
    return load_lexicon().get("admin_plain", [])


@lru_cache(maxsize=1)
def _admin_pattern() -> tuple[re.Pattern[str] | None, dict[str, str]]:
    mapping = {item["admin"]: item["plain"] for item in admin_plain() if item.get("admin")}
    if not mapping:
        return None, mapping
    # 긴 표현부터 — "회신드리겠습니다"가 "회신"에 잡아먹히면 안 된다.
    alternation = "|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True))
    return re.compile(alternation), mapping


def soften(text: str) -> str:
    """공문체 낱말을 어르신이 알아듣는 말로 바꾼다. **to_dialect() 앞에 쓴다.**

    담당자는 "해당 건은 검토 후 회신드리겠습니다" 로 입력하는데, 여기에 어미 변환만
    걸면 "…회신드리겠습니더" 가 되어 표준어일 때보다 오히려 나빠진다. 공무원이 사투리를
    흉내 내는 소리로 들리기 때문이다. 낱말 난이도를 먼저 낮춰야 한다.

    되돌릴 수 없는 의역이라 왕복 검증 대상이 아니고, :func:`convert` 안에서 자동으로
    불리지도 않는다. 부르는 쪽이 명시적으로 선택한다.
    """
    if not text or not text.strip():
        return text
    try:
        pattern, mapping = _admin_pattern()
        if pattern is None:
            return text
        masked, saved = _mask(text)
        masked = pattern.sub(lambda m: mapping[m.group(0)], masked)
        return _unmask(masked, saved)
    except Exception:  # noqa: BLE001 - 이 레이어가 통화를 끊게 두지 않는다
        log.exception("행정용어 순화 실패 — 원문 유지")
        return text

def noun_final() -> list[dict[str, str]]:
    """명사형 종결 → 문장 종결 대응표 (진행 안내 브리핑 전용)."""
    return load_lexicon().get("noun_final", [])


#: 문장 경계. 명사형 종결은 문장 끝에서만 편다.
_SENTENCE_SPLIT = re.compile(r"([.!?。\n]+)")


@lru_cache(maxsize=1)
def _noun_final_pattern() -> tuple[re.Pattern[str] | None, dict[str, str]]:
    mapping = {item["noun"]: item["sentence"] for item in noun_final() if item.get("noun")}
    if not mapping:
        return None, mapping
    # 긴 것부터 — "확인 완료"가 "완료"에 잡아먹히면 안 된다.
    alternation = "|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True))
    return re.compile(rf"(?<![{_HANGUL}])({alternation})\s*$"), mapping


def expand_noun_final(text: str) -> str:
    """명사로 끝나는 공문 문장을 말하는 문장으로 편다.

    "현장 확인 완료." 는 글로 읽을 때는 괜찮지만 **소리 내어 읽으면 공문 낭독**이 된다.
    진행 안내 콜백(계약서 5-C)은 AI 가 읽어 주는 것이라 반드시 펴야 한다.

        >>> expand_noun_final("현장 확인 완료. 이번 주 준설 예정.")
        '현장 확인 다 했습니다. 이번 주 준설할 예정입니다.'

    문장 끝에서만 걸린다. "완료했습니다" 같은 중간 등장은 건드리지 않는다.
    """
    if not text or not text.strip():
        return text
    try:
        pattern, mapping = _noun_final_pattern()
        if pattern is None:
            return text
        parts = _SENTENCE_SPLIT.split(text)
        for index in range(0, len(parts), 2):
            segment = parts[index]
            if not segment.strip():
                continue
            parts[index] = pattern.sub(lambda m: mapping[m.group(1)], segment)
        return "".join(parts)
    except Exception:  # noqa: BLE001
        log.exception("명사형 종결 펴기 실패 — 원문 유지")
        return text


def callback_data() -> dict[str, list[str]]:
    """진행 안내 콜백의 질문 분류·회피 문구 (계약서 5-C)."""
    return load_lexicon().get("callback", {})
