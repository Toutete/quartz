import urllib.request
import re

req = urllib.request.Request('https://html.duckduckgo.com/html/?q=ando+aq6317+python+read+trace+wdata', headers={'User-Agent': 'Mozilla/5.0'})
try:
    html = urllib.request.urlopen(req).read().decode('utf-8')
    snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
    for s in snippets[:10]:
        print(s)
except Exception as e:
    print(e)
