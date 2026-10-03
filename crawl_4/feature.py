"""
전력 피쳐 계산: 데이터셋/지역별_시군구_wide.csv -> 데이터셋/전력피쳐_지역별_시군구.csv

레퍼런스 시군구 코드로 재구성 (추가됨)
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

그래서 아래 가중치는 논문에서 가져온 수치가 아니라, AI 데이터센터 전력 공급의 공학적
특성에 근거해 제가 설계한 것입니다(전문가 검토 전 제안값). 논문의 역할은 "5대 기준 중
전력이 몇 %인지"를 팀 전체 피쳐 결합 단계에서 쓰는 것이고, 이 스크립트는 그 "전력"
점수를 어떻게 만들지만 다룹니다. 설계 논리는 다음과 같습니다.

1) 전력 피쳐는 두 개의 독립적인 하위 축으로 구성됩니다 (한전경영연구원/CBRE 등
   업계 자료가 공통적으로 지적하는 구분):
     - 용량점수 (capacity headroom): 변전소에 "여유 용량"이 있는가
     - 접속점수 (interconnection feasibility): 실제로 "연결할 Bay(설비)"가 있는가
   이 둘은 대체 관계가 아니라 둘 다 충족돼야 하는 관계에 가깝습니다 — 용량이 남아도
   Bay가 없으면 연결 불가능하고, Bay가 있어도 변전소 용량이 없으면 공급 불가능합니다.

2) 용량점수 내부(전력공급229kV vs 154kV, 0.3 / 0.7):
   AI 데이터센터는 통상 수십~수백 MW급 대용량 수요라 154kV급 변전 용량이 결정적이고,
   22.9kV(배전급)는 중소형 수용가 수준이라 상대적으로 부차적입니다.

3) 접속점수 내부(차단기229kV / 154kV / 345kV Bay 여유율, 0.2 / 0.3 / 0.5):
   345kV는 초고압 간선급으로, 대형 데이터센터가 전용 변전소를 새로 받을 때 핵심이
   되는 설비입니다. 그다음이 154kV, 22.9kV Bay는 소규모 연결에 가까워 가중치를
   가장 낮게 뒀습니다.

4) 용량점수·접속점수 결합 방식은 두 가지를 같이 계산해 둡니다:
     - 전력피쳐 (가중합, cap*0.5 + conn*0.5): 보완적(compensatory) 결합 — 분석/회귀에
       넣기 쉽고 해석이 단순해 기본값으로 둡니다.
     - 전력피쳐_병목 (기하평균, sqrt(cap*conn)): 비보완적(non-compensatory) 결합 —
       둘 중 하나가 0에 가까우면 전체도 0에 가깝게 떨어져, "용량과 접속이 모두
       있어야 한다"는 공학적 현실을 더 정확히 반영합니다.
   어느 쪽을 최종 보고서에 쓸지는 분석 목적에 맞게 선택하면 됩니다 — 등수가 크게
   갈리는 지역이 있는지 두 컬럼을 비교해보고 정하는 걸 추천합니다.

가중치·기준연도는 아래 상수에서 조정하면 됩니다. AHP 설문 등으로 실제 가중치가
나오면 숫자만 바꿔서 다시 돌리면 됩니다.

컬럼명은 kepco_crawler.korean_colname()으로 wide 테이블과 동일한 한글명을 그대로
가져와 쓰므로, 블록/집계 이름(KOR_BLOCK/KOR_AGG)이 바뀌어도 이 파일은 고칠 필요가
없습니다.
"""
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crawl_4 import load_wide, save_csv, korean_colname  # noqa: E402

YEAR = 2029                                              # 용량 여유를 어느 연도 기준으로 볼지
W_CAP = {"sup229": 0.3, "sup154": 0.7}                    # 용량점수 내부 가중치 (합 1)
W_CONN = {"cbr_b229": 0.2, "cbr_b154": 0.3, "c345_b345": 0.5}  # 접속점수 내부 가중치 (합 1)
W_FEATURE = {"cap": 0.5, "conn": 0.5}                     # 전력피쳐(가중합) = cap*W + conn*W

# 표준 시군구 코드 레퍼런스 파일 경로. 이 파일과 같은 폴더에 실제 파일명으로 저장한 뒤
# 필요하면 파일명만 바꿔주면 됨. 없으면 remap 단계를 건너뜀(경고만 출력).
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


def main():
    df = load_wide("sgg")

    if os.path.exists(REF_SGG_PATH):
        df = remap_to_reference(df, REF_SGG_PATH)
    else:
        print(f"!! 레퍼런스 파일 없음({REF_SGG_PATH}) — remap 단계를 건너뛰고 기존 시군구 그대로 사용")

    # ── ① 용량점수 (capacity headroom): 전력공급229kV/154kV 여유용량 ──
    cap_score = pd.Series(0.0, index=df.index)
    missing = pd.Series(False, index=df.index)
    for blk, w in W_CAP.items():
        cov = covered_series(df, C_COV[blk])
        missing = missing | (cov == 0)
        val = df[C_CAP[blk]].where(cov == 1)        # 미수집 지역은 NaN 처리 -> 정규화에 안 섞임
        cap_score = cap_score.add(w * minmax(val), fill_value=0.0)
    df["용량점수"] = cap_score.mask(missing)                 # 블록 중 하나라도 미수집이면 전체를 NaN으로
    df["용량데이터없음"] = missing

    # ── ② 접속점수 (interconnection feasibility): 차단기 Bay 여유율 ──
    ratio_cols = {}
    for k in W_CONN:
        col = RATIO_LABEL[k]
        df[col] = safe_ratio(df[C_FUTU[k]], df[C_TOTAL[k]])
        ratio_cols[k] = col
    df["접속점수"] = sum(W_CONN[k] * df[ratio_cols[k]] for k in W_CONN)

    # ── 최종 전력 피쳐: 두 가지 결합 방식을 같이 제공 ──
    # (가중합) 보완적 결합 — 기본값, 해석·후속 분석이 쉬움
    df["전력피쳐"] = W_FEATURE["cap"] * df["용량점수"] + W_FEATURE["conn"] * df["접속점수"]
    # (기하평균) 비보완적/병목 결합 — 용량·접속 중 하나라도 낮으면 전체 점수가 같이 낮아짐
    prod = (df["용량점수"].astype(float).clip(lower=0) * df["접속점수"].astype(float).clip(lower=0))
    df["전력피쳐_병목"] = prod ** 0.5

    out = df[[
        "지역코드", "시도코드", "시도명", "시군구코드", "시군구명",
        "용량점수", "접속점수", "전력피쳐", "전력피쳐_병목", "용량데이터없음",
        RATIO_LABEL["cbr_b229"], RATIO_LABEL["cbr_b154"], RATIO_LABEL["c345_b345"],
    ]].sort_values("전력피쳐", ascending=False).reset_index(drop=True)

    save_csv(out, "전력피쳐_지역별_시군구.csv")
    n_miss = int(out["용량데이터없음"].sum())
    if n_miss:
        print(f"!! 용량데이터없음=True {n_miss}개 지역은 용량 데이터 미수집으로 전력피쳐가 NaN입니다 "
              f"(예: 전력공급/재생e 크롤링이 비어 있던 시도). 분석에서 제외하거나 별도 처리하세요.")

    # 가중합 순위와 병목 순위가 많이 다른 지역은 "용량은 있는데 접속이 안 되는"(또는 그 반대)
    # 극단적 케이스일 가능성이 커서 참고삼아 출력
    ranked = out.dropna(subset=["전력피쳐", "전력피쳐_병목"]).copy()
    ranked["순위차"] = (ranked["전력피쳐"].rank(ascending=False) - ranked["전력피쳐_병목"].rank(ascending=False)).abs()
    big_gap = ranked.sort_values("순위차", ascending=False).head(5)
    if len(big_gap):
        print("\n참고: 가중합 순위 vs 병목(기하평균) 순위 차이가 큰 지역 (용량/접속 불균형 의심)")
        print(big_gap[["시도명", "시군구명", "용량점수", "접속점수", "전력피쳐", "전력피쳐_병목", "순위차"]]
              .to_string(index=False))

    print("\n상위 10개 지역 (전력피쳐 기준)")
    print(out.head(10).to_string(index=False))


if __name__ == "__main__":
    main()