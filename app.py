from flask import Flask, jsonify, request
from flask_cors import CORS
import FinanceDataReader as fdr
import pandas as pd
import requests
import os
import zipfile
import io
import xml.etree.ElementTree as ET
from datetime import datetime
import time

app = Flask(__name__)
CORS(app, origins="*")

DART_API_KEY = os.environ.get("DART_API_KEY", "c0dfa28be5bfbfccf9b738b548aacaa8500acd6f")
DART_BASE = "https://opendart.fss.or.kr/api"

_corp_map = {}
_corp_map_loaded = False

def load_corp_map():
    global _corp_map, _corp_map_loaded
    if _corp_map_loaded:
        return
    try:
        r = requests.get(f"{DART_BASE}/corpCode.xml", params={"crtfc_key": DART_API_KEY}, timeout=30)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml_data = z.read("CORPCODE.xml")
        root = ET.fromstring(xml_data)
        for corp in root.findall("list"):
            stock_code = corp.findtext("stock_code", "").strip()
            corp_code = corp.findtext("corp_code", "").strip()
            corp_name = corp.findtext("corp_name", "").strip()
            if stock_code:
                _corp_map[stock_code] = {"corp_code": corp_code, "corp_name": corp_name}
        _corp_map_loaded = True
        print(f"corp_map 로드 완료: {len(_corp_map)}개")
    except Exception as e:
        print(f"corp_map 로드 오류: {e}")

def get_financial(corp_code, year):
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
                return data.get("list", [])
        except:
            pass
    return []

def extract_val(items, *keys):
    for key in keys:
        for item in items:
            if item.get("account_id") == key or item.get("account_nm") == key:
                val = item.get("thstrm_amount", "").replace(",", "").strip()
                try:
                    return int(val)
                except:
                    pass
    return None

def get_revenue(items):
    return extract_val(items, "ifrs-full_Revenue", "dart_Revenue", "매출액", "수익(매출액)")

def get_op_profit(items):
    return extract_val(items, "ifrs-full_ProfitLossFromOperatingActivities", "dart_OperatingIncomeLoss", "영업이익")

def get_net_income(items):
    return extract_val(items, "ifrs-full_ProfitLoss", "dart_ProfitLoss", "당기순이익")

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

def get_recommendation(stars, per, revenue_growth, profit_margin):
    if stars >= 5:
        return {"label": "강력추천", "color": "green", "icon": "🌟"}
    elif stars >= 4:
        return {"label": "추천", "color": "blue", "icon": "⭐"}
    elif stars >= 3:
        return {"label": "보통", "color": "gray", "icon": "➖"}
    elif profit_margin and profit_margin < 0:
        return {"label": "적자주의", "color": "red", "icon": "⚠️"}
    else:
        return {"label": "비추천", "color": "red", "icon": "❌"}

# 섹터 매핑
SECTOR_MAP = {
    "반도체/IT": ["반도체", "전자", "디스플레이", "IT", "전기전자"],
    "바이오/제약": ["제약", "바이오", "의약품", "의료"],
    "건설/부동산": ["건설", "부동산", "건축"],
    "음식/식품": ["음식료", "식품", "음료", "제과"],
    "금융/은행": ["은행", "금융", "보험", "증권"],
    "자동차": ["자동차", "운수장비"],
    "화학/소재": ["화학", "소재", "정유", "플라스틱"],
    "엔터/미디어": ["엔터", "미디어", "방송", "콘텐츠", "게임"],
    "유통/소비재": ["유통", "도소매", "소비재", "백화점"],
    "에너지": ["에너지", "전기", "가스", "신재생"],
    "운송/물류": ["운송", "항공", "해운", "물류"],
    "통신": ["통신", "서비스"],
    "철강/금속": ["철강", "금속", "비철금속"],
    "방산": ["방산", "항공우주"],
    "2차전지": ["2차전지", "배터리", "전지"],
}

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})

@app.route("/api/sectors")
def sectors():
    return jsonify({"sectors": list(SECTOR_MAP.keys())})

@app.route("/api/screener")
def screener():
    market = request.args.get("market", "ALL").upper()
    sort_by = request.args.get("sort", "per")
    limit = int(request.args.get("limit", 50))
    sector = request.args.get("sector", "")
    search = request.args.get("search", "").strip()

    load_corp_map()

    try:
        if market == "KOSPI":
            df = fdr.StockListing("KOSPI")
            df["Market"] = "KOSPI"
        elif market == "KOSDAQ":
            df = fdr.StockListing("KOSDAQ")
            df["Market"] = "KOSDAQ"
        else:
            kospi = fdr.StockListing("KOSPI")
            kosdaq = fdr.StockListing("KOSDAQ")
            kospi["Market"] = "KOSPI"
            kosdaq["Market"] = "KOSDAQ"
            df = pd.concat([kospi, kosdaq], ignore_index=True)
    except Exception as e:
        return jsonify({"error": f"종목 리스트 오류: {str(e)}"}), 500

    df.columns = [c.strip() for c in df.columns]

    # 시총 상위 100개
    if "Marcap" in df.columns:
        df = df.sort_values("Marcap", ascending=False).head(100)
    else:
        df = df.head(100)

    prev_year = datetime.now().year - 1
    prev2_year = prev_year - 1

    results = []
    for _, row in df.iterrows():
        try:
            code = str(row.get("Code", "")).zfill(6)
            name = str(row.get("Name", ""))
            mkt = str(row.get("Market", market))
            industry = str(row.get("Industry", row.get("Sector", "")))

            if not name or name == "nan":
                continue

            # 검색 필터
            if search and search.lower() not in name.lower() and search not in code:
                continue

            # 섹터 필터
            if sector:
                keywords = SECTOR_MAP.get(sector, [])
                if not any(k in industry for k in keywords):
                    continue

            def to_float(v):
                try:
                    return float(str(v).replace(",", ""))
                except:
                    return None

            per = to_float(row.get("PER"))
            pbr = to_float(row.get("PBR"))
            price = to_float(row.get("Close", row.get("Adj Close")))
            marcap = to_float(row.get("Marcap"))

            per = round(per, 1) if per and 0 < per < 500 else None
            pbr = round(pbr, 1) if pbr and 0 < pbr < 100 else None

            # DART 재무데이터
            corp_info = _corp_map.get(code)
            revenue_cur = revenue_prev = op_profit = net_income = None
            revenue_growth = profit_margin = None

            if corp_info:
                corp_code = corp_info["corp_code"]
                items_cur = get_financial(corp_code, prev_year)
                items_prev = get_financial(corp_code, prev2_year)

                revenue_cur = get_revenue(items_cur)
                revenue_prev = get_revenue(items_prev)
                op_profit = get_op_profit(items_cur)
                net_income = get_net_income(items_cur)

                if revenue_cur and revenue_prev and revenue_prev != 0:
                    revenue_growth = round((revenue_cur - revenue_prev) / abs(revenue_prev) * 100, 1)
                if op_profit and revenue_cur and revenue_cur != 0:
                    profit_margin = round(op_profit / revenue_cur * 100, 1)

            stars = calc_stars(per, pbr, revenue_growth, profit_margin)
            rec = get_recommendation(stars, per, revenue_growth, profit_margin)

            results.append({
                "code": code,
                "name": name,
                "market": mkt,
                "industry": industry,
                "price": int(price) if price else None,
                "per": per,
                "pbr": pbr,
                "revenue": revenue_cur,
                "revenue_prev": revenue_prev,
                "revenue_growth": revenue_growth,
                "operating_profit": op_profit,
                "net_income": net_income,
                "profit_margin": profit_margin,
                "marcap": int(marcap) if marcap else None,
                "stars": stars,
                "recommendation": rec,
            })
            time.sleep(0.03)
        except Exception as e:
            continue

    # 정렬
    if sort_by == "per":
        results = [r for r in results if r["per"]]
        results.sort(key=lambda x: x["per"])
    elif sort_by == "revenue_growth":
        results = [r for r in results if r["revenue_growth"] is not None]
        results.sort(key=lambda x: x["revenue_growth"], reverse=True)
    elif sort_by == "pbr":
        results = [r for r in results if r["pbr"]]
        results.sort(key=lambda x: x["pbr"])
    elif sort_by == "profit_margin":
        results = [r for r in results if r["profit_margin"] is not None]
        results.sort(key=lambda x: x["profit_margin"], reverse=True)
    elif sort_by == "stars":
        results.sort(key=lambda x: x["stars"], reverse=True)

    pers = [r["per"] for r in results if r["per"]]
    growths = [r["revenue_growth"] for r in results if r["revenue_growth"] is not None]

    return jsonify({
        "status": "ok",
        "count": len(results[:limit]),
        "sort": sort_by,
        "market": market,
        "updated": prev_year,
        "avg_per": round(sum(pers)/len(pers), 1) if pers else None,
        "avg_growth": round(sum(growths)/len(growths), 1) if growths else None,
        "data": results[:limit]
    })

@app.route("/api/stock/<code>")
def stock_detail(code):
    load_corp_map()
    code = code.zfill(6)
    corp_info = _corp_map.get(code)
    prev_year = datetime.now().year - 1

    years_data = []
    if corp_info:
        for y in [prev_year-2, prev_year-1, prev_year]:
            items = get_financial(corp_info["corp_code"], y)
            if items:
                rev = get_revenue(items)
                op = get_op_profit(items)
                net = get_net_income(items)
                years_data.append({
                    "year": y,
                    "revenue": rev,
                    "operating_profit": op,
                    "net_income": net,
                    "profit_margin": round(op/rev*100, 1) if op and rev else None
                })

    try:
        price_df = fdr.DataReader(code, '2024-01-01')
        price_history = [
            {"date": str(d.date()), "close": int(r["Close"])}
            for d, r in price_df.tail(60).iterrows()
        ]
        high_52w = int(price_df["Close"].max())
        low_52w = int(price_df["Close"].min())
    except:
        price_history = []
        high_52w = low_52w = None

    return jsonify({
        "code": code,
        "name": corp_info["corp_name"] if corp_info else code,
        "financials": years_data,
        "price_history": price_history,
        "high_52w": high_52w,
        "low_52w": low_52w,
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
