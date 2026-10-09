"""Read-only Zotero / Jianguoyun library with transactional incremental cache."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
import zipfile

import httpx
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
KEY = re.compile(r'^[A-Z0-9]{8}$')
MAX_PDF = 128 * 1024 * 1024
MAX_ARCHIVE = 256 * 1024 * 1024


class LibraryError(Exception):
    """Safe, user-facing error without request headers or credentials."""


class ChangedDuringSync(LibraryError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def valid_key(value: str) -> str:
    if not KEY.fullmatch(value):
        raise LibraryError('文献键必须为 Zotero 的 8 位大写字母或数字。')
    return value


def plain(value: str) -> str:
    return html.unescape(re.sub(r'<[^>]*>', ' ', value or '')).strip()


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_bytes(data)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@dataclass(repr=False)
class Credential:
    user: str
    secret: str


def credential(target: str) -> Credential:
    if target not in ('Codex.Zotero', 'Codex.Jianguoyun'):
        raise LibraryError('不支持该凭据名称。')
    if os.name != 'nt':
        raise LibraryError('此版本使用 Windows 凭据管理器，需要 Windows 用户会话。')

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                    ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                    ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                    ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
                    ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD),
                    ('Attributes', ctypes.c_void_p), ('TargetAlias', wintypes.LPWSTR),
                    ('UserName', wintypes.LPWSTR)]

    dll = ctypes.WinDLL('advapi32', use_last_error=True)
    ptr = ctypes.POINTER(CREDENTIAL)()
    dll.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                             ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    dll.CredReadW.restype = wintypes.BOOL
    dll.CredFree.argtypes = [ctypes.c_void_p]
    if not dll.CredReadW(target, 1, 0, ctypes.byref(ptr)):
        raise LibraryError(f'无法读取 Windows 凭据 {target}，请在保存它的 Windows 用户会话中运行。')
    try:
        row = ptr.contents
        secret = ctypes.string_at(row.CredentialBlob, row.CredentialBlobSize).decode('utf-16-le').rstrip('\0')
        if not secret or not row.UserName:
            raise LibraryError(f'Windows 凭据 {target} 不完整。')
        return Credential(row.UserName, secret)
    finally:
        dll.CredFree(ptr)


class Remote:
    """Fixed origins, GET only, no redirects, no credentials in query strings."""
    def __init__(self, read_credential=credential, transport=None):
        self.read_credential = read_credential
        self.z = read_credential('Codex.Zotero')
        if not re.fullmatch(r'\d+', self.z.user):
            raise LibraryError('Codex.Zotero 的用户名必须为数字 User ID。')
        self.user = self.z.user
        self.prefix = f'/users/{self.user}'
        self.http = httpx.Client(timeout=httpx.Timeout(40, connect=15), follow_redirects=False,
                                 trust_env=False, transport=transport)
        self.backoff_until = 0.0
        self.notes_allowed = False

    def close(self):
        self.http.close()

    def _wait(self):
        delay = self.backoff_until - time.monotonic()
        if delay > 10:
            raise LibraryError(f'远端要求等待约 {int(delay)+1} 秒后重试。')
        if delay > 0:
            time.sleep(delay)

    def get(self, path, params=None, conditional=None):
        if not (path == '/keys/current' or re.fullmatch(re.escape(self.prefix) + r'/(items|collections|deleted)', path)):
            raise LibraryError('不允许该 API 路径。')
        self._wait()
        headers = {'Zotero-API-Key': self.z.secret, 'Zotero-API-Version': '3'}
        if conditional is not None:
            headers['If-Modified-Since-Version'] = str(conditional)
        try:
            r = self.http.get('https://api.zotero.org' + path, params=params, headers=headers)
        except httpx.HTTPError:
            raise LibraryError('Zotero 连接失败或超时。') from None
        for h in ('Backoff', 'Retry-After'):
            try:
                self.backoff_until = max(self.backoff_until, time.monotonic() + float(r.headers.get(h, '0')))
            except ValueError:
                pass
        if r.status_code not in (200, 304):
            raise LibraryError(f'Zotero HTTP {r.status_code}；请检查网络、权限或稍后重试。')
        try:
            version = int(r.headers['Last-Modified-Version']) if 'Last-Modified-Version' in r.headers else None
            total = int(r.headers.get('Total-Results', '0'))
            value = r.json() if r.status_code == 200 else None
        except (ValueError, KeyError):
            raise LibraryError('Zotero 返回格式异常。') from None
        return value, version, total, r.status_code

    def verify(self):
        info, _, _, _ = self.get('/keys/current')
        if str(info.get('userID')) != self.user or not info.get('access', {}).get('user', {}).get('library'):
            raise LibraryError('Zotero 凭据与个人库不匹配，或没有读取权限。')
        self.notes_allowed = bool(info.get('access', {}).get('user', {}).get('notes'))

    def download(self, key: str) -> bytes:
        valid_key(key)
        dav = self.read_credential('Codex.Jianguoyun')
        url = f'https://dav.jianguoyun.com/dav/zotero/{key}.zip'
        try:
            with self.http.stream('GET', url, auth=httpx.BasicAuth(dav.user, dav.secret)) as r:
                if r.status_code != 200:
                    raise LibraryError(f'坚果云 HTTP {r.status_code}；请确认 PDF 已同步，或稍后重试。')
                parts = []; count = 0
                for part in r.iter_bytes(1024 * 1024):
                    count += len(part)
                    if count > MAX_PDF:
                        raise LibraryError('附件压缩包超过 128 MiB 限制。')
                    parts.append(part)
                return b''.join(parts)
        except httpx.HTTPError:
            raise LibraryError('坚果云连接失败或超时。') from None


def select_pdf(archive_bytes: bytes, expected_md5: str = '') -> bytes:
    expected_md5 = expected_md5.lower()
    if expected_md5 and not re.fullmatch(r'[0-9a-f]{32}', expected_md5):
        raise LibraryError('附件 MD5 格式异常。')
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            entries = archive.infolist()
            if len(entries) > 64 or sum(x.file_size for x in entries) > MAX_ARCHIVE:
                raise LibraryError('附件压缩包超过解压大小或文件数量限制。')
            candidates = []
            for entry in entries:
                if entry.is_dir() or not (5 <= entry.file_size <= MAX_PDF):
                    continue
                # Never extract archive paths; Zotero may encode filenames in ZIP entries.
                with archive.open(entry) as stream:
                    head = stream.read(5)
                    if head != b'%PDF-':
                        continue
                    payload = head + stream.read(MAX_PDF)
                    if len(payload) > MAX_PDF:
                        raise LibraryError('PDF 超过 128 MiB 限制。')
                if expected_md5 and hashlib.md5(payload).hexdigest() == expected_md5:
                    return payload
                candidates.append(payload)
            if expected_md5:
                raise LibraryError('PDF 校验值与 Zotero 不一致，请先完成 Zotero 和坚果云同步。')
            if len(candidates) != 1:
                raise LibraryError('压缩包中没有唯一可确认的 PDF。')
            return candidates[0]
    except (zipfile.BadZipFile, RuntimeError, OSError):
        raise LibraryError('无法读取附件压缩包。') from None


class Library:
    def __init__(self, data_dir: Path | None = None, remote_factory=Remote):
        self.data_dir = Path(data_dir or ROOT / 'data').resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / 'library.sqlite3'
        self.remote_factory = remote_factory
        self.lock = threading.RLock()
        self.ttl = 300
        self.last_error = None
        self.last_attempt = 0.0
        with self.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS items (key TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS collections (key TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.execute('PRAGMA journal_mode=WAL')
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def meta(db, key, default=None):
        row = db.execute('SELECT value FROM meta WHERE name=?', (key,)).fetchone()
        return row[0] if row else default

    @staticmethod
    def put_meta(db, key, value):
        db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, str(value)))

    def sync(self, full=False):
        with self.lock:
            remote = self.remote_factory()
            try:
                remote.verify()
                for attempt in range(3):
                    try:
                        result = self._sync_once(remote, full)
                        self.last_error = None
                        self.last_attempt = time.time()
                        return result
                    except ChangedDuringSync:
                        if attempt == 2:
                            raise LibraryError('同步期间文献库持续变化，本次未提交缓存更新，请稍后重试。') from None
                        time.sleep(attempt + 1)
            finally:
                remote.close()

    def _sync_once(self, remote, full):
        with self.db() as db:
            try:
                db.execute('BEGIN IMMEDIATE')
                owner = self.meta(db, 'user')
                if owner and owner != remote.user:
                    raise LibraryError('当前凭据对应另一文献库，请为新账户使用独立 data 目录。')
                previous = int(self.meta(db, 'version', '0'))
                since = 0 if full else previous
                target = None
                received = {}
                for resource in ('collections', 'items'):
                    all_rows = []; start = 0
                    while True:
                        params = {'format': 'json', 'limit': 100, 'start': start, 'since': since}
                        if resource == 'items':
                            params['includeTrashed'] = 1
                        conditional = previous if previous and not full and resource == 'collections' and start == 0 else None
                        rows, version, total, status = remote.get(remote.prefix + '/' + resource, params, conditional)
                        if status == 304:
                            if not conditional:
                                raise LibraryError('收到非预期的缓存响应。')
                            self.put_meta(db, 'last_checked', time.time())
                            self.put_meta(db, 'checked_at', now())
                            self.put_meta(db, 'notes_allowed', int(remote.notes_allowed))
                            db.commit()
                            return {'status': 'unchanged', 'version': previous, 'new_records': 0,
                                    'updated_records': 0, 'removed_records': 0, 'checked_at': now()}
                        if version is None or not isinstance(rows, list):
                            raise LibraryError('同步响应缺少版本号或条目列表。')
                        if target is None:
                            target = version
                        if version != target:
                            raise ChangedDuringSync()
                        all_rows.extend(rows)
                        start += len(rows)
                        if start >= total:
                            break
                        if not rows:
                            raise LibraryError('分页提前结束，未更新本地索引。')
                    keys = [r['key'] for r in all_rows]
                    if len(set(keys)) != len(keys) or len(keys) != total:
                        raise LibraryError('分页条目数量不一致，未更新本地索引。')
                    received[resource] = all_rows
                deleted = {'items': [], 'collections': []}
                if since:
                    deleted, v, _, _ = remote.get(remote.prefix + '/deleted', {'since': since})
                    if v != target:
                        raise ChangedDuringSync()
                # Commit only after all pages, resources and deletion log share a version.
                before = {r[0]: r[1] for r in db.execute('SELECT key,version FROM items')}
                if full or previous == 0:
                    db.execute('DELETE FROM items'); db.execute('DELETE FROM collections')
                for resource, rows in received.items():
                    for obj in rows:
                        valid_key(obj['key'])
                        db.execute(f'INSERT OR REPLACE INTO {resource} VALUES (?,?,?)',
                                   (obj['key'], int(obj['version']), json.dumps(obj, ensure_ascii=False)))
                    for key in deleted.get(resource, []):
                        db.execute(f'DELETE FROM {resource} WHERE key=?', (valid_key(key),))
                after = {r[0]: r[1] for r in db.execute('SELECT key,version FROM items')}
                for k, v in {'user': remote.user, 'version': target, 'last_checked': time.time(),
                             'checked_at': now(), 'notes_allowed': int(remote.notes_allowed)}.items():
                    self.put_meta(db, k, v)
                db.commit()
                new = sorted(set(after) - set(before))
                return {'status': 'synced', 'version': target, 'new_records': len(new),
                        'updated_records': sum(before[k] != after[k] for k in before.keys() & after.keys()),
                        'removed_records': len(before.keys() - after.keys()),
                        'new_keys': new[:50], 'new_keys_truncated': len(new)>50, 'checked_at': now()}
            except Exception:
                db.rollback()
                raise

    def ensure(self):
        with self.db() as db:
            checked = float(self.meta(db, 'last_checked', '0'))
            ready = self.meta(db, 'version') is not None
        if time.time() - checked > self.ttl and time.time() - self.last_attempt > 30:
            self.last_attempt = time.time()
            try:
                self.sync()
            except (LibraryError, sqlite3.Error) as exc:
                self.last_error = str(exc) if isinstance(exc, LibraryError) else '本地索引忙或不可用。'
                if not ready:
                    raise LibraryError(self.last_error) from None
        elif not ready:
            raise LibraryError(self.last_error or '索引尚未建立，请调用 sync_library。')

    def freshness(self):
        with self.db() as db:
            checked = float(self.meta(db, 'last_checked', '0'))
            return {'library_version': self.meta(db, 'version'), 'checked_at': self.meta(db, 'checked_at'),
                    'stale': not checked or time.time()-checked > self.ttl, 'sync_error': self.last_error}

    def rows(self, resource='items'):
        if resource not in ('items', 'collections'):
            raise LibraryError('未知资源。')
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute(f'SELECT payload FROM {resource}')]

    def visible(self, rows):
        deleted = {r['key'] for r in rows if r.get('data', {}).get('deleted')}
        # Also hide children of trashed parents, even when children have no deleted flag.
        for _ in range(3):
            deleted |= {r['key'] for r in rows if r.get('data', {}).get('parentItem') in deleted}
        return [r for r in rows if r['key'] not in deleted]

    def status(self):
        rows = self.visible(self.rows())
        primary = [r for r in rows if not r['data'].get('parentItem') and r['data'].get('itemType') not in ('note','annotation')]
        return {'server': 'zotero-library', 'remote_read_only': True, 'automatic_check_interval_seconds': self.ttl,
                'records': len(rows), 'top_level_records': len(primary),
                'records_with_abstract': sum(bool(r['data'].get('abstractNote','').strip()) for r in primary),
                'collections': len(self.rows('collections')), 'cached_pdfs': len(list((self.data_dir/'pdfs').glob('*.pdf'))),
                'cache_directory': str(self.data_dir), **self.freshness()}

    @staticmethod
    def summary(row):
        d = row['data']
        return {'key': row['key'], 'title': d.get('title',''), 'date': d.get('date',''),
                'authors': '; '.join(c.get('name') or ' '.join([c.get('firstName',''),c.get('lastName','')]).strip()
                                     for c in d.get('creators',[])),
                'type': d.get('itemType'), 'doi': d.get('DOI',''), 'journal': d.get('publicationTitle',''),
                'date_added': d.get('dateAdded'), 'date_modified': d.get('dateModified'),
                'has_abstract': bool(d.get('abstractNote','').strip()),
                'collections': d.get('collections',[]), 'tags': [t.get('tag','') for t in d.get('tags',[])],
                'zotero_url': row.get('links',{}).get('alternate',{}).get('href','')}

    def search(self, query='', year_from=None, year_to=None, collection_key=None, limit=20, offset=0, added_since=None):
        self.ensure()
        if not 1 <= limit <= 50 or offset < 0:
            raise LibraryError('limit 需为 1–50，offset 不得为负。')
        if year_from and year_to and year_from > year_to:
            raise LibraryError('年份范围顺序错误。')
        if collection_key:
            valid_key(collection_key)
        if added_since:
            try:
                datetime.strptime(added_since, '%Y-%m-%d')
            except ValueError:
                raise LibraryError('added_since 使用 YYYY-MM-DD 格式。') from None
        tokens = query.casefold().split()
        found = []
        for row in self.visible(self.rows()):
            d = row['data']
            if d.get('parentItem') or d.get('itemType') in ('note','annotation'):
                continue
            s = self.summary(row)
            haystack = ' '.join([s['title'],s['authors'],s['doi'],s['journal'],plain(d.get('abstractNote','')),*s['tags']]).casefold()
            if not all(t in haystack for t in tokens):
                continue
            if collection_key and collection_key not in s['collections']:
                continue
            year = re.search(r'\b(1[5-9]\d{2}|20\d{2})\b', s['date'])
            y = int(year[0]) if year else None
            if (year_from and (y is None or y < year_from)) or (year_to and (y is None or y > year_to)):
                continue
            if added_since and (s['date_added'] or '')[:10] < added_since:
                continue
            found.append(s)
        found.sort(key=lambda s:s['date_added'] or '', reverse=True)
        return {'total':len(found),'offset':offset,'limit':limit,'items':found[offset:offset+limit],
                'search_scope':'标题、作者、摘要、DOI、期刊和标签；空格分词取 AND，不是全库 PDF 全文检索', **self.freshness()}

    def item_row(self, key):
        valid_key(key)
        for row in self.visible(self.rows()):
            if row['key'] == key:
                return row
        raise LibraryError('本地索引中未找到该条目；新条目请先 sync_library。')

    def item(self, key, include_notes=False):
        self.ensure()
        row = self.item_row(key); d = row['data']
        children = [r for r in self.visible(self.rows()) if r['data'].get('parentItem')==key]
        result = self.summary(row)
        result.update({'abstract':plain(d.get('abstractNote','')), 'abstract_source':'Zotero 当前同步字段',
                       'version':row['version'], 'attachments':[self.attachment_info(r) for r in children if r['data'].get('itemType')=='attachment'],
                       **self.freshness()})
        if d.get('itemType') == 'attachment':
            result['attachment'] = self.attachment_info(row)
        if include_notes:
            with self.db() as db:
                allowed = self.meta(db, 'notes_allowed') == '1'
            result['notes'] = [{'key':r['key'],'text':plain(r['data'].get('note',''))} for r in children if r['data'].get('itemType')=='note'] if allowed else []
            result['notes_permission'] = allowed
        history_path = ROOT/'knowledge'/'reading-notes.json'
        if history_path.exists():
            history = json.loads(history_path.read_text(encoding='utf-8-sig'))
            if key in history:
                h = dict(history[key])
                h['abstract_changed_since_review'] = h.get('original_abstract','') != d.get('abstractNote','')
                h.pop('original_abstract', None)
                result['historical_reading_note'] = h
        return result

    @staticmethod
    def attachment_info(r):
        d=r['data']
        return {'key':r['key'], 'title':d.get('title',''), 'filename':d.get('filename',''),
                'content_type':d.get('contentType',''), 'link_mode':d.get('linkMode','')}

    def collections(self):
        self.ensure()
        return {'collections':[{'key':r['key'],'name':r['data'].get('name',''),
                                'parent':r['data'].get('parentCollection') or None} for r in self.rows('collections')], **self.freshness()}

    def pdf(self, item_key, attachment_key=None):
        self.ensure()
        item = self.item_row(item_key)
        candidates = [item] if item['data'].get('itemType')=='attachment' else [r for r in self.visible(self.rows()) if r['data'].get('parentItem')==item_key]
        candidates = [r for r in candidates if r['data'].get('itemType')=='attachment' and r['data'].get('contentType')=='application/pdf'
                      and r['data'].get('linkMode') in ('imported_file','imported_url')]
        if attachment_key:
            valid_key(attachment_key)
            candidates = [r for r in candidates if r['key']==attachment_key]
        if not candidates:
            raise LibraryError('该条目没有匹配的、可经 WebDAV 同步的 PDF 附件。')
        if len(candidates)>1:
            return {'status':'choose_attachment','attachments':[self.attachment_info(r) for r in candidates]}
        row=candidates[0]; key=row['key']; d=row['data']; md5=d.get('md5') or ''
        if md5 and not re.fullmatch('[0-9a-fA-F]{32}',md5):
            raise LibraryError('附件校验值异常。')
        stamp=md5.lower() or str(int(row['version']))
        path=self.data_dir/'pdfs'/f'{key}-{stamp}.pdf'
        cached=path.exists()
        if cached and md5:
            cached=hashlib.md5(path.read_bytes()).hexdigest()==md5.lower()
        if not cached:
            remote=self.remote_factory()
            try:
                with self.db() as db:
                    if self.meta(db,'user') != remote.user:
                        raise LibraryError('缓存库与当前凭据不一致。')
                payload=select_pdf(remote.download(key), md5)
                atomic_write(path,payload)
            finally:
                remote.close()
        return {'status':'ready','item_key':item_key,'attachment_key':key,'title':item['data'].get('title',''),
                'path':str(path),'bytes':path.stat().st_size,'cache_hit':cached,'md5_verified':bool(md5),**self.freshness()}

    def _pages(self, pdf_info):
        path=Path(pdf_info['path']); text_path=path.with_suffix('.pages.json')
        # Increment when extraction dependencies or normalization change.
        schema=2
        if text_path.exists():
            try:
                stored=json.loads(text_path.read_text(encoding='utf-8'))
                if isinstance(stored,dict) and stored.get('schema')==schema:
                    return stored['pages']
            except (OSError, ValueError):
                pass
        try:
            reader=PdfReader(path)
            if reader.is_encrypted and not reader.decrypt(''):
                raise LibraryError('PDF 已加密，无法提取正文。')
            if len(reader.pages)>1500:
                raise LibraryError('PDF 超过 1500 页，需要另行分段处理。')
            pages=[]; total=0
            for page in reader.pages:
                value=page.extract_text() or ''
                total+=len(value)
                if total>30_000_000:
                    raise LibraryError('PDF 文本超过缓存限制。')
                pages.append(value)
        except LibraryError:
            raise
        except Exception:
            raise LibraryError('PDF 文本提取失败；可通过 get_pdf 获取原文件后另行读取。') from None
        atomic_write(text_path,json.dumps({'schema':schema,'pages':pages},ensure_ascii=False).encode('utf-8'))
        return pages

    def read_pdf(self,item_key,attachment_key=None,start_page=1,page_count=3,max_chars=20000):
        if start_page<1 or not 1<=page_count<=10 or not 500<=max_chars<=40000:
            raise LibraryError('页码从 1 开始；page_count 为 1–10；max_chars 为 500–40000。')
        info=self.pdf(item_key,attachment_key)
        if info['status']!='ready': return info
        pages=self._pages(info)
        if start_page>len(pages): raise LibraryError('起始页码超过 PDF 总页数。')
        output=[]; remaining=max_chars; truncated=False
        for i in range(start_page-1,min(len(pages),start_page-1+page_count)):
            value=pages[i]
            output.append({'page':i+1,'text':value[:remaining], 'truncated':len(value)>remaining})
            remaining-=min(len(value),remaining)
            if len(value)>len(output[-1]['text']): truncated=True
            if remaining<=0:
                truncated=True; break
        return {**info,'total_pages':len(pages),'pages':output,'truncated':truncated,
                'text_layer_empty':not any(p['text'].strip() for p in output),
                'extraction_note':'仅提取文字层；扫描页、公式和图表可能需另行 OCR 或看图。'}

    def search_pdf(self,item_key,query,attachment_key=None,max_hits=10):
        if not query.strip() or not 1<=max_hits<=30:
            raise LibraryError('请提供非空关键词；max_hits 为 1–30。')
        info=self.pdf(item_key,attachment_key)
        if info['status']!='ready': return info
        pages=self._pages(info); hits=[]; total=0
        for i,text in enumerate(pages,1):
            for match in re.finditer(re.escape(query),text,re.IGNORECASE):
                total+=1
                if len(hits)<max_hits:
                    hits.append({'page':i,'excerpt':text[max(0,match.start()-150):match.end()+250]})
        return {**info,'total_pages':len(pages),'total_hits':total,'hits':hits,
                'text_layer_empty':not any(p.strip() for p in pages)}
