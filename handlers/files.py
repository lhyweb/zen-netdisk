# -*- coding: utf-8 -*-
"""文件模块：文件页、浏览/搜索、上传（流式）、下载/预览、文本编辑、打包、可见性、删除。"""
import os
import json
import time
import tempfile
import zipfile

import tornado.web

import config
import db
import utils
from auth import BaseHandler, visible, can_manage


def _to_trash(src):
    """把文件/文件夹移入共享根目录下的 _trash/，文件名以删除时间戳开头（按名称排序即按时间）。"""
    trash = os.path.join(config.CFG['root_dir'], '_trash')
    os.makedirs(trash, exist_ok=True)
    base = os.path.basename(os.path.normpath(src))
    ts = time.strftime('%Y%m%d_%H%M%S')
    dst = os.path.join(trash, '%s_%s' % (ts, base))
    n = 1
    while os.path.exists(dst):
        dst = os.path.join(trash, '%s_%s_%d' % (ts, base, n))
        n += 1
    os.replace(src, dst)


def _stream_file(self, path, filename, disposition):
    """按块流式输出文件，避免大文件占用内存。"""
    self.set_header('X-Content-Type-Options', 'nosniff')
    self.set_header('Content-Type', utils.content_type(filename))
    if disposition == 'inline':
        self.set_header('Content-Disposition', 'inline')
    else:
        self.set_header('Content-Disposition',
                        "attachment; filename*=UTF-8''%s" % utils.rfc5987(filename))
    self.set_header('Content-Length', str(os.path.getsize(path)))
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            self.write(chunk)
            self.flush()


# ---------------- 文件页 / 列表 ----------------

class FilePageHandler(BaseHandler):
    """共享根目录首页（HTML）。"""

    def get(self):
        u = self.require_login()
        if not u:
            return
        self.render('files.html', current_user=u)


class ListHandler(BaseHandler):
    """列出目录内容（JSON）。以真实目录扫描为主，DB 只补充属主/可见性属性。"""

    def get(self):
        u = self.require_login()
        if not u:
            return
        rel = self.get_argument('path', '')
        q = self.get_argument('q', '').strip().lower()
        root = config.CFG['root_dir']
        d = utils.safe_join(root, rel)
        if d is None or not os.path.isdir(d):
            self.json({'ok': False, 'error': self._t('err_dir_missing')}, 400)
            return
        try:
            names = os.listdir(d)
        except OSError:
            self.json({'ok': False, 'error': self._t('err_dir_unreadable')}, 500)
            return
        names = [n for n in names if not n.startswith('_')]
        rels = [rel + '/' + n if rel else n for n in names]
        attrs = db.get_files_by_paths(rels)          # 批量取属性，避免逐文件查库

        items = []
        for n, rp in zip(names, rels):
            if q and q not in n.lower():
                continue
            full = os.path.join(d, n)
            if os.path.isdir(full):
                items.append({'name': n, 'is_dir': True, 'size': 0, 'mtime': 0,
                              'owner': '', 'visibility': '', 'can_manage': False,
                              'can_share': False, 'share': '', 'preview': 'none', 'path': rp})
                continue
            info = attrs.get(rp)
            if not visible(u, info):                 # 私有的他人文件对当前用户隐藏
                continue
            try:
                size = os.path.getsize(full)
                mtime = int(os.path.getmtime(full))
            except OSError:
                size, mtime = 0, 0
            owner = db.owner_display(info['owner_id']) if info else 'admin'
            vis = info['visibility'] if info else 'public'
            can_share = u['role'] in ('admin', 'user')   # 只读账号不生成分享链接
            items.append({'name': n, 'is_dir': False, 'size': size, 'mtime': mtime,
                          'owner': owner or 'admin', 'visibility': vis,
                          'can_manage': can_manage(u, info), 'can_share': can_share,
                          'share': utils.share_link(rp) if can_share else '',
                          'preview': utils.preview_type(n), 'path': rp})
        items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        parent = rel.rsplit('/', 1)[0] if rel else ''
        self.json({'ok': True, 'dir': rel, 'parent': parent, 'items': items,
                   'is_admin': u['role'] == 'admin'})


# ---------------- 上传（流式） ----------------

class UploadHandler(BaseHandler):
    """上传接口：POST /api/upload?name=<文件名>&dir=<相对目录>，请求体为文件原始字节。
       使用 data_received 边收边写临时文件，大文件不占内存。"""

    def prepare(self):
        self._tmp = tempfile.NamedTemporaryFile(delete=False, prefix='up_',
                                                dir=config.CFG['base_dir'])
        self._streamed = False
        try:
            self.request.connection.set_max_body_size(config.CFG['max_upload_bytes'] + 1024 * 1024)
        except Exception:
            pass

    def data_received(self, chunk):
        self._streamed = True
        self._tmp.write(chunk)

    async def post(self):
        u = self.require_login()
        if not u:
            self._cleanup()
            return
        if u['role'] == 'readonly':
            self._cleanup()
            self.json({'ok': False, 'error': self._t('err_upload_denied')}, 403)
            return
        # 若框架未走流式（例如小请求），请求体仍在 self.request.body 中
        if not self._streamed and self.request.body:
            self._tmp.write(self.request.body)
        self._tmp.flush()
        self._tmp.close()

        try:
            size = os.path.getsize(self._tmp.name)
            name = utils.sanitize_name(self.get_argument('name', ''))
            sub = self.get_argument('dir', '').strip('/')
            if not name:
                self.json({'ok': False, 'error': self._t('err_bad_filename')}, 400)
                return
            rel = (sub + '/' + name) if sub else name
            root = config.CFG['root_dir']
            target = utils.safe_join(root, rel)
            if target is None:
                self.json({'ok': False, 'error': self._t('err_bad_path')}, 400)
                return
            if size > config.CFG['max_upload_bytes']:
                self.json({'ok': False, 'error': self._t('err_too_large') % config.CFG['max_upload_mb']}, 413)
                return
            os.makedirs(os.path.dirname(target), exist_ok=True)

            info = db.get_file_by_path(rel)
            if os.path.exists(target):
                # 已存在：属主或管理员可覆盖（旧文件进回收站），否则拒绝
                if not can_manage(u, info):
                    owner = db.owner_display(info['owner_id']) if info else 'admin'
                    self.json({'ok': False, 'error': self._t('err_exists_owner') % owner}, 409)
                    return
                old_vis = info['visibility'] if info else 'public'
                _to_trash(target)
                db.delete_file(rel)
                action = 'overwrite'
            else:
                old_vis = 'public'      # 新上传默认公开
                action = 'upload'
            os.replace(self._tmp.name, target)      # 原子落盘
            db.upsert_file(rel, u['id'], old_vis, size)
            self.log(u['username'], action, rel, str(size))
            self.json({'ok': True, 'path': rel})
        finally:
            self._cleanup()

    def _cleanup(self):
        try:
            if os.path.exists(self._tmp.name):
                os.unlink(self._tmp.name)
        except Exception:
            pass

    def on_finish(self):
        self._cleanup()


# ---------------- 下载 / 预览 ----------------

class DownloadHandler(BaseHandler):
    """下载接口：GET /api/download?path=<rel>。inline=1 时用于图片/PDF 在线预览。"""

    def get(self):
        u = self.require_login()
        if not u:
            return
        rel = self.get_argument('path', '')
        inline = self.get_argument('inline', '') == '1'
        self._serve(u, rel, inline)

    def _serve(self, u, rel, inline):
        root = config.CFG['root_dir']
        p = utils.safe_join(root, rel)
        if p is None or not os.path.isfile(p):
            self.set_status(404)
            self.finish(self._t('err_file_missing'))
            return
        info = db.get_file_by_path(rel)
        if not visible(u, info):
            self.set_status(403)
            self.finish(self._t('err_no_perm'))
            return
        _stream_file(self, p, os.path.basename(rel), 'inline' if inline else 'attachment')
        self.log(u['username'], 'download', rel)


# ---------------- 文本预览 / 在线编辑 ----------------

class TextHandler(BaseHandler):
    """GET /api/text?path= 返回文本内容与编码；POST /api/text 保存（仅属主/管理员，按原编码）。"""

    def get(self):
        u = self.require_login()
        if not u:
            return
        rel = self.get_argument('path', '')
        p = utils.safe_join(config.CFG['root_dir'], rel)
        if p is None or not os.path.isfile(p):
            self.json({'ok': False, 'error': self._t('err_file_missing')}, 404)
            return
        info = db.get_file_by_path(rel)
        if not visible(u, info):
            self.json({'ok': False, 'error': self._t('err_no_perm')}, 403)
            return
        with open(p, 'rb') as f:
            raw = f.read()
        enc = utils.detect_encoding(raw)
        try:
            content = raw.decode(enc)
        except Exception:
            content = raw.decode('utf-8', 'replace')
        self.json({'ok': True, 'name': os.path.basename(rel), 'content': content,
                   'encoding': enc,
                   'can_edit': u['role'] in ('admin', 'user') and can_manage(u, info)})

    def post(self):
        u = self.require_login()
        if not u:
            return
        if u['role'] == 'readonly':
            self.json({'ok': False, 'error': self._t('err_edit_denied')}, 403)
            return
        try:
            body = json.loads(self.request.body)
        except Exception:
            self.json({'ok': False, 'error': self._t('err_bad_params')}, 400)
            return
        rel = body.get('path', '')
        content = body.get('content', '')
        enc = body.get('encoding', '') or 'utf-8'
        if enc not in ('utf-8', 'utf-8-sig', 'gb18030', 'gbk', 'latin-1'):
            enc = 'utf-8'
        p = utils.safe_join(config.CFG['root_dir'], rel)
        if p is None:
            self.json({'ok': False, 'error': self._t('err_bad_path')}, 400)
            return
        info = db.get_file_by_path(rel)
        if not can_manage(u, info):
            self.json({'ok': False, 'error': self._t('err_no_perm')}, 403)
            return
        data = content.encode(enc)
        tmp = p + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, p)
        db.update_file_size(rel, len(data))
        self.log(u['username'], 'edit_text', rel)
        self.json({'ok': True})


# ---------------- 多选打包下载 ----------------

class ZipHandler(BaseHandler):
    """POST /api/zip，body 为 {"paths":[...]}，返回 zip 流（保留相对目录结构）。"""

    def post(self):
        u = self.require_login()
        if not u:
            return
        try:
            body = json.loads(self.request.body)
        except Exception:
            body = {}
        paths = body.get('paths', []) if isinstance(body, dict) else body
        if not isinstance(paths, list) or not paths:
            self.json({'ok': False, 'error': self._t('err_sel_files')}, 400)
            return
        root = config.CFG['root_dir']
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip', dir=config.CFG['base_dir'])
        try:
            with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zf:
                for rel in paths:
                    p = utils.safe_join(root, rel)
                    if p is None or not os.path.exists(p):
                        continue
                    if os.path.isdir(p):
                        for rp in utils.walk_files_under(root, rel):
                            fp = utils.safe_join(root, rp)
                            info = db.get_file_by_path(rp)
                            if fp and os.path.isfile(fp) and visible(u, info):
                                zf.write(fp, rp.replace('\\', '/'))
                    else:
                        info = db.get_file_by_path(rel)
                        if visible(u, info):
                            zf.write(p, rel.replace('\\', '/'))
        finally:
            tmp.close()
        ts = time.strftime('%Y%m%d_%H%M%S')
        self.set_header('Content-Type', 'application/zip')
        self.set_header('Content-Disposition', 'attachment; filename="files_%s.zip"' % ts)
        with open(tmp.name, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.write(chunk)
                self.flush()
        os.unlink(tmp.name)
        self.log(u['username'], 'zip_download', ','.join(paths))


# ---------------- 可见性切换（单个 / 批量） ----------------

class VisibilityHandler(BaseHandler):
    """POST /api/visibility，body 为 {"paths":[...], "visibility":"public|private"}。"""

    def post(self):
        u = self.require_login()
        if not u:
            return
        if u['role'] == 'readonly':
            self.json({'ok': False, 'error': self._t('err_no_perm')}, 403)
            return
        try:
            body = json.loads(self.request.body)
        except Exception:
            self.json({'ok': False, 'error': self._t('err_bad_params')}, 400)
            return
        paths = body.get('paths', [])
        vis = body.get('visibility', 'public')
        if vis not in ('public', 'private') or not isinstance(paths, list):
            self.json({'ok': False, 'error': self._t('err_bad_params')}, 400)
            return
        root = config.CFG['root_dir']
        changed, denied = [], []
        for rel in paths:
            p = utils.safe_join(root, rel)
            if p is None or not os.path.exists(p) or os.path.isdir(p):
                denied.append(rel)      # 文件夹不设可见性
                continue
            info = db.get_file_by_path(rel)
            if info is None:
                # 直接复制进根目录的无记录文件视为 admin 所有
                if u['role'] != 'admin':
                    denied.append(rel)
                    continue
                db.upsert_file(rel, u['id'], vis, os.path.getsize(p))
            else:
                if not can_manage(u, info):
                    denied.append(rel)
                    continue
                db.set_visibility(rel, vis)
            changed.append(rel)
        self.log(u['username'], 'visibility', ','.join(changed), vis)
        self.json({'ok': True, 'changed': changed, 'denied': denied})


# ---------------- 删除（进回收站） ----------------

class DeleteHandler(BaseHandler):
    """POST /api/delete，body 为 {"paths":[...]}。删除=移入 _trash/ 并删 DB 记录。"""

    def post(self):
        u = self.require_login()
        if not u:
            return
        if u['role'] == 'readonly':
            self.json({'ok': False, 'error': self._t('err_del_denied')}, 403)
            return
        try:
            body = json.loads(self.request.body)
        except Exception:
            body = {}
        paths = body.get('paths', []) if isinstance(body, dict) else body
        if not isinstance(paths, list):
            paths = [paths]
        root = config.CFG['root_dir']
        done, errors = [], []
        for rel in paths:
            target = utils.safe_join(root, rel)
            if target is None or not os.path.exists(target):
                errors.append(rel)
                continue
            if os.path.isdir(target):
                # 删除文件夹：要求其内所有文件都属当前用户（或 admin）
                rps = utils.walk_files_under(root, rel)
                if not all(can_manage(u, db.get_file_by_path(rp)) for rp in rps):
                    errors.append(rel)
                    continue
                for rp in rps:
                    db.delete_file(rp)
                _to_trash(target)
            else:
                info = db.get_file_by_path(rel)
                if not can_manage(u, info):
                    errors.append(rel)
                    continue
                _to_trash(target)
                db.delete_file(rel)
            done.append(rel)
            self.log(u['username'], 'delete', rel)
        self.json({'ok': True, 'deleted': done, 'errors': errors})


# ---------------- 新建文件夹 ----------------

class MkdirHandler(BaseHandler):
    """POST /api/mkdir，body 为 {"dir": 当前目录, "name": 新文件夹名}。
       在当前打开的目录下创建子文件夹；只读账号无权限。"""

    def post(self):
        u = self.require_login()
        if not u:
            return
        if u['role'] == 'readonly':
            self.json({'ok': False, 'error': self._t('err_no_perm')}, 403)
            return
        try:
            body = json.loads(self.request.body)
        except Exception:
            self.json({'ok': False, 'error': self._t('err_bad_params')}, 400)
            return
        name = utils.sanitize_name(body.get('name', ''))
        if not name:
            self.json({'ok': False, 'error': self._t('err_folder_name')}, 400)
            return
        sub = (body.get('dir', '') or '').strip('/')
        rel = (sub + '/' + name) if sub else name
        p = utils.safe_join(config.CFG['root_dir'], rel)
        if p is None:
            self.json({'ok': False, 'error': self._t('err_bad_path')}, 400)
            return
        if os.path.exists(p):
            self.json({'ok': False, 'error': self._t('err_exists_same')}, 409)
            return
        try:
            os.makedirs(p)
        except OSError as e:
            self.json({'ok': False, 'error': self._t('err_mkdir_fail') % e}, 500)
            return
        self.log(u['username'], 'mkdir', rel)
        self.json({'ok': True, 'path': rel})
