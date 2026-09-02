import re
import urllib.parse
from flask import Flask, jsonify, request
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

HOST = "https://kinogo.ec"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": HOST + "/"
}

# ==============================================================================
# 1. СТАРТОВЫЙ БЛОК: СТРОГИЙ СТАНДАРТ MSX (МЕНЮ СЛЕВА РАБОТАЕТ ИДЕАЛЬНО)
# ==============================================================================

@app.route('/')
@app.route('/msx/start.json')
def msx_system_handshake():
    """Служебный старт. Направляет ТВ на оригинальный рабочий файл меню."""
    base_url = request.host_url.rstrip('/')
    return jsonify({
        "name": "Мой Кинотеатр",
        "version": "1.0.0",
        "icon": "https://lh1.in",
        "parameter": f"menu:{base_url}/main_menu" 
    })

@app.route('/main_menu')
def msx_display_main_menu():
    """Корневое меню приложения (успешно отображает левую панель)."""
    base_url = request.host_url.rstrip('/')
    return jsonify({
        "headline": "Кинотеатр Kinogo",
        "menu": [
            {
                "label": "🔍 Искать фильм или сериал",
                "icon": "search",
                "data": f"{base_url}/search_page"
            },
            {
                "label": "🔥 Новинки на главной",
                "icon": "rss-feed",
                "data": f"{base_url}/page/1"
            }
        ]
    })

# ==============================================================================
# 2. ИСПРАВЛЕННЫЙ БЛОК КОНТЕНТА (ЗАМЕНА PLAYLIST НА DATA ДЛЯ ФОКУСА ПУЛЬТА)
# ==============================================================================

@app.route('/search_page')
def msx_search_page():
    """Экран ввода, который активирует клавиатуру поиска на телевизоре."""
    base_url = request.host_url.rstrip('/')
    return jsonify({
        "pages": [{
            "headline": "Поиск по сайту",
            "items": [
                {
                    "title": "Нажмите ОК для ввода названия",
                    "input": f"{base_url}/search?query={{input}}",
                    "icon": "https://lh1.in"
                }
            ]
        }]
    })

@app.route('/search')
@app.route('/page/<int:page_num>')
def list_movies(page_num=1):
    """Выводит сетку фильмов. Замена 'playlist' на 'data' активирует пульт."""
    base_url = request.host_url.rstrip('/')
    query = request.args.get('query')
    
    if query:
        search_url = f"{HOST}/index.php?do=search"
        data = {
            "do": "search",
            "subaction": "search",
            "search_start": page_num,
            "full_search": 0,
            "story": query
        }
        response = requests.post(search_url, headers=HEADERS, data=data, timeout=10)
    else:
        url = f"{HOST}/page/{page_num}/" if page_num > 1 else HOST
        response = requests.get(url, headers=HEADERS, timeout=10)
        
    soup = BeautifulSoup(response.text, 'html.parser')
    items = soup.find_all('div', class_='shortstory') or soup.find_all('div', class_='zagolovki')
    
    movie_items = []
    
    for item in items:
        link_tag = item.find('a')
        img_tag = item.find('img')
        if link_tag and img_tag:
            title = img_tag.get('alt') or link_tag.text.strip()
            movie_url = link_tag['href']
            img_url = HOST + img_tag['src'] if img_tag['src'].startswith('/') else img_tag['src']
            encoded_url = urllib.parse.quote_plus(movie_url)
            
            movie_items.append({
                "title": title,
                "icon": img_url,
                # Использование 'data' вместо 'playlist' делает карточку кликабельной!
                "data": f"{base_url}/movie?url={encoded_url}"
            })
            
    # Кнопка перехода на следующую страницу
    next_page = page_num + 1
    next_url = f"{base_url}/search?query={query}&page={next_page}" if query else f"{base_url}/page/{next_page}"
    movie_items.append({
        "title": "➡️ Следующая страница",
        "data": next_url
    })
    
    return jsonify({
        "pages": [{
            "headline": f"Поиск: {query}" if query else f"Страница {page_num}",
            "items": movie_items
        }]
    })

# ==============================================================================
# 3. БЛОК ОПРЕДЕЛЕНИЯ ФИЛЬМА / СЕРИАЛА И ПЛЕЕРА
# ==============================================================================

def get_player_tokens(embed_url):
    try:
        if embed_url.startswith('//'):
            embed_url = 'https:' + embed_url
        res = requests.get(embed_url, headers=HEADERS, timeout=5)
        
        token_match = re.search(r'([a-f0-9]{32}:\d{10})', res.text)
        path_match = re.search(r'tvseries/([a-f0-9]{40})', res.text)
        movie_match = re.search(r'vod/([a-f0-9]{40})', res.text)
        
        token = token_match.group(1) if token_match else "default_token"
        if path_match:
            return token, f"tvseries/{path_match.group(1)}"
        elif movie_match:
            return token, f"vod/{movie_match.group(1)}"
        return token, None
    except:
        return None, None

@app.route('/movie')
def movie_detail():
    base_url = request.host_url.rstrip('/')
    movie_url = urllib.parse.unquote_plus(request.args.get('url'))
    
    res = requests.get(movie_url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    iframe = soup.find('iframe', src=re.compile(r'cinemap|host|play'))
    if not iframe:
        match = re.search(r'src="([^"]+cinemap\.cc[^"]+)"', res.text)
        iframe_url = match.group(1) if match else None
    else:
        iframe_url = iframe['src']
        
    if not iframe_url:
        return jsonify({"pages": [{"headline": "Ошибка", "items": [{"title": "Плеер не найден"}]}]})

    token, video_path = get_player_tokens(iframe_url)
    if not video_path:
        return jsonify({"pages": [{"headline": "Ошибка", "items": [{"title": "Не удалось распознать поток"}]}]})

    is_creative_series = "tvseries" in video_path or "season" in res.text.lower() or "серия" in res.text.lower()
    
    # Для внутренних страниц контента (выбор серий/качества) тоже возвращаем формат pages
    movie_menu = []
    
    if is_creative_series:
        for s in range(1, 5): 
            movie_menu.append({
                "title": f"Сезон {s}",
                "data": f"{base_url}/series-episodes?path={urllib.parse.quote_plus(video_path)}&token={token}&season={s}"
            })
    else:
        movie_menu = [
            {"title": "Смотреть в 1080p", "video": f"https://cinemap.cc{token}/{video_path}/1080.mp4"},
            {"title": "Смотреть в 720p", "video": f"https://cinemap.cc{token}/{video_path}/720.mp4"},
            {"title": "Смотреть в 480p", "video": f"https://cinemap.cc{token}/{video_path}/480.mp4"}
        ]
    return jsonify({
        "pages": [{
            "headline": "Выбор качества / Сезона",
            "items": movie_menu
        }]
    })

@app.route('/series-episodes')
def series_episodes():
    path = urllib.parse.unquote_plus(request.args.get('path'))
    token = request.args.get('token')
    season = request.args.get('season')
    
    episodes_menu = []
    for ep in range(1, 25):
        episodes_menu.append({
            "title": f"Серия {ep}",
            "video": f"https://cinemap.cc{token}/{path}/...ВыборКачества"
        })
        
    return jsonify({
        "pages": [{
            "headline": f"Сезон {season}",
            "items": episodes_menu
        }]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
