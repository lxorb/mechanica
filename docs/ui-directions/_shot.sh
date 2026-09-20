# usage: bash _shot.sh <name-without-ext> [w] [h]
D="C:/Users/me/trustthemanual/docs/ui-directions"
N="$1"; W="${2:-1740}"; H="${3:-2400}"
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless=new --disable-gpu --hide-scrollbars \
 --force-device-scale-factor=1 --virtual-time-budget=9000 --allow-file-access-from-files \
 --screenshot="$D/shots/$N.png" --window-size=$W,$H "file:///$D/$N.html" 2>&1 | tail -1
