"""
전력 피쳐 계산: 데이터셋/지역별_시군구_wide.csv -> 데이터셋/전력피쳐_지역별_시군구.csv

레퍼런스 시군구 코드로 재구성
────────────────────────────────────────────────────────────────
load_wide("sgg")로 원본 wide 테이블을 읽은 직후, REF_SGG_PATH에 있는 '표준
시군구 코드' 파일(컬럼: 시군구코드,개편전코드,시도명,시도,시군구,...)을 기준
grid로 삼아 데이터를 재구성한다(remap_to_reference).
  - 레퍼런스에 없는 코드(예: 상위 시 코드인 부천시/화성시 등)는 제외하고,
    어떤 지역이 빠지는지 콘솔에 출력한다.
  - 레퍼런스에는 있는데 원본에 없는 코드는 전부 '데이터없음' 취급되도록
    집계 컬럼을 NaN으로 남겨둔다(covered류 컬럼만 0으로 채움).
  - 시도명/시군구명은 레퍼런스 표기로 통일한다.
REF_SGG_PATH에 파일이 없으면 이 단계를 건너뛰고 기존 wide 테이블을 그대로
쓴다(출력에 경고가 뜸) — 레퍼런스를 아직 준비 안 했을 때도 스크립트가
깨지지 않게 하기 위함.

재크롤링 후에도 그대로 재사용 가능:
  kepco_crawler.py는 크롤링할 때마다 '컬럼 이름이 같은' 지역별_시군구_wide.csv를
  만들도록 짜여 있습니다(전력공급154kV_2029년_합계 같은 이름은 코드가 고정으로 정하는
  것이지 그날그날 받아온 데이터 내용과는 무관합니다). 그래서 이 스크립트는 수정 없이
  다시 실행하면 됩니다. 단, "같은 계산 방법이 다시 적용된다"는 뜻이지 "같은 숫자가
  나온다"는 뜻은 아닙니다 — 그 사이 KEPCO 쪽 실제 여유용량/Bay 현황이 바뀌었다면 결과도
  바뀌는 게 정상입니다(오히려 안 바뀌면 그게 이상한 겁니다).
  실행 순서: python kepco_crawler.py  ->  python compute_power_feature.py

────────────────────────────────────────────────────────────────
가중치 설계 근거 (중요 — 반드시 읽을 것)
────────────────────────────────────────────────────────────────
팀이 인용한 「Fuzzy-AHP 분석을 이용한 국내 AI 데이터센터 입지요인의 중요도 분석」
(이기수·정준호, 국토지리학회지)은 전력/신재생/재해/네트워크/냉각 5개 "최상위 기준"
사이의 상대 중요도를 다루는 논문으로 보입니다. 재검색해봤지만 논문 원문이나 가중치
수치표를 확인하지 못했고, 설령 확인하더라도 "전력" 항목 안에서 22.9kV/154kV/345kV
전압별 비중이나 '용량여유 vs 접속설비여유' 비중까지 다루는 논문은 아닐 가능성이 큽니다
— 그건 5대 기준 중 "전력" 하나를 어떻게 세분화할지의 문제라서, 보통 이 레벨의
논문에서는 거기까지 내려가지 않습니다.

1) 전력 피쳐는 두 개의 독립적인 하위 축으로 구성됩니다 (한전경영연구원/CBRE 등
   업계 자료가 공통적으로 지적하는 구분):
     - 용량점수 (capacity headroom): 변전소에 "여유 용량"이 있는가
     - 접속점수 (interconnection feasibility): 실제로 "연결할 Bay(설비)"가 있는가
   이 둘은 대체 관계가 아니라 둘 다 충족돼야 하는 관계에 가깝습니다 — 용량이 남아도
   Bay가 없으면 연결 불가능하고, Bay가 있어도 변전소 용량이 없으면 공급 불가능합니다.

2) 용량점수 내부(전력공급229kV vs 154kV, 0.1 / 0.9) — 2026-10 수정:
   22.9kV는 가정용/소규모 배전급 수요에 가까워 AI 데이터센터 입지 평가에는 거의
   의미가 없다고 보고 비중을 0.3→0.1로 낮췄습니다. 154kV에 더 쏠린 이유는
   "154kV가 더 중요해서"가 아니라, KEPCO가 "전력공급 여유용량" 데이터를
   22.9kV/154kV 두 전압에 대해서만 제공하고 345kV 용량(여유용량 MW 단위) 자체를
   공개하지 않기 때문입니다 — 345kV 중요도는 아래 접속점수 쪽 가중치로 반영됩니다.

3) 접속점수 내부(차단기229kV / 154kV / 345kV Bay 여유율, 0.1 / 0.25 / 0.65) — 2026-10 수정:
   "154kV보다 345kV 확보가 더 중요하다"는 팀 조사 결과를 반영해 345kV 비중을
   0.5→0.65로 올리고 154kV는 0.3→0.25로 낮췄습니다. 22.9kV는 0.2→0.1로 낮췄습니다.
   이 345kV>154kV>>22.9kV 순서는 제가 독자적으로 재검증한 건 아니고 사용자가
   조사한 내용을 그대로 반영한 것이니, 팀 회의에서 출처를 같이 확인해두는 걸
   추천합니다.

4) 용량점수·접속점수 결합 방식은 두 가지를 같이 계산해 둡니다:
     - 전력피쳐 (가중합, cap*0.5 + conn*0.5): 보완적(compensatory) 결합.
     - 전력피쳐_병목 (기하평균, sqrt(cap*conn)): 비보완적(non-compensatory) 결합.

5) EWM(엔트로피 가중법) 버전 — 2026-10 추가:
   위 2)·3)의 가중치(W_CAP, W_CONN)는 전부 사람이 설계한 값입니다. 이와 별개로,
   "지표 자체의 데이터 분포(지역 간 변별력)"에서 가중치를 자동 산출하는 엔트로피
   가중법(Entropy Weight Method)을 같이 계산해 _EWM 접미사 컬럼으로 제공합니다.
   참고 논문: Comprehensive Evaluation of Power Grid Renewable Energy Hosting
   Capacity Based on the EWM-GRA-TOPSIS Method (Energies, MDPI, 2026,
   https://www.mdpi.com/1996-1073/19/15/3517) — 전력망 수용 용량 평가에 EWM을
   적용한 사례.
     원리: 지역 간 편차가 큰(=변별력이 큰) 지표일수록 정보 엔트로피가 낮고,
     엔트로피가 낮을수록 가중치가 커진다.
       ① 지표를 0~1 min-max 정규화
       ② 비중 p_ij = x_ij / Σ_i x_ij 계산
       ③ 엔트로피 e_j = -(Σ_i p_ij·ln(p_ij)) / ln(n)
       ④ 차이도 d_j = 1 - e_j
       ⑤ 가중치 w_j = d_j / Σ_j d_j
   용량점수_EWM/접속점수_EWM/전력피쳐_EWM/전력피쳐_병목_EWM 컬럼이 그 결과이고,
   실행 시 콘솔에 "수동 가중치 vs EWM 가중치"를 같이 출력합니다 — 둘이 비슷하면
   수동 설계가 데이터로도 뒷받침된다는 뜻이고, 많이 다르면 재검토 근거가 됩니다.
   주의: EWM은 "이번 크롤링 스냅샷의 지역 간 분포"에서 가중치를 뽑으므로,
   크롤링할 때마다(KEPCO 데이터가 바뀌면) EWM 가중치도 같이 바뀔 수 있습니다
   — 수동 가중치처럼 고정값이 아닙니다.

가중치·기준연도는 아래 상수에서 조정하면 됩니다. AHP 설문 등으로 실제 가중치가
나오면 숫자만 바꿔서 다시 돌리면 됩니다.

컬럼명은 kepco_crawler.korean_colname()으로 wide 테이블과 동일한 한글명을 그대로
가져와 쓰므로, 블록/집계 이름(KOR_BLOCK/KOR_AGG)이 바뀌어도 이 파일은 고칠 필요가
없습니다.
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crawl_4 import load_wide, save_csv, korean_colname  # noqa: E402

YEAR = 2029                                              # 용량 여유를 어느 연도 기준으로 볼지
W_CAP = {"sup229": 0.1, "sup154": 0.9}                    # 용량점수 내부 가중치 (합 1) — 2026-10: 22.9kV 비중 축소(가정용)
W_CONN = {"cbr_b229": 0.1, "cbr_b154": 0.25, "c345_b345": 0.65}  # 접속점수 내부 가중치 (합 1) — 2026-10: 345kV>154kV>>22.9kV 반영
W_FEATURE = {"cap": 0.5, "conn": 0.5}                     # 전력피쳐(가중합) = cap*W + conn*W

# 표준 시군구 코드 레퍼런스 파일 경로. 이 파일과 같은 폴더에 저장해야 함.
REF_SGG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "행정시군구_기준행.csv")

# 내부 처리는 kepco_crawler와 동일한 영문 블록/지표 키를 쓰고, wide 테이블에서 값을
# 읽거나 결과를 저장할 때만 korean_colname()으로 실제 한글 컬럼명을 찾는다.
C_CAP = {blk: korean_colname(f"{blk}_y{YEAR}_sum") for blk in W_CAP}            # 예: 전력공급229kV_2029년_합계
C_COV = {blk: korean_colname(f"{blk}_covered") for blk in W_CAP}                # 예: 전력공급229kV_데이터있음
C_FUTU = {k: korean_colname(f"{k}_futu_sum") for k in W_CONN}                   # 예: 차단기_변전소기준_22.9kV여유_합계
C_TOTAL = {k: korean_colname(f"{k}_total_sum") for k in W_CONN}                 # 예: 차단기_변전소기준_22.9kV전체_합계

RATIO_LABEL = {"cbr_b229": "차단기229kV_여유율", "cbr_b154": "차단기154kV_여유율", "c345_b345": "차단기345kV_여유율"}


def load_reference_grid(path):
    """표준 시군구 코드 레퍼런스(컬럼: 시군구코드,시도명,시군구,...)를 읽어
    (지역코드, 시도코드, 시도명, 시군구코드, 시군구명) grid로 반환."""
    ref = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    return pd.DataFrame({
        "지역코드": ref["시군구코드"],
        "시도코드": ref["시군구코드"].str[:2],
        "시도명": ref["시도명"],
        "시군구코드": ref["시군구코드"].str[2:],
        "시군구명": ref["시군구"],
    })


def remap_to_reference(df, ref_path):
    """df(지역별_시군구_wide 원본)를 레퍼런스 시군구 기준으로 재구성.
      - 레퍼런스에 없는 지역코드(예: 부천시/화성시 같은 상위 시 코드)는 제외 -> 로그 출력
      - 레퍼런스에는 있는데 df에 없는 지역코드는 집계 컬럼을 NaN으로 남겨
        (covered 계열만 0으로 채움) 기존 '미수집' 처리 로직이 그대로 먹히게 함
      - 시도명/시군구명은 레퍼런스 표기로 통일
    """
    ref = load_reference_grid(ref_path)

    extra = df[~df["지역코드"].isin(ref["지역코드"])]
    if len(extra):
        names = ", ".join(extra["시도명"] + " " + extra["시군구명"])
        print(f"[remap] 레퍼런스에 없어 제외되는 지역 {len(extra)}개: {names}")
    else:
        print("[remap] 제외되는 지역 없음")

    missing = ref[~ref["지역코드"].isin(df["지역코드"])]
    if len(missing):
        names = ", ".join(missing["시도명"] + " " + missing["시군구명"])
        print(f"[remap] 원본엔 없어 데이터없음으로 채워지는 지역 {len(missing)}개: {names}")
    else:
        print("[remap] 레퍼런스 전체가 원본에 이미 있음")

    data_cols = [c for c in df.columns if c not in ("지역코드", "시도코드", "시도명", "시군구코드", "시군구명")]
    merged = ref.merge(df[["지역코드"] + data_cols], on="지역코드", how="left")

    cov_cols = [c for c in data_cols if c.endswith("데이터있음")]
    for c in cov_cols:
        merged[c] = merged[c].fillna(0).astype("int64")
    count_cols = [c for c in data_cols if c.endswith("_변전소수")]
    for c in count_cols:
        merged[c] = merged[c].fillna(0).astype("int64")

    print(f"[remap] 최종 {len(merged)}행 (레퍼런스 {len(ref)}행과 같아야 정상)")
    return merged


def covered_series(df, col):
    """{블록}_데이터있음 컬럼이 있으면 그대로, 없으면(옛 산출물) 전부 수집된 것으로 간주."""
    return df[col] if col in df.columns else pd.Series(1, index=df.index)


def minmax(s):
    lo, hi = s.min(), s.max()           # skipna=True 기본값 -> NaN(미수집)은 정규화 기준에서 자동 제외
    if pd.isna(lo) or hi == lo:
        return pd.Series(0.0, index=s.index)
    return (s - lo) / (hi - lo)


def safe_ratio(num, den):
    """분모가 0이거나 결측이면(예: 그 지역에 345kV 변전소가 없음) 0으로 처리 — '접속 여유 없음'과 동일하게 취급.
    pd.NA 대신 float NaN(den.where)을 써서 object dtype으로 안 바뀌게 함 — pandas 2.x의
    'Downcasting object dtype ... fillna' FutureWarning을 피하기 위함(결과값은 동일)."""
    num = pd.to_numeric(num, errors="coerce").astype(float)
    den = pd.to_numeric(den, errors="coerce").astype(float)
    return (num / den.where(den != 0)).fillna(0.0)


def entropy_weights(norm_series_dict):
    """엔트로피 가중법(EWM). norm_series_dict: {라벨: 0~1 정규화된 Series(지역별)}.
    결측(NaN)·음수(이상치)는 그 지표의 비중 계산에서만 제외(로그 계산 안전성 확보).
    반환: {라벨: 가중치} (합 1). 모든 지표가 변별력 0이면(값이 전부 같음) 균등 가중치."""
    diffs = {}
    for label, s in norm_series_dict.items():
        x = s.dropna()
        x = x[x >= 0]
        total = x.sum()
        if len(x) <= 1 or total <= 0:
            diffs[label] = 0.0
            continue
        p = x / total
        p = p[p > 0]
        e = -(p * np.log(p)).sum() / np.log(len(x))
        diffs[label] = 1 - e
    s_total = sum(diffs.values())
    n = len(norm_series_dict)
    if s_total <= 0:
        return {k: 1.0 / n for k in norm_series_dict}
    return {k: v / s_total for k, v in diffs.items()}


def main():
    df = load_wide("sgg")

    if os.path.exists(REF_SGG_PATH):
        df = remap_to_reference(df, REF_SGG_PATH)
    else:
        print(f"!! 레퍼런스 파일 없음({REF_SGG_PATH}) — remap 단계를 건너뛰고 기존 시군구 그대로 사용")

    # ── ① 용량점수 (capacity headroom): 전력공급229kV/154kV 여유용량 ──
    cap_norm = {}
    missing = pd.Series(False, index=df.index)
    for blk in W_CAP:
        cov = covered_series(df, C_COV[blk])
        missing = missing | (cov == 0)
        val = df[C_CAP[blk]].where(cov == 1)        # 미수집 지역은 NaN 처리 -> 정규화에 안 섞임
        cap_norm[blk] = minmax(val)

    cap_score = sum(W_CAP[blk] * cap_norm[blk] for blk in W_CAP)
    df["용량점수"] = cap_score.mask(missing)                 # 블록 중 하나라도 미수집이면 전체를 NaN으로
    df["용량데이터없음"] = missing

    w_cap_ewm = entropy_weights(cap_norm)
    cap_score_ewm = sum(w_cap_ewm[blk] * cap_norm[blk] for blk in W_CAP)
    df["용량점수_EWM"] = cap_score_ewm.mask(missing)

    # ── ② 접속점수 (interconnection feasibility): 차단기 Bay 여유율 ──
    ratio_cols = {}
    ratio_norm = {}
    for k in W_CONN:
        col = RATIO_LABEL[k]
        df[col] = safe_ratio(df[C_FUTU[k]], df[C_TOTAL[k]])
        ratio_cols[k] = col
        ratio_norm[k] = minmax(df[col])              # EWM은 0~1로 정규화된 값 기준(음수 비율도 자연스럽게 눌림)

    df["접속점수"] = sum(W_CONN[k] * df[ratio_cols[k]] for k in W_CONN)   # 수동 가중치: 원본 비율 그대로 가중합

    w_conn_ewm = entropy_weights(ratio_norm)
    df["접속점수_EWM"] = sum(w_conn_ewm[k] * ratio_norm[k] for k in W_CONN)  # EWM: 정규화된 비율 기준 가중합

    print("\n[EWM] 엔트로피 가중법 산출 가중치 vs 수동 가중치")
    print("  용량점수  수동:", {k: round(v, 3) for k, v in W_CAP.items()},
          " / EWM:", {k: round(v, 3) for k, v in w_cap_ewm.items()})
    print("  접속점수  수동:", {k: round(v, 3) for k, v in W_CONN.items()},
          " / EWM:", {k: round(v, 3) for k, v in w_conn_ewm.items()})

    # ── 최종 전력 피쳐: 수동 가중치 버전 + EWM 버전, 각각 두 가지 결합 방식 ──
    df["전력피쳐"] = W_FEATURE["cap"] * df["용량점수"] + W_FEATURE["conn"] * df["접속점수"]
    prod = (df["용량점수"].astype(float).clip(lower=0) * df["접속점수"].astype(float).clip(lower=0))
    df["전력피쳐_병목"] = prod ** 0.5

    df["전력피쳐_EWM"] = W_FEATURE["cap"] * df["용량점수_EWM"] + W_FEATURE["conn"] * df["접속점수_EWM"]
    prod_ewm = (df["용량점수_EWM"].astype(float).clip(lower=0) * df["접속점수_EWM"].astype(float).clip(lower=0))
    df["전력피쳐_병목_EWM"] = prod_ewm ** 0.5

    out = df[[
        "지역코드", "시도코드", "시도명", "시군구코드", "시군구명",
        "용량점수", "접속점수", "전력피쳐", "전력피쳐_병목",
        "용량점수_EWM", "접속점수_EWM", "전력피쳐_EWM", "전력피쳐_병목_EWM",
        "용량데이터없음",
        RATIO_LABEL["cbr_b229"], RATIO_LABEL["cbr_b154"], RATIO_LABEL["c345_b345"],
    ]].sort_values("전력피쳐", ascending=False).reset_index(drop=True)

    save_csv(out, "전력피쳐_지역별_시군구.csv")

    # EWM 가중치 기준 결과만 따로 저장 (수동 가중치 버전과 섞이지 않게 별도 파일로)
    out_ewm = df[[
        "지역코드", "시도코드", "시도명", "시군구코드", "시군구명",
        "용량점수_EWM", "접속점수_EWM", "전력피쳐_EWM", "전력피쳐_병목_EWM",
        "용량데이터없음",
        RATIO_LABEL["cbr_b229"], RATIO_LABEL["cbr_b154"], RATIO_LABEL["c345_b345"],
    ]].rename(columns={
        "용량점수_EWM": "용량점수", "접속점수_EWM": "접속점수",
        "전력피쳐_EWM": "전력피쳐", "전력피쳐_병목_EWM": "전력피쳐_병목",
    }).sort_values("전력피쳐", ascending=False).reset_index(drop=True)
    save_csv(out_ewm, "전력피쳐_지역별_시군구_EWM.csv")

    n_miss = int(out["용량데이터없음"].sum())
    if n_miss:
        print(f"\n!! 용량데이터없음=True {n_miss}개 지역은 용량 데이터 미수집으로 전력피쳐가 NaN입니다 "
              f"(예: 전력공급/재생e 크롤링이 비어 있던 시도). 분석에서 제외하거나 별도 처리하세요.")

    # 수동 가중합 순위와 EWM 가중합 순위가 많이 다른 지역 — 가중치 설계가 결과에
    # 실제로 얼마나 영향을 주는지 보여주는 참고 지표
    ranked = out.dropna(subset=["전력피쳐", "전력피쳐_EWM"]).copy()
    ranked["순위차_수동vsEWM"] = (ranked["전력피쳐"].rank(ascending=False)
                               - ranked["전력피쳐_EWM"].rank(ascending=False)).abs()
    big_gap_ewm = ranked.sort_values("순위차_수동vsEWM", ascending=False).head(5)
    if len(big_gap_ewm):
        print("\n참고: 수동 가중합(전력피쳐) vs EWM 가중합(전력피쳐_EWM) 순위 차이가 큰 지역")
        print(big_gap_ewm[["시도명", "시군구명", "전력피쳐", "전력피쳐_EWM", "순위차_수동vsEWM"]]
              .to_string(index=False))

    # 가중합 순위와 병목 순위가 많이 다른 지역 (수동 가중치 기준, 기존 로직)
    ranked2 = out.dropna(subset=["전력피쳐", "전력피쳐_병목"]).copy()
    ranked2["순위차"] = (ranked2["전력피쳐"].rank(ascending=False) - ranked2["전력피쳐_병목"].rank(ascending=False)).abs()
    big_gap = ranked2.sort_values("순위차", ascending=False).head(5)
    if len(big_gap):
        print("\n참고: 가중합 순위 vs 병목(기하평균) 순위 차이가 큰 지역 (용량/접속 불균형 의심, 수동 가중치 기준)")
        print(big_gap[["시도명", "시군구명", "용량점수", "접속점수", "전력피쳐", "전력피쳐_병목", "순위차"]]
              .to_string(index=False))

    print("\n상위 10개 지역 (전력피쳐 기준, 수동 가중치)")
    print(out.head(10)[["시도명", "시군구명", "전력피쳐", "전력피쳐_EWM", "전력피쳐_병목"]].to_string(index=False))

    print("\n상위 10개 지역 (전력피쳐_EWM 기준)")
    print(out.sort_values("전력피쳐_EWM", ascending=False).head(10)
          [["시도명", "시군구명", "전력피쳐_EWM", "전력피쳐"]].to_string(index=False))


if __name__ == "__main__":
    main()