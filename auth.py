# -*- coding: utf-8 -*-
"""认证模块：密码哈希、登录会话（secure_cookie）、权限判定、BaseHandler 基类。
   会话不建表：登录后把 uid 写入 Tornado 签名 cookie，退出即清除。
   权限判定收敛成 visible() / can_manage() 两个函数，后续改权限只改这里。"""
import os
import sys
import hashlib
import hmac
import json

import tornado.web

import config
import db
import i18n

PBKDF2_ITER = 100000


def hash_password(pw, salt=None):
    """PBKDF2-SHA256 加盐哈希，输出格式：salt_hex$hash_hex。"""
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt, PBKDF2_ITER)
    return salt.hex() + '$' + dk.hex()


def verify_password(pw, stored):
    try:
        salt_hex, _, dk_hex = stored.partition('$')
        salt = bytes.fromhex(salt_hex)
    except Exception:
        return False
    dk = hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt, PBKDF2_ITER)
    return hmac.compare_digest(dk.hex(), dk_hex)


def visible(user, fileinfo):
    """判断某文件对用户是否可见。
       fileinfo 为 files 表记录 dict 或 None；
       None 表示磁盘上无记录的文件（直接复制进根目录的），视为属主 admin、公开。"""
    if user and user['role'] == 'admin':
        return True
    if fileinfo is None:
        return True
    if fileinfo['visibility'] == 'public':
        return True
    return user is not None and fileinfo['owner_id'] == user['id']


def can_manage(user, fileinfo):
    """判断用户能否管理（覆盖/删除/改可见性/编辑）某文件。"""
    if not user:
        return False
    if user['role'] == 'admin':
        return True
    if fileinfo is None:            # 无记录文件视为 admin 所有
        return False
    return fileinfo['owner_id'] == user['id']


class BaseHandler(tornado.web.RequestHandler):
    """所有 handler 的基类：会话、权限、JSON、日志等公共能力。"""

    def prepare(self):
        # 提前生成 XSRF cookie，供前端 fetch 携带
        self.xsrf_token

    # ---------- 会话 ----------
    def current_user_obj(self):
        b = self.get_secure_cookie('uid')
        if not b:
            return None
        try:
            uid = int(b)
        except Exception:
            return None
        u = db.get_user_by_id(uid)
        if db.is_pending(u):      # 待启用账户的旧会话一律失效
            return None
        return u

    def require_login(self):
        """要求登录；未登录时 API 返回 401、页面跳转登录。返回当前用户 dict 或 None。"""
        u = self.current_user_obj()
        if not u:
            if self.request.path.startswith('/api') or self.request.path.startswith('/admin'):
                self.json({'ok': False, 'error': self._t('err_not_login')}, 401)
            else:
                self.redirect('/login')
            return None
        return u

    def set_auth_cookie(self, uid):
        """写入登录会话 cookie（签名 + HttpOnly）。
           SameSite=Lax 仅 Python 3.8+ 附加：3.7 的 http.cookies 标准库
           Morsel 不识别 samesite 属性，会抛 CookieError，故自动省略。"""
        kw = {'httponly': True}
        if sys.version_info >= (3, 8):
            kw['samesite'] = 'Lax'
        self.set_secure_cookie('uid', str(uid),
                               expires_days=config.CFG['session_hours'] / 24.0, **kw)

    def is_admin(self, u):
        return u['role'] == 'admin'

    def is_super_admin(self, u):
        """最高管理员：仅用户 ID 为 admin（大小写不敏感）的管理员，可见系统设置。"""
        return u and u['role'] == 'admin' and (u['username'] or '').lower() == 'admin'

    # ---------- 国际化 ----------
    @property
    def L(self):
        """当前语言字典（cookie lang=zh/en，默认中文）。"""
        return i18n.lang_of(self.get_cookie('lang', 'zh'))

    def _t(self, key):
        """取当前语言文案；未知 key 原样返回。"""
        return self.L.get(key, key)

    # ---------- 输出 ----------
    def json(self, obj, status=200):
        self.set_status(status)
        self.set_header('Content-Type', 'application/json; charset=utf-8')
        self.write(json.dumps(obj, ensure_ascii=False))

    def render(self, *args, **kwargs):
        """统一注入模板变量：站点标题（数据库实时生效）、当前用户显示名、语言字典 L。"""
        kwargs.setdefault('site_title', db.site_title())
        kwargs.setdefault('L', self.L)
        u = self.current_user_obj()
        kwargs.setdefault('display_name', db.display_name(u) if u else '')
        super().render(*args, **kwargs)

    # ---------- 日志 ----------
    def log(self, username, action, path='', detail=''):
        db.add_log(username, action, path, detail, self.request.remote_ip)
