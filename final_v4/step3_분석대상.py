"""
3단계: 분석대상 범위 재결정 (B결정 갱신, 2026-10-06)
====================================================
기존 B결정(10-04, feature_v3.py): 용량 결측 6개 시도(부산·대구·울산·경북·경남·제주)를 '시도 목록'으로 제외
  + 전력공급 무응답 5곳 + 변전소응답없음 → 분석대상 174개
변경: 영남 전력공급 데이터가 공개되어 '시도 목록' 대신 '지역별 실제 응답 여부'로 분류한다.

분류 규칙 (위에서부터 먼저 걸리는 것 적용, 상수로 조정 가능)
  R1 제외      변전소 응답 전무 (전력공급·재생e·차단기 모두 0) → 판정 불가 (예: 울릉군)
  R2 참고등급  시도 전체가 전력공급 미수집 (전력공급154kV_데이터있음 = 0) → 접속점수 단독 (예: 제주)
  R3 참고등급  154kV 전력공급 응답 없음 → 용량점수 계산 불가 (용량 가중치 0.9가 154kV)
               REQUIRE_154 = False로 두면 기존 v3 규칙(154·22.9 둘 다 0일 때만 무응답)으로 돌아감
  R4 참고등급  차단기(변전소기준) 응답 없음 → 22.9/154kV 접속 여유율 계산 불가
               기존 v3는 이 경우 여유율을 0으로 계산해 분석대상에 남겼음(사실상 '여유 없음'으로 감점).
               CBR_MISSING_TO_REF = False로 두면 기존 방식 유지
  그 외        분석대상
  ※ 345kV 공급지역 없음(0)은 결측이 아니라 '345kV 공급가능지역에 포함 안 됨'이라는 실제 값 → 분석대상 유지
  ※ 22.9kV만 없는 지역은 범위에서 빼지 않음 (가중치 0.1). 4단계에서 0으로 볼지 결측으로 볼지 결정 — 플래그만 붙임

입력  데이터셋/전력_시군구wide_256_재집계_*.csv (가장 최근 날짜)
      (선택) ../final_v3/데이터셋/전력_최종피쳐_공유용_v3_*.csv  — 기존 분류와 비교용
출력  데이터셋/분석대상_분류_256_{날짜}.csv   256행: 지역코드, 시도명, 시군구명, 분류, 사유, 판단 근거 플래그
"""
import glob
import os
import sys
from datetime import datetime
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "데이터셋")
TAG = datetime.now().strftime("%Y%m%d")
OUT = os.path.join(DATA, f"분석대상_분류_256_{TAG}.csv")
OLD_GLOB = os.path.join(HERE, "..", "final_v3", "데이터셋", "전력_최종피쳐_공유용_v3_*.csv")

REQUIRE_154 = True          # R3: 154kV 응답 필수
CBR_MISSING_TO_REF = True   # R4: 차단기 무응답은 참고등급

N154, N229 = "전력공급154kV_변전소수", "전력공급229kV_변전소수"
NREN, NCBR, N345 = "재생e연계_변전소수", "차단기_변전소기준_변전소수", "차단기_공급지역기준_변전소수"
COV154 = "전력공급154kV_데이터있음"


def latest(pattern):
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def classify(w):
    f = w[["지역코드", "시도명", "시군구명"]].copy()
    f["154kV응답"] = w[N154] > 0
    f["22.9kV응답"] = w[N229] > 0
    f["차단기응답"] = w[NCBR] > 0
    f["345kV공급지역"] = w[N345] > 0
    f["시도_전력공급수집"] = w[COV154] == 1
    f["변전소응답전무"] = (w[[N154, N229, NREN, NCBR]].sum(axis=1) == 0)
    no_cap = ~f["154kV응답"] if REQUIRE_154 else (~f["154kV응답"] & ~f["22.9kV응답"])

    rules = [  # (조건, 분류, 사유) — 위에서부터 먼저 걸리는 것
        (f["변전소응답전무"], "제외", "R1 변전소 응답 전무"),
        (~f["시도_전력공급수집"], "참고등급", "R2 시도 전력공급 미수집"),
        (f["시도_전력공급수집"] & no_cap, "참고등급", "R3 154kV 전력공급 무응답"),
    ]
    if CBR_MISSING_TO_REF:
        rules.append((~f["차단기응답"], "참고등급", "R4 차단기 무응답"))
    f["분류"], f["사유"] = "분석대상", ""
    done = pd.Series(False, index=f.index)
    for cond, cls, why in rules:
        hit = cond & ~done
        f.loc[hit, ["분류", "사유"]] = [cls, why]
        done |= hit
    f["22.9kV결측_분석대상"] = (f["분류"] == "분석대상") & ~f["22.9kV응답"]   # 4단계 처리 결정용
    return f


def compare_old(f):
    p = latest(OLD_GLOB)
    if not p:
        print("  (기존 v3 공유용 파일 없음 — 비교 생략)")
        return
    o = pd.read_csv(p, encoding="utf-8-sig")
    o["기존"] = o["분석대상"].map({True: "분석대상", False: "비대상"})
    o.loc[o.get("참고등급", False) == True, "기존"] = "참고등급"
    m = f.merge(o[["지역코드", "기존"]], on="지역코드", how="left")
    print(f"\n[기존 v3 → 새 분류]  ({os.path.basename(p)})")
    print(pd.crosstab(m["기존"].fillna("?"), m["분류"], margins=True, margins_name="합계").to_string())
    moved = m[(m["기존"] == "분석대상") & (m["분류"] != "분석대상")]
    if len(moved):
        print("  기존 분석대상 → 이번에 빠진 지역:",
              [f"{a} {b}({c})" for a, b, c in zip(moved["시도명"], moved["시군구명"], moved["사유"])])


def main():
    src = latest(os.path.join(DATA, "전력_시군구wide_256_재집계_*.csv"))
    if not src:
        sys.exit("!! 재집계 wide 없음 — 2단계(step2_시군구.py) 먼저 실행")
    w = pd.read_csv(src, encoding="utf-8-sig")
    assert len(w) == 256 and w["지역코드"].is_unique, "재집계 wide가 256행이 아님"
    print(f"입력: {os.path.basename(src)}")
    print(f"규칙: REQUIRE_154={REQUIRE_154}, CBR_MISSING_TO_REF={CBR_MISSING_TO_REF}")

    f = classify(w)
    f.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"저장: {OUT}")

    print("\n[분류 요약]", f["분류"].value_counts().to_dict())
    for why, g in f[f["분류"] != "분석대상"].groupby("사유"):
        print(f"  {why} ({len(g)}): {(g['시도명'] + ' ' + g['시군구명']).tolist()}")
    print("\n[시도별 분석대상 수]")
    print(f.groupby("시도명")["분류"].apply(lambda s: f"{(s == '분석대상').sum()}/{len(s)}").to_string())
    g = f[f["22.9kV결측_분석대상"]]
    print(f"\n[4단계 결정 필요] 분석대상 중 22.9kV 응답 없는 지역 {len(g)}곳 (0 처리 vs 결측 처리)")
    print("  ", g.groupby("시도명").size().to_dict())
    compare_old(f)


if __name__ == "__main__":
    main()