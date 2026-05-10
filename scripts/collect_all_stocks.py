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
        if revenue_growth > 20: score += 2
        elif revenue_growth > 10: score += 1
        elif revenue_growth < 0: score -= 1
    if profit_margin is not None:
        if profit_margin > 15: score += 2
        elif profit_margin > 8: score += 1
        elif profit_margin < 0: score -= 1
    if score >= 6: return 5
    elif score >= 4: return 4
    elif score >= 2: return 3
    elif score >= 1: return 2
    else: return 1

def get_recommendation(stars):
    if stars >= 5: return {"label": "적직매수", "color": "green", "icon": "🟢"}
    elif stars >= 4: return {"label": "매수관심", "color": "blue", "icon": "🔵"}
    elif stars >= 3: return {"label": "중립", "color": "gray", "icon": "⚪"}
    else: return {"label": "주의", "color": "red", "icon": "🔴"}

def load_corp_map():
    corp_map = {}
    try:
        r = requests.get(f"{DART_BASE}/corpCode.xml", params={"crtfc_key": DART_API_KEY}, timeout=30)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml_data = z.read("CORPCODE.xml")
        root = ET.fromstring(xml_data)
        for corp in root.findall("list"):
            stock_code = corp.findtext("stock_code", "").strip()
            corp_code = corp.findtext("corp_code", "").strip()
            if stock_code:
                corp_map[stock_code] = corp_code
        print(f"corp_map 로드: {len(corp_map)}개")
    except Exception as e:
        print(f"corp_map 오류: {e}")
    return corp_map

def get_dart_financial(corp_code, year):
    for fs_div in ["CFS", "OFS"]:
        try:
            r = requests.get(
                f"{DART_BASE}/fnlttSinglAcntAll.json",
                params={
                    "crtfc_key": DART_API_KEY,
                    "corp_code": corp_code,
                    "bsns_year": str(year),
                    "reprt_code": "11011",
                    "fs_div": fs_div
                },
                timeout=10
            )
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
                    if any(k in acct for k in ["매출액", "수익"]) and revenue is None:
                        revenue = val
                    elif "영업이익" in acct and "소계" not in acct and op_profit is None:
                        op_profit = val
                return revenue, op_profit
        except:
            pass
    return None, None

def main():
    print("한국 주식 전체 수집 시작...")
    k1 = fdr.StockListing("KOSPI")
    k1["Market"] = "KOSPI"
    k2 = fdr.StockListing("KOSDAQ")
    k2["Market"] = "KOSDAQ"
    df = pd.concat([k1, k2], ignore_index=True)
    df.columns = [c.strip() for c in df.columns]
    print(f"전체 종목: {len(df)}개")

    corp_map = load_corp_map()
    prev_year = datetime.now().year - 1
    prev2_year = prev_year - 1

    industry_col = next((c for c in ["Industry", "Sector", "업종"] if c in df.columns), None)

    def to_float(v):
        try:
            return float(str(v).replace(",", ""))
        except:
            return None

    stocks = []
    total = len(df)
    for i, (_, row) in enumerate(df.iterrows()):
        try:
            code = str(row.get("Code", "")).zfill(6)
            name = str(row.get("Name", ""))
            mkt = str(row.get("Market", ""))
            industry = str(row.get(industry_col, "")) if industry_col else ""
            if not name or name == "nan":
                continue
            per = to_float(row.get("PER"))
            pbr = to_float(row.get("PBR"))
            price = to_float(row.get("Close") or row.get("Adj Close"))
            marcap = to_float(row.get("Marcap"))
            per = round(per, 1) if per and 0 < per < 500 else None
            pbr = round(pbr, 1) if pbr and 0 < pbr < 100 else None

            corp_code = corp_map.get(code)
            revenue_cur = revenue_prev = op_profit = None
            if corp_code:
                revenue_cur, op_profit = get_dart_financial(corp_code, prev_year)
                revenue_prev, _ = get_dart_financial(corp_code, prev2_year)
                time.sleep(0.05)

            revenue_growth = None
            profit_margin = None
            if revenue_cur and revenue_prev and revenue_prev != 0:
                revenue_growth = round((revenue_cur - revenue_prev) / abs(revenue_prev) * 100, 1)
            if op_profit and revenue_cur and revenue_cur != 0:
                profit_margin = round(op_profit / revenue_cur * 100, 1)

            stars = calc_stars(per, pbr, revenue_growth, profit_margin)
            rec = get_recommendation(stars)
            stocks.append({
                "code": code,
                "name": name,
                "market": mkt,
                "industry": industry,
                "price": int(price) if price else None,
                "per": per,
                "pbr": pbr,
                "revenue": revenue_cur,
                "revenue_growth": revenue_growth,
                "operating_profit": op_profit,
                "profit_margin": profit_margin,
                "marcap": int(marcap) if marcap else None,
                "stars": stars,
                "recommendation": rec,
            })
            if (i + 1) % 100 == 0:
                print(f"{i+1}/{total} 수집 중...")
        except Exception as e:
            continue

    print(f"한국 주식 전체 수집 완료!")
    os.makedirs("data", exist_ok=True)
    output = {
        "updated": datetime.now().isoformat(),
        "count": len(stocks),
        "stocks": stocks
    }
    with open("data/stocks.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)
    print(f"저장 완료! {len(stocks)}개")

if __name__ == "__main__":
    main()
