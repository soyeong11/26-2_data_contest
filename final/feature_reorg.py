"""
전력 피쳐 — 행정구역 개편 재배정 반영 (A단계)
================================================
기존 방식: 256행 기준에 없는 상위 시 행(화성시, 부천시, 인천 중구·동구·서구)을 삭제
  → 그 코드로 응답된 변전소 데이터가 함께 사라지고 신설구가 가짜 0이 됨
변경 방식:
  1) 읍면동 wide의 구 코드 행을 법정동 이름 기준으로 신 시군구에 재배정
  2) 시군구 단위로 다시 합산 (합계는 sum, 최대는 max)
  3) 345kV(공급지역 텍스트 기준)는 쪼갤 수 없으므로 화성시 값을 4개 구에 복제 + 플래그
  4) 기존 feature 계산식을 그대로 적용
v2 (2026-10-04)
  5) [C] 음수 차단기 여유율: 원값은 *_여유율_원값 으로 보존, 점수 계산용 *_여유율 은 0으로 절단,
         음수여유율 플래그 추가 (KEPCO 사이트도 사용예정 음수를 그대로 표시함을 확인)
  6) 재배정으로 같은 시군구 안에 같은 변전소가 두 번 들어간 1건 제거
     (화성시 새솔동[구 코드] = 만세구 팔탄면[새 코드], 차단기 8개 항목 값 완전 일치)
     ※ 같은 변전소가 '서로 다른' 시군구에 나오는 것은 KEPCO가 공급 변전소 기준으로
       응답하기 때문이며 정상 → 제거하지 않음 (예: 중부 변전소 = 종로·중구·은평·서대문·마포)

최종 (2026-10-04)
  7) [B] 용량 결측 6개 시도(부산·대구·울산·경북·경남·제주, 77행)는 분석 제외 → 분석대상=False
         (행은 256개 유지: 팀 병합 시 다른 피처와 1:1로 붙이기 위함)
  8) 기준연도 2029년, 장기 후보 2032년 시나리오 점수·순위 추가
  9) 공유용(핵심 열만) / 상세(전체 열) 파일 분리

입력 (같은 폴더)
  전력_지역별_읍면동_wide.csv, 전력_지역별_시군구_wide.csv, 행정시군구_기준행.csv, 개편매핑_법정동.csv
출력
  전력_최종피쳐_공유용_20261004.csv      ← ★ 팀 공유·병합용 (이 파일 하나만 공유)
  전력피쳐_상세_256_20261004.csv         ← 전체 열 (EWM·병목·원값 등), 검증·부록용
  전력_시군구wide_256_재집계_20261004.csv ← 재집계된 중간 wide
  개편재배정_내역_20261004.csv           ← 읍면동별 재배정·중복제거 내역
"""
import os
import numpy as np
import pandas as pd

os.chdir(os.path.dirname(os.path.abspath(__file__)))  # 어디서 실행해도 스크립트 폴더 기준

EMD_PATH = "전력_지역별_읍면동_wide.csv"
SGG_PATH = "전력_지역별_시군구_wide.csv"
BASE_PATH = "행정시군구_기준행.csv"
MAP_PATH = "개편매핑_법정동.csv"
TAG = "20261004"
OUT_SHARE = f"전력_최종피쳐_공유용_{TAG}.csv"
OUT_FEAT = f"전력피쳐_상세_256_{TAG}.csv"
OUT_WIDE = f"전력_시군구wide_256_재집계_{TAG}.csv"
OUT_LOG = f"개편재배정_내역_{TAG}.csv"

BASE_YEAR = 2029   # 기준연도: AIDC 가동 시점(약 3년 후), 22.9kV 비교 가능(2028~), 2028~2030 결과 안정
LONG_YEAR = 2032   # 장기 후보 시나리오: 계획 증설 반영, 불확실성 큼

# 345kV: 공급지역 텍스트가 상위 시 단위라 하위 구에 복제 (구 코드 → 신 코드들)
COPY_345 = {41590: [41591, 41593, 41595, 41597]}

# 재배정 후 같은 시군구 안 중복 변전소: (원래코드, 읍면동명) → 차단기 값만 제거
# 전력공급(MW) 값은 차단기 중복의 근거가 없으므로 유지
DEDUP_CBR = {(41590, "새솔동"): "만세구 팔탄면(41591)과 차단기 8개 항목 완전 일치 → 동일 변전소 이중계산"}
CBR_PREFIX = "차단기_변전소기준_"
CLIP_NEGATIVE = True  # [C] 점수 계산 시 음수 여유율 0 절단

# 기존 feature.py 계산식 (현재 파일에서 역산해 오차 1e-15 수준으로 일치 확인)
CAP_W = (0.1, 0.9)  # 22.9kV / 154kV 공급여유 가중치


def cap_cols(year):
    return {f"전력공급229kV_{year}년_합계": CAP_W[0], f"전력공급154kV_{year}년_합계": CAP_W[1]}


W_CAP = cap_cols(BASE_YEAR)
RATIO = {  # 출력컬럼: (여유, 전체)
    "차단기229kV_여유율": ("차단기_변전소기준_22.9kV여유_합계", "차단기_변전소기준_22.9kV전체_합계"),
    "차단기154kV_여유율": ("차단기_변전소기준_154kV여유_합계", "차단기_변전소기준_154kV전체_합계"),
    "차단기345kV_여유율": ("차단기_공급지역기준_345kV여유_합계", "차단기_공급지역기준_345kV전체_합계"),
}
W_CONN = {"차단기229kV_여유율": 0.1, "차단기154kV_여유율": 0.25, "차단기345kV_여유율": 0.65}
NO_CAP_SIDO = [26, 27, 31, 47, 48, 50]  # KEPCO 미공개: 부산·대구·울산·경북·경남·제주


def load():
    rd = lambda p: pd.read_csv(p, encoding="utf-8-sig")
    return rd(EMD_PATH), rd(SGG_PATH), rd(BASE_PATH), rd(MAP_PATH)


def reassign(emd, base, mp):
    base_codes = set(base["시군구코드"])
    emd = emd.copy()
    emd["원래코드"] = emd["지역코드"]
    emd["지역코드"] = emd["지역코드"].astype("float")  # 미배정(NaN)을 담기 위해
    key = emd["읍면동명"].fillna("").str.replace(" ", "")
    lut = {(int(c), str(n).replace(" ", "")): int(t)
           for c, n, t in zip(mp["개편전코드"], mp["읍면동명"], mp["신코드"])}

    orphan = ~emd["지역코드"].isin(base_codes)
    new = [lut.get((c, k)) for c, k in zip(emd.loc[orphan, "지역코드"], key[orphan])]
    emd.loc[orphan, "지역코드"] = [np.nan if v is None else float(v) for v in new]
    unmatched = emd[orphan & emd["지역코드"].isna()]
    emd = emd[emd["지역코드"].notna()].astype({"지역코드": int})
    assert emd["지역코드"].isin(base_codes).all()

    log = emd[orphan.reindex(emd.index, fill_value=False)][
        ["원래코드", "시군구명", "읍면동명", "지역코드",
         "전력공급229kV_변전소수", "차단기_변전소기준_변전소수",
         "전력공급154kV_2029년_합계", "차단기_변전소기준_22.9kV전체_합계"]
    ].rename(columns={"지역코드": "신코드", "시군구명": "원래시군구명"})
    log["처리"] = "재배정"
    if len(unmatched):
        u = unmatched[["원래코드", "시군구명", "읍면동명",
                       "전력공급229kV_변전소수", "차단기_변전소기준_변전소수",
                       "전력공급154kV_2029년_합계", "차단기_변전소기준_22.9kV전체_합계"]]
        u = u.rename(columns={"시군구명": "원래시군구명"}).assign(신코드=np.nan, 처리="미배정(법정동 소속 불명)")
        log = pd.concat([log, u], ignore_index=True)
    return emd, log


def dedup_within_sgg(emd, log):
    """재배정으로 같은 시군구 안에 같은 변전소가 두 번 들어간 경우 차단기 값만 제거"""
    cbr_cols = [c for c in emd.columns if c.startswith(CBR_PREFIX) and not c.endswith("_데이터있음")]
    key = emd["읍면동명"].fillna("").str.replace(" ", "")
    for (code, name), reason in DEDUP_CBR.items():
        hit = (emd["원래코드"] == code) & (key == name)
        if hit.sum() != 1:
            raise ValueError(f"중복제거 대상 ({code}, {name})이 {hit.sum()}건 — 입력 파일 확인 필요")
        emd.loc[hit, cbr_cols] = 0
        m = (log["원래코드"] == code) & (log["읍면동명"].fillna("").str.replace(" ", "") == name)
        log.loc[m, "처리"] = "재배정 + 차단기 중복제거"
        log.loc[m, "비고"] = reason

    # 자동 검사: 같은 시군구 안에서 서로 다른 원래코드 행의 차단기 값이 완전히 같으면 경고
    sig_cols = [c for c in cbr_cols if c.endswith("_합계")]
    x = emd[emd[f"{CBR_PREFIX}22.9kV전체_합계"] + emd[f"{CBR_PREFIX}154kV전체_합계"] > 0]
    x = x.assign(_sig=x[sig_cols].astype(str).agg("|".join, axis=1))
    dup = x.groupby(["지역코드", "_sig"])["원래코드"].nunique()
    dup = dup[dup > 1]
    if len(dup):
        print("[경고] 같은 시군구 안 중복 의심 변전소가 남아 있음:", list(dup.index.get_level_values(0)))
    else:
        print("[검사] 재배정으로 인한 시군구 내 중복 변전소 없음")
    return emd, log


def reaggregate(emd, sgg, base):
    sum_cols = [c for c in emd.columns if c.endswith("_합계") or c.endswith("_변전소수")]
    max_cols = [c for c in emd.columns if c.endswith("_최대") or c.endswith("_데이터있음")]
    g = emd.groupby("지역코드").agg({**{c: "sum" for c in sum_cols}, **{c: "max" for c in max_cols}})

    # 345kV·공급지역기준 컬럼은 읍면동 wide에 없으므로 시군구 wide에서 가져옴
    sup_cols = [c for c in sgg.columns if c.startswith("차단기_공급지역기준")]
    sup = sgg.set_index("지역코드")[sup_cols]
    shared = pd.Series(False, index=base["시군구코드"])
    for parent, kids in COPY_345.items():
        for k in kids:
            if sup.loc[k, "차단기_공급지역기준_변전소수"] == 0:
                sup.loc[k] = sup.loc[parent]
                shared[k] = True
            else:
                raise ValueError(f"{k}에 이미 345kV 값이 있음 — 복제 시 중복 위험, 수동 확인 필요")

    wide = base[["시군구코드", "시도명", "시군구"]].rename(columns={"시군구코드": "지역코드", "시군구": "시군구명"})
    wide = wide.merge(g, left_on="지역코드", right_index=True, how="left")
    wide = wide.merge(sup, left_on="지역코드", right_index=True, how="left")
    wide["시도코드"] = wide["지역코드"] // 1000
    wide["시군구코드"] = wide["지역코드"] % 1000
    wide["345kV_상위지역공유"] = wide["지역코드"].map(shared).fillna(False)
    # 읍면동 wide에 아예 없는 지역(제물포구·효행구·병점구·울릉군 등)은 변전소 응답 0건
    wide["변전소응답없음"] = wide["차단기_변전소기준_변전소수"].isna() & wide["전력공급229kV_변전소수"].isna()
    num = sum_cols + max_cols
    wide[num] = wide[num].fillna(0)
    return wide


def features(wide, base_codes_reassigned):
    f = wide[["지역코드", "시도코드", "시도명", "시군구코드", "시군구명"]].copy()
    f["용량데이터없음"] = wide["시도코드"].isin(NO_CAP_SIDO)

    for out, (num, den) in RATIO.items():
        raw = np.where(wide[den] > 0, wide[num] / wide[den].where(wide[den] > 0), 0.0)
        f[f"{out}_원값"] = raw                                        # 음수 보존
        f[out] = np.clip(raw, 0, None) if CLIP_NEGATIVE else raw     # [C] 점수 계산용
    f["음수여유율"] = (f[[f"{c}_원값" for c in RATIO]] < 0).any(axis=1)

    ok = ~f["용량데이터없음"]
    mm = lambda x, ref: (x - ref.min()) / (ref.max() - ref.min())
    cap = sum(w * mm(wide.loc[ok, c], wide.loc[ok, c]) for c, w in W_CAP.items())
    f["용량점수"] = np.nan
    f.loc[ok, "용량점수"] = cap
    f["접속점수"] = sum(w * f[c] for c, w in W_CONN.items())
    f["전력피쳐"] = 0.5 * f["용량점수"] + 0.5 * f["접속점수"]
    f["전력피쳐_병목"] = np.sqrt(f["용량점수"].clip(lower=0) * f["접속점수"].clip(lower=0))

    # EWM: 지표별 min-max 후 엔트로피 가중치
    def ewm(N):
        P = N / N.sum(axis=0)
        P = P.replace(0, np.nan)
        e = -(P * np.log(P)).sum(axis=0) / np.log(len(N))
        d = 1 - e
        return d / d.sum()

    Nc = f[list(RATIO)].apply(lambda x: mm(x, x))
    wc = ewm(Nc)
    f["접속점수_EWM"] = (Nc * wc).sum(axis=1)
    Nk = wide.loc[ok, list(W_CAP)].apply(lambda x: mm(x, x))
    wk = ewm(Nk)
    f["용량점수_EWM"] = np.nan
    f.loc[ok, "용량점수_EWM"] = (Nk * wk).sum(axis=1)
    f["전력피쳐_EWM"] = 0.5 * f["용량점수_EWM"] + 0.5 * f["접속점수_EWM"]
    f["전력피쳐_병목_EWM"] = np.sqrt(f["용량점수_EWM"] * f["접속점수_EWM"])

    # [B] 분석 대상: 용량 자료가 있는 179개 지역
    f["분석대상"] = ok
    # 장기 후보 시나리오 (같은 계산식, 연도만 변경)
    cap_l = sum(w * mm(wide.loc[ok, c], wide.loc[ok, c]) for c, w in cap_cols(LONG_YEAR).items())
    f[f"용량점수_{LONG_YEAR}"] = np.nan
    f.loc[ok, f"용량점수_{LONG_YEAR}"] = cap_l
    f[f"전력피쳐_{LONG_YEAR}"] = 0.5 * f[f"용량점수_{LONG_YEAR}"] + 0.5 * f["접속점수"]
    # 순위: 분석대상 179개 안에서 (1 = 가장 유리), 제외 지역은 빈칸
    rk = lambda s: s.where(ok).rank(ascending=False, method="min").astype("Int64")
    f["전력순위"] = rk(f["전력피쳐"])
    f[f"전력순위_{LONG_YEAR}"] = rk(f[f"전력피쳐_{LONG_YEAR}"])

    f["개편재배정"] = f["지역코드"].isin(base_codes_reassigned)
    f["345kV_상위지역공유"] = wide["345kV_상위지역공유"].values
    f["변전소응답없음"] = wide["변전소응답없음"].values
    cols = ["지역코드", "시도코드", "시도명", "시군구코드", "시군구명", "분석대상",
            "전력피쳐", "전력순위", "용량점수", "접속점수", "전력피쳐_병목",
            f"전력피쳐_{LONG_YEAR}", f"전력순위_{LONG_YEAR}", f"용량점수_{LONG_YEAR}",
            "용량점수_EWM", "접속점수_EWM", "전력피쳐_EWM", "전력피쳐_병목_EWM",
            "용량데이터없음", "차단기229kV_여유율", "차단기154kV_여유율", "차단기345kV_여유율",
            "차단기229kV_여유율_원값", "차단기154kV_여유율_원값", "차단기345kV_여유율_원값",
            "음수여유율", "개편재배정", "345kV_상위지역공유", "변전소응답없음"]
    print("EWM 가중치  접속:", dict(zip(RATIO, wc.round(4))), " 용량:", dict(zip(W_CAP, wk.round(4))))
    return f[cols]


SHARE_COLS = ["지역코드", "시도명", "시군구명", "분석대상",
              "전력피쳐", "전력순위", "용량점수", "접속점수",
              f"전력피쳐_{LONG_YEAR}", f"전력순위_{LONG_YEAR}", f"용량점수_{LONG_YEAR}",
              "음수여유율", "개편재배정", "345kV_상위지역공유"]


def share_table(f):
    """팀 공유용: 병합 키 + 기준(2029)·장기(2032) 점수·순위 + 해석에 필요한 플래그만"""
    s = f[SHARE_COLS].copy()
    for c in ["전력피쳐", "용량점수", "접속점수", f"전력피쳐_{LONG_YEAR}", f"용량점수_{LONG_YEAR}"]:
        s[c] = s[c].round(6)
    return s


def check(f, base):
    assert len(f) == 256 and f["지역코드"].is_unique
    assert list(f["지역코드"]) == list(base["시군구코드"]), "기준 순서와 불일치"
    assert f["용량데이터없음"].sum() == 77
    ratio = ["차단기229kV_여유율", "차단기154kV_여유율", "차단기345kV_여유율"]
    if CLIP_NEGATIVE:
        assert (f[ratio] >= 0).all().all() and (f["접속점수"] >= 0).all(), "절단 후 음수 남음"
    print("[검증] 256행 · 코드 유일 · 기준 코드/순서 일치 · 용량결측 77 · 점수 음수 0건 → 통과")
    print(f"  음수여유율 {int(f['음수여유율'].sum())}개 지역:", f.loc[f["음수여유율"], "시군구명"].tolist())
    n = int(f["분석대상"].sum())
    assert n == 179 and f["전력순위"].notna().sum() == n and f["전력순위"].max() <= n
    assert f.loc[~f["분석대상"], ["전력피쳐", "전력순위"]].isna().all().all()
    print(f"[검증] 분석대상 {n}개 · 순위 1~{int(f['전력순위'].max())} · 제외 지역 점수·순위 빈칸 → 통과")


if __name__ == "__main__":
    emd, sgg, base, mp = load()
    emd2, log = reassign(emd, base, mp)
    emd2, log = dedup_within_sgg(emd2, log)
    wide = reaggregate(emd2, sgg, base)
    reassigned = set(log["신코드"].dropna().astype(int)) | {k for v in COPY_345.values() for k in v}
    feat = features(wide, reassigned)
    check(feat, base)
    share_table(feat).to_csv(OUT_SHARE, index=False, encoding="utf-8-sig")
    feat.to_csv(OUT_FEAT, index=False, encoding="utf-8-sig")
    wide.to_csv(OUT_WIDE, index=False, encoding="utf-8-sig")
    log.to_csv(OUT_LOG, index=False, encoding="utf-8-sig")
    print(f"저장: ★{OUT_SHARE}, {OUT_FEAT}, {OUT_WIDE}, {OUT_LOG}")
    print(log["처리"].value_counts().to_string())