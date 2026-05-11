from flask import Flask, jsonify, request
from flask_cors import CORS
import FinanceDataReader as fdr
import pandas as pd
import requests
import os
import zipfile
import io
import xml.etree.ElementTree as ET
import json
import threading
import time
from datetime import datetime

app = Flask(__name__)
CORS(app, origins="*")

DART_API_KEY = os.environ.get("DART_API_KEY", "c0dfa28be5bfbfccf9b738b548aacaa8500acd6f")
DART_BASE = "https://opendart.fss.or.kr/api"
GITHUB_RAW = "https://raw.githubusercontent.com/heohyun1/stock-screener/main/data/stocks.json"

_cache = {"stocks": [], "last_updated": None, "loading": False}

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

def load_from_github():
    """GitHub에서 미리 만들어진 전체 종목 데이터 로드"""
    try:
        r = requests.get(GITHUB_RAW, timeout=15)
        if r.status_code == 200:
            data = r.json()
            stocks = data.get("stocks", [])
            print(f"GitHub 데이터 로드: {len(stocks)}개")
            return stocks, data.get("updated")
    except Exception as e:
        print(f"GitHub 로드 오류: {e}")
    return None, None

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
            }, timeout=8)
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

def build_cache():
    global _cache
    _cache["loading"] = True

    # 먼저 GitHub 데이터 시도 (전체 종목)
    stocks, updated = load_from_github()
    if stocks:
        _cache["stocks"] = stocks
        _cache["last_updated"] = updated
        _cache["loading"] = False
        print(f"GitHub 데이터 사용: {len(stocks)}개 종목")
        return

    # GitHub 데이터 없으면 직접 수집 (상위 100개)
    print("GitHub 데이터 없음. 직접 수집 시작...")
    try:
        k1 = fdr.StockListing("KOSPI"); k1["Market"] = "KOSPI"
        k2 = fdr.StockListing("KOSDAQ"); k2["Market"] = "KOSDAQ"
        df = pd.concat([k1, k2], ignore_index=True)
        df.columns = [c.strip() for c in df.columns]
        if "Marcap" in df.columns:
            df = df.sort_values("Marcap", ascending=False).head(100)

        corp_map = load_corp_map()
        prev_year = datetime.now().year - 1
        prev2_year = prev_year - 1
        industry_col = next((c for c in ["Industry", "Sector", "업종"] if c in df.columns), None)

        def to_float(v):
            try: return float(str(v).replace(",", ""))
            except: return None

        stocks = []
        for i, (_, row) in enumerate(df.iterrows()):
            try:
                code = str(row.get("Code", "")).zfill(6)
                name = str(row.get("Name", ""))
                mkt = str(row.get("Market", ""))
                industry = str(row.get(industry_col, "")) if industry_col else ""
                if not name or name == "nan": continue

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
                    time.sleep(0.1)

                revenue_growth = profit_margin = None
                if revenue_cur and revenue_prev and revenue_prev != 0:
                    revenue_growth = round((revenue_cur - revenue_prev) / abs(revenue_prev) * 100, 1)
                if op_profit and revenue_cur and revenue_cur != 0:
                    profit_margin = round(op_profit / revenue_cur * 100, 1)

                stars = calc_stars(per, pbr, revenue_growth, profit_margin)
                stocks.append({
                    "code": code, "name": name, "market": mkt, "industry": industry,
                    "price": int(price) if price else None,
                    "per": per, "pbr": pbr,
                    "revenue": revenue_cur, "revenue_growth": revenue_growth,
                    "operating_profit": op_profit, "profit_margin": profit_margin,
                    "marcap": int(marcap) if marcap else None,
                    "stars": stars, "recommendation": get_recommendation(stars),
                })
                print(f"[{i+1}/100] {name} 완료")
            except: continue

        _cache["stocks"] = stocks
        _cache["last_updated"] = datetime.now().isoformat()
        print(f"캐시 완료: {len(stocks)}개")
    except Exception as e:
        print(f"캐시 오류: {e}")
    finally:
        _cache["loading"] = False

@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "time": datetime.now().isoformat(),
        "cache_count": len(_cache["stocks"]),
        "last_updated": _cache["last_updated"],
        "loading": _cache["loading"]
    })

@app.route("/api/screener")
def screener():
    sort_by = request.args.get("sort", "stars")
    market = request.args.get("market", "ALL").upper()
    limit = int(request.args.get("limit", 50))
    sector = request.args.get("sector", "").strip()
    search = request.args.get("search", "").strip()

    if not _cache["stocks"] and not _cache["loading"]:
        thread = threading.Thread(target=build_cache)
        thread.daemon = True
        thread.start()

    if _cache["loading"] and not _cache["stocks"]:
        return jsonify({"status": "loading", "message": "데이터 로딩 중 (2~3분 소요)", "data": []})

    results = list(_cache["stocks"])
    if market != "ALL":
        results = [r for r in results if r["market"] == market]
    if search:
        results = [r for r in results if search.lower() in r["name"].lower() or search in r["code"]]
    if sector:
        results = [r for r in results if sector in r.get("industry", "")]

    if sort_by == "per":
        has = [r for r in results if r["per"]]; no = [r for r in results if not r["per"]]
        has.sort(key=lambda x: x["per"]); results = has + no
    elif sort_by == "revenue_growth":
        has = [r for r in results if r["revenue_growth"] is not None]; no = [r for r in results if r["revenue_growth"] is None]
        has.sort(key=lambda x: x["revenue_growth"], reverse=True); results = has + no
    elif sort_by == "pbr":
        has = [r for r in results if r["pbr"]]; no = [r for r in results if not r["pbr"]]
        has.sort(key=lambda x: x["pbr"]); results = has + no
    elif sort_by == "profit_margin":
        has = [r for r in results if r["profit_margin"] is not None]; no = [r for r in results if r["profit_margin"] is None]
        has.sort(key=lambda x: x["profit_margin"], reverse=True); results = has + no
    elif sort_by == "stars":
        results.sort(key=lambda x: x["stars"], reverse=True)

    pers = [r["per"] for r in results if r["per"]]
    growths = [r["revenue_growth"] for r in results if r["revenue_growth"] is not None]

    return jsonify({
        "status": "ok",
        "count": len(results[:limit]),
        "sort": sort_by, "market": market,
        "updated": _cache["last_updated"],
        "total_stocks": len(_cache["stocks"]),
        "avg_per": round(sum(pers)/len(pers), 1) if pers else None,
        "avg_growth": round(sum(growths)/len(growths), 1) if growths else None,
        "data": results[:limit]
    })

@app.route("/api/stock/<code>")
def stock_detail(code):
    code = code.zfill(6)
    stock = next((s for s in _cache["stocks"] if s["code"] == code), None)
    try:
        price_df = fdr.DataReader(code, '2024-01-01')
        price_history = [{"date": str(d.date()), "close": int(r["Close"])} for d, r in price_df.tail(60).iterrows()]
        high_52w = int(price_df["Close"].max())
        low_52w = int(price_df["Close"].min())
    except:
        price_history = []; high_52w = low_52w = None

    return jsonify({
        "code": code,
        "name": stock["name"] if stock else code,
        "financials": [],
        "price_history": price_history,
        "high_52w": high_52w, "low_52w": low_52w,
    })

thread = threading.Thread(target=build_cache)
thread.daemon = True
thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
