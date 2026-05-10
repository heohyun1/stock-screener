import FinanceDataReader as fdr
import pandas as pd
import requests
import os
import zipfile
import io
import xml.etree.ElementTree as ET
import json
import time
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
    corp_map = {}
    try:
        r = requests.get(f"{DART_BASE}/corpCode.xml",
            params={"crtfc_key": DART_API_KEY}, timeout=30)
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
    return corp_map

def get_dart_financial(corp_code, year):
    for fs_div in ["CFS", "OFS"]:
        try:
            r = requests.get(f"{DART_BASE}/fnlttSinglAcntAll.json", params={
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": "11011",
                "fs_div": fs_div
            }, timeout=10)
            data = r.json()
            if data.get("status") == "000":
                items = data.get("list", [])
                revenue = op_profit = None
                for item in items:
                    acct = item.get("account_nm", "")
                    val_str = item.get("thstrm_amount", "").replace(",", "").strip()
                    try:
                        val = int(val_str)
                    except:
                        continue
                    if any(k in acct for k in ["매출액", "수익(매출액)"]) and revenue is None:
                        revenue = val
                    elif "영업이익" in acct and "영업이익률" not in acct and op_profit is None:
                        op_profit = val
                return revenue, op_profit
        except:
            pass
    return None, None

def process_stock(args):
    """단일 종목 처리 (병렬용)"""
    row, corp_map, prev_year, prev2_year, industry_col = args
    try:
        code = str(row.get("Code", "")).zfill(6)
        name = str(row.get("Name", ""))
        mkt = str(row.get("Market", ""))
        industry = str(row.get(industry_col, "")) if industry_col else ""

        if not name or name == "nan":
            return None

        def to_float(v):
            try: return float(str(v).replace(",", ""))
            except: return None

        per = to_float(row.get("PER"))
        pbr = to_float(row.get("PBR"))
        price = to_float(row.get("Close", row.get("Adj Close")))
        marcap = to_float(row.get("Marcap"))

        per = round(per, 1) if per and 0 < per < 500 else None
        pbr = round(pbr, 1) if pbr and 0 < pbr < 100 else None

        corp_code = corp_map.get(code)
        revenue_cur = revenue_prev = op_profit = None
        if corp_code:
            revenue_cur, op_profit = get_dart_financial(corp_code, prev_year)
            revenue_prev, _ = get_dart_financial(corp_code, prev2_year)

        revenue_growth = profit_margin = None
        if revenue_cur and revenue_prev and revenue_prev != 0:
            revenue_growth = round((revenue_cur - revenue_prev) / abs(revenue_prev) * 100, 1)
        if op_profit and revenue_cur and revenue_cur != 0:
            profit_margin = round(op_profit / revenue_cur * 100, 1)

        stars = calc_stars(per, pbr, revenue_growth, profit_margin)

        return {
            "code": code, "name": name, "market": mkt, "industry": industry,
            "price": int(price) if price else None,
            "per": per, "pbr": pbr,
            "revenue": revenue_cur, "revenue_growth": revenue_growth,
            "operating_profit": op_profit, "profit_margin": profit_margin,
            "marcap": int(marcap) if marcap else None,
            "stars": stars, "recommendation": get_recommendation(stars),
        }
    except:
        return None

def main():
    print("전체 종목 데이터 수집 시작...")

    k1 = fdr.StockListing("KOSPI"); k1["Market"] = "KOSPI"
    k2 = fdr.StockListing("KOSDAQ"); k2["Market"] = "KOSDAQ"
    df = pd.concat([k1, k2], ignore_index=True)
    df.columns = [c.strip() for c in df.columns]
    print(f"전체 종목: {len(df)}개")

    corp_map = load_corp_map()
    prev_year = datetime.now().year - 1
    prev2_year = prev_year - 1
    industry_col = next((c for c in ["Industry", "Sector", "업종"] if c in df.columns), None)

    # 병렬 처리 준비
    args_list = [
        (row, corp_map, prev_year, prev2_year, industry_col)
        for _, row in df.iterrows()
    ]

    stocks = []
    completed = 0
    total = len(args_list)

    # 10개씩 병렬 처리
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_stock, args): args for args in args_list}
        for future in as_completed(futures):
            result = future.result()
            if result:
                stocks.append(result)
            completed += 1
            if completed % 100 == 0:
                print(f"[{completed}/{total}] 진행 중... ({len(stocks)}개 수집)")

    print(f"수집 완료: {len(stocks)}개 종목")

    os.makedirs("data", exist_ok=True)
    output = {
        "updated": datetime.now().isoformat(),
        "count": len(stocks),
        "stocks": stocks
    }
    with open("data/stocks.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)

    print(f"저장 완료! data/stocks.json")

if __name__ == "__main__":
    main()
