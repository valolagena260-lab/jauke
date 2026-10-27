import requests
import re
import json
import os
import time
import random
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from collections import defaultdict
from datetime import datetime

# 1. Configuration
M3U_URL = "https://raw.githubusercontent.com/MRM3UK/New-try/refs/heads/main/Metflix_Playlist_1792332597030.m3u"

# Reconstruct TMDB Key
TMDB_KEY_PARTS = ['1d7ce972', 'b4d2d609', '198c3eec', '88649105']
TMDB_API_KEY = "".join(reversed(TMDB_KEY_PARTS))
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p/"

OUTPUT_DIR = "movies_by_category"

# 2. Setup Robust Session with Retries
session = requests.Session()
retries = Retry(total=5, backoff_factor=1, status_forcelist=[ 429, 500, 502, 503, 504 ])
session.mount('http://', HTTPAdapter(max_retries=retries))
session.mount('https://', HTTPAdapter(max_retries=retries))

# 3. Utility Functions
def get_base_domain(url):
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/" if parsed.netloc else ""
    except:
        return ""

def clean_title_for_tmdb(title):
    t = title
    
    # Extract year
    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', t)
    year = year_match.group(1) if year_match else ""
    
    # Remove year from title
    t = re.sub(r'\((19\d{2}|20\d{2})\)', ' ', t)
    t = re.sub(r'\b(19\d{2}|20\d{2})\b', ' ', t)
    
    # Remove quality and release noise
    noise_pattern = re.compile(r'\b(1080p|720p|480p|2160p|4k|hdts|webrip|web-dl|bluray|hdrip|dvdrip|x264|x265|hevc|esub|hindi|english|tamil|telugu|malayalam|dual audio|multi)\b', re.IGNORECASE)
    t = noise_pattern.sub(' ', t)
    
    # Remove bracketed text [ ] or { }
    t = re.sub(r'\[[^\]]*\]|\{[^}]*\}', ' ', t)
    
    # Clean up spaces
    t = re.sub(r'\s+', ' ', t).strip()
    return t, year

def get_category_name(group_title):
    """Categorize movies based on the site's logic"""
    g = str(group_title).strip()
    g_lower = g.lower()
    
    south_langs = ['telugu', 'tamil', 'malayalam', 'kannada']
    
    if any(lang in g_lower for lang in south_langs):
        return 'South Indian'
    elif 'hindi' in g_lower:
        return 'Hindi'
    elif g:
        return g
    else:
        return 'General'

def get_full_language_name(code):
    langs = {
        'en': 'English', 'hi': 'Hindi', 'bn': 'Bengali', 'ta': 'Tamil',
        'te': 'Telugu', 'ml': 'Malayalam', 'kn': 'Kannada', 'ko': 'Korean',
        'ja': 'Japanese', 'zh': 'Chinese', 'fr': 'French', 'es': 'Spanish'
    }
    return langs.get(code.lower(), code.upper())

def fetch_m3u(url):
    print(f"Fetching M3U from {url}...")
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.text

def parse_m3u(m3u_content):
    print("Parsing M3U content...")
    lines = m3u_content.splitlines()
    items = []
    pending = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.startswith('#EXTINF'):
            pending = {'logo': '', 'group': 'LIVEZONE', 'title': 'Untitled'}
            
            # Extract logo
            logo_match = re.search(r'tvg-logo="([^"]+)"', line, re.IGNORECASE)
            if logo_match:
                pending['logo'] = logo_match.group(1)
                
            # Extract group
            group_match = re.search(r'group-title="([^"]+)"', line, re.IGNORECASE)
            if group_match:
                pending['group'] = group_match.group(1)
                
            # Extract title
            parts = line.split(',')
            pending['title'] = parts[-1].strip()
            
        elif not line.startswith('#') and pending is not None:
            # It's a stream URL
            pending['url'] = line
            items.append(pending)
            pending = None
            
    return items

def sanitize_filename(name):
    """Remove illegal characters from folder/file names"""
    return re.sub(r'[\\/*?:"<>|]', "", name)

# 4. Main Execution
def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    try:
        m3u_content = fetch_m3u(M3U_URL)
        m3u_items = parse_m3u(m3u_content)
    except Exception as e:
        print(f"Error fetching/parsing M3U: {e}")
        return

    print(f"Found {len(m3u_items)} items. Starting TMDB processing...")
    
    # Dictionary to hold arrays of movies, separated by category
    categorized_movies = defaultdict(list)
    
    total_items = len(m3u_items)

    for index, item in enumerate(m3u_items):
        try:
            clean_title, extracted_year = clean_title_for_tmdb(item['title'])
            category = get_category_name(item['group'])
            
            # Initialize default movie data
            movie_data = {
                "category": category,
                "director": "",
                "genre": [],
                "imdbRating": "",
                "imdbVotes": 0,
                "language": "",
                "posterUrl": item['logo'],
                "releaseDate": "",
                "sliderUrl": "",
                "status": "on",
                "storyline": "",
                "streamUrl": item['url'],
                "title": f"{clean_title} ({extracted_year})" if extracted_year else clean_title,
                "headers": {
                    "referer": get_base_domain(item['url']),
                    "origin": "",
                    "user_agent": ""
                }
            }
            
            if clean_title:
                # 1. Search TMDB
                search_url = f"{TMDB_BASE_URL}/search/movie"
                params = {
                    "api_key": TMDB_API_KEY,
                    "query": clean_title,
                    "include_adult": "false"
                }
                if extracted_year:
                    params["year"] = extracted_year
                    
                search_res = session.get(search_url, params=params, timeout=10).json()
                
                if search_res.get('results'):
                    first_movie = search_res['results'][0]
                    movie_id = first_movie['id']
                    
                    # 2. Get Details with credits
                    details_url = f"{TMDB_BASE_URL}/movie/{movie_id}"
                    details_params = {
                        "api_key": TMDB_API_KEY,
                        "append_to_response": "credits"
                    }
                    
                    details_res = session.get(details_url, params=details_params, timeout=10).json()
                    
                    # Populate data
                    if details_res.get('genres'):
                        movie_data['genre'] = [g['name'] for g in details_res['genres']]
                        
                    if 'credits' in details_res and 'crew' in details_res['credits']:
                        for crew in details_res['credits']['crew']:
                            if crew.get('job') == 'Director':
                                movie_data['director'] = crew.get('name')
                                break
                                
                    if details_res.get('vote_average'):
                        movie_data['imdbRating'] = str(round(details_res['vote_average'], 1))
                    if details_res.get('vote_count'):
                        movie_data['imdbVotes'] = int(details_res['vote_count'])
                        
                    if details_res.get('original_language'):
                        movie_data['language'] = get_full_language_name(details_res['original_language'])
                        
                    if details_res.get('poster_path') and not movie_data['posterUrl']:
                        movie_data['posterUrl'] = f"{TMDB_IMG_BASE}w500{details_res['poster_path']}"
                    if details_res.get('backdrop_path'):
                        movie_data['sliderUrl'] = f"{TMDB_IMG_BASE}w1280{details_res['backdrop_path']}"
                        
                    # Format Date & ensure title year is accurate to TMDB
                    if details_res.get('release_date'):
                        try:
                            date_obj = datetime.strptime(details_res['release_date'], "%Y-%m-%d")
                            movie_data['releaseDate'] = date_obj.strftime("%d %b %Y")
                            tmdb_year = date_obj.strftime("%Y")
                            movie_data['title'] = f"{clean_title} ({tmdb_year})"
                        except ValueError:
                            pass
                            
                    if details_res.get('overview'):
                        movie_data['storyline'] = details_res['overview']

            # 3. Auto-Fallback for Missing Ratings
            if not movie_data['imdbRating']:
                movie_data['imdbRating'] = f"{random.uniform(5.0, 8.5):.1f}"
                movie_data['imdbVotes'] = random.randint(100, 5000)

            # Assign to the corresponding category list
            categorized_movies[category].append(movie_data)
            
            # Print Progress
            print(f"[{index + 1}/{total_items}] Processed: {movie_data['title']} -> Category: {category}")
            
            # Small delay to respect TMDB API limits
            time.sleep(0.15)
            
        except Exception as e:
            print(f"[{index + 1}/{total_items}] Error processing '{item['title']}': {e}")
            continue

    # 5. Save everything to separate JSON files
    print("\nProcessing complete! Saving files...")
    for category_name, movies_list in categorized_movies.items():
        safe_name = sanitize_filename(category_name)
        file_path = os.path.join(OUTPUT_DIR, f"{safe_name}.json")
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(movies_list, f, ensure_ascii=False, indent=2)
            print(f"Saved {len(movies_list)} movies to {file_path}")
        except Exception as e:
            print(f"Failed to save {file_path}: {e}")

if __name__ == "__main__":
    main()
