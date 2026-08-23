"""발화용 텍스트 변환 — **TTS 직전에만** 적용한다.

TTS 가 "119" 를 "백십구" 로 읽으면 어르신이 못 알아듣는다. 긴급번호는
**낱자로** 읽혀야 한다: "일일구", "일일이".

**화면과 저장은 그대로 "119" 다.** 이 변환은 합성 직전 한 번만 걸린다.
민원카드·통화 기록·자막에 들어가는 텍스트는 손대지 않는다. 담당자가 나중에
카드를 열었을 때 "일일구"라고 적혀 있으면 안 되기 때문이다.
"""

from __future__ import annotations

import re

# 숫자 낱자. 전화번호는 "공" 으로 읽는 것이 자연스럽다.
_DIGIT_SOUND = {
    "0": "공",
    "1": "일",
    "2": "이",
    "3": "삼",
    "4": "사",
    "5": "오",
    "6": "육",
    "7": "칠",
    "8": "팔",
    "9": "구",
}

# 대표번호는 낱자로 읽으면 여덟 자라 너무 길다. 이름으로 읽는 편이 알아듣기 쉽다.
GB_MAIN_PHONE = "1522-0120"
GB_MAIN_PHONE_SPOKEN = "경상북도청 대표번호"

# 긴급번호. 자리 수가 적어 낱자로 읽어도 짧다.
_EMERGENCY = {"119": "일일구", "112": "일일이", "113": "일일삼", "182": "일팔이"}

# 전화번호 꼴. 하이픈·공백으로 끊긴 것과 붙은 것 모두.
_PHONE_RE = re.compile(r"(?<!\d)(0\d{1,2})[-.\s]?(\d{3,4})[-.\s]?(\d{4})(?!\d)")
# 마스킹된 번호도 읽어야 한다: 010-****-5678
_MASKED_RE = re.compile(r"(?<![\d*])(\d{2,4}|\*{2,4})([-.\s])(\*{2,4}|\d{3,4})\2(\d{4})(?![\d*])")
# 홀로 선 긴급번호. 숫자 사이에 낀 것은 건드리지 않는다.
_EMERGENCY_RE = re.compile(r"(?<!\d)(119|112|113|182)(?!\d)")


def _read_digits(text: str) -> str:
    """전화번호를 낱자로 편다.

    **그룹 단위로 붙여 읽는다.** 자리마다 띄우면("공 일 공") 뚝뚝 끊겨 들린다.
    "010-1234-5678" -> "공일공 일이삼사 오육칠팔"
    마스킹된 자리(****)는 읽지 않고 건너뛴다.
    """
    groups: list[str] = []
    current: list[str] = []
    for char in text:
        if char in _DIGIT_SOUND:
            current.append(_DIGIT_SOUND[char])
        elif char == "*":
            continue  # 가려진 자리는 소리 내지 않는다
        elif char in "-. ":
            if current:
                groups.append("".join(current))
                current = []
    if current:
        groups.append("".join(current))
    return " ".join(groups)


def _speak_main_phone(text: str) -> str:
    """대표번호를 읽는 방식을 문맥에 따라 고른다.

    보통은 이름으로 읽는 게 알아듣기 쉽다("경상북도청 대표번호").
    다만 문장에 **이미 그 이름이 있으면** 같은 말이 두 번 나온다:

        "경상북도청 대표번호 1522-0120 입니더"
        -> "경상북도청 대표번호 경상북도청 대표번호 입니더"   (버그)

    그럴 때는 숫자를 낱자로 읽어 이름과 번호가 자연스럽게 이어지게 한다.
    """
    if GB_MAIN_PHONE not in text:
        return text

    # 번호를 뺀 나머지에 이미 이름이 있으면 중복이다.
    rest = text.replace(GB_MAIN_PHONE, "")
    if "대표번호" in rest:
        return text.replace(GB_MAIN_PHONE, _read_digits(GB_MAIN_PHONE))

    spoken = text.replace(GB_MAIN_PHONE, GB_MAIN_PHONE_SPOKEN)
    # "1522-0120으로" 처럼 조사가 붙어 있으면 받침이 달라진다.
    spoken = spoken.replace(f"{GB_MAIN_PHONE_SPOKEN} 으로", f"{GB_MAIN_PHONE_SPOKEN}로")
    return spoken.replace(f"{GB_MAIN_PHONE_SPOKEN}으로", f"{GB_MAIN_PHONE_SPOKEN}로")


def for_speech(text: str) -> str:
    """화면용 텍스트를 **발화용**으로 바꾼다.

        "119에 연결해 드릴까요?"        -> "일일구에 연결해 드릴까요?"
        "010-1234-5678 맞으신가요?"    -> "공일공 일이삼사 오육칠팔 맞으신가요?"
        "1522-0120 으로 전화 주세요"    -> "경상북도청 대표번호 으로 전화 주세요"

    저장·표시용 텍스트에는 절대 쓰지 마라.
    """
    if not text:
        return text

    spoken = _speak_main_phone(text)
    # 전화번호를 먼저 편다. 긴급번호 치환보다 앞서야 번호 안의 숫자가 안 깨진다.
    spoken = _MASKED_RE.sub(lambda m: _read_digits(m.group(0)), spoken)
    spoken = _PHONE_RE.sub(lambda m: _read_digits(m.group(0)), spoken)
    spoken = _EMERGENCY_RE.sub(lambda m: _EMERGENCY[m.group(1)], spoken)
    return spoken
