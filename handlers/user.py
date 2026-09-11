# -*- coding: utf-8 -*-
"""用户模块：首次初始化、登录/退出、统一认证回调、我的设置页、修改密码、修改用户名称。"""
import base64
import json
import secrets

import tornado.web

import config
import db
import auth
from auth import BaseHandler


class SetupHandler(BaseHandler):
    """首次运行引导：创建第一个管理员。
       - 系统无账号：显示初始化表单（含站点标题、固定 admin/系统管理员、密码）；
       - 已有账号：本机（127.0.0.1）访问时自动以最早创建的管理员登录；其他电脑跳转登录页。"""

    def get(self):
        if db.count_users() == 0:
            self.render('setup.html', error='', site_title_default=db.site_title())
            return
        ip = (self.request.remote_ip or '')
        if ip.startswith('127.0.0.1') or ip == '::1':
            admin = self._earliest_admin()
            if admin:
                self.set_auth_cookie(admin['id'])
                self.redirect('/')
                return
        self.redirect('/login')

    def _earliest_admin(self):
        """最早创建的管理员（ID 最小）。"""
        c = db.conn()
        r = c.execute("SELECT * FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
        c.close()
        return dict(r) if r else None

    def post(self):
        if db.count_users() > 0:
            self.redirect('/login')
            return
        # 最高管理员账号锁定：admin / 系统管理员（不可修改，前端置灰，后端强制）
        name = 'admin'
        dname = '系统管理员'
        pw = self.get_argument('password', '')
        cf = self.get_argument('confirm', '')
        if not pw:
            self.render('setup.html', error=self._t('err_pw_empty'),
                        site_title_default=db.site_title())
            return
        if pw != cf:
            self.render('setup.html', error=self._t('pw_mismatch'),
                        site_title_default=db.site_title())
            return
        title = self.get_argument('site_title', '').strip()[:40]
        if title:
            db.set_setting('site_title', title)
        uid = db.create_user(name, auth.hash_password(pw), 'admin', dname)
        if uid is None:
            self.render('setup.html', error=self._t('err_user_exists'),
                        site_title_default=db.site_title())
            return
        self.set_auth_cookie(uid)
        self.log(name, 'setup_admin')
        self.redirect('/')


class LoginHandler(BaseHandler):
    def get(self):
        if self.current_user_obj():
            self.redirect('/')
            return
        self.render('login.html', error='', sso_url=config.SSO_URL)

    def post(self):
        name = self.get_argument('username', '').strip()
        pw = self.get_argument('password', '')
        u = db.find_user_login(name)
        if not u or not auth.verify_password(pw, u['password_hash']):
            self.log(name or '?', 'login_fail', '', '')
            self.render('login.html', error=self._t('err_bad_creds'), sso_url=config.SSO_URL)
            return
        if db.is_pending(u):
            self.render('login.html', error=self._t('err_pending'), sso_url=config.SSO_URL)
            return
        self.set_auth_cookie(u['id'])
        self.log(u['username'], 'login')
        self.redirect('/')


class IcbcHandler(BaseHandler):
    """统一认证回调（SSO）：GET /icbc?code=<base64>。
       解码 JSON 取 ID：
       - ID 存在且可登录 → 直接登录；
       - ID 存在但待启用 → 提示需管理员启用；
       - ID 不存在 → 自动创建待启用账号（用户名称留空默认显示 ID，随机密码）。
       注意：本阶段未验签，正式对接时请在此处增加签名/共享密钥校验。"""

    def get(self):
        code = self.get_argument('code', '')
        try:
            raw = base64.b64decode(code + '===')
            payload = json.loads(raw.decode('utf-8'))
        except Exception:
            self.render('login.html', error=self._t('err_bad_params'), sso_url=config.SSO_URL)
            return
        login_id = str(payload.get('ID') or payload.get('id') or payload.get('username') or '').strip()
        if not login_id:
            self.render('login.html', error=self._t('err_bad_params'), sso_url=config.SSO_URL)
            return
        u = db.get_user_by_name(login_id)
        if not u:
            # 自动创建待启用账号：随机密码（启用后由管理员重置）
            db.create_user(login_id, auth.hash_password(secrets.token_hex(8)), 'pending', '')
            self.log('sso', 'sso_create_pending', '', login_id)
            self.render('login.html', error=self._t('err_pending_created') % login_id,
                        sso_url=config.SSO_URL)
            return
        if db.is_pending(u):
            self.log(u['username'], 'sso_pending_blocked', '', login_id)
            self.render('login.html', error=self._t('err_pending_detail') % db.display_name(u),
                        sso_url=config.SSO_URL)
            return
        self.set_auth_cookie(u['id'])
        self.log(u['username'], 'sso_login')
        self.redirect('/')


class LogoutHandler(BaseHandler):
    def post(self):
        self.clear_cookie('uid')
        self.redirect('/login')


class SettingsHandler(BaseHandler):
    """我的设置页：我的资料（用户 ID / 用户名称）、修改密码。"""

    def get(self):
        u = self.require_login()
        if not u:
            return
        self.render('settings.html', current_user=u)


class MeHandler(BaseHandler):
    """当前用户信息（设置页用）。"""

    def get(self):
        u = self.require_login()
        if not u:
            return
        self.json({'ok': True, 'username': u['username'],
                   'display_name': db.display_name(u),
                   'role': u['role'],
                   'max_upload_mb': config.CFG['max_upload_mb']})


class PasswordHandler(BaseHandler):
    """修改自己的密码（不能为空，长度不限）。"""

    def post(self):
        u = self.require_login()
        if not u:
            return
        try:
            body = json.loads(self.request.body)
        except Exception:
            self.json({'ok': False, 'error': self._t('err_bad_params')}, 400)
            return
        old = body.get('old', '')
        new = body.get('new', '')
        if not new:
            self.json({'ok': False, 'error': self._t('err_pw_empty')}, 400)
            return
        if not auth.verify_password(old, u['password_hash']):
            self.json({'ok': False, 'error': self._t('err_old_pw')}, 403)
            return
        db.update_user_password(u['id'], auth.hash_password(new))
        self.log(u['username'], 'change_password')
        self.json({'ok': True})


class DisplayNameHandler(BaseHandler):
    """修改自己的用户名称（可留空=显示用户 ID；不得与他人用户 ID/名称重复）。"""

    def post(self):
        u = self.require_login()
        if not u:
            return
        try:
            body = json.loads(self.request.body)
        except Exception:
            self.json({'ok': False, 'error': self._t('err_bad_params')}, 400)
            return
        name = (body.get('display_name', '') or '').strip()[:30]
        if not db.display_ok(name, u['username'], u['id']):
            self.json({'ok': False, 'error': self._t('err_name_taken')}, 409)
            return
        db.update_user_display(u['id'], name)
        self.log(u['username'], 'set_display_name', '', name)
        self.json({'ok': True})
