# -*- coding: utf-8 -*-
"""公告与分享模块。
   - 全局公告：仅管理员在管理后台维护，含「登录自动通知」开关；所有登录用户可查看；
   - 文件分享链接：HMAC 无存储校验，访客只读下载。
   注：早期「每用户专属公告链接 /s/u/<token>」已按需求移除。"""
import os
import json
import time
import urllib.parse

import tornado.web

import config
import db
import utils
from auth import BaseHandler
from handlers.files import _stream_file

NOTICE_TITLE_KEY = 'notice_title'
NOTICE_BODY_KEY = 'notice_body'
NOTICE_ENABLED_KEY = 'notice_enabled'


class NoticeHandler(BaseHandler):
    """全局公告：GET 任何登录用户可读；POST 仅管理员保存（含登录自动通知开关）。"""

    def get(self):
        u = self.require_login()
        if not u:
            return
        self.json({'ok': True,
                   'title': db.get_setting(NOTICE_TITLE_KEY, ''),
                   'body': db.get_setting(NOTICE_BODY_KEY, ''),
                   'enabled': db.get_setting(NOTICE_ENABLED_KEY, '0') == '1'})

    def post(self):
        u = self.require_login()
        if not u:
            return
        if u['role'] != 'admin':
            self.json({'ok': False, 'error': self._t('err_notice_perm')}, 403)
            return
        try:
            body = json.loads(self.request.body)
        except Exception:
            self.json({'ok': False, 'error': self._t('err_bad_params')}, 400)
            return
        title = (body.get('title', '') or '')[:100]
        html = utils.sanitize_html(body.get('body', ''))   # 白名单过滤防 XSS
        enabled = '1' if body.get('enabled') else '0'
        db.set_setting(NOTICE_TITLE_KEY, title)
        db.set_setting(NOTICE_BODY_KEY, html)
        db.set_setting(NOTICE_ENABLED_KEY, enabled)
        self.log(u['username'], 'notice_edit', '', title + ('(自动通知开)' if enabled == '1' else ''))
        self.json({'ok': True})


class NoticeUploadHandler(BaseHandler):
    """上传公告图片到共享根目录的 _notice/（隐藏目录），返回可访问路径。仅管理员。"""

    def post(self):
        u = self.require_login()
        if not u:
            return
        if u['role'] != 'admin':
            self.json({'ok': False, 'error': self._t('err_notice_upload_perm')}, 403)
            return
        files = self.request.files.get('file')
        if not files:
            self.json({'ok': False, 'error': self._t('err_no_file')}, 400)
            return
        f = files[0]
        name = utils.sanitize_name(f.get('filename') or 'img.png')
        if not name or utils.preview_type(name) != 'image':
            self.json({'ok': False, 'error': self._t('err_img_only')}, 400)
            return
        ndir = os.path.join(config.CFG['root_dir'], '_notice')
        os.makedirs(ndir, exist_ok=True)
        base, ext = os.path.splitext(name)
        dst = os.path.join(ndir, '%s_%s%s' % (base, int(time.time()), ext))
        with open(dst, 'wb') as out:
            out.write(f['body'])
        self.log(u['username'], 'notice_upload', os.path.basename(dst))
        self.json({'ok': True, 'url': '/notice_img/' + urllib.parse.quote(os.path.basename(dst))})


class NoticeImgHandler(BaseHandler):
    """公告图片访问（公开）：从 _notice/ 目录安全读取。"""

    def get(self, name):
        p = utils.safe_join(os.path.join(config.CFG['root_dir'], '_notice'), name)
        if p is None or not os.path.isfile(p):
            self.set_status(404)
            self.finish('not found')
            return
        _stream_file(self, p, name, 'inline')


class FileShareHandler(BaseHandler):
    """文件分享链接：GET /s/f/<URL编码的相对路径>/<HMAC>。
       特点：不占用任何数据库记录；绕过可见性（私有也能下载）；只读下载、不可修改删除；
       换服务器 secret_key 后所有链接立即失效。"""

    def get(self, quoted, token):
        try:
            rel = urllib.parse.unquote(quoted)
        except Exception:
            self.set_status(404)
            self.finish(self._t('err_share_invalid'))
            return
        if not utils.verify_share(rel, token):
            self.set_status(404)
            self.finish(self._t('err_share_invalid'))
            return
        root = config.CFG['root_dir']
        p = utils.safe_join(root, rel)
        if p is None or not os.path.isfile(p):
            self.set_status(404)
            self.finish(self._t('err_file_deleted'))
            return
        name = os.path.basename(rel)
        inline = utils.preview_type(name) in ('image', 'pdf')   # 图片/PDF 直接预览，其余下载
        _stream_file(self, p, name, 'inline' if inline else 'attachment')
        self.log('share', 'share_download', rel)
