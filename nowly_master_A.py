import os
import time
import datetime
import requests
import xml.etree.ElementTree as ET
import google.generativeai as genai
from supabase import create_client, Client

# 1. 환경변수 로드 (A봇은 1번 열쇠를 씁니다!)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY_1") # 🚨 1번 열쇠 수정 완료!

# 2. 클라이언트 세팅
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel('gemini-flash-latest')

# ─── 데이터 크롤링 영역 ───
def get_google_trends():
    url = "https://trends.google.com/trending/rss?geo=KR"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        root = ET.fromstring(res.text)
        return {item.find('title').text.strip(): i + 1 for i, item in enumerate(root.findall('.//item')[:10])}
    except:
        return {}

def get_signal_trends():
    url = "https://api.signal.bz/news/realtime"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        signal_dict = {}
        for i, item in enumerate(res.json().get("top10", [])):
            raw_keyword = item.get("keyword", "").strip()
            short_keyword = raw_keyword.split(' ')[0] if ' ' in raw_keyword else raw_keyword
            if short_keyword not in signal_dict:
                signal_dict[short_keyword] = i + 1
        return signal_dict
    except:
        return {}

def create_nowly_ranking():
    google_data = get_google_trends()
    signal_data = get_signal_trends()
    scoring_board = []
    processed_signal_words = set()

    for g_word, g_rank in google_data.items():
        g_score = 11 - g_rank
        matched = False
        for s_word, s_rank in signal_data.items():
            clean_g = g_word.replace(" ", "").lower()
            clean_s = s_word.replace(" ", "").lower()
            if clean_g in clean_s or clean_s in clean_g:
                s_score = 11 - s_rank
                best_title = g_word if len(g_word) <= len(s_word) else s_word
                scoring_board.append({"title": best_title, "score": g_score + s_score + 100, "source": "통합🔥"})
                processed_signal_words.add(s_word)
                matched = True
                break
        if not matched:
            scoring_board.append({"title": g_word, "score": g_score, "source": "구글"})

    for s_word, s_rank in signal_data.items():
        if s_word not in processed_signal_words:
            scoring_board.append({"title": s_word, "score": 11 - s_rank, "source": "시그널"})

    scoring_board.sort(key=lambda x: x['score'], reverse=True)
    final_trends = []
    seen_titles = set()
    for item in scoring_board:
        check_title = item["title"].replace(" ", "").lower()
        if check_title not in seen_titles:
            seen_titles.add(check_title)
            rank = len(final_trends) + 1
            final_trends.append({"id": rank, "rank": rank, "title": item["title"], "volume": item["source"]})
        if len(final_trends) == 10:
            break
    return final_trends

def get_wiki_summary(keyword):
    search_term = keyword.split(' ')[0] if ' ' in keyword else keyword
    url = f"https://ko.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(search_term)}"
    try:
        headers = {'User-Agent': 'NowlyBot/1.0 (admin@nowly.kr)'}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            return data.get('extract', data.get('description', '위키백과 본문 요약을 찾을 수 없습니다.'))
        elif res.status_code == 404:
            return f"'{search_term}'에 대한 위키백과 문서를 찾을 수 없습니다."
        else:
            return "위키백과 정보를 불러오는 중 서버 오류가 발생했습니다."
    except Exception as e:
        return "위키백과와 통신 중 오류가 발생했습니다."

def get_news_headlines(keyword):
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(keyword)}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        res = requests.get(url, timeout=5)
        root = ET.fromstring(res.text)
        headlines = [item.find('title').text for item in root.findall('.//item')[:3]]
        return " / ".join(headlines) if headlines else "관련 뉴스 없음"
    except:
        return "뉴스 검색 실패"

# 🚨 완전히 새로워진 제미나이 단일 요약 (안전성 1000%)
def get_batch_ai_summaries(keywords):
    if not keywords:
        return {}
    
    summary_dict = {}
    
    for k in keywords:
        headlines = get_news_headlines(k)
        prompt = f"""
        현재 한국 실시간 검색어 '{k}'에 대한 요약을 작성해주세요.
        최신 뉴스 헤드라인: {headlines}

        [분석 지침]
        1. 뉴스 헤드라인을 바탕으로 이 키워드가 왜 이슈인지 딱 1문장으로 명확히 요약하세요.
        2. 뉴스가 없다면 당신의 최신 지식을 바탕으로 추론하세요.
        3. 별표(*), 샵(#), 대괄호 등 특수문자는 절대 사용하지 말고 존댓말로 작성하세요.
        """
        
        try:
            # AI가 당황하지 않게 2초씩 숨 고르기 (API 한도 초과 완벽 방어)
            time.sleep(2) 
            response = model.generate_content(prompt)
            # 제미나이가 준 답변에서 특수문자랑 줄바꿈을 싹 지우고 한 줄로 만듦
            clean_text = response.text.strip().replace('*', '').replace('#', '').replace('\n', ' ')
            summary_dict[k] = clean_text
            print(f"▶ [{k}] AI 응답 완벽 수신!", flush=True)
        except Exception as e:
            print(f"\n[!] [{k}] 요약 에러: {e}\n", flush=True)
            
    return summary_dict

# ─── 메인 프로세스 ───
def process_trends():
    print(f"\n🚀 [{datetime.datetime.now()}] [A봇] 실시간 크롤링 (1~5위) 시작!", flush=True)
    
    # 🚨 수정: 전체 10개 중 [0번째부터 5번째 전까지] 딱 5개만 자릅니다!
    current_trends = create_nowly_ranking()[:5] 

    if not current_trends:
        print("수집된 트렌드 데이터가 없습니다.", flush=True)
        return

    # 🚨 A봇 반장 전용 코드: 기존 랭킹을 99위로 싹 초기화하여 청소합니다!
    try:
        supabase.table("google_trends").update({"rank": 99}).neq("rank", 99).execute()
        print("🧹 [A봇] 기존 랭킹 99위로 초기화 완료!", flush=True)
    except Exception as e:
        pass

    needs_ai_keywords = []
    trend_data_list = []

    for item in current_trends:
        keyword = item['title']
        existing_data = supabase.table("google_trends").select("*").eq("title", keyword).execute()

        should_update_ai = True
        saved_ai_summary = "최신 트렌드를 분석하여 요약 중입니다."
        saved_wiki_content = ""

        if existing_data.data:
            row = existing_data.data[0]
            if row.get('updated_at'):
                time_str = row['updated_at']
                time_str = time_str.split('.')[0] + '+00:00' if '.' in time_str else time_str.replace('Z', '+00:00')
                last_updated = datetime.datetime.fromisoformat(time_str)
                now = datetime.datetime.now(datetime.timezone.utc)

                if row.get('summary') and (now - last_updated).total_seconds() < 3600:
                    if "요약 중입니다" not in row['summary']:
                        should_update_ai = False
                        saved_ai_summary = row['summary']
                        saved_wiki_content = row.get('wiki_content', '')
                        print(f"✅ [{keyword}] 기존 캐시 사용", flush=True)

        if should_update_ai:
            needs_ai_keywords.append(keyword)
            saved_wiki_content = get_wiki_summary(keyword)

        trend_data_list.append({
            "rank": item['rank'],
            "title": keyword,
            "volume": item['volume'],
            "summary": saved_ai_summary,
            "wiki_content": saved_wiki_content,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        })

    if needs_ai_keywords:
        print(f"\n⚡ [A봇] AI 팩트체크 요약 중... ({len(needs_ai_keywords)}개)", flush=True)
        batch_summaries = get_batch_ai_summaries(needs_ai_keywords)

        for t_data in trend_data_list:
            if t_data['title'] in batch_summaries:
                t_data['summary'] = batch_summaries[t_data['title']]
                print(f"▶ [{t_data['title']}] 요약 장착 완료!", flush=True)

    print("\n💾 [A봇] 수파베이스 저장 중...", flush=True)
    for t_data in trend_data_list:
        keyword = t_data['title']
        existing_data = supabase.table("google_trends").select("*").eq("title", keyword).execute()
        if existing_data.data:
            supabase.table("google_trends").update(t_data).eq("title", keyword).execute()
        else:
            supabase.table("google_trends").insert(t_data).execute()

    print("\n🎉 [A봇] 업데이트 완료!", flush=True)

if __name__ == "__main__":
    process_trends()
