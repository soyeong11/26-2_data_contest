"""
전력 피쳐 계산: 데이터셋/지역별_시군구_wide.csv -> 데이터셋/전력피쳐_지역별_시군구.csv

재크롤링 후에도 그대로 재사용 가능:
  kepco_crawler.py는 크롤링할 때마다 '컬럼 이름이 같은' 지역별_시군구_wide.csv를
  만들도록 짜여 있습니다(sup154_y2029_sum 같은 이름은 코드가 고정으로 정하는 것이지
  그날그날 받아온 데이터 내용과는 무관합니다). 그래서 이 스크립트는 수정 없이 다시
  실행하면 됩니다. 단, "같은 계산 방법이 다시 적용된다"는 뜻이지 "같은 숫자가 나온다"는
  뜻은 아닙니다 — 그 사이 KEPCO 쪽 실제 여유용량/Bay 현황이 바뀌었다면 결과도 바뀌는
  게 정상입니다(오히려 안 바뀌면 그게 이상한 겁니다).
  실행 순서: python kepco_crawler.py  ->  python compute_power_feature.py

가중치·기준연도는 아래 상수에서 조정하면 됩니다. 숫자 자체(0.3/0.7, 0.2/0.3/0.5,
0.5/0.5)는 아직 근거 논문/전문가 검토를 거치지 않은 제 제안값이니, AHP 가중치가
정해지면 바꿔서 다시 돌리면 됩니다.
"""
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kepco_crawler import load_wide, save_csv  # noqa: E402

YEAR = 2029                                              # 용량 여유를 어느 연도 기준으로 볼지
W_CAP = {"sup229": 0.3, "sup154": 0.7}                    # 용량 여유 내부 가중치 (합 1)
W_CONN = {"cbr_b229": 0.2, "cbr_b154": 0.3, "c345_b345": 0.5}  # 접속 여유 내부 가중치 (합 1)
W_FEATURE = {"cap": 0.5, "conn": 0.5}                     # 전력피쳐 = cap*W + conn*W


def covered_series(df, block):
    """{block}_covered 컬럼이 있으면 그대로, 없으면(옛 산출물) 전부 수집된 것으로 간주."""
    col = f"{block}_covered"
    return df[col] if col in df.columns else pd.Series(1, index=df.index)


def minmax(s):
    lo, hi = s.min(), s.max()           # skipna=True 기본값 -> NaN(미수집)은 정규화 기준에서 자동 제외
    if pd.isna(lo) or hi == lo:
        return pd.Series(0.0, index=s.index)
    return (s - lo) / (hi - lo)


def safe_ratio(num, den):
    """분모가 0이거나 결측이면(예: 그 지역에 345kV 변전소가 없음) 0으로 처리 — '접속 여유 없음'과 동일하게 취급."""
    return (num / den.replace(0, pd.NA)).fillna(0.0)


def main():
    df = load_wide("sgg")

    # ── ① 용량 여유 (capacity headroom): sup229/sup154 전력공급 여유용량 ──
    cap_score = pd.Series(0.0, index=df.index)
    missing = pd.Series(False, index=df.index)
    for blk, w in W_CAP.items():
        cov = covered_series(df, blk)
        missing = missing | (cov == 0)
        val = df[f"{blk}_y{YEAR}_sum"].where(cov == 1)        # 미수집 지역은 NaN 처리 -> 정규화에 안 섞임
        cap_score = cap_score.add(w * minmax(val), fill_value=0.0)
    df["cap_score"] = cap_score.mask(missing)                 # 블록 중 하나라도 미수집이면 전체를 NaN으로
    df["cap_missing"] = missing

    # ── ② 접속 여유 (interconnection feasibility): 차단기 Bay 여유율 ──
    df["cbr_b229_futu_ratio"] = safe_ratio(df["cbr_b229_futu_sum"], df["cbr_b229_total_sum"])
    df["cbr_b154_futu_ratio"] = safe_ratio(df["cbr_b154_futu_sum"], df["cbr_b154_total_sum"])
    df["c345_b345_futu_ratio"] = safe_ratio(df["c345_b345_futu_sum"], df["c345_b345_total_sum"])
    df["conn_score"] = (
        W_CONN["cbr_b229"] * df["cbr_b229_futu_ratio"]
        + W_CONN["cbr_b154"] * df["cbr_b154_futu_ratio"]
        + W_CONN["c345_b345"] * df["c345_b345_futu_ratio"]
    )

    # ── 최종 전력 피쳐 ──
    df["power_feature"] = W_FEATURE["cap"] * df["cap_score"] + W_FEATURE["conn"] * df["conn_score"]

    out = df[[
        "region_cd", "sido_cd", "sido_nm", "sgg_cd", "sgg_nm",
        "cap_score", "conn_score", "power_feature", "cap_missing",
        "cbr_b229_futu_ratio", "cbr_b154_futu_ratio", "c345_b345_futu_ratio",
    ]].sort_values("power_feature", ascending=False).reset_index(drop=True)

    save_csv(out, "전력피쳐_지역별_시군구.csv")
    n_miss = int(out["cap_missing"].sum())
    if n_miss:
        print(f"!! cap_missing=True {n_miss}개 지역은 용량 데이터 미수집으로 power_feature가 NaN입니다 "
              f"(예: 전력공급/재생e 크롤링이 비어 있던 시도). 분석에서 제외하거나 별도 처리하세요.")
    print(out.head(10).to_string(index=False))


if __name__ == "__main__":
    main()