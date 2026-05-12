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

SECTOR_NAMES = {
    "111":"식량작물 재배업","112":"채소·화훼작물 재배업","113":"과실·음료용 작물 재배업",
    "121":"소 사육업","122":"돼지 사육업","123":"가금류 사육업",
    "130":"임업","150":"어업",
    "101":"식료품 제조업","102":"음료 제조업","103":"담배 제조업",
    "104":"섬유제품 제조업","105":"의복·액세서리 제조업",
    "106":"가죽·가방·신발 제조업","107":"목재·나무제품 제조업",
    "108":"펄프·종이 제조업","201":"기초화학물질 제조업",
    "202":"합성고무·플라스틱 제조업","203":"의약품 제조업",
    "204":"화학섬유 제조업","205":"고무·플라스틱 제조업",
    "211":"비금속 광물제품 제조업","212":"1차 금속 제조업",
    "213":"금속가공제품 제조업","221":"전자부품·컴퓨터·통신장비 제조업",
    "222":"의료·정밀·광학기기 제조업","223":"전기장비 제조업",
    "231":"기타 기계 및 장비 제조업","241":"자동차·트레일러 제조업",
    "242":"기타 운송장비 제조업","251":"가구 제조업",
    "259":"기타 제품 제조업","261":"반도체 제조업",
    "262":"전자부품 제조업","263":"컴퓨터 제조업",
    "264":"반도체·전자부품","265":"통신·방송 장비 제조업",
    "266":"영상·음향기기 제조업","267":"측정·광학·의료기기 제조업",
    "271":"전동기·발전기 제조업","272":"배터리 제조업",
    "281":"일반 기계 제조업","282":"특수목적용 기계 제조업",
    "291":"자동차 제조업","292":"자동차 부품 제조업",
    "301":"선박·보트 제조업","302":"철도·항공기 제조업","303":"항공우주산업",
    "351":"전기업","352":"가스업","360":"수도·하수·폐기물 처리업",
    "411":"종합건설업","412":"전문직별 공사업",
    "451":"자동차 판매업","461":"도매 및 상품중개업",
    "471":"음·식료품 소매업","481":"무점포 소매업",
    "491":"육상 운송업","492":"수상 운송업","493":"항공 운송업",
    "511":"영상·오디오 제작업","512":"방송업",
    "521":"유선 통신업","522":"무선 통신업",
    "531":"컴퓨터 프로그래밍·시스템 통합 관리업",
    "532":"정보서비스업",
    "581":"소프트웨어 개발·공급업","582":"IT 서비스업",
    "61":"금융업","62":"보험업",
    "641":"은행업","642":"저축기관","649":"기타 금융업",
    "651":"생명보험업","652":"손해보험업",
    "661":"금융투자업","662":"집합투자업","663":"투자자문업",
    "64992":"금융지주회사","66199":"기타 금융서비스",
    "66110":"증권업",
    "681":"부동산 임대업","682":"부동산 개발·공급업",
    "683":"부동산 관리업","684":"부동산 중개업",
    "701":"연구개발업","711":"광고업","721":"엔지니어링 서비스업",
    "751":"사업시설 관리업","752":"사업지원 서비스업",
    "771":"인력공급업","772":"여행사업","781":"경비·경호업",
    "2610":"반도체","2612":"반도체·메모리",
    "2620":"전자부품","2630":"컴퓨터","2640":"통신장비",
    "2629":"기타 전자부품","5821":"게임 소프트웨어",
    "58211":"온라인 게임","58212":"모바일 게임",
    "58221":"IT 솔루션","5822":"응용 소프트웨어",
    "29271":"자동차 전장부품","2927":"자동차용 전장부품",
    "56":"숙박업","5611":"한식 음식점업","5619":"기타 음식점업",
    "5911":"영화 제작업","582":"소프트웨어",
}

def get_sector_name(code):
    if not code:
        return ""
    code = str(code).strip()
    if code in SECTOR_NAMES:
        return SECTOR_NAMES[code]
    if len(code) >= 4 and code[:4] in SECTOR_NAMES:
        return SECTOR_NAMES[code[:4]]
    if len(code) >= 3 and code[:3] in SECTOR_NAMES:
        return SECTOR_NAMES[code[:3]]
    if len(code) >= 2 and code[:2] in SECTOR_NAMES:
        return SECTOR_NAMES[code[:2]]
    return ""

def calc_stars(per, pbr, revenue_growth, profit_margin, sector=""):
    """
    현실적인 별점 계산
    - PBR 0.5 미만이면 최소 별 3개 보장
    - 매출 소폭 감소(-20% 이내)는 감점 없음
    - 별 5개 기준 완화 (5점 이상)
    - 데이터 없는 항목은 감점 없음
    """
    score = 0

    # PBR: 자산 대비 저평가 핵심 지표
    if pbr is not None:
        if pbr < 0.5:   score += 3  # 엄청난 저평가
        elif pbr < 1.0: score += 2  # 저평가
        elif pbr < 1.5: score += 1  # 적정
        elif pbr > 5:   score -= 1  # 고평가

    # PER: 이익 대비 주가
    if per is not None:
        if per < 8:    score += 2
        elif per < 15: score += 1
        elif per > 30: score -= 1

    # 매출 성장률: 급감(-20% 초과)만 감점
    if revenue_growth is not None:
        if revenue_growth >= 20:   score += 2
        elif revenue_growth >= 10: score += 1
        elif revenue_growth < -20: score -= 1

    # 영업이익률: 5% 이상이면 가점
    if profit_margin is not None:
        if profit_margin >= 15:  score += 2
        elif profit_margin >= 5: score += 1
        elif profit_margin < 0:  score -= 1

    # PBR 0.5 미만은 무조건 최소 별 3개 (저평가 보호)
    min_stars = 3 if (pbr is not None and pbr < 0.5) else 1

    if score >= 5:   stars = 5
    elif score >= 3: stars = 4
    elif score >= 1: stars = 3
    elif score >= 0: stars = 2
    else:            stars = 1

    return max(stars, min_stars)

def get_recommendation(stars):
    if stars >= 5: return {"label": "강력추천", "color": "green", "icon": "🌟"}
    elif stars >= 4: return {"label": "추천", "color": "blue", "icon": "⭐"}
    elif stars >= 3: return {"label": "보통", "color": "gray", "icon": "➖"}
    else: return {"label": "비추천", "color": "red", "icon": "❌"}

def get_krx_per_pbr():
    """KRX에서 PER/PBR 수집 (실패시 빈 dict 반환 — DART 계산으로 대체)"""
    per_pbr = {}
    try:
        url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
        headers = {
            "Referer": "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020101",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        today = datetime.now().strftime("%Y%m%d")
        for mktid in ["STK", "KSQ"]:
            params = {
                "bld": "dbms/MDC/STAT/standard/MDCSTAT03501",
                "mktId": mktid,
                "trdDd": today,
                "share": "1",
                "money": "1",
                "csvxls_isNo": "false",
            }
            r = requests.post(url, data=params, headers=headers, timeout=30)
            data = r.json()
            items = data.get("OutBlock_1", [])
            for item in items:
                code = str(item.get("ISU_SRT_CD", "")).zfill(6)
                try:
                    per = float(str(item.get("PER", "")).replace(",", "").strip())
                    if 0 < per < 500:
                        per_pbr.setdefault(code, {})["per"] = round(per, 1)
                except: pass
                try:
                    pbr = float(str(item.get("PBR", "")).replace(",", "").strip())
                    if 0 < pbr < 100:
                        per_pbr.setdefault(code, {})["pbr"] = round(pbr, 1)
                except: pass
            print(f"KRX {mktid}: {len(items)}개 종목 처리")
        print(f"KRX PER/PBR 수집 완료: {len(per_pbr)}개")
    except Exception as e:
        print(f"KRX PER/PBR 오류 (DART 계산으로 대체): {e}")
    return per_pbr


def calc_per_pbr_from_dart(price, shares, net_profit, total_equity):
    """
    DART 재무데이터 + 주가 + 주식수로 PER/PBR 직접 계산
    PER = 주가 / EPS(주당순이익)   EPS = 순이익 / 주식수
    PBR = 주가 / BPS(주당순자산)   BPS = 자본총계 / 주식수
    """
    per = pbr = None
    try:
        if price and shares and shares > 0 and net_profit and net_profit > 0:
            eps = net_profit / shares
            if eps > 0:
                per_val = price / eps
                if 0 < per_val < 500:
                    per = round(per_val, 1)
    except: pass
    try:
        if price and shares and shares > 0 and total_equity and total_equity > 0:
            bps = total_equity / shares
            if bps > 0:
                pbr_val = price / bps
                if 0 < pbr_val < 100:
                    pbr = round(pbr_val, 1)
    except: pass
    return per, pbr

def load_corp_map():
    corp_map = {}
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
    return corp_map

def get_sector_batch(corp_codes_chunk):
    result = {}
    for corp_code, stock_code in corp_codes_chunk:
        try:
            r = requests.get(f"{DART_BASE}/company.json", params={
                "crtfc_key": DART_API_KEY,
                "corp_code": corp_code,
            }, timeout=10)
            data = r.json()
            if data.get("status") == "000":
                induty_code = data.get("induty_code", "").strip()
                sector_name = get_sector_name(induty_code)
                result[stock_code] = sector_name
        except:
            result[stock_code] = ""
    return result

def get_dart_financials_batch(corp_codes_list, year):
    all_data = {}
    total = len(corp_codes_list)
    for i, batch in enumerate(corp_codes_list):
        try:
            r = requests.get(f"{DART_BASE}/fnlttMultiAcnt.json", params={
                "crtfc_key": DART_API_KEY,
                "corp_code": ",".join(batch),
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
                    try: val = int(val_str)
                    except: continue
                    if code not in all_data:
                        all_data[code] = {}
                    if any(k in acct for k in ["매출액", "수익(매출액)"]) and "revenue" not in all_data[code]:
                        all_data[code]["revenue"] = val
                    elif "영업이익" in acct and "영업이익률" not in acct and "operating_profit" not in all_data[code]:
                        all_data[code]["operating_profit"] = val
                    elif "당기순이익" in acct and "net_profit" not in all_data[code]:
                        all_data[code]["net_profit"] = val
                    elif "부채총계" in acct and "total_debt" not in all_data[code]:
                        all_data[code]["total_debt"] = val
                    elif "자본총계" in acct and "total_equity" not in all_data[code]:
                        all_data[code]["total_equity"] = val
            if (i+1) % 5 == 0:
                print(f"  재무 배치 {i+1}/{total} ({len(all_data)}개 누적)")
        except Exception as e:
            print(f"배치 {i+1} 예외: {e}")
    return all_data

def main():
    print("=" * 50)
    print("전종목 수집 시작:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 50)

    k1 = fdr.StockListing("KOSPI");  k1["Market"] = "KOSPI"
    k2 = fdr.StockListing("KOSDAQ"); k2["Market"] = "KOSDAQ"
    df = pd.concat([k1, k2], ignore_index=True)
    df.columns = [c.strip() for c in df.columns]
    print(f"전체 종목: {len(df)}개")

    print("KRX PER/PBR 수집 중...")
    per_pbr_map = get_krx_per_pbr()

    try:
        r = requests.get(f"{DART_BASE}/fnlttMultiAcnt.json", params={
            "crtfc_key": DART_API_KEY, "corp_code": "00126380",
            "bsns_year": "2024", "reprt_code": "11011",
        }, timeout=15)
        dart_ok = r.json().get("status") == "000"
    except:
        dart_ok = False
    print(f"DART API: {dart_ok}")

    fin_cur = fin_prev = {}
    sector_map = {}

    if dart_ok:
        corp_map = load_corp_map()
        prev_year = datetime.now().year - 1
        prev2_year = prev_year - 1

        all_corp_codes = []
        corp_stock_pairs = []
        for _, row in df.iterrows():
            code = str(row.get("Code", "")).zfill(6)
            corp_code = corp_map.get(code)
            if corp_code:
                all_corp_codes.append(corp_code)
                corp_stock_pairs.append((corp_code, code))

        batches = [all_corp_codes[i:i+100] for i in range(0, len(all_corp_codes), 100)]
        print(f"재무 배치 {len(batches)}개")

        print(f"{prev_year}년 재무 수집 중...")
        fin_cur = get_dart_financials_batch(batches, prev_year)
        print(f"{prev_year}년: {len(fin_cur)}개")

        print(f"{prev2_year}년 재무 수집 중...")
        fin_prev = get_dart_financials_batch(batches, prev2_year)
        print(f"{prev2_year}년: {len(fin_prev)}개")

        print("업종 수집 중...")
        chunks = [corp_stock_pairs[i:i+50] for i in range(0, len(corp_stock_pairs), 50)]
        collected = 0
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(get_sector_batch, c): c for c in chunks}
            for future in as_completed(futures):
                try:
                    sector_map.update(future.result())
                    collected += 1
                    if collected % 10 == 0:
                        print(f"  업종 청크 {collected}/{len(chunks)} 완료")
                except Exception as e:
                    print(f"업종 오류: {e}")
        print(f"업종 수집 완료: {len(sector_map)}개")

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

            # KRX에서 가져온 PER/PBR 우선, 없으면 DART 계산
            per = per_pbr_map.get(code, {}).get("per")
            pbr = per_pbr_map.get(code, {}).get("pbr")
            price = to_float(row.get("Close", row.get("Adj Close")))
            marcap = to_float(row.get("Marcap"))

            fin = fin_cur.get(code, {})
            fin_p = fin_prev.get(code, {})
            revenue_cur = fin.get("revenue")
            revenue_prev = fin_p.get("revenue")
            op_profit = fin.get("operating_profit")
            net_profit = fin.get("net_profit")
            total_debt = fin.get("total_debt")
            total_equity = fin.get("total_equity")

            # KRX 실패시 DART로 PER/PBR 계산
            shares = to_float(row.get("Stocks"))
            if per is None or pbr is None:
                d_per, d_pbr = calc_per_pbr_from_dart(price, shares, net_profit, total_equity)
                if per is None: per = d_per
                if pbr is None: pbr = d_pbr

            revenue_growth = profit_margin = debt_ratio = None
            if revenue_cur and revenue_prev and revenue_prev != 0:
                revenue_growth = round((revenue_cur - revenue_prev) / abs(revenue_prev) * 100, 1)
            if op_profit and revenue_cur and revenue_cur != 0:
                profit_margin = round(op_profit / revenue_cur * 100, 1)
            if total_debt and total_equity and total_equity > 0:
                debt_ratio = round(total_debt / total_equity * 100, 1)

            sector = sector_map.get(code, "")
            stars = calc_stars(per, pbr, revenue_growth, profit_margin, sector)

            stocks.append({
                "code": code, "name": name, "market": mkt, "sector": sector, "industry": sector,
                "price": int(price) if price else None,
                "per": per, "pbr": pbr,
                "revenue": revenue_cur, "revenue_prev": revenue_prev,
                "revenue_growth": revenue_growth,
                "operating_profit": op_profit, "net_profit": net_profit,
                "profit_margin": profit_margin, "debt_ratio": debt_ratio,
                "total_equity": total_equity,
                "marcap": int(marcap) if marcap else None,
                "stars": stars, "recommendation": get_recommendation(stars),
            })
        except:
            continue

    per_count = sum(1 for s in stocks if s["per"] is not None)
    sec_count = sum(1 for s in stocks if s["sector"])
    print(f"최종 {len(stocks)}개 | PER: {per_count}개 | 섹터: {sec_count}개")

    sec_dist = {}
    for s in stocks:
        k = s["sector"] or "미분류"
        sec_dist[k] = sec_dist.get(k, 0) + 1
    print("업종 TOP10:", sorted(sec_dist.items(), key=lambda x: -x[1])[:10])

    os.makedirs("data", exist_ok=True)
    with open("data/stocks.json", "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now().isoformat(), "count": len(stocks), "stocks": stocks}, f, ensure_ascii=False)

    print("=" * 50)
    print("완료!")
    print("=" * 50)

if __name__ == "__main__":
    main()
