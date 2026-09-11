# -*- coding: utf-8 -*-
"""管理模块：管理后台页、用户管理（含批量新增）、站点标题、操作日志、回收站清单、重置系统。"""
import os
import json

import config
import db
import auth
from auth import BaseHandler

ROLES = ('admin', 'user', 'readonly', 'pending')   # 角色顺序：管理员/普通/只读/待启用


class AdminPanelHandler(BaseHandler):
    def get(self):
        u = self.require_login()
        if not u:
            return
        if u['role'] != 'admin':
            self.redirect('/')
            return
        self.render('admin.html', current_user=u,
                    is_super_admin=self.is_super_admin(u))


class UsersHandler(BaseHandler):
    def get(self):
        u = self.require_login()
        if not u or u['role'] != 'admin':
            self.json({'ok': False, 'error': self._t('err_no_perm')}, 403)
            return
        self.json({'ok': True, 'users': db.list_users()})


class UserAddHandler(BaseHandler):
    def post(self):
        u = self.require_login()
        if not u or u['role'] != 'admin':
            self.json({'ok': False, 'error': self._t('err_no_perm')}, 403)
            return
        try:
            body = json.loads(self.request.body)
        except Exception:
            self.json({'ok': False, 'error': self._t('err_bad_params')}, 400)
            return
        name = body.get('username', '').strip()
        pw = body.get('password', '')
        role = body.get('role', 'user')
        dname = (body.get('display_name', '') or '').strip()[:30]
        if not name:
            self.json({'ok': False, 'error': self._t('err_username_empty')}, 400)
            return
        if not pw:
            self.json({'ok': False, 'error': self._t('err_pw_empty')}, 400)
            return
        if role not in ROLES:
            role = 'user'
        if db.username_taken(name):
            self.json({'ok': False, 'error': self._t('err_user_exists')}, 409)
            return
        if not db.display_ok(dname, name):
            self.json({'ok': False, 'error': self._t('err_name_taken')}, 409)
            return
        uid = db.create_user(name, auth.hash_password(pw), role, dname)
        if uid is None:
            self.json({'ok': False, 'error': self._t('err_user_exists')}, 409)
            return
        self.log(u['username'], 'add_user', '', name)
        self.json({'ok': True})


class UserBatchAddHandler(BaseHandler):
    """批量新增用户：多行用户 ID（换行分隔）+ 统一初始密码，角色=普通用户，用户名称=用户 ID。
       逐条校验：重复/非法 ID 跳过并在返回中汇总，其余正常创建。"""

    def post(self):
        u = self.require_login()
        if not u or u['role'] != 'admin':
            self.json({'ok': False, 'error': self._t('err_no_perm')}, 403)
            return
        try:
            body = json.loads(self.request.body)
        except Exception:
            self.json({'ok': False, 'error': self._t('err_bad_params')}, 400)
            return
        pw = body.get('password', '')
        if not pw:
            self.json({'ok': False, 'error': self._t('err_pw_empty')}, 400)
            return
        ids = [x.strip() for x in (body.get('ids', '') or '').splitlines()]
        ids = [x for x in ids if x]
        if not ids:
            self.json({'ok': False, 'error': self._t('err_username_empty')}, 400)
            return
        created, skipped = [], []
        for name in ids:
            if not name or db.username_taken(name):
                skipped.append(name)
                continue
            uid = db.create_user(name, auth.hash_password(pw), 'user', name)
            if uid is None:
                skipped.append(name)
            else:
                created.append(name)
        self.log(u['username'], 'batch_add_user', '', '%d/%d' % (len(created), len(ids)))
        self.json({'ok': True, 'created': created, 'skipped': skipped})


class UserUpdateHandler(BaseHandler):
    """修改用户 ID / 用户名称 / 角色。"""

    def post(self):
        u = self.require_login()
        if not u or u['role'] != 'admin':
            self.json({'ok': False, 'error': self._t('err_no_perm')}, 403)
            return
        try:
            body = json.loads(self.request.body)
        except Exception:
            self.json({'ok': False, 'error': self._t('err_bad_params')}, 400)
            return
        uid = body.get('id')
        target = db.get_user_by_id(uid)
        if not target:
            self.json({'ok': False, 'error': self._t('err_user_not_found')}, 404)
            return
        # 用户 ID（登录 ID）：非空、不得与他人 ID/名称重复；admin 锁定不可改
        if 'username' in body:
            if target['username'].lower() == 'admin':
                self.json({'ok': False, 'error': self._t('err_admin_locked')}, 400)
                return
            new_name = (body.get('username') or '').strip()[:30]
            if not new_name:
                self.json({'ok': False, 'error': self._t('err_username_empty')}, 400)
                return
            if db.username_taken(new_name, uid):
                self.json({'ok': False, 'error': self._t('err_user_exists')}, 409)
                return
            db.update_user_username(uid, new_name)
            self.log(u['username'], 'rename_user_id', '', '%s -> %s' % (target['username'], new_name))
        # 用户名称：可留空、可等于自己的 ID、不得与他人 ID/名称重复
        if 'display_name' in body:
            dname = (body.get('display_name') or '').strip()[:30]
            cur_username = body.get('username', '').strip() or target['username']
            if not db.display_ok(dname, cur_username, uid):
                self.json({'ok': False, 'error': self._t('err_name_taken')}, 409)
                return
            db.update_user_display(uid, dname)
            self.log(u['username'], 'set_display_name', '', '%s -> %s' % (
                target['username'], dname or '(默认用户 ID)'))
        # 角色：不能改自己
        role = body.get('role')
        if role is not None:
            if target['id'] == u['id']:
                self.json({'ok': False, 'error': self._t('err_self_role')}, 400)
                return
            if role not in ROLES:
                role = 'user'
            db.update_user_role(uid, role)
            self.log(u['username'], 'set_role', '', '%s -> %s' % (target['username'], role))
        self.json({'ok': True})


class UserPasswordHandler(BaseHandler):
    def post(self):
        u = self.require_login()
        if not u or u['role'] != 'admin':
            self.json({'ok': False, 'error': self._t('err_no_perm')}, 403)
            return
        try:
            body = json.loads(self.request.body)
        except Exception:
            self.json({'ok': False, 'error': self._t('err_bad_params')}, 400)
            return
        uid = body.get('id')
        pw = body.get('password', '')
        cf = body.get('confirm')
        if not pw:
            self.json({'ok': False, 'error': self._t('err_pw_empty')}, 400)
            return
        if cf is not None and pw != cf:
            self.json({'ok': False, 'error': self._t('pw_mismatch')}, 400)
            return
        db.update_user_password(uid, auth.hash_password(pw))
        self.log(u['username'], 'reset_password', '', 'uid=%s' % uid)
        self.json({'ok': True})


class UserDeleteHandler(BaseHandler):
    def post(self):
        u = self.require_login()
        if not u or u['role'] != 'admin':
            self.json({'ok': False, 'error': self._t('err_no_perm')}, 403)
            return
        try:
            body = json.loads(self.request.body)
        except Exception:
            self.json({'ok': False, 'error': self._t('err_bad_params')}, 400)
            return
        uid = body.get('id')
        target = db.get_user_by_id(uid)
        if not target:
            self.json({'ok': False, 'error': self._t('err_user_not_found')}, 404)
            return
        if target['id'] == u['id']:
            self.json({'ok': False, 'error': self._t('err_self_delete')}, 400)
            return
        if target['role'] == 'admin':
            admins = [x for x in db.list_users() if x['role'] == 'admin']
            if len(admins) <= 1:
                self.json({'ok': False, 'error': self._t('err_min_admin')}, 400)
                return
        db.delete_user(uid)
        self.log(u['username'], 'delete_user', '', target['username'])
        self.json({'ok': True})


class SiteHandler(BaseHandler):
    """站点标题：仅最高管理员（用户 ID 为 admin，大小写不敏感）可读写。"""

    def get(self):
        u = self.require_login()
        if not u or not self.is_super_admin(u):
            self.json({'ok': False, 'error': self._t('err_no_perm')}, 403)
            return
        self.json({'ok': True, 'site_title': db.site_title()})

    def post(self):
        u = self.require_login()
        if not u or not self.is_super_admin(u):
            self.json({'ok': False, 'error': self._t('err_no_perm')}, 403)
            return
        try:
            body = json.loads(self.request.body)
        except Exception:
            self.json({'ok': False, 'error': self._t('err_bad_params')}, 400)
            return
        title = (body.get('site_title', '') or '').strip()[:40]
        db.set_setting('site_title', title)
        self.log(u['username'], 'set_site_title', '', title)
        self.json({'ok': True, 'site_title': db.site_title()})


class LogsHandler(BaseHandler):
    def get(self):
        u = self.require_login()
        if not u or u['role'] != 'admin':
            self.json({'ok': False, 'error': self._t('err_no_perm')}, 403)
            return
        self.json({'ok': True, 'logs': db.list_logs(300)})


class RecycleHandler(BaseHandler):
    """回收站清单：直接扫描 _trash/ 目录（文件名自带删除时间戳），不建表。"""

    def get(self):
        u = self.require_login()
        if not u or u['role'] != 'admin':
            self.json({'ok': False, 'error': self._t('err_no_perm')}, 403)
            return
        trash = os.path.join(config.CFG['root_dir'], '_trash')
        items = []
        if os.path.isdir(trash):
            for n in sorted(os.listdir(trash)):
                fp = os.path.join(trash, n)
                is_dir = os.path.isdir(fp)
                size = 0 if is_dir else os.path.getsize(fp)
                items.append({'name': n, 'size': size,
                              'mtime': int(os.path.getmtime(fp)), 'is_dir': is_dir})
        self.json({'ok': True, 'items': items})


class ResetHandler(BaseHandler):
    """重置系统：仅最高管理员；清空数据库（账号/设置/文件属性/日志），共享文件本体保留。
       清空后当前会话失效，前端跳转 /setup 重新创建管理员。"""

    def post(self):
        u = self.require_login()
        if not u or not self.is_super_admin(u):
            self.json({'ok': False, 'error': self._t('err_no_perm')}, 403)
            return
        db.reset_all()
        self.clear_cookie('uid')
        self.log(u['username'], 'reset_system')
        self.json({'ok': True, 'setup': True})
