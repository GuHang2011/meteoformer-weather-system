"""Download self-hosted Noto Sans SC subsets for the visible workspace copy."""
from pathlib import Path
import re
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / 'frontend' if (ROOT / 'frontend').is_dir() else ROOT / 'upload/CropDiseasesDetection_vue'
OUT = FRONT / 'src/weather/fonts'
OUT.mkdir(parents=True, exist_ok=True)
text = ''.join(p.read_text('utf-8') for p in (FRONT / 'src/weather').glob('*') if p.suffix in ('.vue', '.ts'))
text += (FRONT / 'demo-public/demo/snapshot.json').read_text('utf-8')
characters = ''.join(sorted(set(chr(c) for c in range(32, 127)) | {c for c in text if '\u4e00' <= c <= '\u9fff'} | set('°≥≤→↗×—–·…％℃')))
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'}
for weight, name in [(400, 'regular'), (600, 'semibold')]:
    params = urllib.parse.urlencode({'family': f'Noto Sans SC:wght@{weight}', 'display': 'swap', 'text': characters})
    request = urllib.request.Request('https://fonts.googleapis.com/css2?' + params, headers=headers)
    css = urllib.request.urlopen(request, timeout=45).read().decode('utf-8')
    urls = re.findall(r'url\((https://[^)]+)\)', css)
    if len(urls) != 1:
        raise RuntimeError('Expected one text subset per font weight')
    data = urllib.request.urlopen(urls[0], timeout=45).read()
    if data[:4] != b'wOF2':
        raise RuntimeError(f'Expected WOFF2 font; received {data[:4]!r}; css={css[:300]}')
    (OUT / f'meteo-sans-{name}.woff2').write_bytes(data)
    print(f'{name}: {len(data):,} bytes, {len(characters)} characters')
license_url = 'https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/OFL.txt'
license_text = urllib.request.urlopen(license_url, timeout=45).read().decode('utf-8')
(OUT / 'OFL.txt').write_text('\n'.join(line.rstrip() for line in license_text.splitlines()) + '\n', encoding='utf-8')
(OUT / 'README.md').write_text('''# Workspace typeface

Noto Sans SC, by the Noto Project, licensed under SIL Open Font License 1.1.
Source: https://fonts.google.com/noto/specimen/Noto+Sans+SC
License: OFL.txt in this directory.

The regular (400) and semibold (600) WOFF2 files are subsets served by Google
Fonts for the workspace text and demo dataset. They are shipped locally;
the application makes no runtime requests to Google Fonts. Characters outside
the subset use the system Chinese font. Rerun scripts/prepare-ui-fonts.py in
the development workspace after adding substantial interface copy.
''', encoding='utf-8')
