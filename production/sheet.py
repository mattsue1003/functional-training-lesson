import json, re, subprocess, sys
from PIL import Image
# 用法：python3 sheet.py [秒 ...]；不給秒數就取每個場景的 1/3 與結尾前
T = json.loads(re.search(r'window.TIMING = (.*?);\n', open('timing.js').read()).group(1))
ts = sys.argv[1:] or [f'{t["start"] + (t["end"] - t["start"]) * f:.2f}' for t in T for f in (.35, .92)]
subprocess.run(['node', 'render.js', 'still', *ts], check=True)
ims = [Image.open(f'build/still_{t}.png').convert('RGB').resize((640, 360)) for t in ts]
cols = 4; rows = (len(ims) + cols - 1) // cols
sh = Image.new('RGB', (cols * 644, rows * 364), (30, 30, 30))
for i, im in enumerate(ims): sh.paste(im, ((i % cols) * 644, (i // cols) * 364))
sh.save('build/sheet.png'); print(sh.size, len(ims))
