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

def get_player_tokens(embed_url):
    """Парсит динамические токены из iframe плеера"""
    try:
        if embed_url.startswith('//'):
            embed_url = 'https:' + embed_url
        res = requests.get(embed_url, headers=HEADERS, timeout=5)
        
        token_match = re.search(r'([a-f0-9]{32}:\d{10})', res.text)
        path_match = re.search(r'tvseries/([a-f0-9]{40})', res.text)
        movie_match = re.search(r'vod/([a-f0-9]{40})', res.text) # Для фильмов
        
        token = token_match.group(1) if token_match else "default_token"
        
        if path_match:
            return token, f"tvseries/{path_match.group(1)}"
        elif movie_match:
            return token, f"vod/{movie_match.group(1)}"
        return token, None
    except:
        return None, None

@app.route('/')
@app.route('/tv')
@app.route('/index.html')
def main_menu():
    """Главное меню с поиском и категориями"""
    base_url = request.host_url.rstrip('/')
    
    msx_json = {
        "name": "Мой Кинотеатр Kinogo",
        "type": "list",
        "items": [
            {
                "title": "🔍 Искать фильм или сериал",
                "input": f"{base_url}/search?query={{input}}",
                "icon": "https://lh1.in"
            },
            {
                "title": "🔥 Новинки на главной",
                "playlist": f"{base_url}/page/1"
            }
        ]
    }
    return jsonify(msx_json)

@app.route('/search')
@app.route('/page/<int:page_num>')
def list_movies(page_num=1):
    """Выводит список фильмов (с главной страницы или из поиска)"""
    base_url = request.host_url.rstrip('/')
    query = request.args.get('query')
    
    if query:
        # Если это поиск, делаем POST запрос к поисковому движку Kinogo
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
        # Если это главная, просто загружаем нужную страницу
        url = f"{HOST}/page/{page_num}/" if page_num > 1 else HOST
        response = requests.get(url, headers=HEADERS, timeout=10)
        
    soup = BeautifulSoup(response.text, 'html.parser')
    # Находим все блоки с фильмами (на Kinogo они обычно имеют класс shortstory или аналогичный)
    items = soup.find_all('div', class_='shortstory') or soup.find_all('div', class_='zagolovki')
    
    msx_json = {
        "name": f"Поиск: {query}" if query else f"Страница {page_num}",
        "items": []
    }
    
    for item in items:
        link_tag = item.find('a')
        img_tag = item.find('img')
        
        if link_tag and img_tag:
            title = img_tag.get('alt') or link_tag.text.strip()
            movie_url = link_tag['href']
            img_url = HOST + img_tag['src'] if img_tag['src'].startswith('/') else img_tag['src']
            
            # Кодируем URL фильма, чтобы безопасно передать его через роуты Flask
            encoded_url = urllib.parse.quote_plus(movie_url)
            
            msx_json["items"].append({
                "title": title,
                "icon": img_url,
                "playlist": f"{base_url}/movie?url={encoded_url}"
            })
            
    # Добавляем кнопку "Дальше", если страниц много
    next_page = page_num + 1
    next_url = f"{base_url}/search?query={query}&page={next_page}" if query else f"{base_url}/page/{next_page}"
    msx_json["items"].append({
        "title": "➡️ Следующая страница",
        "playlist": next_url
    })
    
    return jsonify(msx_json)

@app.route('/movie')
def movie_detail():
    """Анализирует страницу фильма: определяет сериал это или одиночный фильм"""
    base_url = request.host_url.rstrip('/')
    movie_url = urllib.parse.unquote_plus(request.args.get('url'))
    
    res = requests.get(movie_url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    # Ищем плеер
    iframe = soup.find('iframe', src=re.compile(r'cinemap|host|play'))
    if not iframe:
        match = re.search(r'src="([^"]+cinemap\.cc[^"]+)"', res.text)
        iframe_url = match.group(1) if match else None
    else:
        iframe_url = iframe['src']
        
    if not iframe_url:
        return jsonify({"name": "Ошибка", "items": [{"title": "Плеер не найден"}]})

    token, video_path = get_player_tokens(iframe_url)
    if not video_path:
        return jsonify({"name": "Ошибка", "items": [{"title": "Не удалось распознать видеопоток"}]})

    encoded_path = urllib.parse.quote_plus(video_path)
    
    # ПРОВЕРКА: Сериал или фильм?
    # Если в путях плеера или на странице есть упоминание сезонов/серий
    is_creative_series = "tvseries" in video_path or "season" in res.text.lower() or "серия" in res.text.lower()
    
    msx_json = {"name": "Выбор контента", "items": []}
    
    if is_creative_series:
        # Для простоты создаем универсальное меню сезонов (например, до 4 сезонов по 20 серий)
        # В идеале нужно парсить точное число из фрейма, но для личного использования можно сделать сетку:
        for s in range(1, 5): 
            msx_json["items"].append({
                "title": f"Сезон {s}",
                "playlist": f"{base_url}/series-episodes?path={encoded_path}&token={token}&season={s}"
            })
    else:
        # Если это фильм — сразу отдаем меню выбора качества
        msx_json["items"] = [
            {"title": "Смотреть фильм 1080p", "video": f"https://cinemap.cc{token}/{video_path}/1080.mp4"},
            {"title": "Смотреть фильм 720p", "video": f"https://cinemap.cc{token}/{video_path}/720.mp4"},
            {"title": "Смотреть фильм 480p", "video": f"https://cinemap.cc{token}/{video_path}/480.mp4"}
        ]
        
    return jsonify(msx_json)

@app.route('/series-episodes')
def series_episodes():
    """Выводит список серий для выбранного сезона сериала"""
    path = urllib.parse.unquote_plus(request.args.get('path'))
    token = request.args.get('token')
    season = request.args.get('season')
    
    msx_json = {"name": f"Сезон {season}", "items": []}
    # Выводим стандартную сетку на 24 серии (если серии нет, плеер просто сообщит об этом при клике)
    for ep in range(1, 25):
        msx_json["items"].append({
            "title": f"Серия {ep}",
            "playlist": f"https://cinemap.cc{token}/{path}/...ВыборКачества" # Сюда подставляется логика качества плеера
        })
    return jsonify(msx_json)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
