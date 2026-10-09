"""Portable stdio smoke test; private data and online checks are optional."""
import argparse
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parent


async def main(live=False,item_key=None):
    if item_key and not live:
        raise ValueError('--item-key requires --live')
    config=StdioServerParameters(command=sys.executable,args=['-X','utf8',str(ROOT/'server.py')],env=dict(os.environ))
    report={}
    async with stdio_client(config) as (read,write):
        async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=180)) as session:
            initialized=await session.initialize()
            listing=await session.list_tools()
            report['server']=initialized.serverInfo.name
            report['tools']=[t.name for t in listing.tools]
            assert len(report['tools'])==9
            assert all(t.annotations.readOnlyHint and not t.annotations.destructiveHint for t in listing.tools)

            async def call(name,args=None):
                result=await session.call_tool(name,args or {})
                assert not result.isError,name
                data=result.structuredContent
                if data is None:
                    data=json.loads(next(c.text for c in result.content if c.type=='text'))
                assert data.get('status')!='error',data
                return data

            taxonomy=await call('get_knowledge_map',{'branch':2})
            assert {r['二级'] for r in taxonomy['entries']}=={'解释机理','预测性能','结构优化','实时控制'}
            report['taxonomy_branch_2_entries']=len(taxonomy['entries'])
            if live:
                report['sync']=await call('sync_library')
                search=await call('search_library',{'limit':3})
                report['search_matches']=search['total']
                if search['items']:
                    details=await call('get_item',{'item_key':search['items'][0]['key']})
                    assert details['key']==search['items'][0]['key']
                    report['item_read']='passed'
            report['status']=await call('library_status')
            if item_key:
                item=await call('get_item',{'item_key':item_key})
                candidates=[a for a in item['attachments'] if a['content_type']=='application/pdf'
                            and a['link_mode'] in ('imported_file','imported_url')]
                if item.get('attachment'):
                    candidates=[item['attachment']]
                assert candidates,'Selected item has no supported PDF attachment'
                args={'item_key':item_key,'attachment_key':candidates[0]['key']}
                pdf=await call('read_pdf',{**args,'page_count':1,'max_chars':1500})
                assert pdf['status']=='ready'
                report['pdf']={k:pdf[k] for k in ('bytes','cache_hit','md5_verified','total_pages','text_layer_empty')}
                report['pdf']['first_page_characters']=len(pdf['pages'][0]['text'])
                # An empty text layer is a valid scanned PDF, not a failed download.
    report['result']='passed'
    (ROOT/'test-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--item-key')
    args=parser.parse_args()
    asyncio.run(main(args.live,args.item_key))
