# -*- coding: utf-8 -*-
"""왕복 보존 테스트 — 이 모듈의 품질 게이트다.

``to_dialect`` 로 사투리를 만든 뒤 ``normalize`` 로 되돌렸을 때 **의미가 보존되는지**
확인한다. 글자까지 똑같아야 한다는 뜻은 아니다. "되십니까"와 "되세요"는 문자열은
다르지만 같은 말이고, 그런 차이까지 실패로 처리하면 자연스러운 규칙을 버리게 된다.

그래서 두 단계로 본다.

* **exact**  — 원문과 글자까지 같다.
* **semantic** — 어절 수가 같고, 달라진 어절도 어간을 공유하며, 되돌린 문장에
  사투리 흔적이 남아 있지 않고, 높임 등급이 유지된다.

둘 다 아니면 **실패**다. 실패하는 규칙은 ``lexicon.json`` 에서 ``roundtrip: false``
로 내려 ``to_dialect`` 에서 빼야 한다. 양보다 자연스러움이 먼저다.
"""

from __future__ import annotations

import re
import unittest

from voisso.dialect import normalize, to_dialect

#: 민원 통화에서 시스템이 실제로 내보낼 만한 표준어 문장들.
CORPUS = [
    # 인사·안내
    "안녕하세요. 경상북도 민원실입니다.",
    "무엇을 도와드릴까요?",
    "어떤 일로 전화 주셨어요?",
    "네, 말씀하세요.",
    "천천히 말씀해 주세요.",
    "잘 안 들리는데 다시 한 번 말씀해 주시겠어요?",
    "확인해 드리겠습니다.",
    "잠시만 기다려 주세요.",
    "조금만 기다려 주시겠어요?",
    "지금 확인하고 있습니다.",
    # 접수
    "접수해 드리겠습니다.",
    "접수되었습니다.",
    "민원이 정상적으로 접수되었어요.",
    "담당 부서로 전달하겠습니다.",
    "담당자가 연락드릴 예정입니다.",
    "담당자가 확인 후 연락드리겠습니다.",
    "빠른 시일 안에 처리하겠습니다.",
    "오늘 중으로 처리해 드릴게요.",
    "내일 다시 연락드릴게요.",
    "접수 번호를 알려 드릴게요.",
    # 정보 확인
    "성함을 알려 주시겠어요?",
    "어느 마을에 사세요?",
    "주소를 말씀해 주세요.",
    "연락처를 남겨 주세요.",
    "연락처를 하나만 남겨 주시겠어요?",
    "언제부터 그러셨어요?",
    "언제쯤 시작되었나요?",
    "다친 곳은 없으세요?",
    "지금도 계속 그런가요?",
    "사진을 보내 주실 수 있나요?",
    # 물·상하수
    "물이 새는 위치를 알려 주세요.",
    "수도가 언제부터 안 나왔어요?",
    "하수구가 막힌 것 같습니다.",
    "배수 시설을 점검하겠습니다.",
    "도랑 정비를 요청하겠습니다.",
    "비가 오면 물이 고이는군요.",
    "상수도과로 연결해 드릴게요.",
    # 도로
    "길이 패인 곳이 어디쯤인가요?",
    "도로 보수를 요청하겠습니다.",
    "가로등이 언제부터 안 켜졌어요?",
    "그 길은 군에서 관리합니다.",
    "위험하니 조심하세요.",
    "현장에 나가서 확인하겠습니다.",
    # 농사
    "농기계 지원 사업을 안내해 드릴게요.",
    "수매 일정은 농협에 문의하세요.",
    "멧돼지 피해는 별도로 신고하셔야 합니다.",
    "비료 지원 신청 기간이 지났습니다.",
    "과수원 피해 조사를 나가겠습니다.",
    # 보건·복지
    "보건소에 문의해 보시겠어요?",
    "많이 아프시면 병원부터 가세요.",
    "기초연금은 읍면사무소에서 신청합니다.",
    "노인 돌봄 서비스를 안내해 드릴게요.",
    "거동이 불편하시면 방문 접수도 됩니다.",
    # 교통
    "버스 시간표를 확인해 드릴게요.",
    "그 노선은 하루 세 번 다닙니다.",
    "정류장 위치를 알려 주세요.",
    "터미널에 문의해 보세요.",
    # 금전·서류
    "지원금 신청은 다음 달부터입니다.",
    "서류를 준비해 오셔야 합니다.",
    "도장을 가지고 오세요.",
    "신분증만 있으면 됩니다.",
    "수수료는 없습니다.",
    "고지서를 다시 보내 드릴게요.",
    # 마무리
    "더 궁금한 점 있으세요?",
    "다른 문의 사항은 없으신가요?",
    "말씀 감사합니다.",
    "고맙습니다.",
    "안녕히 계세요.",
    "건강하세요.",
    "언제든지 전화 주세요.",
    "도움이 되었으면 좋겠습니다.",
    # 숫자·고유명사 보존
    "대표번호는 1522-0120입니다.",
    "건설도시국 도로과로 접수했습니다.",
    "안동시 옥동으로 확인했습니다.",
    "3일 이내에 처리됩니다.",
    "오전 9시부터 오후 6시까지 운영합니다.",
    "담당자는 054-880-XXXX으로 연락드립니다.",
    "농축산유통국 축산정책과 소관입니다.",
    # 다양한 어미
    "그렇습니다.",
    "맞습니다.",
    "아닙니다.",
    "가능합니다.",
    "어렵습니다.",
    "확인했습니다.",
    "알겠습니다.",
    "그런가요?",
    "괜찮으세요?",
    "그렇군요.",
    "알겠어요.",
    "그렇죠.",
    "맞아요.",
    "좋아요.",
    "그럼요.",
    "여기 있어요.",
    "제가 도와드릴게요.",
    "같이 확인해 봅시다.",
    "이렇게 하시면 됩니다.",
    "그러면 제가 접수하겠습니다.",
    "그런데 주소가 어떻게 되세요?",
    "그리고 연락처도 필요합니다.",
    "다시 말씀드리겠습니다.",
    "제가 다시 설명해 드릴게요.",
    "잘 알겠습니다.",
    "조금 더 자세히 말씀해 주세요.",
    "빨리 처리해 드리겠습니다.",
    "많이 불편하셨겠어요.",
    "불편을 드려 죄송합니다.",
    "이해해 주셔서 감사합니다.",
]

#: 되돌린 문장에 남아 있으면 안 되는 사투리 흔적.
_RESIDUE = re.compile(
    r"니더|니꺼|니껴|심더|입시더|이소(?=[\s.,!?…]|$)|능교|는교|인교"
    r"|지예|네예|라예|그란데|그라믄|그라고|예(?=[\s.,!?…]|$)"
)
#: 높임 등급 판정에 쓰는 종결형. 표준어와 경북 정중체를 **둘 다** 알아야 한다.
#: ("드리겠습니더"는 정중한 말이지 반말이 아니다.)
_POLITE = re.compile(
    r"(?:요|죠|니다|니까|시오|세요"      # 표준어
    r"|니더|니꺼|니껴|심더|입시더|이소|지예|네예|라예|능교|인교|예"  # 경북 정중체
    r")[\s.,!?…\"'’”\)\]]*$"
)


def _politeness(text: str) -> bool:
    return bool(_POLITE.search(text.strip()))


def classify(original: str, back: str) -> str:
    """왕복 결과를 exact / semantic / fail 로 분류한다."""
    if original == back:
        return "exact"
    if _RESIDUE.search(back):
        return "fail"
    if _politeness(original) != _politeness(back):
        return "fail"
    src, dst = original.split(), back.split()
    if len(src) != len(dst):
        return "fail"
    for a, b in zip(src, dst):
        if a == b:
            continue
        # 달라진 어절은 어간을 공유해야 한다. 내용어가 통째로 바뀌면 실패다.
        if not (a[0] == b[0] and (len(a) == 1 or len(b) == 1 or a[:2] == b[:2] or a[0] == b[0])):
            return "fail"
        if a[0] != b[0]:
            return "fail"
    return "semantic"


class RoundTripTest(unittest.TestCase):
    """to_dialect → normalize 를 거쳐도 의미가 보존되는가."""

    def test_no_failures(self):
        failures = []
        for sentence in CORPUS:
            dialect = to_dialect(sentence)
            back = normalize(dialect)
            if classify(sentence, back) == "fail":
                failures.append(f"\n  원문 : {sentence}\n  사투리: {dialect}\n  복원 : {back}")
        self.assertEqual(
            [], failures,
            "왕복에서 의미가 깨진 문장이 있다. 원인이 된 규칙을 lexicon.json 에서 "
            "roundtrip: false 로 내려 to_dialect 에서 빼라." + "".join(failures),
        )

    def test_exact_rate_is_high(self):
        """대부분은 글자까지 복원되어야 한다. 낮아지면 규칙이 비가역적이라는 뜻이다."""
        exact = sum(1 for s in CORPUS if classify(s, normalize(to_dialect(s))) == "exact")
        rate = exact / len(CORPUS)
        self.assertGreaterEqual(
            rate, 0.80,
            f"글자 단위 복원율이 {rate:.1%} 로 낮다 (기준 80%). 비가역 규칙을 점검하라.",
        )

    def test_to_dialect_actually_changes_text(self):
        """변환이 실제로 일어나야 한다. 아무것도 안 바뀌면 레이어가 죽은 것이다."""
        changed = sum(1 for s in CORPUS if to_dialect(s) != s)
        self.assertGreaterEqual(
            changed / len(CORPUS), 0.80,
            "to_dialect 가 문장 대부분을 그대로 통과시키고 있다.",
        )

    def test_politeness_never_drops(self):
        """어르신 대상 공공 서비스다. 존댓말이 반말로 떨어지면 안 된다."""
        for sentence in CORPUS:
            if not _politeness(sentence):
                continue
            with self.subTest(sentence=sentence):
                self.assertTrue(
                    _politeness(to_dialect(sentence)),
                    f"높임이 사라졌다: {sentence!r} → {to_dialect(sentence)!r}",
                )

    def test_idempotent(self):
        """두 번 돌려도 결과가 같아야 한다."""
        for sentence in CORPUS[:30]:
            with self.subTest(sentence=sentence):
                once = to_dialect(sentence)
                self.assertEqual(once, to_dialect(once))
                norm = normalize(sentence)
                self.assertEqual(norm, normalize(norm))


if __name__ == "__main__":
    unittest.main()
