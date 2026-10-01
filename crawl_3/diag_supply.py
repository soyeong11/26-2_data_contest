"""
진단 전용 (파일 생성/수정 없음) — 지역 마스터는 정상인데 왜 sup229/154 데이터가
비는지, subSt23/subSt154 API를 직접 호출해 원본 응답을 확인.

사용: kepco_crawler.py와 같은 폴더에 넣고
      python diag_supply.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kepco_crawler import headers_for, get_sido_energy, get_sigg_energy, api_post, BASE, YEAR  # noqa: E402

TARGET_NAMES = ["부산광역시", "대구광역시", "울산광역시", "세종특별자치시", "경상북도", "경상남도", "제주특별자치도"]
N_SAMPLE = 2   # 시도마다 앞에서 몇 개 시군구만 샘플로 호출

headers = headers_for("EWM104D04")
sido_list = get_sido_energy(headers)
by_name = {s["ADDR_NM"]: s for s in sido_list}

for name in TARGET_NAMES:
    sido = by_name.get(name)
    if not sido:
        print(f"[{name}] selectDo에 없음 (이전 진단과 모순 — 다시 확인 필요)")
        continue
    sido_code = sido["NSDIP_ALL_ADDR_CD"]
    gu_list = get_sigg_energy(headers, sido_code)
    print(f"\n=== {name} ({sido_code}) — 시군구 {len(gu_list)}개, 샘플 {min(N_SAMPLE, len(gu_list))}개 호출 ===")
    for g in gu_list[:N_SAMPLE]:
        full_code = str(g["NSDIP_ALL_ADDR_CD"])
        sigg_req = full_code[2:] if len(full_code) >= 5 else full_code
        for voltage in ("23", "154"):
            key = f"dma_subSt{voltage}"
            payload = {key: {"sidoCode": sido_code, "siggCode": sigg_req, "emdCode": "", "year": YEAR}}
            url = f"{BASE}/ew/api/energy/subSt{voltage}"
            raw = api_post(url, payload, headers)
            if raw is None:
                print(f"  {g['ADDR_NM']} [{voltage}] -> 요청 자체 실패(None)")
                continue
            rows = raw.get(f"{key}list", "<<키 없음>>")
            n = len(rows) if isinstance(rows, list) else rows
            print(f"  {g['ADDR_NM']} [{voltage}kV] siggCode={sigg_req!r} -> 행 {n}")
            if not isinstance(rows, list) or len(rows) == 0:
                # 응답 전체를 찍어서 혹시 에러 메시지/다른 키가 있는지 확인
                print(f"      원본 응답: {json.dumps(raw, ensure_ascii=False)[:500]}")