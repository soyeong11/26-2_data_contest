"""
전력 피쳐 v4 (2026-10-06) — 영남 포함 재크롤링 · 용량점수 단독 · B안
=====================================================================
v3 → v4 변경
  [범위]  분석대상을 3단계 분류 파일(분석대상_분류_256_*.csv)에서 읽음
          (기존: 코드 안의 NO_CAP_SIDO 6개 시도 목록) → 분석대상 250 / 참고등급 5 / 제외 1
  [지표]  전력피쳐 = 용량점수 단독 (접속점수·병목·EWM 삭제)
  [용량]  B안: 용량MW = max(22.9kV 단일변전소 최대 여유, 154kV 단일변전소 최대 여유)
          → 분석대상 기준 min-max (최솟값 0이라 사실상 MW ÷ 최댓값)
          근거: 한 부지는 한 전압으로 받으므로 받을 수 있는 최대 전력은 둘 중 큰 쪽이고,
                단위가 같은 MW라 전압별 가중치가 필요 없음 (기존 1:9는 각각 정규화한 뒤
                가중치를 곱해 22.9kV처럼 범위가 좁은 값이 부풀려지는 문제가 있었음)
          22.9kV 변전소의 99.9%가 154kV 목록과 같은 변전소 → 합치지 않고 max만 써서 이중계산 없음
  [순위]  동점은 그대로 (rank method="min": 같은 순위, 다음 순위는 건너뜀)
  [판정]  수용가능_1GW/0.5GW는 용량MW 기준만 (1,250MW / 625MW = IT 1GW·0.5GW × PUE 1.25)
          345kV 여유 Bay는 점수에 넣지 않는 참고 열로만 남김
  [2032]  장기 시나리오는 상세 파일에만 (참고)
  [10-08] 256곳 전부 분석대상 (step3 INCLUDE_ALL=True). 전력공급 응답이 없는 6곳(제주시·서귀포시·강진·영종·옹진·울릉)은
          0MW로 계산되며 '전력공급무응답' 플래그로 구분 (0 = 자료 없음, 여유 없음 아님)

실행 (final_v4 폴더)
  python step3_분석대상.py   (REQUIRE_154=False, CBR_MISSING_TO_REF=False 상태로 먼저)
  python feature_v4.py
  python sensitivity_v4.py

입력  데이터셋/전력_시군구wide_256_재집계_*.csv, 데이터셋/분석대상_분류_256_*.csv (각각 최신 날짜)
      데이터셋/기준_시군구256.csv, 데이터셋/개편재배정_내역_*.csv (개편재배정 플래그용, 없으면 False)
출력  데이터셋/전력_최종피쳐_공유용_v4_{날짜}.csv   ← 팀 공유·병합용 (256행)
      데이터셋/전력피쳐_상세_256_v4_{날짜}.csv      ← 원값·2032 시나리오 포함
"""
import glob
import os
import sys
from datetime import datetime
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "데이터셋")
TAG = datetime.now().strftime("%Y%m%d")
OUT_SHARE = os.path.join(DATA, f"전력_최종피쳐_공유용_v4_{TAG}.csv")
OUT_FEAT = os.path.join(DATA, f"전력피쳐_상세_256_v4_{TAG}.csv")

BASE_YEAR, LONG_YEAR = 2029, 2032
DEMAND_MW = {"1GW": 1250, "0.5GW": 625}      # IT 부하 × PUE 1.25 (v3·신재생 피처와 동일 가정)
COL_345 = "차단기_공급지역기준_345kV여유_합계"


def latest(pattern):
    files = sorted(glob.glob(os.path.join(DATA, pattern)))
    if not files:
        sys.exit(f"!! 입력 없음: 데이터셋/{pattern}")
    return files[-1]


def load():
    wp, cp = latest("전력_시군구wide_256_재집계_*.csv"), latest("분석대상_분류_256_*.csv")
    w = pd.read_csv(wp, encoding="utf-8-sig")
    c = pd.read_csv(cp, encoding="utf-8-sig")
    base = pd.read_csv(os.path.join(DATA, "기준_시군구256.csv"), encoding="utf-8-sig")
    print(f"입력: {os.path.basename(wp)}, {os.path.basename(cp)}")
    if list(w["지역코드"]) != list(base["시군구코드"]) or list(c["지역코드"]) != list(base["시군구코드"]):
        sys.exit("!! 재집계 wide / 분류 파일의 코드·순서가 기준표와 다름")
    if c["사유"].fillna("").str.startswith("R4").any():
        sys.exit("!! 분류 파일에 R4(차단기 무응답)가 남아 있음 — step3_분석대상.py의 CBR_MISSING_TO_REF=False로 다시 실행")
    if c["사유"].fillna("").str.startswith("R3").any() and \
            (c.loc[c["사유"].fillna("").str.startswith("R3"), "22.9kV응답"]).any():
        sys.exit("!! R3에 22.9kV 응답이 있는 지역이 있음 — step3_분석대상.py의 REQUIRE_154=False로 다시 실행")
    return w, c


def capacity_mw(w, year):
    """B안: 지역별 max(22.9kV 최대, 154kV 최대) MW와 그 값을 준 전압"""
    v229, v154 = w[f"전력공급229kV_{year}년_최대"], w[f"전력공급154kV_{year}년_최대"]
    mw = np.maximum(v229, v154)
    volt = np.select([mw <= 0, v154 >= v229], ["없음", "154kV"], "22.9kV")   # 같으면 154kV
    return mw, pd.Series(volt, index=w.index)


def minmax(x, ok):
    lo, hi = x[ok].min(), x[ok].max()
    return (x * 0.0 if hi == lo else (x - lo) / (hi - lo)).where(ok)


def rank_desc(s, ok):
    return s.where(ok).rank(ascending=False, method="min").astype("Int64")


def reassigned_codes():
    files = sorted(glob.glob(os.path.join(DATA, "개편재배정_내역_*.csv")))
    if not files:
        print("  (개편재배정_내역 없음 — 개편재배정 플래그는 False)")
        return set()
    lg = pd.read_csv(files[-1], encoding="utf-8-sig", dtype={"신코드": str})
    hit = lg["처리"].str.startswith("재배정") | lg["처리"].str.startswith("345kV 상위지역 복제")
    return set(lg.loc[hit, "신코드"].dropna().astype(float).astype(int))


def build(w, c):
    ok = c["분류"].eq("분석대상")
    f = pd.DataFrame({"시군구코드": w["지역코드"], "지역코드": w["지역코드"],
                      "시도명": w["시도명"], "시군구명": w["시군구명"], "분류": c["분류"], "분류사유": c["사유"]})

    for y in (BASE_YEAR, LONG_YEAR):
        mw, volt = capacity_mw(w, y)
        sfx = "" if y == BASE_YEAR else f"_{y}"
        f[f"용량MW_{y}"] = mw.where(ok)
        f[f"결정전압{sfx}"] = volt.where(ok)
        f[f"전력피쳐{sfx}"] = minmax(mw, ok)
        f[f"전력순위{sfx}"] = rank_desc(f[f"전력피쳐{sfx}"], ok)
        f[f"전력공급229kV_{y}년_최대"] = w[f"전력공급229kV_{y}년_최대"].where(ok)
        f[f"전력공급154kV_{y}년_최대"] = w[f"전력공급154kV_{y}년_최대"].where(ok)

    mw = f[f"용량MW_{BASE_YEAR}"]
    for k, need in DEMAND_MW.items():          # 분석대상만 판정, 나머지는 빈칸(미충족과 구분)
        f[f"수용가능_{k}"] = (mw >= need).astype("boolean").where(ok, pd.NA)

    # 원본에 전력공급 응답이 없어 0MW로 계산된 지역 (0 = '여유 없음'이 아니라 '자료 없음')
    f["전력공급무응답"] = (w["전력공급229kV_변전소수"] + w["전력공급154kV_변전소수"]) == 0
    f["345kV여유Bay"] = w[COL_345]              # 참고 열 — 점수 미반영
    f["345kV_상위지역공유"] = w["345kV_상위지역공유"].astype(bool)
    f["개편재배정"] = f["지역코드"].isin(reassigned_codes())
    return f


SHARE_COLS = ["시군구코드", "지역코드", "시도명", "시군구명", "분류",
              "전력피쳐", "전력순위", f"용량MW_{BASE_YEAR}", "결정전압",
              "수용가능_0.5GW", "수용가능_1GW", "전력공급무응답", "345kV여유Bay", "345kV_상위지역공유", "개편재배정"]


def check(f, c):
    errs = []
    ok = f["분류"].eq("분석대상")
    if len(f) != 256 or not f["시군구코드"].is_unique:
        errs.append("256행·코드 유일")
    if not (f["분류"].values == c["분류"].values).all():
        errs.append("분류 파일과 불일치")
    s = f.loc[ok, "전력피쳐"]
    if s.isna().any() or s.min() < 0 or s.max() > 1 + 1e-12:
        errs.append("분석대상 전력피쳐 범위/결측")
    if f.loc[~ok, ["전력피쳐", "전력순위", f"용량MW_{BASE_YEAR}"]].notna().any().any():
        errs.append("참고·제외 지역에 점수 있음")
    if f.loc[ok, "전력순위"].isna().any() or f.loc[ok, "전력순위"].max() > ok.sum():
        errs.append("순위")
    if f.loc[ok, "수용가능_0.5GW"].isna().any() or f.loc[~ok, "수용가능_0.5GW"].notna().any():
        errs.append("수용가능 판정 범위")
    print("[검증]", "통과" if not errs else errs)
    assert not errs


def summary(f):
    ok = f["분류"].eq("분석대상")
    print(f"\n분석대상 {int(ok.sum())} · 참고등급 {int(f['분류'].eq('참고등급').sum())} · 제외 {int(f['분류'].eq('제외').sum())}")
    print("결정전압:", f.loc[ok, "결정전압"].value_counts().to_dict())
    zero = int((f.loc[ok, f"용량MW_{BASE_YEAR}"] == 0).sum())
    print(f"용량 0MW(공동 최하위): {zero}곳 · 최댓값 {f.loc[ok, f'용량MW_{BASE_YEAR}'].max():.0f}MW")
    print(f"수용가능 0.5GW {int(f['수용가능_0.5GW'].sum())}곳 · 1GW {int(f['수용가능_1GW'].sum())}곳 (MW 기준)")
    print(f"참고: 345kV 여유Bay ≥1 인 분석대상 {int((f.loc[ok, '345kV여유Bay'] >= 1).sum())}곳 (점수 미반영)")
    top = f[ok].sort_values(["전력순위", "시군구코드"]).head(15)
    print("\n상위 15 (동점 포함):")
    print(top[["전력순위", "시도명", "시군구명", f"용량MW_{BASE_YEAR}", "결정전압", "전력피쳐"]]
          .round({"전력피쳐": 3}).to_string(index=False))


def main():
    w, c = load()
    f = build(w, c)
    check(f, c)
    s = f[SHARE_COLS].copy()
    s["전력피쳐"] = s["전력피쳐"].round(6)
    s.to_csv(OUT_SHARE, index=False, encoding="utf-8-sig")
    f.to_csv(OUT_FEAT, index=False, encoding="utf-8-sig")
    print("저장:", os.path.basename(OUT_SHARE), os.path.basename(OUT_FEAT))
    summary(f)


if __name__ == "__main__":
    main()