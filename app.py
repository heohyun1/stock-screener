from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import os
from datetime import datetime

app = Flask(__name__)
CORS(app, origins="*")

GITHUB_RAW = "https://raw.githubusercontent.com/heohyun1/stock-screener/main/data/stocks.json"

_cache = {"stocks": [], "last_updated": None}

def load_from_github():
    global _cache
    try:
        r = requests.get(GITHUB_RAW, timeout=30)
        if r.status_code == 200:
            data = r.json()
            stocks = data.get("stocks", [])
            if stocks:
                _cache["stocks"] = stocks
                _cache["last_updated"] = data.get("updated")
                print(f"GitHub 데이터 로드: {len(stocks)}개")
                return True
    except Exception as e:
        print(f"GitHub 로드 오류: {e}")
    return False

def get_cache():
    if not _cache["stocks"]:
        load_from_github()
    return _cache["stocks"]

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

@app.route("/api/health")
def health():
    stocks = get_cache()
    return jsonify({
        "status": "ok",
        "time": datetime.now().isoformat(),
        "cache_count": len(stocks),
        "last_updated": _cache["last_updated"],
    })

@app.route("/api/screener")
def screener():
    sort_by = request.args.get("sort", "stars")
    market = request.args.get("market", "ALL").upper()
    limit = int(request.args.get("limit", 50))
    sector = request.args.get("sector", "").strip()
    search = request.args.get("search", "").strip()

    stocks = get_cache()

    if not stocks:
        return jsonify({"status": "error", "message": "데이터 없음", "data": []}), 500

    results = list(stocks)

    if market != "ALL":
        results = [r for r in results if r.get("market") == market]
    if search:
        results = [r for r in results if search.lower() in r.get("name","").lower() or search in r.get("code","")]
    if sector:
        results = [r for r in results if sector in r.get("industry", "")]

    if sort_by == "per":
        has = [r for r in results if r.get("per")]
        no = [r for r in results if not r.get("per")]
        has.sort(key=lambda x: x["per"])
        results = has + no
    elif sort_by == "revenue_growth":
        has = [r for r in results if r.get("revenue_growth") is not None]
        no = [r for r in results if r.get("revenue_growth") is None]
        has.sort(key=lambda x: x["revenue_growth"], reverse=True)
        results = has + no
    elif sort_by == "pbr":
        has = [r for r in results if r.get("pbr")]
        no = [r for r in results if not r.get("pbr")]
        has.sort(key=lambda x: x["pbr"])
        results = has + no
    elif sort_by == "profit_margin":
        has = [r for r in results if r.get("profit_margin") is not None]
        no = [r for r in results if r.get("profit_margin") is None]
        has.sort(key=lambda x: x["profit_margin"], reverse=True)
        results = has + no
    elif sort_by == "stars":
        results.sort(key=lambda x: x.get("stars", 1), reverse=True)

    pers = [r["per"] for r in results if r.get("per")]
    growths = [r["revenue_growth"] for r in results if r.get("revenue_growth") is not None]

    return jsonify({
        "status": "ok",
        "count": len(results[:limit]),
        "sort": sort_by,
        "market": market,
        "updated": _cache["last_updated"],
        "total_stocks": len(_cache["stocks"]),
        "avg_per": round(sum(pers)/len(pers), 1) if pers else None,
        "avg_growth": round(sum(growths)/len(growths), 1) if growths else None,
        "data": results[:limit]
    })

@app.route("/api/stock/<code>")
def stock_detail(code):
    stocks = get_cache()
    stock = next((s for s in stocks if s.get("code") == code.zfill(6)), None)
    return jsonify({
        "code": code,
        "name": stock["name"] if stock else code,
        "financials": [],
        "price_history": [],
        "high_52w": None,
        "low_52w": None,
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
