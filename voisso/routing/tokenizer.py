"""한국어 질의/사무분장 텍스트를 문자 n-gram 항으로 바꾸는 경량 토크나이저.

형태소 분석기(konlpy/mecab)는 설치 부담이 커서 쓰지 않는다. 대신
  1) 정규화 -> 2) 조사·어미 꼬리 제거 -> 3) 불용어 제거 -> 4) 문자 2~3gram
순으로 처리한다. 한국어는 어절 안에서 어간이 앞에 오므로, 꼬리를 떨어내고
문자 n-gram을 쓰면 "하수구가"와 "하수관로"가 "하수"로 겹친다.

외부 의존성 없음 (표준 라이브러리만).
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------- 정규화

_KEEP = re.compile(r"[^0-9a-z가-힣]+")


def normalize(text: str) -> str:
    """NFKC 정규화 + 소문자 + 한글/영숫자 외 문자를 공백으로."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    # 가운뎃점(・, ·)·슬래시 등 구분자는 공백으로 떨어뜨린다.
    return _KEEP.sub(" ", text).strip()


# ------------------------------------------------- 조사 / 어미 꼬리 목록
#
# 긴 것부터 검사한다. 꼬리를 떼고 남은 어간이 2글자 미만이면 떼지 않는다
# (예: "도로" 의 "로" 를 조사로 오인해 "도"만 남는 사고를 막는다).

_TAILS = (
    # 종결 어미
    "습니다", "입니다", "합니다", "됩니다", "ㅂ니다",
    "이라고", "라고", "이라는", "라는",
    "했는데", "하는데", "인데요", "는데요", "은데요",
    "했다고", "한다고", "된다고",
    "해주세요", "주세요", "해주이소", "해주소", "주이소",
    "했어요", "해어요", "했어", "해요", "네요", "어요", "아요", "예요", "에요",
    "졌다", "였다", "었다", "았다", "했다", "한다", "된다", "이다",
    # 연결 어미
    "면서", "니까", "길래", "는데", "은데", "지만", "라서", "여서", "어서", "아서",
    "해서", "하고", "하는", "하여", "려고", "도록", "느라",
    "달라", "달라고", "주라", "바랍니다", "바람",
    # 조사
    "에서는", "에게는", "으로는", "에서", "에게", "한테", "께서", "이랑",
    "부터", "까지", "보다", "처럼", "만큼", "밖에", "조차", "마저",
    "으로", "이나", "라도", "이며", "이고",
    "은", "는", "이", "가", "을", "를", "의", "에", "도", "만", "과", "와", "랑", "로", "야", "아",
)
_TAILS = tuple(sorted(set(_TAILS), key=len, reverse=True))

# 꼬리를 떼면 안 되는 단어(어간 자체가 조사처럼 끝나는 도메인 용어)
_PROTECTED = {
    "도로", "농로", "수로", "통로", "진로", "경로", "항로", "노선", "상수도", "하수도",
    "국도", "지방도", "고속도로", "차로", "임도", "선로", "회로", "제도", "보도",
    "민원", "지원", "복지", "재난", "교통", "버스", "농업", "일자리", "하수", "배수",
}

_MIN_STEM = 2


def strip_tail(token: str) -> str:
    """어절에서 조사·어미 꼬리를 한 번 떼어낸다."""
    if token in _PROTECTED or len(token) <= _MIN_STEM:
        return token
    for tail in _TAILS:
        if token.endswith(tail):
            stem = token[: -len(tail)]
            if len(stem) >= _MIN_STEM and stem not in ("", tail):
                return stem
            break
    return token


# ---------------------------------------------------------------- 불용어
#
# 사무분장 원문이 아니라 "전화로 말하는 사람"이 붙이는 군더더기 위주로 골랐다.
# 부서 업무를 가리키는 실질 명사(신청, 접수, 지원 등)는 남긴다.

STOPWORDS = frozenset(
    """
    그 저 이 것 거 게 좀 참 진짜 너무 아주 정말 되게 마 예 네 응 어 음 아이고 아이구
    요즘 지금 오늘 어제 내일 이번 저번 매번 자꾸 계속 항상 아직 벌써 이제
    우리 저희 나 내 니 너 당신 여러분 사람 사람들
    여기 거기 저기 어디 어느 무슨 어떤 어떻게 왜 언제 누구 얼마 뭐 뭔가
    관련 관하여 대하여 대한 대해 위하여 위해 통하여 통해
    문의 궁금 질문 알려 여쭤 여쭙 물어 확인 부탁 요청드립 드립니다 드려요
    방법 경우 정도 부분 상황 상태 문제 때문 이유 내용 사항
    같아요 같은데 같습니다 있어요 없어요 있습니다 없습니다 인가요 나요 가요
    그리고 그런데 그래서 그러면 하지만 또는 및 등 등등 수 때 및
    """.split()
)


def analyze(text: str) -> list[str]:
    """정규화 -> 꼬리 제거 -> 불용어 제거된 어절 목록."""
    out: list[str] = []
    for raw in normalize(text).split():
        if raw in STOPWORDS:
            continue
        tok = strip_tail(raw)
        if len(tok) < 2 and not tok.isdigit():
            continue  # 1글자 어절은 노이즈가 커서 버린다
        if tok in STOPWORDS:
            continue
        out.append(tok)
    return out


# ---------------------------------------------------------------- n-gram

NGRAM_SIZES = (2, 3)
# 3-gram 은 더 구체적이라 가중치를 조금 더 준다.
NGRAM_WEIGHT = {2: 1.0, 3: 1.25}


def ngrams(token: str) -> list[str]:
    """한 어절을 문자 2/3-gram 으로 쪼갠다. 짧으면 어절 자체를 항으로 쓴다."""
    if len(token) <= 2:
        return [token]
    grams: list[str] = []
    for n in NGRAM_SIZES:
        if len(token) < n:
            continue
        grams.extend(token[i : i + n] for i in range(len(token) - n + 1))
    return grams


def terms(text: str) -> list[str]:
    """텍스트 -> 검색 항(문자 n-gram) 리스트. 중복은 빈도로 유지한다."""
    out: list[str] = []
    for tok in analyze(text):
        out.extend(ngrams(tok))
    return out


def term_weight(term: str) -> float:
    return NGRAM_WEIGHT.get(len(term), 1.0)
