import hashlib
import io
import json
import time
import zipfile

import httpx
import pytest

from library import Library, LibraryError, ChangedDuringSync, Remote, Credential, select_pdf


def item(key='AAAA0001', version=1, **extra):
    return {'key':key,'version':version,'data':{'itemType':'journalArticle','title':'PVC gel actuator',
            'date':'2024-03','abstractNote':'Hydrodynamic propulsion and PVC.', 'dateAdded':'2026-10-01T00:00:00Z',**extra}}


class FakeRemote:
    user='123'; prefix='/users/123'; notes_allowed=True
    def __init__(self, version, items, deleted=None, unstable=False):
        self.version=version; self.items=items; self.deleted=deleted or []; self.unstable=unstable; self.calls=[]
    def verify(self): pass
    def close(self): pass
    def get(self,path,params=None,conditional=None):
        self.calls.append((path,params,conditional))
        if conditional==self.version:
            return None,self.version,0,304
        v=self.version+(1 if self.unstable and path.endswith('/items') else 0)
        if path.endswith('/deleted'): return {'items':self.deleted,'collections':[]},v,0,200
        rows=self.items if path.endswith('/items') else []
        rows=[r for r in rows if r['version']>params.get('since',0)]
        return rows[params.get('start',0):params.get('start',0)+100],v,len(rows),200


def setup(tmp_path, remote):
    lib=Library(tmp_path,lambda:remote)
    lib.sync()
    return lib


def test_full_paging_and_304(tmp_path):
    remote=FakeRemote(1,[item(f'A{i:07d}') for i in range(205)])
    lib=setup(tmp_path,remote)
    assert lib.status()['top_level_records']==205
    remote.calls.clear()
    assert lib.sync()['status']=='unchanged'
    assert len(remote.calls)==1


def test_incremental_add_update_delete_and_trash(tmp_path):
    r=FakeRemote(1,[item(),item('AAAA0002'),item('AAAA0003'),item('AAAA0004',parentItem='AAAA0003',itemType='attachment')])
    lib=setup(tmp_path,r)
    r.version=2; r.items=[item(version=2,title='New title'), item('AAAA0003',2,deleted=1),item('AAAA0005',2)]
    r.deleted=['AAAA0002']
    result=lib.sync()
    assert (result['new_records'],result['updated_records'],result['removed_records'])==(1,2,1)
    assert {x['key'] for x in lib.search()['items']}=={'AAAA0001','AAAA0005'}
    assert 'AAAA0004' not in {x['key'] for x in lib.visible(lib.rows())}


def test_atomic_rollback_on_version_race(tmp_path):
    r=FakeRemote(1,[item()]); lib=setup(tmp_path,r)
    r.version=2; r.unstable=True; r.items=[item('AAAA0002',2)]
    with pytest.raises(ChangedDuringSync): lib._sync_once(r,False)
    assert lib.status()['library_version']=='1'
    assert {r['key'] for r in lib.rows()}=={'AAAA0001'}


def test_offline_cache_is_explicit(tmp_path):
    lib=setup(tmp_path,FakeRemote(1,[item()]))
    with lib.db() as db:
        lib.put_meta(db,'last_checked',0); db.commit()
    def broken(): raise LibraryError('offline')
    lib.remote_factory=broken; lib.last_attempt=0
    response=lib.search('pvc')
    assert response['total']==1 and response['stale'] is True and response['sync_error']=='offline'


def test_search_filters_and_html(tmp_path):
    lib=setup(tmp_path,FakeRemote(1,[item(abstractNote='<p>水下 <b>柔性</b>推进</p>')]))
    assert lib.search('水下 柔性',year_from=2024,year_to=2024,added_since='2026-10-01')['total']==1
    assert lib.search('PVC',year_from=2025)['total']==0
    assert lib.item('AAAA0001')['abstract']=='水下  柔性 推进'
    with pytest.raises(LibraryError): lib.search(added_since='yesterday')


def zipped(payload, name='../escape.pdf'):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr(name,payload)
    return b.getvalue()


def test_archive_hash_and_path_safety(tmp_path):
    payload=b'%PDF-1.7 test fixture'
    archive=zipped(payload)
    assert select_pdf(archive,hashlib.md5(payload).hexdigest())==payload
    assert not list(tmp_path.iterdir())
    with pytest.raises(LibraryError,match='不一致'): select_pdf(archive,'0'*32)
    with pytest.raises(LibraryError): select_pdf(b'bad zip')


def test_remote_only_get_and_no_redirects():
    calls=[]
    def transport(request):
        calls.append(request)
        return httpx.Response(302,headers={'Location':'https://example.org/leak'})
    creds=lambda target:Credential('123','do-not-log-this')
    r=Remote(creds,httpx.MockTransport(transport))
    try:
        with pytest.raises(LibraryError) as exc:r.get('/keys/current')
        assert 'do-not-log-this' not in str(exc.value)
        assert len(calls)==1 and calls[0].method=='GET'
        with pytest.raises(LibraryError): r.get('https://example.org/')
        with pytest.raises(LibraryError): r.download('../bad')
    finally:r.close()


def test_account_mismatch_preserves_cache(tmp_path):
    r=FakeRemote(1,[item()]); lib=setup(tmp_path,r); r.user='456'
    with pytest.raises(LibraryError,match='另一'):lib.sync()
    assert len(lib.rows())==1


def test_pdf_candidates_and_stale_hash(tmp_path):
    a=item('PDF00001',parentItem='AAAA0001',itemType='attachment',contentType='application/pdf',linkMode='imported_file')
    b=item('PDF00002',parentItem='AAAA0001',itemType='attachment',contentType='application/pdf',linkMode='imported_file')
    lib=setup(tmp_path,FakeRemote(1,[item(),a,b]))
    assert lib.pdf('AAAA0001')['status']=='choose_attachment'
    with pytest.raises(LibraryError):lib.pdf('AAAA0001','NOPE0001')


def test_permission_to_notes(tmp_path):
    r=FakeRemote(1,[item(),item('NOTE0001',itemType='note',parentItem='AAAA0001',note='<p>secret note</p>')])
    lib=setup(tmp_path,r)
    assert len(lib.item('AAAA0001',True)['notes'])==1
    r.notes_allowed=False; lib.sync()
    assert lib.item('AAAA0001',True)['notes']==[]
