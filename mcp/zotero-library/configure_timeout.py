"""Set only this MCP's timeouts after registration by the official Codex CLI."""
from datetime import datetime
import os
from pathlib import Path
import re
import tomllib

root=Path(__file__).resolve().parent
config=Path.home()/'.codex'/'config.toml'
original=config.read_bytes()
text=original.decode('utf-8-sig')
parsed=tomllib.loads(text)
server=parsed.get('mcp_servers',{}).get('zotero-library')
if not server or Path(server.get('command','')).resolve()!= (root/'.venv'/'Scripts'/'python.exe').resolve():
    raise SystemExit('Refusing to edit a missing or unrelated MCP entry.')
if str(root/'server.py') not in server.get('args',[]):
    raise SystemExit('Unexpected MCP arguments; configuration unchanged.')
pattern=r'(?ms)^\[mcp_servers\.zotero-library\][ \t]*\r?\n(.*?)(?=^\[|\Z)'
match=re.search(pattern,text)
if not match: raise SystemExit('MCP stanza not found.')
body=match.group(1)
for name,value in [('startup_timeout_sec',20),('tool_timeout_sec',180)]:
    setting=rf'(?m)^{name}\s*=.*$'
    if re.search(setting,body):body=re.sub(setting,f'{name} = {value}',body)
    else:body=body.rstrip()+f'\n{name} = {value}\n\n'
updated=text[:match.start(1)]+body+text[match.end(1):]
after=tomllib.loads(updated)
before_other={k:v for k,v in parsed['mcp_servers'].items() if k!='zotero-library'}
after_other={k:v for k,v in after['mcp_servers'].items() if k!='zotero-library'}
assert before_other==after_other
assert {k:v for k,v in parsed.items() if k!='mcp_servers'}=={k:v for k,v in after.items() if k!='mcp_servers'}
if updated!=text:
    backup=config.with_name('config.toml.zotero-library-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.bak')
    backup.write_bytes(original)
    temp=config.with_name('config.toml.zotero-library.tmp')
    temp.write_text(updated,encoding='utf-8')
    os.replace(temp,config)
print('zotero-library: startup 20s; tool 180s; other settings preserved.')
