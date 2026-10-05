"""
전력 피쳐 v3 (2026-10-05) — 8차시 전체 피드백 반영
====================================================
입력: 데이터셋/전력_시군구wide_256_재집계_20261004.csv  (feature_reorg.py 산출물, 개편 재배정·중복제거 반영)
      ../crawl_4/행정시군구_기준행.csv                   (256행 기준·순서 검증용)

v2 → v3 변경
  [2] 전력공급 무응답 5곳(순천·구례·강진·영종·옹진): 차단기 변전소는 있는데 전력공급 응답만 없음
      → 기존 '용량 0' 처리를 결측으로 변경, 플래그 전력공급_무응답, 분석대상에서 제외(참고등급으로 이동)
  [3-1] 용량점수: 시군구 '합계' MW → 단일 변전소 '최대' MW (한 부지에 여러 변전소 여유를 합쳐 받을 수 없음)
        22.9kV/154kV 가중치 0.1/0.9는 유지(0은 민감도 변형으로 비교)
  [3-2] 접속점수: 0.1/0.25/0.65 가중합 후 분석대상 기준 min-max 정규화(용량점수와 같은 0~1 척도)
        최소 절대 Bay 조건은 진단 결과 해당 지역 0곳이라 추가하지 않음
  [3-3] 수용가능 판정 열 추가 (목표 시설 1GW IT × PUE 1.25 = 1,250MW, 0.5GW = 625MW)
        - 2029 154kV 단일 변전소 최대 여유 ≥ 1,250MW 지역이 0곳 → 154kV 단독 판정 불가
        - 1GW: 345kV 여유 Bay ≥ 1
        - 0.5GW: 154kV 최대 여유 ≥ 625MW 또는 345kV 여유 Bay ≥ 1
        ※ 345kV 1 Bay가 1GW 수전을 보장한다는 근거는 미확보(조건부 판정)
  [4] 참고등급(용량 자료 없는 82곳 = 영남·제주 77 + 무응답 5): 접속점수 단독 순위 + 345kV 판정
  [병합키] 공유용 파일에 시군구코드(5자리) 열 추가. 상세 파일의 3자리 코드는 시군구코드_뒤3자리로 이름 변경
"""
import os
import numpy as np
import pandas as pd

os.chdir(os.path.dirname(os.path.abspath(__file__)))
WIDE = "데이터셋/전력_시군구wide_256_재집계_20261004.csv"
BASE = "../crawl_4/행정시군구_기준행.csv"
TAG = "20261005"
OUT_SHARE = f"데이터셋/전력_최종피쳐_공유용_v3_{TAG}.csv"
OUT_FEAT = f"데이터셋/전력피쳐_상세_256_v3_{TAG}.csv"

BASE_YEAR, LONG_YEAR = 2029, 2032
DEMAND_MW = {"1GW": 1250, "0.5GW": 625}          # IT 부하 × PUE 1.25 (신재생 피처와 동일 가정)
NO_CAP_SIDO = [26, 27, 31, 47, 48, 50]            # KEPCO 미공개: 부산·대구·울산·경북·경남·제주
CAP_W = {"22.9": 0.1, "154": 0.9}
CONN_W = {"차단기229kV_여유율": 0.1, "차단기154kV_여유율": 0.25, "차단기345kV_여유율": 0.65}
RATIO = {
    "차단기229kV_여유율": ("차단기_변전소기준_22.9kV여유_합계", "차단기_변전소기준_22.9kV전체_합계"),
    "차단기154kV_여유율": ("차단기_변전소기준_154kV여유_합계", "차단기_변전소기준_154kV전체_합계"),
    "차단기345kV_여유율": ("차단기_공급지역기준_345kV여유_합계", "차단기_공급지역기준_345kV전체_합계"),
}


def mm(x, ref):
    lo, hi = ref.min(), ref.max()
    return x * 0.0 if hi == lo else (x - lo) / (hi - lo)


def cap_cols(year, agg="최대"):
    return {f"전력공급229kV_{year}년_{agg}": CAP_W["22.9"], f"전력공급154kV_{year}년_{agg}": CAP_W["154"]}


def ratios(w):
    out = {}
    for c, (n, d) in RATIO.items():
        raw = np.where(w[d] > 0, w[n] / w[d].where(w[d] > 0), 0.0)
        out[c + "_원값"] = raw
        out[c] = np.clip(raw, 0, None)
    return pd.DataFrame(out, index=w.index)


def ewm_weights(N):
    P = (N / N.sum(axis=0)).replace(0, np.nan)
    e = -(P * np.log(P)).sum(axis=0) / np.log(len(N))
    d = 1 - e
    return d / d.sum()


def build(w):
    f = w[["지역코드", "시도명", "시군구명"]].copy()
    f["시군구코드"] = f["지역코드"]                                   # 병합 키(5자리)
    f["시군구코드_뒤3자리"] = w["시군구코드"]
    f["용량데이터없음"] = w["시도코드"].isin(NO_CAP_SIDO)
    f["전력공급_무응답"] = (~f["용량데이터없음"]) & (w["전력공급154kV_변전소수"] == 0) \
        & (w["전력공급229kV_변전소수"] == 0) & (w["차단기_변전소기준_변전소수"] > 0)
    f["변전소응답없음"] = w["변전소응답없음"]
    ok = ~f["용량데이터없음"] & ~f["전력공급_무응답"] & ~f["변전소응답없음"]
    f["분석대상"] = ok

    r = ratios(w)
    f = pd.concat([f, r], axis=1)
    f["음수여유율"] = (r[[c + "_원값" for c in RATIO]] < 0).any(axis=1)

    # 원값(MW) 보존
    for y in (BASE_YEAR, LONG_YEAR):
        f[f"154kV최대여유_{y}_MW"] = w[f"전력공급154kV_{y}년_최대"].where(~f["용량데이터없음"] & ~f["전력공급_무응답"])
    f["345kV여유Bay"] = w["차단기_공급지역기준_345kV여유_합계"]

    def cap_score(year, agg="최대"):
        s = sum(wt * mm(w.loc[ok, c], w.loc[ok, c]) for c, wt in cap_cols(year, agg).items())
        return s.reindex(w.index)

    conn_raw = sum(wt * r[c] for c, wt in CONN_W.items())
    f["접속점수_원점수"] = conn_raw
    f["용량점수"] = cap_score(BASE_YEAR)
    f["접속점수"] = mm(conn_raw, conn_raw[ok]).where(ok)              # 분석대상 기준 정규화
    f["전력피쳐"] = 0.5 * f["용량점수"] + 0.5 * f["접속점수"]
    f["전력피쳐_병목"] = np.sqrt(f["용량점수"] * f["접속점수"])
    f[f"용량점수_{LONG_YEAR}"] = cap_score(LONG_YEAR)
    f[f"전력피쳐_{LONG_YEAR}"] = 0.5 * f[f"용량점수_{LONG_YEAR}"] + 0.5 * f["접속점수"]

    # EWM(부록): 같은 지표·같은 척도에서 가중치만 엔트로피로
    Nc = r.loc[ok, list(CONN_W)].apply(lambda x: mm(x, x))
    wc = ewm_weights(Nc)
    conn_e = (Nc * wc).sum(axis=1)
    Nk = w.loc[ok, list(cap_cols(BASE_YEAR))].apply(lambda x: mm(x, x))
    wk = ewm_weights(Nk)
    f["용량점수_EWM"] = (Nk * wk).sum(axis=1).reindex(w.index)
    f["접속점수_EWM"] = mm(conn_e, conn_e).reindex(w.index)
    f["전력피쳐_EWM"] = 0.5 * f["용량점수_EWM"] + 0.5 * f["접속점수_EWM"]
    print("EWM 가중치 접속:", wc.round(4).to_dict(), "용량:", wk.round(4).to_dict())

    rk = lambda s: s.where(ok).rank(ascending=False, method="min").astype("Int64")
    f["전력순위"] = rk(f["전력피쳐"])
    f[f"전력순위_{LONG_YEAR}"] = rk(f[f"전력피쳐_{LONG_YEAR}"])

    # [3-3] 수용가능 판정 (2029 기준)
    has345 = f["345kV여유Bay"] >= 1
    m154 = f[f"154kV최대여유_{BASE_YEAR}_MW"]
    f["수용가능_1GW"] = has345 | (m154 >= DEMAND_MW["1GW"]).fillna(False)
    f["수용가능_0.5GW"] = has345 | (m154 >= DEMAND_MW["0.5GW"]).fillna(False)
    f["판정근거"] = np.select(
        [(m154 >= 1250).fillna(False), has345, (m154 >= 625).fillna(False)],
        ["154kV≥1250MW", "345kV 여유Bay", "154kV≥625MW(0.5GW만)"], "미충족")
    f.loc[f["변전소응답없음"], ["수용가능_1GW", "수용가능_0.5GW"]] = False
    f.loc[f["변전소응답없음"], "판정근거"] = "응답없음"

    # [4] 참고등급: 용량 자료 없는 지역은 접속점수 단독(같은 정규화 기준 재사용 불가 → 참고군 내부 순위)
    ref = ~ok & ~f["변전소응답없음"]
    f["참고등급"] = ref
    f["참고_접속점수"] = mm(conn_raw, conn_raw).where(ref | ok)          # 256 전체 기준 0~1 (비교용)
    f["참고_접속순위"] = f["참고_접속점수"].where(ref).rank(ascending=False, method="min").astype("Int64")
    f["345kV_상위지역공유"] = w["345kV_상위지역공유"]
    return f


SHARE_COLS = ["시군구코드", "지역코드", "시도명", "시군구명", "분석대상",
              "전력피쳐", "전력순위", "용량점수", "접속점수",
              "수용가능_1GW", "수용가능_0.5GW", "판정근거",
              f"전력피쳐_{LONG_YEAR}", f"전력순위_{LONG_YEAR}",
              "참고등급", "참고_접속순위",
              "용량데이터없음", "전력공급_무응답", "음수여유율", "345kV_상위지역공유"]
ROUND = ["전력피쳐", "용량점수", "접속점수", f"전력피쳐_{LONG_YEAR}"]


def check(f, base):
    errs = []
    if len(f) != 256: errs.append("행 수")
    if not f["시군구코드"].is_unique: errs.append("코드 중복")
    if list(f["시군구코드"]) != list(base["시군구코드"]): errs.append("기준 코드/순서 불일치")
    ok = f["분석대상"]
    for c in ["용량점수", "접속점수", "전력피쳐", f"용량점수_{LONG_YEAR}"]:
        v = f.loc[ok, c]
        if v.isna().any() or v.min() < 0 or v.max() > 1 + 1e-12: errs.append(f"{c} 범위/결측")
        if f.loc[~ok, c].notna().any(): errs.append(f"{c}: 제외지역에 값 있음")
    if f.loc[ok, "전력순위"].isna().any() or f.loc[~ok, "전력순위"].notna().any(): errs.append("순위")
    if (f[list(CONN_W)] < 0).any().any(): errs.append("절단 후 음수")
    if not (ok | f["참고등급"] | f["변전소응답없음"]).all(): errs.append("분류 누락")
    if (ok & f["참고등급"]).any(): errs.append("분류 중복")
    if f["용량데이터없음"].sum() != 77: errs.append("용량결측 77 아님")
    print("[검증]", "통과" if not errs else errs)
    assert not errs
    print(f"  분석대상 {int(ok.sum())} · 참고등급 {int(f['참고등급'].sum())} · 응답없음 {int(f['변전소응답없음'].sum())}")
    print(f"  무응답: {f.loc[f['전력공급_무응답'], '시군구명'].tolist()}")
    print(f"  음수여유율: {f.loc[f['음수여유율'], '시군구명'].tolist()}")
    print(f"  수용가능 1GW: 분석대상 {int(f.loc[ok,'수용가능_1GW'].sum())} / 참고 {int(f.loc[f['참고등급'],'수용가능_1GW'].sum())}"
          f" · 0.5GW: 분석대상 {int(f.loc[ok,'수용가능_0.5GW'].sum())} / 참고 {int(f.loc[f['참고등급'],'수용가능_0.5GW'].sum())}")


if __name__ == "__main__":
    w = pd.read_csv(WIDE, encoding="utf-8-sig")
    base = pd.read_csv(BASE, encoding="utf-8-sig")
    f = build(w)
    check(f, base)
    s = f[SHARE_COLS].copy()
    s[ROUND] = s[ROUND].round(6)
    s.to_csv(OUT_SHARE, index=False, encoding="utf-8-sig")
    f.to_csv(OUT_FEAT, index=False, encoding="utf-8-sig")
    print("저장:", OUT_SHARE, OUT_FEAT)
