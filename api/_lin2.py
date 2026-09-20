import re, json
from app.registry._http import client, get_text
PAIR = re.compile(r"owner-manuals-details/([a-z0-9][a-z0-9-]*)/((?:19|20)\d{2})")
with client() as c:
    h = get_text(c, "https://www.ford.com/support/owner-manuals-details/owner-manuals-library")
models = sorted({m.group(1) for m in PAIR.finditer(h)})
print("ford library models:", len(models))
print(models)
lincolnish = [m for m in models if m in ("navigator","aviator","continental","corsair","nautilus","mkz","mkx","mkc","mks","mkt","town-car","zephyr","ls","blackwood","mark-lt")]
print("lincoln nameplates present:", lincolnish)
with client() as c:
    l = get_text(c, "https://www.lincoln.com/owner-manuals/")
print("lincoln page len", len(l or ""))
for pat in (r"owner-manuals-details/[a-z0-9-]+/\d{4}", r"\.pdf", r"ownerManual", r"vdirsnet", r"Variantid"):
    print(" ", pat, len(re.findall(pat, l or "", re.I)))
for m in list(re.finditer(r"owner-?manual", l or "", re.I))[:6]:
    print("   ...", (l[max(0,m.start()-160):m.start()+160]).replace("\n"," ")[:320])
