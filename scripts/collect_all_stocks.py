import FinanceDataReader as fdr
import pandas as pd
import requests
import json
import os
import zipfile
import io
import xml.etree.ElementTree as ET
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

DART_API_KEY = os.environ.get("DART_API_KEY", "c0dfa28be5bfbfccf9b738b548aacaa8500acd6f")
DART_BASE = "https://opendart.fss.or.kr/api"

def calc_stars(per, pbr, revenue_growth, profit_margin):
    score = 0
    if per:
        if per < 10: score += 2
        elif per < 15: score += 1
    if pbr:
        if pbr < 1: score += 2
        elif pbr < 1.5: score += 1
    if revenue_growth is not None:
        if revenue_growth >= 20: score += 2
        elif revenue_growth >= 10: score += 1
        elif revenue_growth < 0: score -= 1
    if profit_margin is not None:
        if profit_margin >= 15: score += 2
        elif profit_margin >= 8: score += 1
        elif profit_margin < 0: score -= 1
    if score >= 6: return 5
    elif score >= 4: return 4
    elif score >= 2: return 3
    elif score >= 1: return 2
    else: return 1

def get_recommendation(stars):
    if stars >= 5: return {"label": "강력추천", "color": "green", "icon": "🌟"}
    elif stars >= 4: return {"label": "추천", "color": "blue", "icon": "⭐"}
    elif stars >= 3: return {"label": "보통", "color": "gray", "icon": "➖"}
    else: return {"label": "비추천", "color": "red", "icon": "❌"}

def load_corp_map():
    """DART 종목코드 → corp_code 매핑 + 업종(induty_code) 포함"""
    corp_map = {}     # stock_code → corp_code
    sector_map = {}   # stock_code → 업종명
    try:
        r = requests.get(f"{DART_BASE}/corpCode.xml",
            params={"crtfc_key": DART_API_KEY}, timeout=60)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml_data = z.read("CORPCODE.xml")
        root = ET.fromstring(xml_data)
        for corp in root.findall("list"):
            stock_code = corp.findtext("stock_code", "").strip()
            corp_code = corp.findtext("corp_code", "").strip()
            if stock_code:
                corp_map[stock_code] = corp_code
        print(f"corp_map: {len(corp_map)}개")
    except Exception as e:
        print(f"corp_map 오류: {e}")
    return corp_map, sector_map

def get_sector_batch(corp_codes_chunk):
    """DART company API로 업종 수집 (청크 단위)"""
    result = {}
    for corp_code, stock_code in corp_codes_chunk:
        try:
            r = requests.get(f"{DART_BASE}/company.json", params={
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code,
            }, timeout=10)
            data = r.json()
            if data.get("status") == "000":
                induty = data.get("induty_code", "")   # 업종코드
                # DART에 업종명이 없으면 업종코드라도 저장
                business = data.get("business", "") or induty
                result[stock_code] = business[:20] if business else ""
        except:
            result[stock_code] = ""
    return result

def get_dart_financials_batch(corp_codes_list, year):
    """100개씩 배치로 DART 재무데이터 조회"""
    all_data = {}
    total = len(corp_codes_list)

    for i, batch in enumerate(corp_codes_list):
        try:
            corp_code_str = ",".join(batch)
            r = requests.get(f"{DART_BASE}/fnlttMultiAcnt.json", params={
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code_str,
                "bsns_year": str(year),
                "reprt_code": "11011",
            }, timeout=30)
            data = r.json()
            if data.get("status") == "000":
                for item in data.get("list", []):
                    code = str(item.get("stock_code", "")).strip().zfill(6)
                    if not code or code == "000000": continue
                    acct = item.get("account_nm", "")
                    val_str = item.get("thstrm_amount", "").replace(",", "").strip()
                    try:
                        val = int(val_str)
                    except:
                        continue
                    if code not in all_data:
                        all_data[code] = {}
                    if any(k in acct for k in ["매출액", "수익(매출액)"]) and "revenue" not in all_data[code]:
                        all_data[code]["revenue"] = val
                    elif "영업이익" in acct and "영업이익률" not in acct and "operating_profit" not in all_data[code]:
                        all_data[code]["operating_profit"] = val
            else:
                print(f"배치 {i+1} 오류: status={data.get('status')}")

            if (i+1) % 5 == 0:
                print(f"  재무 배치 {i+1}/{total} 완료 ({len(all_data)}개 누적)")
        except Exception as e:
            print(f"배치 {i+1} 예외: {e}")

    return all_data

def get_per_pbr_from_fdr(df):
    """FDR에서 PER/PBR 컬럼 추출 — 실제 컬럼명 자동 감지"""
    print("FDR 컬럼 목록:", df.columns.tolist())

    per_col = next((c for c in df.columns if c.upper() in ["PER", "P/E", "PE"]), None)
    pbr_col = next((c for c in df.columns if c.upper() in ["PBR", "P/B", "PB"]), None)

    print(f"PER 컬럼: {per_col}, PBR 컬럼: {pbr_col}")
    return per_col, pbr_col

def main():
    print("=" * 50)
    print("전종목 데이터 수집 시작:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 50)

    # ── 1. FDR 전종목 로딩 ──────────────────────────────
    k1 = fdr.StockListing("KOSPI");  k1["Market"] = "KOSPI"
    k2 = fdr.StockListing("KOSDAQ"); k2["Market"] = "KOSDAQ"
    df = pd.concat([k1, k2], ignore_index=True)
    df.columns = [c.strip() for c in df.columns]
    print(f"전체 종목: {len(df)}개")

    per_col, pbr_col = get_per_pbr_from_fdr(df)

    # ── 2. DART API 테스트 ──────────────────────────────
    try:
        r = requests.get(f"{DART_BASE}/fnlttMultiAcnt.json", params={
            "crtfc_key": DART_API_KEY,
            "corp_code": "00126380",
            "bsns_year": "2024",
            "reprt_code": "11011",
        }, timeout=15)
        dart_ok = r.json().get("status") == "000"
    except:
        dart_ok = False
    print(f"DART API 사용 가능: {dart_ok}")

    fin_cur = {}
    fin_prev = {}
    sector_map = {}

    if dart_ok:
        corp_map, _ = load_corp_map()
        prev_year = datetime.now().year - 1
        prev2_year = prev_year - 1

        # corp_code 배치
        all_corp_codes = []
        corp_stock_pairs = []  # (corp_code, stock_code) — 업종 수집용
        for _, row in df.iterrows():
            code = str(row.get("Code", "")).zfill(6)
            corp_code = corp_map.get(code)
            if corp_code:
                all_corp_codes.append(corp_code)
                corp_stock_pairs.append((corp_code, code))

        batch_size = 100
        batches = [all_corp_codes[i:i+batch_size] for i in range(0, len(all_corp_codes), batch_size)]
        print(f"총 {len(batches)}개 재무 배치")

        # ── 3. 재무데이터 수집 ──────────────────────────
        print(f"{prev_year}년 재무데이터 수집 중...")
        fin_cur = get_dart_financials_batch(batches, prev_year)
        print(f"{prev_year}년 완료: {len(fin_cur)}개")

        print(f"{prev2_year}년 재무데이터 수집 중...")
        fin_prev = get_dart_financials_batch(batches, prev2_year)
        print(f"{prev2_year}년 완료: {len(fin_prev)}개")

        # ── 4. 업종(섹터) 수집 — 병렬 처리 ────────────
        print("업종 데이터 수집 중 (병렬 10스레드)...")
        chunk_size = 50
        chunks = [corp_stock_pairs[i:i+chunk_size] for i in range(0, len(corp_stock_pairs), chunk_size)]
        print(f"업종 청크: {len(chunks)}개")

        collected = 0
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(get_sector_batch, chunk): chunk for chunk in chunks}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    sector_map.update(result)
                    collected += len(result)
                    if collected % 500 == 0:
                        print(f"  업종 수집: {collected}개")
                except Exception as e:
                    print(f"업종 청크 오류: {e}")
        print(f"업종 수집 완료: {len(sector_map)}개")

    # ── 5. 종목 데이터 조립 ─────────────────────────────
    def to_float(v):
        try: return float(str(v).replace(",", "").strip())
        except: return None

    stocks = []
    for _, row in df.iterrows():
        try:
            code = str(row.get("Code", "")).zfill(6)
            name = str(row.get("Name", ""))
            mkt = str(row.get("Market", ""))
            if not name or name == "nan": continue

            # PER/PBR — 감지된 컬럼에서 읽기
            per = to_float(row.get(per_col)) if per_col else None
            pbr = to_float(row.get(pbr_col)) if pbr_col else None
            per = round(per, 1) if per and 0 < per < 500 else None
            pbr = round(pbr, 1) if pbr and 0 < pbr < 100 else None

            price = to_float(row.get("Close", row.get("Adj Close")))
            marcap = to_float(row.get("Marcap"))

            # 재무
            fin = fin_cur.get(code, {})
            fin_p = fin_prev.get(code, {})
            revenue_cur = fin.get("revenue")
            revenue_prev = fin_p.get("revenue")
            op_profit = fin.get("operating_profit")

            revenue_growth = profit_margin = None
            if revenue_cur and revenue_prev and revenue_prev != 0:
                revenue_growth = round((revenue_cur - revenue_prev) / abs(revenue_prev) * 100, 1)
            if op_profit and revenue_cur and revenue_cur != 0:
                profit_margin = round(op_profit / revenue_cur * 100, 1)

            # 업종
            sector = sector_map.get(code, "")

            stars = calc_stars(per, pbr, revenue_growth, profit_margin)

            stocks.append({
                "code": code,
                "name": name,
                "market": mkt,
                "sector": sector,       # ← "industry" 대신 "sector"로 통일
                "industry": sector,     # ← 호환성 유지
                "price": int(price) if price else None,
                "per": per,
                "pbr": pbr,
                "revenue": revenue_cur,
                "revenue_growth": revenue_growth,
                "operating_profit": op_profit,
                "profit_margin": profit_margin,
                "marcap": int(marcap) if marcap else None,
                "stars": stars,
                "recommendation": get_recommendation(stars),
            })
        except:
            continue

    print(f"최종 {len(stocks)}개 종목 조립 완료")

    # 업종 분포 출력 (디버그용)
    sector_counts = {}
    for s in stocks:
        sec = s.get("sector", "") or "미분류"
        sector_counts[sec] = sector_counts.get(sec, 0) + 1
    top_sectors = sorted(sector_counts.items(), key=lambda x: -x[1])[:10]
    print("업종 TOP10:", top_sectors)

    # PER 있는 종목 수
    per_count = sum(1 for s in stocks if s["per"] is not None)
    print(f"PER 데이터 있는 종목: {per_count}개")

    # ── 6. 저장 ─────────────────────────────────────────
    os.makedirs("data", exist_ok=True)
    output = {
        "updated": datetime.now().isoformat(),
        "count": len(stocks),
        "stocks": stocks,
    }
    with open("data/stocks.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)

    print("=" * 50)
    print("저장 완료: data/stocks.json")
    print("=" * 50)

if __name__ == "__main__":
    main()
