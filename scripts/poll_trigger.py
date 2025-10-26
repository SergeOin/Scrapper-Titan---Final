import json, os, time, urllib.request
base = 'http://127.0.0.1:8000'
info_path = os.path.join(os.environ.get('LOCALAPPDATA',''), 'TitanScraper', 'last_server.json')
try:
    with open(info_path,'r',encoding='utf-8') as f:
        d=json.load(f); base=f"http://{d.get('host','127.0.0.1')}:{d.get('port',8000)}"
except Exception:
    pass

def get_json(path):
    try:
        with urllib.request.urlopen(base+path, timeout=8) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        return {'error': str(e)}

def post(path, data=None):
    try:
        if data is None:
            data=b''
        elif isinstance(data,dict):
            data = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(base+path, data=data, method='POST')
        req.add_header('Content-Type','application/x-www-form-urlencoded')
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except Exception as e:
        return str(e)

h0 = get_json('/health')
print('Before:', json.dumps(h0, ensure_ascii=False))
print('Trigger status:', post('/trigger'))
last0 = h0.get('last_run') if isinstance(h0, dict) else None
start=time.time()
changed=False
while time.time()-start < 180:
    time.sleep(10)
    h=get_json('/health')
    lr=h.get('last_run') if isinstance(h, dict) else None
    pc=h.get('posts_count') if isinstance(h, dict) else None
    print('Health:', json.dumps({'last_run':lr,'posts_count':pc,'active':h.get('autonomous_worker_active')}, ensure_ascii=False))
    if lr and lr!=last0:
        changed=True
        break
print('Changed:', changed)
print('Posts:', json.dumps(get_json('/api/posts?limit=5'), ensure_ascii=False))
