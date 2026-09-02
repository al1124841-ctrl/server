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
# 1. СИСТЕМНЫЙ БЛОК АВТОРИЗАЦИИ И МЕНЮ (СТАНДАРТ MSX API)
# ==============================================================================

@app.route('/')
@app.route('/msx/start.json')
def msx_system_handshake():
    """Служебный старт. Авторизует ТВ и направляет его на корневое меню."""
    base_url = request.host_url.rstrip('/')
    return jsonify({
        "name": "Мой Кинотеатр",
        "version": "1.0.0",
        "icon": "https://lh1.in",
        "parameter": f"menu:{base_url}/main_menu"  # Вызываем тип 'menu'
    })

@app.route('/main_menu')
@app.route('/tv_menu')
@app.route('/tv_playlist')
def msx_display_main_menu():
    """
    Корневое меню приложения. Использует свойство 'data'
    для полной совместимости с плеером Samsung Smart TV.
    """
    base_url = request.host_url.rstrip('/')
    return jsonify({
        "name": "Кинотеатр Kinogo",
        "type": "menu",  # Задаем системный тип меню
        "items": [
            {
                "title": "🔍 Искать фильм или сериал",
                "icon": "https://lh1.in",
                "data": f"{base_url}/search_page"  # Ведет на страницу ввода текста
            },
            {
                "title": "🔥 Новинки на главной",
                "icon": "https://lh1.in",
                "data": f"{base_url}/page/1"  # Ведет на список новинок
            }
        ]
    })

@app.route('/search_page')
def msx_search_page():
    """Промежуточный экран, который активирует клавиатуру ввода на ТВ."""
    base_url = request.host_url.rstrip('/')
    return jsonify({
        "type": "list",
        "items": [
            {
                "title": "Нажмите ОК для ввода названия",
                "input": f"{base_url}/search?query={{input}}",
                "icon": "https://lh1.in"
            }
        ]
    })

# ==============================================================================
# 2. БЛОК ПАРСИНГА САЙТА KINOGO (КАТАЛОГ И ПОИСК)
# ==============================================================================

def get_player_tokens(embed_url):
    """Вытаскивает динамические токены времени и пути из плеера cinemap."""
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

@app.route('/search')
@app.route('/page/<int:page_num>')
def list_movies(page_num=1):
    """Выводит сетку фильмов (с главной страницы или результатов поиска)."""
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
    
    msx_json = {
        "name": f"Поиск: {query}" if query else f"Страница {page_num}",
        "type": "list",
        "items": []
    }
    
    for item in items:
        link_tag = item.find('a')
        img_tag = item.find('img')
        if link_tag and img_tag:
            title = img_tag.get('alt') or link_tag.text.strip()
            movie_url = link_tag['href']
            img_url = HOST + img_tag['src'] if img_tag['src'].startswith('/') else img_tag['src']
            encoded_url = urllib.parse.quote_plus(movie_url)
            
            msx_json["items"].append({
                "title": title,
                "icon": img_url,
                "playlist": f"{base_url}/movie?url={encoded_url}"
            })
            
    # Кнопка перехода на следующую страницу контента
    next_page = page_num + 1
    next_url = f"{base_url}/search?query={query}&page={next_page}" if query else f"{base_url}/page/{next_page}"
    msx_json["items"].append({
        "title": "➡️ Следующая страница",
        "playlist": next_url
    })
    return jsonify(msx_json)

@app.route('/movie')
def movie_detail():
    """Определяет тип контента (фильм/сериал) и генерирует ссылки на видео."""
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
        return jsonify({"name": "Ошибка", "type": "list", "items": [{"title": "Плеер не найден"}]})

    token, video_path = get_player_tokens(iframe_url)
    if not video_path:
        return jsonify({"name": "Ошибка", "type": "list", "items": [{"title": "Не удалось распознать поток"}]})

    is_creative_series = "tvseries" in video_path or "season" in res.text.lower() or "серия" in res.text.lower()
    msx_json = {"name": "Выбор контента", "type": "list", "items": []}
    
    if is_creative_series:
        # Если сериал — строим сетку из 4 сезонов (универсальный шаблон)
        for s in range(1, 5): 
            msx_json["items"].append({
                "title": f"Сезон {s}",
                "playlist": f"{base_url}/series-episodes?path={urllib.parse.quote_plus(video_path)}&token={token}&season={s}"
            })
    else:
        # Если фильм — выводим доступные качества видеофайла
        msx_json["items"] = [
            {"title": "Смотреть в 1080p", "video": f"https://cinemap.cc{token}/{video_path}/1080.mp4"},
            {"title": "Смотреть в 720p", "video": f"https://cinemap.cc{token}/{video_path}/720.mp4"},
            {"title": "Смотреть в 480p", "video": f"https://cinemap.cc{token}/{video_path}/480.mp4"}
        ]
    return jsonify(msx_json)

@app.route('/series-episodes')
def series_episodes():
    """Выводит список серий для выбранного сезона сериала."""
    path = urllib.parse.unquote_plus(request.args.get('path'))
    token = request.args.get('token')
    season = request.args.get('season')
    
    msx_json = {"name": f"Сезон {season}", "type": "list", "items": []}
    # Генерируем стандартный список на 24 серии
    for ep in range(1, 25):
        msx_json["items"].append({
            "title": f"Серия {ep}",
            "playlist": f"https://cinemap.cc{token}/{path}/...ВыборКачества"
        })
    return jsonify(msx_json)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
