"""
KEPCO 한전ON 전력망 여유용량 통합 크롤러 (최종 확정판)
포털: https://online.kepco.co.kr/EWM088D00

대상 5종
  1) 전력공급 여유용량 22.9kV   EWM104D04  POST /ew/api/energy/subSt23   — 시도만 순회(1단계)
  2) 전력공급 여유용량 154kV    EWM104D04  POST /ew/api/energy/subSt154  — 시도만 순회(1단계)
  3) 재생e 연계 여유용량        EWM094D00  POST /ew/cpct/retrieveTransCpct154kV — 시도만 순회(1단계)
  4) 22.9kV/154kV 변전소 차단기 여유 Bay  EWM100D00  POST /ew/cpct/retrieveCbrOvplsInfo — 시도->시군구 2단계
  5) 345kV 변전소 차단기 여유 Bay        EWM100D01  화면정의 XML에 데이터 내장, API 호출 불필요

4)의 필드명은 실제 응답으로 확인 완료: 154kV는 B005_*, 22.9kV는 B009_*.

출력 (데이터셋/ 폴더)
  전력공급_여유용량_22.9kV.csv
  전력공급_여유용량_154kV.csv
  재생e_연계_여유용량.csv
  차단기_여유Bay_229_154kV.csv
  차단기_여유Bay_345kV.csv
  전력망_통합.csv (변전소명 기준 outer join)
"""

import requests
import pandas as pd
import os
import time
import json
import re
from datetime import datetime

BASE = "https://online.kepco.co.kr"
SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "데이터셋")
os.makedirs(SAVE_DIR, exist_ok=True)


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


def get_sido_energy(headers):
    d = api_post(f"{BASE}/ew/api/energy/selectDo", {}, headers)
    return d.get("dma_Dolist", []) if d else []


def get_sido_cpct(headers):
    d = api_post(f"{BASE}/ew/cpct/selectChangeDoMapJson", {}, headers)
    return d.get("dlt_sido", []) if d else []


# ------------------------------------------------------------------
# 1)+2) 전력공급 여유용량 (22.9kV / 154kV) — 시도만 순회
# ------------------------------------------------------------------
def crawl_power_supply(voltage):
    """voltage: '23' (22.9kV) 또는 '154' (154kV)"""
    assert voltage in ("23", "154")
    label = "22.9kV" if voltage == "23" else "154kV"
    print(f"\n{'='*60}")
    print(f"[{datetime.now():%H:%M:%S}] 전력공급 여유용량 ({label}) 크롤링 시작")
    print("=" * 60)

    headers = headers_for("EWM104D04")
    sido_list = get_sido_energy(headers)
    print(f"시도: {len(sido_list)}개")

    rows = []
    for si, sido in enumerate(sido_list, 1):
        sido_code = sido["NSDIP_ALL_ADDR_CD"]
        sido_nm = sido["ADDR_NM"]

        payload = {
            f"dma_subSt{voltage}": {
                "sidoCode": sido_code,
                "siggCode": "",
                "emdCode": "",
                "year": "2026",
            }
        }
        d = api_post(f"{BASE}/ew/api/energy/subSt{voltage}", payload, headers)
        data = d.get(f"dma_subSt{voltage}list", []) if d else []
        time.sleep(0.3)

        for row in data:
            rows.append({
                "시도": row.get("SIDO_NM", sido_nm),
                "시군구": row.get("SGG_NM", ""),
                "읍면동": row.get("EMD_NM", ""),
                "변전소": row.get("PSPWP_NM", row.get("PSPWPNM", "")),
                "변전소관리번호": row.get("PSPWPMNGNO", ""),
                "기준연도": row.get("CRTR_YY", ""),
                f"전력공급여유_{label}_2026": row.get("THIS_YY", ""),
                f"전력공급여유_{label}_2027": row.get("ONE_YY", ""),
                f"전력공급여유_{label}_2028": row.get("TWO_YY", ""),
                f"전력공급여유_{label}_2029": row.get("THR_YY", ""),
                f"전력공급여유_{label}_2030": row.get("FOR_YY", ""),
                f"전력공급여유_{label}_2031": row.get("FIV_YY", ""),
                f"전력공급여유_{label}_2032": row.get("SIX_YY", ""),
                "최소여유용량_추정": row.get("PSSMINOVPLSCPCT", ""),
            })

        print(f"[{si:02d}/{len(sido_list)}] {sido_nm} — {len(data)}개")

    out = os.path.join(SAVE_DIR, f"전력공급_여유용량_{label}.csv")
    if rows:
        pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
        print(f"\n완료! {out}")
        print(f"총 {len(rows)}행")
    else:
        print("수집된 데이터 없음")

    return out if rows else None


# ------------------------------------------------------------------
# 3) 재생e 연계 여유용량 — 시도만 순회
# ------------------------------------------------------------------
def crawl_renewable():
    print(f"\n{'='*60}")
    print(f"[{datetime.now():%H:%M:%S}] 재생e 연계 여유용량 크롤링 시작")
    print("=" * 60)

    headers = headers_for("EWM094D00")
    sido_list = get_sido_cpct(headers)
    print(f"시도: {len(sido_list)}개")

    rows = []
    for si, sido in enumerate(sido_list, 1):
        sido_code = sido["NSDIP_ALL_ADDR_CD"]
        sido_nm = sido["ADDR_NM"]

        payload = {
            "dma_reqParam": {
                "sido_code": sido_code,
                "sigg_code": "",
                "emd_code": "",
                "year": "2026",
                "gubun": "etc",
            }
        }
        d = api_post(f"{BASE}/ew/cpct/retrieveTransCpct154kV", payload, headers)
        data = d.get("dlt_resultList", []) if d else []
        time.sleep(0.3)

        for row in data:
            rows.append({
                "시도": row.get("SIDO_NM", sido_nm),
                "시군구": row.get("SGG_NM", ""),
                "읍면동": row.get("EMD_NM", ""),
                "변전소": row.get("PSPWPNM", row.get("PSS_NM", "")),
                "변전소관리번호": row.get("PSPWPMNGNO", ""),
                "검토연도": row.get("RVW_YY", ""),
                "재생e연계여유_2026": row.get("THIS_YY", ""),
                "재생e연계여유_2027": row.get("ONE_YY", ""),
                "재생e연계여유_2028": row.get("TWO_YY", ""),
                "재생e연계여유_2029": row.get("THR_YY", ""),
                "재생e연계여유_2030": row.get("FOR_YY", ""),
                "재생e연계여유_2031": row.get("FIV_YY", ""),
                "재생e연계여유_2032": row.get("SIX_YY", ""),
                "최소여유용량_추정": row.get("PSSMINOVPLSCPCT", ""),
                "6년후검토용량_추정": row.get("SIXYEARRVWCPCT", ""),
            })

        print(f"[{si:02d}/{len(sido_list)}] {sido_nm} — {len(data)}개")

    out = os.path.join(SAVE_DIR, "재생e_연계_여유용량.csv")
    if rows:
        pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
        print(f"\n완료! {out}")
        print(f"총 {len(rows)}행")
    else:
        print("수집된 데이터 없음")

    return out if rows else None


# ------------------------------------------------------------------
# 4) 22.9kV/154kV 변전소 차단기 여유 Bay — 시도->시군구 2단계
#    154kV: B005_*, 22.9kV: B009_* (둘 다 실제 응답으로 확인됨)
# ------------------------------------------------------------------
def crawl_breaker_229_154():
    print(f"\n{'='*60}")
    print(f"[{datetime.now():%H:%M:%S}] 22.9kV/154kV 변전소 차단기 여유 Bay 크롤링 시작")
    print("=" * 60)

    headers = headers_for("EWM100D00")
    final_path = os.path.join(SAVE_DIR, "차단기_여유Bay_229_154kV.csv")
    interim_path = os.path.join(SAVE_DIR, "_interim_cbr229154.csv")

    sido_list = get_sido_cpct(headers)
    print(f"시도: {len(sido_list)}개")

    all_rows, done_gu = [], set()
    if os.path.exists(interim_path):
        prev = pd.read_csv(interim_path)
        all_rows = prev.to_dict("records")
        done_gu = set(zip(prev["_sido_code"].astype(str), prev["_sigg_code"].astype(str)))
        print(f"이전 저장 로드: {len(prev)}행")

    done_count = 0
    for si, sido in enumerate(sido_list, 1):
        sido_code = sido["NSDIP_ALL_ADDR_CD"]
        sido_nm = sido["ADDR_NM"]

        d2 = api_post(
            f"{BASE}/ew/cpct/selectChangeGuMapJson",
            {"dma_reqParam": {"sido_code": sido_code, "sigg_code": "", "emd_code": ""}},
            headers,
        )
        gu_list = d2.get("dlt_gu", []) if d2 else []
        time.sleep(0.3)
        print(f"[{si:02d}/{len(sido_list)}] {sido_nm} — {len(gu_list)}개 시군구")

        for gi, gu in enumerate(gu_list, 1):
            sigg_code = gu["NSDIP_ALL_ADDR_CD"]
            sigg_nm = gu["ADDR_NM"]

            if (sido_code, sigg_code) in done_gu:
                continue

            d3 = api_post(
                f"{BASE}/ew/cpct/retrieveCbrOvplsInfo",
                {"dma_reqParam": {"sido_code": sido_code, "sigg_code": sigg_code, "emd_code": ""}},
                headers,
            )
            data = d3.get("dlt_resultList", []) if d3 else []
            time.sleep(0.35)

            for row in data:
                all_rows.append({
                    "시도": sido_nm,
                    "시군구": sigg_nm,
                    "변전소": row.get("S_NM", row.get("SNM", "")),
                    "변전소코드": row.get("S_CD", ""),
                    "차단기_154kV_전체대수": row.get("B005_TOTAL_BAY", 0),
                    "차단기_154kV_사용중": row.get("B005_USE_BAY_TO", 0),
                    "차단기_154kV_사용예정": row.get("B005_SUBS_BAY", 0),
                    "차단기_154kV_여유대수": row.get("B005_FUTU_BAY", 0),
                    "차단기_22.9kV_전체대수": row.get("B009_TOTAL_BAY", 0),
                    "차단기_22.9kV_사용중": row.get("B009_USE_BAY_TO", 0),
                    "차단기_22.9kV_사용예정": row.get("B009_SUBS_BAY", 0),
                    "차단기_22.9kV_여유대수": row.get("B009_FUTU_BAY", 0),
                    "_sido_code": sido_code,
                    "_sigg_code": sigg_code,
                })

            done_gu.add((sido_code, sigg_code))
            done_count += 1
            print(f"  [{gi:02d}/{len(gu_list)}] {sigg_nm} — {len(data)}개")

            if done_count % 15 == 0:
                pd.DataFrame(all_rows).to_csv(interim_path, index=False, encoding="utf-8-sig")
                print(f"  >>> 중간저장: {len(all_rows)}행")

    if all_rows:
        df = pd.DataFrame(all_rows).drop(columns=["_sido_code", "_sigg_code"], errors="ignore")
        df.to_csv(final_path, index=False, encoding="utf-8-sig")
        print(f"\n완료! {final_path}")
        print(f"총 {len(df)}행")
    else:
        print("수집된 데이터 없음")

    if os.path.exists(interim_path):
        os.remove(interim_path)

    return final_path if all_rows else None


# ------------------------------------------------------------------
# 5) 345kV 변전소 차단기 여유 Bay — API 호출 불필요, 화면정의 XML에서 직접 파싱
# ------------------------------------------------------------------
def crawl_breaker_345():
    print(f"\n{'='*60}")
    print(f"[{datetime.now():%H:%M:%S}] 345kV 변전소 차단기 여유 Bay 크롤링 시작")
    print("=" * 60)

    headers = headers_for("EWM100D01")
    url = f"{BASE}/ui/ew/cpct/EWM100D01.xml"
    try:
        r = requests.get(url, headers=headers, params={"postfix": str(int(time.time()))}, timeout=20)
        r.raise_for_status()
        text = r.text
    except Exception as e:
        print(f"!! 요청 실패: {e}")
        return None

    m = re.search(r"var\s+arr\s*=\s*(\[.*?\])\s*;", text, re.S)
    if not m:
        print("!! arr 배열을 찾지 못했습니다. 화면 구조가 바뀌었을 수 있습니다.")
        return None

    raw = m.group(1)
    json_text = re.sub(r"(\w+)\s*:", r'"\1":', raw)
    json_text = re.sub(r",\s*([}\]])", r"\1", json_text)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        print(f"!! JSON 파싱 실패: {e}")
        return None

    rows = [{
        "지역본부": item.get("region", ""),
        "변전소": item.get("substation", ""),
        "차단기_345kV_최종": item.get("bay345A", ""),
        "차단기_345kV_사용중": item.get("bay345B", ""),
        "차단기_345kV_사용예정": item.get("bay345C", ""),
        "차단기_345kV_잔여": item.get("bay345D", ""),
        "차단기_154kV_최종": item.get("bay154A", ""),
        "차단기_154kV_사용중": item.get("bay154B", ""),
        "차단기_154kV_사용예정": item.get("bay154C", ""),
        "차단기_154kV_잔여": item.get("bay154D", ""),
        "공급가능지역": item.get("supplyArea", ""),
        "준공예정일": item.get("completionDate", ""),
    } for item in data]

    out = os.path.join(SAVE_DIR, "차단기_여유Bay_345kV.csv")
    pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n완료! {out}")
    print(f"총 {len(rows)}행")
    return out


# ------------------------------------------------------------------
# 통합 머지: 변전소명 기준 outer join
# ------------------------------------------------------------------
def merge_all():
    print(f"\n{'='*60}")
    print(f"[{datetime.now():%H:%M:%S}] 데이터셋 통합 머지")
    print("=" * 60)

    files = {
        "전력공급_22.9kV": "전력공급_여유용량_22.9kV.csv",
        "전력공급_154kV": "전력공급_여유용량_154kV.csv",
        "재생e": "재생e_연계_여유용량.csv",
        "차단기_22.9_154kV": "차단기_여유Bay_229_154kV.csv",
        "차단기_345kV": "차단기_여유Bay_345kV.csv",
    }

    dfs = {}
    for key, fname in files.items():
        path = os.path.join(SAVE_DIR, fname)
        if os.path.exists(path):
            dfs[key] = pd.read_csv(path)
            print(f"{key}: {len(dfs[key])}행 ({fname})")
        else:
            print(f"{key}: 파일 없음 — 건너뜀 ({fname})")

    if not dfs:
        print("병합할 데이터가 없습니다.")
        return None

    base_key = next(iter(dfs))
    merged = dfs[base_key]
    for key, df in dfs.items():
        if key == base_key or "변전소" not in df.columns:
            continue
        merged = merged.merge(df, on="변전소", how="outer", suffixes=("", f"_{key}"))

    out_path = os.path.join(SAVE_DIR, "전력망_통합.csv")
    merged.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n통합 완료! {out_path}")
    print(f"총 {len(merged)}행")
    return out_path


if __name__ == "__main__":
    crawl_power_supply("23")
    crawl_power_supply("154")
    crawl_renewable()
    crawl_breaker_229_154()
    crawl_breaker_345()
    merge_all()