import json, os, time, urllib.request, urllib.error, sys
base = 'http://127.0.0.1:8000'
info_path = os.path.join(os.environ.get('LOCALAPPDATA',''), 'TitanScraper', 'last_server.json')
try:
    with open(info_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        base = f"http://{data.get('host','127.0.0.1')}:{data.get('port',8000)}"
except Exception:
    pass

def get_json(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            ct = r.read()
            return json.loads(ct.decode('utf-8'))
    except Exception as e:
        return {'error': str(e)}

print('Base=', base)
print('Health=', json.dumps(get_json(base + '/health'), ensure_ascii=False))
print('Posts=', json.dumps(get_json(base + '/api/posts?limit=5'), ensure_ascii=False))
