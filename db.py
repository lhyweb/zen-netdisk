# -*- coding: utf-8 -*-
"""数据库模块：SQLite 建表与全部查询封装。
   设计要点：
   - 所有 SQL 一律参数化，杜绝注入；
   - files 表只存「属主/可见性/大小」等属性，文件本体以真实目录为准（目录扫描方案）；
   - 删除文件即删除其 DB 记录（回收站只扫 _trash 目录，不建表不加字段）；
   - settings 表以 key-value 存系统参数（站点标题/全局公告），改完实时生效；
   - users 表：用户名(登录ID) / 显示名称 / 密码 三个字段分开存储。
   每次操作新建连接，简单可靠，配合 WAL 模式支持并发读写。"""
import os
import time
import sqlite3

import config


def now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def conn():
    c = sqlite3.connect(config.CFG['db_path'])
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')   # 并发读写不互相锁死
    return c


def init():
    os.makedirs(os.path.dirname(config.CFG['db_path']) or '.', exist_ok=True)
    c = conn()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,      -- 登录 ID（唯一）
      display_name TEXT DEFAULT '',       -- 显示名称（空则用用户名显示）
      password_hash TEXT NOT NULL,        -- PBKDF2 加盐哈希
      role TEXT NOT NULL DEFAULT 'user',  -- admin / user / readonly / pending(待启用账户)
      enabled INTEGER DEFAULT 1,          -- 旧版「禁用」状态已合并为 role=pending，本列不再使用
      created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS settings(
      key TEXT PRIMARY KEY,               -- site_title / notice_title / notice_body / notice_enabled
      value TEXT
    );
    CREATE TABLE IF NOT EXISTS files(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      rel_path TEXT UNIQUE NOT NULL,      -- 相对共享根目录的路径（唯一索引）
      owner_id INTEGER,                   -- 上传者；NULL 视为 admin
      visibility TEXT DEFAULT 'public',   -- public 公开 / private 私有
      size INTEGER DEFAULT 0,
      created_at TEXT,
      updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS logs(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT,
      action TEXT,
      path TEXT,
      detail TEXT,
      ip TEXT,
      created_at TEXT
    );
    ''')
    # 兼容旧版本库：缺 display_name 列则补上（其余旧列不再使用，保留无碍）
    cols = [r['name'] for r in c.execute('PRAGMA table_info(users)').fetchall()]
    if 'display_name' not in cols:
        c.execute('ALTER TABLE users ADD COLUMN display_name TEXT DEFAULT ""')
    # V1.7 迁移：旧版「禁用」状态合并为「待启用账户」角色（enabled 列不再使用）
    c.execute("UPDATE users SET role='pending' WHERE enabled=0 AND role!='admin'")
    c.execute('UPDATE users SET enabled=1 WHERE enabled=0')
    c.commit()
    c.close()


# ---------------- 系统设置（settings 表） ----------------

def get_setting(key, default=''):
    c = conn()
    r = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    c.close()
    return r['value'] if r else default


def set_setting(key, value):
    c = conn()
    c.execute('INSERT INTO settings(key,value) VALUES(?,?) '
              'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))
    c.commit()
    c.close()


def site_title():
    """站点标题（左上角品牌文字），默认「巡察工作组资料平台V202609」。"""
    return (get_setting('site_title') or '').strip() or '巡察工作组资料平台V202609'


# ---------------- 用户 ----------------

def count_users():
    c = conn()
    n = c.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n']
    c.close()
    return n


def create_user(username, password_hash, role, display_name=''):
    c = conn()
    try:
        cur = c.execute(
            'INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)',
            (username, (display_name or '').strip(), password_hash, role, now()))
        c.commit()
        uid = cur.lastrowid
    except sqlite3.IntegrityError:
        uid = None
    c.close()
    return uid


def get_user_by_name(name):
    c = conn()
    r = c.execute('SELECT * FROM users WHERE username=?', (name,)).fetchone()
    c.close()
    return dict(r) if r else None


def find_user_login(login):
    """登录匹配：先按用户 ID（username）精确匹配，再按用户名称（display_name）匹配。
       用户名称全局唯一（含不得与他人 ID 重复），故按名称匹配结果唯一。"""
    login = (login or '').strip()
    if not login:
        return None
    c = conn()
    r = c.execute('SELECT * FROM users WHERE username=?', (login,)).fetchone()
    if r:
        c.close()
        return dict(r)
    r = c.execute('SELECT * FROM users WHERE display_name=?', (login,)).fetchone()
    c.close()
    return dict(r) if r else None


def is_pending(u):
    """待启用账户：不能登录（等价于旧版「禁用」）。"""
    return u is not None and u['role'] == 'pending'


def username_taken(name, exclude_uid=None):
    """用户 ID 是否与他人冲突：不得与他人用户 ID 或用户名称相同（防登录歧义）。"""
    name = (name or '').strip()
    if not name:
        return True
    c = conn()
    if exclude_uid:
        r = c.execute('SELECT 1 FROM users WHERE (username=? OR display_name=?) AND id!=?',
                      (name, name, exclude_uid)).fetchone()
    else:
        r = c.execute('SELECT 1 FROM users WHERE username=? OR display_name=?',
                      (name, name)).fetchone()
    c.close()
    return r is not None


def display_ok(display, username, uid=None):
    """用户名称是否可用：可留空、可等于自己的用户 ID；
       不得与他人用户 ID 或他人用户名称相同。uid 为 None 表示新用户。"""
    display = (display or '').strip()
    if not display or display == (username or '').strip():
        return True
    c = conn()
    if uid:
        r = c.execute('SELECT 1 FROM users WHERE (username=? OR display_name=?) AND id!=?',
                      (display, display, uid)).fetchone()
    else:
        r = c.execute('SELECT 1 FROM users WHERE username=? OR display_name=?',
                      (display, display)).fetchone()
    c.close()
    return r is None


def get_user_by_id(uid):
    c = conn()
    r = c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    c.close()
    return dict(r) if r else None


def display_name(u):
    """用户显示名：有显示名称用显示名称，否则用用户名。"""
    return (u.get('display_name') or '').strip() or u['username']


def owner_display(uid):
    """按属主 id 返回显示名（文件列表用）；uid 为空视为 admin。"""
    if uid is None:
        return 'admin'
    c = conn()
    r = c.execute('SELECT username,display_name FROM users WHERE id=?', (uid,)).fetchone()
    c.close()
    if not r:
        return 'admin'
    return (r['display_name'] or '').strip() or r['username']


def get_username(uid):
    if uid is None:
        return 'admin'
    c = conn()
    r = c.execute('SELECT username FROM users WHERE id=?', (uid,)).fetchone()
    c.close()
    return r['username'] if r else None


def list_users():
    c = conn()
    rs = c.execute('SELECT id,username,display_name,role,enabled,created_at FROM users ORDER BY id').fetchall()
    c.close()
    return [dict(r) for r in rs]


def update_user_role(uid, role):
    c = conn()
    c.execute('UPDATE users SET role=? WHERE id=?', (role, uid))
    c.commit()
    c.close()


def update_user_enabled(uid, enabled):
    c = conn()
    c.execute('UPDATE users SET enabled=? WHERE id=?', (1 if enabled else 0, uid))
    c.commit()
    c.close()


def update_user_password(uid, ph):
    c = conn()
    c.execute('UPDATE users SET password_hash=? WHERE id=?', (ph, uid))
    c.commit()
    c.close()


def update_user_username(uid, name):
    """修改用户 ID（登录 ID）。调用前应先经 username_taken 校验。"""
    c = conn()
    try:
        c.execute('UPDATE users SET username=? WHERE id=?', ((name or '').strip(), uid))
        c.commit()
        ok = True
    except Exception:
        ok = False
    c.close()
    return ok


def update_user_display(uid, name):
    c = conn()
    c.execute('UPDATE users SET display_name=? WHERE id=?', ((name or '').strip(), uid))
    c.commit()
    c.close()


def delete_user(uid):
    c = conn()
    c.execute('DELETE FROM users WHERE id=?', (uid,))
    c.commit()
    c.close()


# ---------------- 文件属性 ----------------

def get_file_by_path(rel):
    c = conn()
    r = c.execute('SELECT * FROM files WHERE rel_path=?', (rel,)).fetchone()
    c.close()
    return dict(r) if r else None


def get_files_by_paths(rels):
    """一次批量取多个文件属性（列表页避免逐文件查库）。"""
    if not rels:
        return {}
    c = conn()
    ph = ','.join('?' * len(rels))
    rs = c.execute('SELECT * FROM files WHERE rel_path IN (%s)' % ph, list(rels)).fetchall()
    c.close()
    return {r['rel_path']: dict(r) for r in rs}


def upsert_file(rel, owner_id, visibility, size):
    c = conn()
    c.execute(
        'INSERT INTO files(rel_path,owner_id,visibility,size,created_at,updated_at) '
        'VALUES(?,?,?,?,?,?) '
        'ON CONFLICT(rel_path) DO UPDATE SET owner_id=?,visibility=?,size=?,updated_at=?',
        (rel, owner_id, visibility, size, now(), now(),
         owner_id, visibility, size, now()))
    c.commit()
    c.close()


def set_visibility(rel, vis):
    c = conn()
    c.execute('UPDATE files SET visibility=? WHERE rel_path=?', (vis, rel))
    c.commit()
    c.close()


def update_file_size(rel, size):
    c = conn()
    c.execute('UPDATE files SET size=?, updated_at=? WHERE rel_path=?', (size, now(), rel))
    c.commit()
    c.close()


def delete_file(rel):
    c = conn()
    c.execute('DELETE FROM files WHERE rel_path=?', (rel,))
    c.commit()
    c.close()


def like_escape(s):
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def delete_files_under(prefix):
    """删除某个目录前缀下的所有文件记录（含该目录本身）。"""
    c = conn()
    c.execute("DELETE FROM files WHERE rel_path=? OR rel_path LIKE ? ESCAPE '\\'",
              (prefix, like_escape(prefix) + '/%'))
    c.commit()
    c.close()


# ---------------- 操作日志 ----------------

def add_log(username, action, path='', detail='', ip=''):
    try:
        c = conn()
        c.execute('INSERT INTO logs(username,action,path,detail,ip,created_at) VALUES(?,?,?,?,?,?)',
                  (username, action, path, detail, ip, now()))
        c.commit()
        c.close()
    except Exception:
        pass   # 日志失败不影响主流程


def list_logs(limit=300):
    c = conn()
    rs = c.execute('SELECT * FROM logs ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rs]


# ---------------- 重置系统（清空数据库，文件保留） ----------------

def reset_all():
    """清空全部数据（账号/系统设置/文件属性/日志），共享文件本体保留。
       清空后系统回到无账号状态，网页 /setup 重新引导创建管理员。"""
    c = conn()
    for t in ('users', 'files', 'logs', 'settings'):
        c.execute('DELETE FROM %s' % t)
    c.commit()
    c.close()
