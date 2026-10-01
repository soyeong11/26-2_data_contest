"""
KEPCO 한전ON 전력망 여유용량 크롤러 v3  —  '지역별 wide 테이블' 산출판
포털: https://online.kepco.co.kr/EWM088D00

실행
  python kepco_crawler.py          크롤링 + wide 테이블 생성 (전체)
  python kepco_crawler.py crawl    크롤링만 (원본 CSV 5종 + 지역마스터 2종)
  python kepco_crawler.py merge    저장된 원본 CSV로 wide 테이블만 다시 생성 (크롤링 X)

산출물 (데이터셋/ 폴더)
  [원본, 변전소 단위]
    전력공급_여유용량_22.9kV.csv / 전력공급_여유용량_154kV.csv / 재생e_연계_여유용량.csv
    차단기_여유Bay_22.9_154kV.csv / 차단기_여유Bay_345kV.csv
    지역마스터_시군구.csv(cpct 네임스페이스) / 지역마스터_시군구_전력공급.csv(energy 네임스페이스)
  [지역별 wide, 1행 = 1지역]   <- 분석용
    지역별_시도_wide.csv / 지역별_시군구_wide.csv / 지역별_읍면동_wide.csv
    컬럼사전_지역별_wide.csv (컬럼 설명)
  [345kV 지역 매핑 점검용]
    345kV_공급지역_매핑.csv / 345kV_지역매핑_미매칭.csv

wide 컬럼명은 전부 한글입니다. 규칙: {블록}_{지표}_{집계}   예) 전력공급154kV_2027년_합계, 차단기_변전소기준_22.9kV여유_최대
  블록: 전력공급229kV / 전력공급154kV / 재생e연계 /
        차단기_변전소기준(22.9·154kV, 변전소 소재지 기준) / 차단기_공급지역기준(345·154kV, 공급가능지역 기준)
  집계: 지역 안에 변전소가 여러 개면 AGG_FUNCS(기본 합계, 최대)로 묶음.  {블록}_변전소수, {블록}_데이터있음도 있음
  지역키(코드는 전부 문자열, 이름은 '~코드'를 뗀 '~명'): 시도코드(2자리) 시군구코드(3자리)
      지역코드(=시도+시군구 5자리) 읍면동코드(3자리) 읍면동전체코드(8자리)
  코드는 문자열이라 앞자리 0이 있으면 CSV를 그냥 읽을 때 깨짐 -> load_wide() 사용:
      from kepco_crawler import load_wide;  df = load_wide("sgg")
  내부 처리(크롤링·병합 로직)는 영문 변수명을 그대로 쓰고, wide CSV로 저장되는 마지막 순간에만
  korean_colname()으로 한글 컬럼명으로 바꿉니다 — 코드를 고치려면 KOR_BLOCK/KOR_METRIC/KOR_AGG/KOR_ID를 보세요.

주의
  - sup229/sup154/renw는 시도->시군구 2단계로 순회합니다(차단기 2단계 순회와 동일 패턴).
    "시도만 선택해도 전체가 나온다"는 초기 확인과 달리 실제 비교 결과 값 오류가 발견되어
    되돌린 것 — 시군구까지 명시해 조회하는 편이 더 신뢰할 수 있다고 판단함 (2026-09 기준).
  - 한 변전소가 여러 읍면동에 걸쳐 같은 값으로 중복 응답되는 경우를 대비해, sup229/sup154/renw는
    (시도,시군구,변전소관리번호) 기준으로 중복 제거 후 저장함 — 시군구 단위 합계가 중복 집계되지
    않도록 하기 위함. 읍면동 단위로 볼 때는 이 중복 제거로 인해 일부 읍면동 행이 빠질 수 있음.
  - 값이 없는 지역은 0 (기존 규칙). 차단기(cbr)는 Bay 8개 값이 전부 0인 행을 제외.
  - c345: 변전소의 '공급가능지역' 텍스트를 시군구로 풀어 배분. 변전소 1개가 여러 지역에
    중복 반영되며, 이름이 안 맞는 항목은 '미매칭' 파일로 따로 저장. 읍면동 표에는 c345 없음.
  - {블록}_데이터있음: 그 시도에서 해당 블록 원본이 1행도 없으면 0 (예: 제주의 전력공급*/재생e연계).
    이 경우 그 블록의 0값은 '없음'이 아니라 '미수집'이므로 분석에서 제외하거나 NaN 처리할 것.
  - 여유용량의 단위, min_cpct / sixyr_cpct 필드의 의미는 원본 필드명 그대로(미확인).
"""

import os
import re
import sys
import json
import time
import requests
import pandas as pd
from datetime import datetime

BASE = "https://online.kepco.co.kr"
SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "데이터셋")
os.makedirs(SAVE_DIR, exist_ok=True)

YEAR = "2026"
AGG_FUNCS = ("sum", "max")
YEAR_KEYS = ["THIS_YY", "ONE_YY", "TWO_YY", "THR_YY", "FOR_YY", "FIV_YY", "SIX_YY"]
YEARS = [int(YEAR) + i for i in range(len(YEAR_KEYS))]
POSTFIX_345 = "260902324"   # EWM100D01.xml 요청에서 관찰된 캐시 파라미터

F_SUP229 = "전력공급_여유용량_22.9kV.csv"
F_SUP154 = "전력공급_여유용량_154kV.csv"
F_RENW = "재생e_연계_여유용량.csv"
F_CBR = "차단기_여유Bay_22.9_154kV.csv"
F_C345 = "차단기_여유Bay_345kV.csv"
F_MASTER = "지역마스터_시군구.csv"
F_ENERGY_MASTER = "지역마스터_시군구_전력공급.csv"
F_MAP345 = "345kV_공급지역_매핑.csv"
F_UNMATCHED = "345kV_지역매핑_미매칭.csv"
F_DICT = "컬럼사전_지역별_wide.csv"
WIDE_FILES = {
    "sido": "지역별_시도_wide.csv",
    "sgg": "지역별_시군구_wide.csv",
    "emd": "지역별_읍면동_wide.csv",
}
LEVEL_KEYS = {
    "sido": ["sido_cd"],
    "sgg": ["sido_cd", "sgg_cd"],
    "emd": ["sido_cd", "sgg_cd", "emd_cd"],
}
CODE_DTYPES = {c: str for c in ["시도코드", "시군구코드", "읍면동코드", "변전소관리번호", "변전소코드"]}


# ══════════════════════════════════════════════════════════════
# 공통 유틸
# ══════════════════════════════════════════════════════════════
def headers_for(referer_path):
    return {
        "Content-Type": 'application/json; charset="UTF-8"',
        "Referer": f"{BASE}/{referer_path}",
        "User-Agent": "Mozilla/5.0",
    }


def api_post(url, payload, headers, retry=3):
    for attempt in range(retry):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt < retry - 1:
                time.sleep(2 ** attempt)
    return None


def post_rows(url, payload, headers, key):
    """성공하면 리스트(비어 있을 수 있음), 요청 자체가 실패하면 None"""
    d = api_post(url, payload, headers)
    return None if d is None else d.get(key, [])


def norm_cd(x, n=0):
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return ""
    s = str(x).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s.zfill(n) if s else ""


def sgg3(x):
    """시군구 코드는 3자리로 통일 (5자리로 오면 뒤 3자리)"""
    s = norm_cd(x)
    return s[-3:].zfill(3) if s else ""


def save_csv(df, fname):
    path = os.path.join(SAVE_DIR, fname)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  저장: {path}  ({len(df)}행)")
    return path


def read_raw(fname):
    path = os.path.join(SAVE_DIR, fname)
    if not os.path.exists(path):
        return None
    return pd.read_csv(path, dtype=CODE_DTYPES, encoding="utf-8-sig")


def get_sido_energy(headers):
    d = api_post(f"{BASE}/ew/api/energy/selectDo", {}, headers)
    return d.get("dma_Dolist", []) if d else []


def get_sigg_energy(headers, sido_code):
    d = api_post(f"{BASE}/ew/api/energy/selectGu", {"dma_viewMap": {"Do": sido_code}}, headers)
    return d.get("dma_Gulist", []) if d else []


def crawl_energy_master():
    """전력공급 여유용량(energy 네임스페이스) 전용 시도->시군구 목록. cpct 네임스페이스 마스터와는 코드 부여 방식이 달라 별도로 둠.
    get_sigg_energy가 빈 리스트를 주는 시도는 crawl_per_sido에서 실제로 겪었던 것과 같은 '서버가
    일시적으로 빈 응답을 준' 경우일 수 있어, 바로 "시군구 없음"으로 확정하지 않고 재시도한다
    (최대 3라운드, 5초/10초 대기). 재시도 후에도 끝까지 비면 진짜 그런 것으로 받아들인다."""
    banner("지역 마스터 (전력공급, energy 네임스페이스)")
    headers = headers_for("EWM104D04")
    sido_list = get_sido_energy(headers)
    pending, failed, results = list(sido_list), [], {}   # results: sido_code -> gu_list
    for round_no in range(3):
        failed = []
        for si, sido in enumerate(pending, 1):
            sido_code, sido_nm = sido["NSDIP_ALL_ADDR_CD"], sido["ADDR_NM"]
            gu_list = get_sigg_energy(headers, sido_code)
            time.sleep(0.3)
            if not gu_list:
                failed.append(sido)
                print(f"  [{si:02d}/{len(pending)}] {sido_nm} — 0개 응답(재시도 예정)")
                continue
            results[sido_code] = gu_list
            print(f"  [{si:02d}/{len(pending)}] {sido_nm} — {len(gu_list)}개 시군구")
        if not failed:
            break
        if round_no < 2:
            wait = 5 * (round_no + 1)
            print(f"  >>> 빈 응답 {len(failed)}개 시도 재시도 ({wait}초 후)")
            time.sleep(wait)
        pending = failed
    if failed:
        print(f"!! [지역마스터-전력공급] 재시도 후에도 0개인 시도: {[s['ADDR_NM'] for s in failed]} — "
              f"실제로 시군구가 없는 시도인지, 여전히 서버 문제인지 직접 확인 필요.")

    recs = []
    for sido in sido_list:
        sido_code, sido_nm = sido["NSDIP_ALL_ADDR_CD"], sido["ADDR_NM"]
        gu_list = results.get(sido_code, [])
        for g in gu_list:
            code = str(g["NSDIP_ALL_ADDR_CD"])
            sigg_req = code[2:] if len(code) >= 5 else code     # subSt23/154의 siggCode 파라미터는 3자리
            recs.append({"sido_cd": norm_cd(sido_code, 2), "sido_nm": sido_nm,
                         "sgg_req_cd": sigg_req, "sgg_cd": sgg3(sigg_req), "sgg_nm": g["ADDR_NM"]})
        if not gu_list:
            recs.append({"sido_cd": norm_cd(sido_code, 2), "sido_nm": sido_nm,
                         "sgg_req_cd": "", "sgg_cd": "", "sgg_nm": ""})
    if not recs:
        print("수집된 데이터 없음")
        return None
    em = pd.DataFrame(recs)
    save_csv(em, F_ENERGY_MASTER)
    return em


def get_sido_cpct(headers):
    d = api_post(f"{BASE}/ew/cpct/selectChangeDoMapJson", {}, headers)
    return d.get("dlt_sido", []) if d else []


def crawl_per_sido(name, sido_list, url, payload_fn, list_key, headers, sleep=0.3, retry_empty=True):
    """시도별 1회 호출. 실패한 시도는 재시도(최대 3라운드, 5초/10초 대기).
    retry_empty=True면 '요청은 성공했지만 0개'도 재시도 대상으로 취급한다 — 시도 대부분은
    시군구가 여러 개 있어야 정상이라, 0개는 서버가 일시적으로 빈 응답을 준 경우가 많기 때문
    (실제로 세종특별자치시처럼 진짜 1개뿐인 시도도 있어, 마지막까지 0개면 그대로 받아들이고 경고만 출력).
    각 행에 _sido_code/_sido_nm 부착."""
    rows_all, pending, failed = [], list(sido_list), []
    empty_names = set()
    for round_no in range(3):
        failed = []
        for si, sido in enumerate(pending, 1):
            code, nm = sido["NSDIP_ALL_ADDR_CD"], sido["ADDR_NM"]
            rows = post_rows(url, payload_fn(code), headers, list_key)
            time.sleep(sleep)
            if rows is None:
                failed.append(sido)
                print(f"  [{si:02d}/{len(pending)}] {nm} — 요청 실패")
                continue
            if retry_empty and len(rows) == 0:
                failed.append(sido)
                empty_names.add(nm)
                print(f"  [{si:02d}/{len(pending)}] {nm} — 0개 응답(재시도 예정)")
                continue
            empty_names.discard(nm)
            for r in rows:
                r["_sido_code"], r["_sido_nm"] = code, nm
            rows_all.extend(rows)
            print(f"  [{si:02d}/{len(pending)}] {nm} — {len(rows)}개")
        if not failed:
            break
        if round_no < 2:
            wait = 5 * (round_no + 1)
            print(f"  >>> 실패/빈 응답 {len(failed)}개 시도 재시도 ({wait}초 후)")
            time.sleep(wait)
        pending = failed
    if failed:
        still_empty = [s["ADDR_NM"] for s in failed if s["ADDR_NM"] in empty_names]
        still_err = [s["ADDR_NM"] for s in failed if s["ADDR_NM"] not in empty_names]
        if still_err:
            print(f"!! [{name}] 끝내 요청 실패한 시도: {still_err} — 결과가 불완전합니다.")
        if still_empty:
            print(f"!! [{name}] 재시도 후에도 0개인 시도: {still_empty} — 실제로 시군구가 없는 시도(세종 등)인지, "
                  f"여전히 서버 문제인지 직접 확인 필요.")
    return rows_all


def crawl_per_gu(name, tasks, url, payload_fn, list_key, headers, sleep=0.35):
    """시군구별(= tasks의 각 원소) 1회 호출. 실패분은 5초 뒤 한 번 더. 각 행에 _t(조회 당시 튜플) 부착."""
    rows_all, pending, failed = [], list(tasks), []
    for round_no in range(2):
        failed = []
        for i, t in enumerate(pending, 1):
            rows = post_rows(url, payload_fn(t), headers, list_key)
            time.sleep(sleep)
            if rows is None:
                failed.append(t)
                print(f"  [{i:03d}/{len(pending)}] {t.sido_nm} {t.sgg_nm} — 요청 실패")
                continue
            for r in rows:
                r["_t"] = t
            rows_all.extend(rows)
            if rows:
                print(f"  [{i:03d}/{len(pending)}] {t.sido_nm} {t.sgg_nm} — {len(rows)}개")
        if not failed:
            break
        if round_no == 0:
            print(f"  >>> 실패 {len(failed)}개 시군구 재시도 (5초 후)")
            time.sleep(5)
        pending = failed
    if failed:
        print(f"!! [{name}] 끝내 실패한 시군구 {len(failed)}개: {[(t.sido_nm, t.sgg_nm) for t in failed][:10]} ...")
    return rows_all


def banner(title):
    print(f"\n{'=' * 60}\n[{datetime.now():%H:%M:%S}] {title}\n{'=' * 60}")


# ══════════════════════════════════════════════════════════════
# 크롤링 (원본, 변전소 단위)
# ══════════════════════════════════════════════════════════════
def energy_rows_to_df(rows, renewable=False):
    recs = []
    for r in rows:
        t = r.get("_t")      # crawl_per_gu가 붙인 (시도/시군구) 조회 당시 정보 — API 응답에 누락된 값의 대체용
        rec = {
            "시도코드": norm_cd(r.get("SIDO_CD") or r.get("_sido_code") or (t.sido_cd if t is not None else ""), 2),
            "시도": r.get("SIDO_NM") or r.get("_sido_nm") or (t.sido_nm if t is not None else ""),
            "시군구코드": sgg3(r.get("SGG_CD")) or (t.sgg_cd if t is not None else ""),
            "시군구": r.get("SGG_NM") or (t.sgg_nm if t is not None else ""),
            "읍면동코드": norm_cd(r.get("EMD_CD"), 3),
            "읍면동": r.get("EMD_NM", ""),
            "변전소": r.get("PSPWPNM") or r.get("PSPWP_NM") or r.get("PSS_NM") or "",
            "변전소관리번호": str(r.get("PSPWPMNGNO", "")),
            "기준연도": r.get("RVW_YY" if renewable else "CRTR_YY", ""),
        }
        for y, k in zip(YEARS, YEAR_KEYS):
            rec[f"여유용량_{y}"] = r.get(k)
        rec["최소여유용량"] = r.get("PSSMINOVPLSCPCT")
        if renewable:
            rec["6년후검토용량"] = r.get("SIXYEARRVWCPCT")
            rec["기타"] = r.get("ETC")
        recs.append(rec)
    if not recs:
        return pd.DataFrame()
    df = pd.DataFrame(recs).drop_duplicates().reset_index(drop=True)
    # 한 변전소가 여러 읍면동에 같은 값으로 중복 응답되는 경우 방지: (시도,시군구,관리번호) 기준 1행만 남김.
    # 관리번호가 비어 있는 행은 서로 다른 변전소일 수 있으므로 건드리지 않음.
    mgmt = df["변전소관리번호"].astype(str).str.strip()
    has_mgmt = mgmt.ne("") & mgmt.ne("nan")
    key = df["시도코드"] + "|" + df["시군구코드"] + "|" + mgmt
    dup = has_mgmt & key.duplicated()
    if dup.any():
        print(f"  (참고) 같은 변전소가 같은 시군구에서 여러 행으로 중복 수집되어 {int(dup.sum())}행 제거")
    return df.loc[~dup].reset_index(drop=True)


def crawl_power_supply(voltage, energy_master):
    """voltage: '23'(22.9kV) 또는 '154'(154kV) — 시도->시군구 2단계 순회"""
    label = "22.9kV" if voltage == "23" else "154kV"
    banner(f"전력공급 여유용량 ({label})")
    headers = headers_for("EWM104D04")
    key = f"dma_subSt{voltage}"
    tasks = list(energy_master[energy_master["sgg_cd"] != ""].itertuples(index=False))
    rows = crawl_per_gu(
        f"전력공급 {label}", tasks, f"{BASE}/ew/api/energy/subSt{voltage}",
        lambda t: {key: {"sidoCode": t.sido_cd, "siggCode": t.sgg_req_cd, "emdCode": "", "year": YEAR}},
        f"{key}list", headers,
    )
    df = energy_rows_to_df(rows)
    if df.empty:
        print("수집된 데이터 없음")
        return None
    return save_csv(df, F_SUP229 if voltage == "23" else F_SUP154)


def crawl_renewable(master):
    """재생e 연계 여유용량 — 시도->시군구 2단계 순회 (차단기와 같은 cpct 지역마스터 재사용)"""
    banner("재생e 연계 여유용량")
    headers = headers_for("EWM094D00")
    tasks = list(master[master["sgg_cd"] != ""].itertuples(index=False))
    rows = crawl_per_gu(
        "재생e", tasks, f"{BASE}/ew/cpct/retrieveTransCpct154kV",
        lambda t: {"dma_reqParam": {"sido_code": t.sido_cd, "sigg_code": t.sgg_req_cd, "emd_code": "",
                                    "year": YEAR, "gubun": "etc"}},
        "dlt_resultList", headers,
    )
    df = energy_rows_to_df(rows, renewable=True)
    if df.empty:
        print("수집된 데이터 없음")
        return None
    return save_csv(df, F_RENW)


def crawl_region_master():
    """시도 -> 시군구 목록. 지역 격자(모든 시군구 포함)와 차단기 크롤링에 사용."""
    banner("지역 마스터 (시도/시군구)")
    headers = headers_for("EWM100D00")
    sido_list = get_sido_cpct(headers)
    gu_rows = crawl_per_sido(
        "지역마스터", sido_list, f"{BASE}/ew/cpct/selectChangeGuMapJson",
        lambda code: {"dma_reqParam": {"sido_code": code, "sigg_code": "", "emd_code": ""}},
        "dlt_gu", headers,
    )
    recs = [{
        "sido_cd": norm_cd(g["_sido_code"], 2),
        "sido_nm": g["_sido_nm"],
        "sgg_req_cd": str(g["NSDIP_ALL_ADDR_CD"]),     # API 요청에 그대로 쓰는 값
        "sgg_cd": sgg3(g["NSDIP_ALL_ADDR_CD"]),         # 키로 쓰는 3자리
        "sgg_nm": g["ADDR_NM"],
    } for g in gu_rows]
    have = {r["sido_cd"] for r in recs}
    for s in sido_list:  # 시군구가 없는 시도도 이름은 남김
        cd = norm_cd(s["NSDIP_ALL_ADDR_CD"], 2)
        if cd not in have:
            recs.append({"sido_cd": cd, "sido_nm": s["ADDR_NM"], "sgg_req_cd": "", "sgg_cd": "", "sgg_nm": ""})
    if not recs:
        print("수집된 데이터 없음")
        return None
    master = pd.DataFrame(recs)
    save_csv(master, F_MASTER)
    return master


def crawl_breaker_229_154(master):
    """22.9kV/154kV 변전소 차단기 여유 Bay — 시도->시군구 2단계"""
    banner("22.9kV/154kV 변전소 차단기 여유 Bay")
    headers = headers_for("EWM100D00")
    url = f"{BASE}/ew/cpct/retrieveCbrOvplsInfo"
    tasks = list(master[master["sgg_cd"] != ""].itertuples(index=False))
    rows_all, pending, failed = [], tasks, []
    for round_no in range(2):
        failed = []
        for i, t in enumerate(pending, 1):
            payload = {"dma_reqParam": {"sido_code": t.sido_cd, "sigg_code": t.sgg_req_cd, "emd_code": ""}}
            rows = post_rows(url, payload, headers, "dlt_resultList")
            time.sleep(0.35)
            if rows is None:
                failed.append(t)
                print(f"  [{i:03d}/{len(pending)}] {t.sido_nm} {t.sgg_nm} — 요청 실패")
                continue
            for r in rows:
                r["_t"] = t
            rows_all.extend(rows)
            if rows:
                print(f"  [{i:03d}/{len(pending)}] {t.sido_nm} {t.sgg_nm} — {len(rows)}개")
        if not failed:
            break
        if round_no == 0:
            print(f"  >>> 실패 {len(failed)}개 시군구 재시도 (5초 후)")
            time.sleep(5)
        pending = failed
    if failed:
        print(f"!! 끝내 실패한 시군구 {len(failed)}개: {[(t.sido_nm, t.sgg_nm) for t in failed][:10]} ...")

    recs = []
    for r in rows_all:
        t = r["_t"]
        recs.append({
            "시도코드": norm_cd(r.get("SIDO_CD") or t.sido_cd, 2),
            "시도": t.sido_nm,
            "시군구코드": sgg3(r.get("SGG_CD") or t.sgg_cd),
            "시군구": t.sgg_nm,
            "읍면동코드": norm_cd(r.get("EMD_CD"), 3),
            "변전소": r.get("S_NM") or r.get("SNM") or "",
            "변전소코드": str(r.get("S_CD", "")),
            "차단기_22.9kV_전체대수": r.get("B009_TOTAL_BAY"),
            "차단기_22.9kV_사용중": r.get("B009_USE_BAY_TO"),
            "차단기_22.9kV_사용예정": r.get("B009_SUBS_BAY"),
            "차단기_22.9kV_여유대수": r.get("B009_FUTU_BAY"),
            "차단기_154kV_전체대수": r.get("B005_TOTAL_BAY"),
            "차단기_154kV_사용중": r.get("B005_USE_BAY_TO"),
            "차단기_154kV_사용예정": r.get("B005_SUBS_BAY"),
            "차단기_154kV_여유대수": r.get("B005_FUTU_BAY"),
        })
    if not recs:
        print("수집된 데이터 없음")
        return None
    df = pd.DataFrame(recs).drop_duplicates().reset_index(drop=True)
    bay_cols = [c for c in df.columns if c.startswith("차단기_")]
    df[bay_cols] = df[bay_cols].apply(pd.to_numeric, errors="coerce")
    df = df[df[bay_cols].fillna(0).abs().sum(axis=1) > 0].reset_index(drop=True)  # Bay 전부 0인 행 제외
    return save_csv(df, F_CBR)


# ---- 345kV: 화면정의 XML 안의 `var arr = [...]` 를 직접 파싱 ----
_OBJ_RE = re.compile(r"\{(.*?)\}", re.S)
_PAIR_RE = re.compile(r"(\w+)\s*:\s*(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')", re.S)


def parse_345_arr(text):
    """JS 객체 배열 파싱. 큰따옴표/작은따옴표 문자열 모두 처리 (첫 항목이 작은따옴표라 JSON 변환은 실패함)."""
    m = re.search(r"var\s+arr\s*=\s*\[(.*?)\]\s*;", text, re.S)
    if not m:
        return []
    objs = []
    for om in _OBJ_RE.finditer(m.group(1)):
        d = {}
        for pm in _PAIR_RE.finditer(om.group(1)):
            val = pm.group(2)[1:-1]
            d[pm.group(1)] = val.replace("\\n", "\n").replace('\\"', '"').replace("\\'", "'")
        if d:
            objs.append(d)
    return objs


def fetch_345_xml():
    url = f"{BASE}/ui/ew/cpct/EWM100D01.xml"
    hdr = {"Referer": f"{BASE}/EWM100D01", "User-Agent": "Mozilla/5.0",
           "Accept": "application/xml, text/xml, */*"}
    try:
        r = requests.get(url, headers=hdr, params={"postfix": POSTFIX_345}, timeout=20)
        print(f"  GET {r.status_code}, {len(r.content)} bytes")
        r.raise_for_status()
        r.encoding = "utf-8"          # 인코딩 미지정 응답의 한글 깨짐 방지
        return r.text
    except Exception as e:
        print(f"!! 요청 실패: {e}")
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "EWM100D01.xml")
    if os.path.exists(local):
        print(f"  로컬 파일 사용: {local}")
        with open(local, encoding="utf-8") as f:
            return f.read()
    print("!! 브라우저에서 저장한 EWM100D01.xml을 이 스크립트와 같은 폴더에 두면 그 파일로 진행합니다.")
    return None


def crawl_breaker_345():
    banner("345kV 변전소 차단기 여유 Bay")
    text = fetch_345_xml()
    if not text:
        return None
    data = parse_345_arr(text)
    if not data:
        print("!! arr 배열을 찾지 못했습니다. 화면 구조가 바뀌었을 수 있습니다.")
        return None
    recs = [{
        "지역본부": d.get("region", ""),
        "변전소": d.get("substation", ""),
        "차단기_345kV_최종": d.get("bay345A"), "차단기_345kV_사용중": d.get("bay345B"),
        "차단기_345kV_사용예정": d.get("bay345C"), "차단기_345kV_잔여": d.get("bay345D"),
        "차단기_154kV_최종": d.get("bay154A"), "차단기_154kV_사용중": d.get("bay154B"),
        "차단기_154kV_사용예정": d.get("bay154C"), "차단기_154kV_잔여": d.get("bay154D"),
        "공급가능지역": d.get("supplyArea", "").replace("\n", " | "),
        "준공예정일": d.get("completionDate", ""),
    } for d in data]
    df = pd.DataFrame(recs)
    num = [c for c in df.columns if c.startswith("차단기_")]
    df[num] = df[num].apply(pd.to_numeric, errors="coerce")
    print(f"  파싱된 변전소: {len(df)}개")
    return save_csv(df, F_C345)


# ══════════════════════════════════════════════════════════════
# 345kV 공급가능지역 텍스트 -> (시도, 시군구) 매핑
# ══════════════════════════════════════════════════════════════
_SIDO_ALIAS_GROUPS = {
    "서울특별시": ["서울특별시", "서울시", "서울"],
    "부산광역시": ["부산광역시", "부산시", "부산"],
    "대구광역시": ["대구광역시", "대구시", "대구"],
    "인천광역시": ["인천광역시", "인천시", "인천"],
    "대전광역시": ["대전광역시", "대전시", "대전"],
    "울산광역시": ["울산광역시", "울산시", "울산"],
    "세종특별자치시": ["세종특별자치시", "세종시", "세종"],
    "경기도": ["경기도", "경기"],
    "강원특별자치도": ["강원특별자치도", "강원도", "강원"],
    "충청북도": ["충청북도", "충북"],
    "충청남도": ["충청남도", "청청남도", "충남"],          # '청청남도'는 원본의 오타
    "전북특별자치도": ["전북특별자치도", "전라북도", "전북"],
    "전남광주통합특별시": ["전남광주통합특별시", "광주광역시", "전라남도", "전남", "광주"],
    "경상북도": ["경상북도", "경북"],
    "경상남도": ["경상남도", "경남"],
    "제주특별자치도": ["제주특별자치도", "제주도", "제주"],
}
_ALIASES = sorted(((a, off) for off, al in _SIDO_ALIAS_GROUPS.items() for a in al),
                  key=lambda x: -len(x[0]))


TOKEN_FIXES = {"군신시": "군산시", "부잔진구": "부산진구"}   # 원본 화면의 명백한 오타


def _fix_typos(text):
    for wrong, right in TOKEN_FIXES.items():
        text = text.replace(wrong, right)
    return text


def _split_sido_prefix(token):
    for alias, official in _ALIASES:
        if token == alias:
            return official, ""
        if token.startswith(alias) and token[len(alias)] in " \t":
            return official, token[len(alias):].strip()
    return None, token


def _match_sgg(token, entries):
    """entries: [(sgg_cd, 공백제거 시군구명)]. 매칭되는 sgg_cd 리스트 반환."""
    t = token.replace(" ", "")
    if not t:
        return []
    exact = [c for c, n in entries if n == t]
    if exact:
        return exact
    out = []
    for c, n in entries:   # '부천시 원미구' <-> '원미구' 처럼 '시' 접두 차이만 허용
        if len(n) >= 2 and len(t) >= 2:
            if n.endswith(t) and n[:-len(t)].endswith("시"):
                out.append(c)
            elif t.endswith(n) and t[:-len(n)].endswith("시"):
                out.append(c)
    if out:
        return out
    if t.endswith("시"):   # '성남시' -> 성남시수정구/중원구/분당구 전체
        return [c for c, n in entries if n.startswith(t)]
    return []


def map_supply_area(df345, master):
    """반환: (매핑 DataFrame[sub_idx, sido_cd, sgg_cd], 미매칭 DataFrame)"""
    sido_by_name = {r.sido_nm: r.sido_cd for r in master[["sido_cd", "sido_nm"]].drop_duplicates().itertuples()}
    sgg_entries = {}
    for r in master[master["sgg_cd"] != ""].itertuples():
        sgg_entries.setdefault(r.sido_cd, []).append((r.sgg_cd, r.sgg_nm.replace(" ", "")))

    mapped, unmatched = [], []
    for idx, row in df345.iterrows():
        v = row.get("공급가능지역")
        text = "" if pd.isna(v) else str(v)
        cur = None
        for line in re.split(r"[\n|]", text):
            for tok in line.split(","):
                tok = tok.strip()
                if not tok:
                    continue
                off, rest = _split_sido_prefix(tok)
                rest = _fix_typos(rest)
                if off:
                    cur = off
                if off and not rest:            # 시도 단독 표기 (예: 세종특별자치시)
                    if off in sido_by_name:
                        mapped.append((idx, sido_by_name[off], ""))
                    else:
                        unmatched.append((row["변전소"], off, tok))
                    continue
                if cur:
                    sd = sido_by_name.get(cur)
                    hits = _match_sgg(rest, sgg_entries.get(sd, [])) if sd else []
                    if hits:
                        mapped.extend((idx, sd, h) for h in hits)
                    else:
                        unmatched.append((row["변전소"], cur, tok))
                else:                            # 시도 표기가 전혀 없는 경우: 전국에서 유일하게 일치할 때만 인정
                    cand = [(sd, c) for sd, ents in sgg_entries.items() for c in _match_sgg(rest, ents)]
                    if len(cand) == 1:
                        mapped.append((idx, cand[0][0], cand[0][1]))
                    else:
                        unmatched.append((row["변전소"], "", tok))
    mp = pd.DataFrame(mapped, columns=["sub_idx", "sido_cd", "sgg_cd"]).drop_duplicates().reset_index(drop=True)
    um = pd.DataFrame(unmatched, columns=["변전소", "시도(추정)", "원문토큰"])
    return mp, um


# ══════════════════════════════════════════════════════════════
# 정규화 (원본 CSV -> 분석용 표준 컬럼)
# ══════════════════════════════════════════════════════════════
E_METRICS = [f"y{y}" for y in YEARS] + ["min_cpct"]
R_METRICS = E_METRICS + ["sixyr_cpct"]
CBR_MAP = {
    "b229_total": "차단기_22.9kV_전체대수", "b229_use": "차단기_22.9kV_사용중",
    "b229_subs": "차단기_22.9kV_사용예정", "b229_futu": "차단기_22.9kV_여유대수",
    "b154_total": "차단기_154kV_전체대수", "b154_use": "차단기_154kV_사용중",
    "b154_subs": "차단기_154kV_사용예정", "b154_futu": "차단기_154kV_여유대수",
}
C345_MAP = {
    "b345_total": "차단기_345kV_최종", "b345_use": "차단기_345kV_사용중",
    "b345_subs": "차단기_345kV_사용예정", "b345_futu": "차단기_345kV_잔여",
    "b154_total": "차단기_154kV_최종", "b154_use": "차단기_154kV_사용중",
    "b154_subs": "차단기_154kV_사용예정", "b154_futu": "차단기_154kV_잔여",
}


def _base_cols(df):
    return pd.DataFrame({
        "sido_cd": df["시도코드"].map(lambda x: norm_cd(x, 2)),
        "sido_nm": df["시도"].fillna(""),
        "sgg_cd": df["시군구코드"].map(sgg3),
        "sgg_nm": df["시군구"].fillna(""),
        "emd_cd": df["읍면동코드"].map(lambda x: norm_cd(x, 3)),
        "emd_nm": df["읍면동"].fillna("") if "읍면동" in df.columns else "",
    })


def norm_energy(df, renewable=False):
    out = _base_cols(df)
    for y in YEARS:
        out[f"y{y}"] = pd.to_numeric(df[f"여유용량_{y}"], errors="coerce")
    out["min_cpct"] = pd.to_numeric(df["최소여유용량"], errors="coerce")
    if renewable:
        out["sixyr_cpct"] = pd.to_numeric(df["6년후검토용량"], errors="coerce")
    return out.dropna(subset=[f"y{y}" for y in YEARS], how="all").reset_index(drop=True)


def norm_cbr(df):
    out = _base_cols(df)
    for k, col in CBR_MAP.items():
        out[k] = pd.to_numeric(df[col], errors="coerce")
    return out


def norm_c345(df):
    out = pd.DataFrame({"sub_idx": df.index})
    for k, col in C345_MAP.items():
        out[k] = pd.to_numeric(df[col], errors="coerce").values
    return out


# ══════════════════════════════════════════════════════════════
# 한글 컬럼명 변환 (wide CSV로 저장되는 마지막 순간에만 적용 — 내부 처리는 영문 그대로)
# ══════════════════════════════════════════════════════════════
KOR_ID = {
    "sido_cd": "시도코드", "sido_nm": "시도명",
    "sgg_cd": "시군구코드", "sgg_nm": "시군구명",
    "emd_cd": "읍면동코드", "emd_nm": "읍면동명",
    "region_cd": "지역코드", "emd_full_cd": "읍면동전체코드",
}
KOR_BLOCK = {
    "sup229": "전력공급229kV", "sup154": "전력공급154kV", "renw": "재생e연계",
    "cbr": "차단기_변전소기준", "c345": "차단기_공급지역기준",
}
KOR_AGG = {"sum": "합계", "max": "최대", "mean": "평균", "min": "최소"}
KOR_METRIC_STATIC = {
    "min_cpct": "최소여유용량", "sixyr_cpct": "6년후검토용량",
    "b229_total": "22.9kV전체", "b229_use": "22.9kV사용중",
    "b229_subs": "22.9kV사용예정", "b229_futu": "22.9kV여유",
    "b154_total": "154kV전체", "b154_use": "154kV사용중",
    "b154_subs": "154kV사용예정", "b154_futu": "154kV여유",
    "b345_total": "345kV전체", "b345_use": "345kV사용중",
    "b345_subs": "345kV사용예정", "b345_futu": "345kV여유",
}
_YEAR_RE = re.compile(r"^y(\d{4})$")


def kor_metric(m):
    mm = _YEAR_RE.match(m)
    if mm:
        return f"{mm.group(1)}년"
    return KOR_METRIC_STATIC.get(m, m)


def korean_colname(col):
    """{블록}_{지표}_{집계} / {블록}_n_sub / {블록}_covered / 지역키 컬럼을 한글명으로 변환.
    알 수 없는 패턴이면 원본 컬럼명을 그대로 돌려줌(안전장치)."""
    if col in KOR_ID:
        return KOR_ID[col]
    for suffix, label in (("_covered", "_데이터있음"), ("_n_sub", "_변전소수")):
        if col.endswith(suffix):
            prefix = col[: -len(suffix)]
            return KOR_BLOCK.get(prefix, prefix) + label
    parts = col.split("_")
    if len(parts) >= 3 and parts[0] in KOR_BLOCK and parts[-1] in KOR_AGG:
        prefix, agg = parts[0], parts[-1]
        metric = "_".join(parts[1:-1])
        return f"{KOR_BLOCK[prefix]}_{kor_metric(metric)}_{KOR_AGG[agg]}"
    return col


# ══════════════════════════════════════════════════════════════
# wide 테이블 생성
# ══════════════════════════════════════════════════════════════
def aggregate_block(df, keys, prefix, metrics):
    g = df.groupby(keys, sort=True)
    cols = {f"{prefix}_n_sub": g.size()}
    for m in metrics:
        for agg in AGG_FUNCS:
            cols[f"{prefix}_{m}_{agg}"] = g[m].agg(agg)
    return pd.DataFrame(cols).reset_index()


def _names(frames, master, level):
    """이름 사전 (마스터 우선, 없으면 데이터에서)"""
    allf = pd.concat([f[["sido_cd", "sido_nm", "sgg_cd", "sgg_nm", "emd_cd", "emd_nm"]] for f in frames],
                     ignore_index=True).replace("", pd.NA)
    m = master.replace("", pd.NA)
    res = {}
    res["sido"] = pd.concat([m[["sido_cd", "sido_nm"]], allf[["sido_cd", "sido_nm"]]]) \
        .dropna().drop_duplicates("sido_cd")
    if level in ("sgg", "emd"):
        res["sgg"] = pd.concat([m[["sido_cd", "sgg_cd", "sgg_nm"]], allf[["sido_cd", "sgg_cd", "sgg_nm"]]]) \
            .dropna().drop_duplicates(["sido_cd", "sgg_cd"])
    if level == "emd":
        res["emd"] = allf[["sido_cd", "sgg_cd", "emd_cd", "emd_nm"]].dropna() \
            .drop_duplicates(["sido_cd", "sgg_cd", "emd_cd"])
    return res


def build_level(level, blocks, master, frames, coverage=None):
    keys = LEVEL_KEYS[level]
    wide = None
    for prefix, df, metrics in blocks:
        agg = aggregate_block(df, keys, prefix, metrics)
        wide = agg if wide is None else wide.merge(agg, on=keys, how="outer")
    if wide is None:
        return None
    if level == "sido" and len(master):      # 데이터가 없는 지역도 0으로 포함
        wide = master[["sido_cd"]].drop_duplicates().merge(wide, on=keys, how="outer")
    if level == "sgg" and len(master):
        grid = master.loc[master["sgg_cd"] != "", ["sido_cd", "sgg_cd"]].drop_duplicates()
        wide = grid.merge(wide, on=keys, how="outer")

    nm = _names(frames, master, level)
    wide = wide.merge(nm["sido"], on="sido_cd", how="left")
    if "sgg" in nm:
        wide = wide.merge(nm["sgg"], on=["sido_cd", "sgg_cd"], how="left")
    if "emd" in nm:
        wide = wide.merge(nm["emd"], on=["sido_cd", "sgg_cd", "emd_cd"], how="left")

    if level == "sido":
        id_cols = ["sido_cd", "sido_nm"]
    else:
        wide["region_cd"] = wide["sido_cd"] + wide["sgg_cd"]
        id_cols = ["region_cd", "sido_cd", "sido_nm", "sgg_cd", "sgg_nm"]
        if level == "emd":
            wide["emd_full_cd"] = wide["region_cd"] + wide["emd_cd"]
            id_cols = ["emd_full_cd"] + id_cols + ["emd_cd", "emd_nm"]
    for c in id_cols:
        if c.endswith("_nm"):
            wide[c] = wide[c].fillna("")
    num_cols = [c for c in wide.columns if c not in id_cols]
    wide[num_cols] = wide[num_cols].fillna(0)
    for c in num_cols:
        if c.endswith("_n_sub") or c.startswith(("cbr_", "c345_")):
            wide[c] = wide[c].round().astype("int64")
    cov_cols = []
    for p, cov in (coverage or {}).items():      # 0/1 플래그는 0 채우기 이후에 붙임
        wide[f"{p}_covered"] = wide["sido_cd"].isin(cov).astype("int64")
        cov_cols.append(f"{p}_covered")
    result = wide[id_cols + cov_cols + num_cols].sort_values(keys).reset_index(drop=True)
    return result.rename(columns=korean_colname)   # 저장 직전 한글 컬럼명으로 변환


BLOCK_DESC = {
    "sup229": "전력공급 여유용량(22.9kV)", "sup154": "전력공급 여유용량(154kV)",
    "renw": "재생e 연계 여유용량",
    "cbr": "22.9kV/154kV 변전소 차단기 여유 Bay (변전소 소재지 기준)",
    "c345": "345kV 변전소 차단기 여유 Bay (공급가능지역 기준, 변전소가 여러 지역에 중복 반영)",
}
METRIC_DESC = {
    **{f"y{y}": f"{y}년 여유용량(원본 단위)" for y in YEARS},
    "min_cpct": "원본 PSSMINOVPLSCPCT (의미 미확인)",
    "sixyr_cpct": "원본 SIXYEARRVWCPCT (의미 미확인)",
    "b229_total": "22.9kV Bay 전체", "b229_use": "22.9kV Bay 사용중",
    "b229_subs": "22.9kV Bay 사용예정", "b229_futu": "22.9kV Bay 여유",
    "b154_total": "154kV Bay 전체(최종)", "b154_use": "154kV Bay 사용중",
    "b154_subs": "154kV Bay 사용예정", "b154_futu": "154kV Bay 여유(잔여)",
    "b345_total": "345kV Bay 최종", "b345_use": "345kV Bay 사용중",
    "b345_subs": "345kV Bay 사용예정", "b345_futu": "345kV Bay 잔여",
}
AGG_DESC = {"sum": "지역 내 변전소 합계", "max": "지역 내 변전소 최대값",
            "mean": "지역 내 변전소 평균", "min": "지역 내 변전소 최소값"}


def build_dictionary(block_defs, covered=()):
    recs = []
    for prefix in covered:
        col = f"{prefix}_covered"
        recs.append({"column": korean_colname(col), "block": BLOCK_DESC[prefix],
                     "description": "해당 시도에서 이 블록 원본이 1행 이상 수집됨(1) / 시도 전체가 0행(0). 0이면 이 블록의 0값은 '없음'이 아니라 '미수집'"})
    for prefix, metrics in block_defs:
        col = f"{prefix}_n_sub"
        recs.append({"column": korean_colname(col), "block": BLOCK_DESC[prefix],
                     "description": "지역 안에서 이 블록에 잡힌 변전소 행 수"})
        for m in metrics:
            for agg in AGG_FUNCS:
                col = f"{prefix}_{m}_{agg}"
                recs.append({"column": korean_colname(col), "block": BLOCK_DESC[prefix],
                             "description": f"{METRIC_DESC.get(m, m)} / {AGG_DESC.get(agg, agg)}"})
    return pd.DataFrame(recs)


def build_wide_tables():
    banner("지역별 wide 테이블 생성")
    mp = os.path.join(SAVE_DIR, F_MASTER)
    master = pd.read_csv(mp, dtype=str, keep_default_na=False, encoding="utf-8-sig") if os.path.exists(mp) \
        else pd.DataFrame(columns=["sido_cd", "sido_nm", "sgg_req_cd", "sgg_cd", "sgg_nm"])
    if master.empty:
        print("!! 지역마스터가 없어 (a) 데이터 없는 지역 0행 채우기 (b) 345kV 지역 매핑을 건너뜁니다. `crawl` 먼저 실행하세요.")

    raws = {"sup229": read_raw(F_SUP229), "sup154": read_raw(F_SUP154),
            "renw": read_raw(F_RENW), "cbr": read_raw(F_CBR), "c345": read_raw(F_C345)}
    for k, v in raws.items():
        print(f"  {k}: {'없음 — 건너뜀' if v is None else f'{len(v)}행'}")

    norm = {}
    if raws["sup229"] is not None: norm["sup229"] = (norm_energy(raws["sup229"]), E_METRICS)
    if raws["sup154"] is not None: norm["sup154"] = (norm_energy(raws["sup154"]), E_METRICS)
    if raws["renw"] is not None: norm["renw"] = (norm_energy(raws["renw"], renewable=True), R_METRICS)
    if raws["cbr"] is not None: norm["cbr"] = (norm_cbr(raws["cbr"]), list(CBR_MAP))
    frames = [df for df, _ in norm.values()]
    coverage = {p: set(df["sido_cd"]) for p, (df, _) in norm.items()}
    if not frames:
        print("병합할 원본 데이터가 없습니다.")
        return None

    c345_norm = c345_map = None
    if raws["c345"] is not None and not master.empty:
        c345_norm = norm_c345(raws["c345"])
        c345_map, unmatched = map_supply_area(raws["c345"], master)
        labeled = c345_map.merge(raws["c345"][["변전소", "지역본부"]], left_on="sub_idx", right_index=True) \
            .merge(master[["sido_cd", "sido_nm"]].drop_duplicates(), on="sido_cd", how="left") \
            .merge(master[["sido_cd", "sgg_cd", "sgg_nm"]], on=["sido_cd", "sgg_cd"], how="left")
        save_csv(labeled.drop(columns="sub_idx"), F_MAP345)
        save_csv(unmatched, F_UNMATCHED)
        no_map = set(range(len(raws["c345"]))) - set(c345_map["sub_idx"])
        print(f"  345kV 지역 매핑: {len(c345_map)}건, 미매칭 토큰 {len(unmatched)}건, 지역이 하나도 안 잡힌 변전소 {len(no_map)}개")

    sgg_defs = None
    for level in ("sido", "sgg", "emd"):
        blocks = [(p, df, m) for p, (df, m) in norm.items()]
        if c345_map is not None and level != "emd":
            mp_l = c345_map
            if level == "sgg":
                mp_l = mp_l[mp_l["sgg_cd"] != ""]
            else:
                mp_l = mp_l.drop_duplicates(["sub_idx", "sido_cd"])
            blocks.append(("c345", mp_l.merge(c345_norm, on="sub_idx"), list(C345_MAP)))
        wide = build_level(level, blocks, master, frames, coverage)
        print(f"[{level}] {wide.shape[0]}행 x {wide.shape[1]}열")
        save_csv(wide, WIDE_FILES[level])
        if level == "sgg":
            sgg_defs = [(p, m) for p, _, m in blocks]
    save_csv(build_dictionary(sgg_defs, list(coverage)), F_DICT)


def load_wide(level="sgg"):
    """지역별 wide 테이블 로드 (코드 컬럼은 문자열 유지, 컬럼명은 한글). level: 'sido' | 'sgg' | 'emd'"""
    dtypes = {c: str for c in ["시도코드", "시군구코드", "지역코드", "읍면동코드", "읍면동전체코드"]}
    return pd.read_csv(os.path.join(SAVE_DIR, WIDE_FILES[level]), dtype=dtypes,
                       keep_default_na=False, encoding="utf-8-sig")


def run_crawl():
    master = crawl_region_master()
    energy_master = crawl_energy_master()
    if energy_master is not None:
        crawl_power_supply("23", energy_master)
        crawl_power_supply("154", energy_master)
    else:
        print("!! 전력공급용 지역마스터 실패 — 전력공급 여유용량 크롤링 건너뜀")
    if master is not None:
        crawl_renewable(master)
        crawl_breaker_229_154(master)
    else:
        print("!! 지역마스터 실패 — 재생e/차단기(22.9/154kV) 크롤링 건너뜀")
    crawl_breaker_345()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("all", "crawl"):
        run_crawl()
    if mode in ("all", "merge"):
        build_wide_tables()