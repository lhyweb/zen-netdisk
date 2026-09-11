# -*- coding: utf-8 -*-
"""配置模块：读取 / 生成 setup.ini，把参数集中到全局 config.CFG。
   所有可调参数都在这一个文件里管理，方便二次修改。
   多实例做法：复制整个项目目录，改 setup.ini 里的端口与 root_dir 即可独立运行。"""
import os
import configparser
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # 项目根目录
INI_PATH = os.path.join(BASE_DIR, 'setup.ini')           # 配置文件路径
CFG = {}                                                 # 全局配置字典（load() 后填充）

# 统一认证（SSO）跳转地址：登录页「跳转到统一认证登录」按钮指向。
# 本阶段为示例地址，正式对接时请手工修改为真实认证系统地址。
SSO_URL = 'http://192.168.0.1/auth'

DEFAULT_INI = """[server]
; 监听端口（默认 8080；如需用 80 可改，但 Windows 上可能需管理员权限）
port = 8080
; 监听地址，0.0.0.0 表示局域网所有网卡均可访问
host = 0.0.0.0
; 共享根目录：真实文件都放这里（可改成任意独立路径，如 D:/共享文件）
root_dir = ./files
; 单文件上传大小上限（MB）
max_upload_mb = 500

[database]
; SQLite 数据库文件路径（记录账号/文件属性/日志）
db_path = ./netdisk.db

[security]
; 会话有效时长（小时），到期需重新登录
session_hours = 8
; 服务器密钥：首次启动自动生成随机值，用于签名登录会话与文件分享链接
; 更换该值会使所有会话与分享链接失效
secret_key =

[admin]
; 首次初始化时创建的管理员账号名（仅在系统无任何账号时生效）
username = admin
"""


def load():
    """读取 setup.ini 并填充 CFG；不存在时先自动生成默认配置。"""
    if not os.path.exists(INI_PATH):
        generate_default()
    p = configparser.ConfigParser()
    p.read(INI_PATH, encoding='utf-8')
    try:
        port = p.getint('server', 'port')
        host = p.get('server', 'host', fallback='0.0.0.0')
        root = p.get('server', 'root_dir', fallback='./files')
        max_mb = p.getint('server', 'max_upload_mb', fallback=500)
        db_path = p.get('database', 'db_path', fallback='./netdisk.db')
        session_hours = p.getint('security', 'session_hours', fallback=8)
        secret = p.get('security', 'secret_key', fallback='').strip()
        admin_user = p.get('admin', 'username', fallback='admin').strip()
    except Exception as e:
        raise SystemExit('setup.ini 解析失败：%s' % e)
    if not secret:
        raise SystemExit('setup.ini 缺少 secret_key，请删除 setup.ini 后重新启动以自动生成。')
    # 相对路径一律以项目目录为基准解析
    root = os.path.abspath(root if os.path.isabs(root) else os.path.join(BASE_DIR, root))
    db_path = os.path.abspath(db_path if os.path.isabs(db_path) else os.path.join(BASE_DIR, db_path))
    os.makedirs(root, exist_ok=True)
    CFG.update(
        port=port,
        host=host,
        root_dir=root,
        max_upload_mb=max_mb,
        max_upload_bytes=max_mb * 1024 * 1024,
        db_path=db_path,
        session_hours=session_hours,
        secret_key=secret,
        admin_user=admin_user,
        base_dir=BASE_DIR,
    )


def generate_default():
    """首次运行：生成带随机 secret_key 的 setup.ini。"""
    secret = secrets.token_hex(32)
    text = DEFAULT_INI.replace('secret_key =\n', 'secret_key = %s\n' % secret)
    with open(INI_PATH, 'w', encoding='utf-8') as f:
        f.write(text)
    print('[初始化] 已生成 setup.ini（内含随机 secret_key，请妥善保管）')
