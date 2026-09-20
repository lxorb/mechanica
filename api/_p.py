import sys, time
from app.registry._http import client, request, UA, BROWSER_UA, GOOGLEBOT_UA
UAS={"d":UA,"b":BROWSER_UA,"g":GOOGLEBOT_UA}
def probe(url, ua="d"):
    try:
        with client(ua=UAS[ua]) as c:
            r=request(c,"GET",url,headers={"Range":"bytes=0-511","Accept-Encoding":"identity"})
    except Exception as e:
        return f"ERR {type(e).__name__}"
    if r is None: return "UNREACHABLE"
    ct=(r.headers.get("content-type") or "?").split(";")[0]
    magic = r.content[:5]
    return f"{r.status_code} {ct} len={r.headers.get('content-length','?')} {magic!r} -> {str(r.url)[:110]}"
if __name__=="__main__":
    for u in sys.argv[1:]:
        ua="d"
        if u.startswith("b:"): ua,u="b",u[2:]
        if u.startswith("g:"): ua,u="g",u[2:]
        print(f"{probe(u,ua)}\n    {u[:130]}")
        time.sleep(0.5)
