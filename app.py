# -*- coding: utf-8 -*-
"""局域网网盘 · 入口文件
   用法：python app.py
   流程：加载 setup.ini → 初始化数据库 → 注册路由 → 启动 Tornado。
   首次运行会自动生成 setup.ini，并在网页 /setup 引导创建管理员。"""
import os
import glob
import socket
import time

import tornado.web
import tornado.ioloop

import config
import db
from handlers import files, user, admin, share


def cleanup_stale_tmp():
    """清理上次异常退出遗留的上传临时文件（up_*，超过 1 小时）。"""
    for f in glob.glob(os.path.join(config.CFG['base_dir'], 'up_*')):
        try:
            if time.time() - os.path.getmtime(f) > 3600:
                os.unlink(f)
        except Exception:
            pass


def make_app():
    base = config.CFG['base_dir']
    settings = dict(
        template_path=os.path.join(base, 'templates'),
        static_path=os.path.join(base, 'static'),
        cookie_secret=config.CFG['secret_key'],     # 会话与分享链接共用同一密钥
        xsrf_cookies=True,
        debug=False,
        max_body_size=config.CFG['max_upload_bytes'] + 2 * 1024 * 1024,
        max_buffer_size=config.CFG['max_upload_bytes'] + 4 * 1024 * 1024,
    )
    handlers = [
        # 页面
        (r'/', files.FilePageHandler),
        (r'/login', user.LoginHandler),
        (r'/icbc', user.IcbcHandler),        # 统一认证（SSO）回调
        (r'/logout', user.LogoutHandler),
        (r'/setup', user.SetupHandler),
        (r'/settings', user.SettingsHandler),
        (r'/admin', admin.AdminPanelHandler),
        # 文件接口
        (r'/api/list', files.ListHandler),
        (r'/api/upload', files.UploadHandler),
        (r'/api/download', files.DownloadHandler),
        (r'/api/text', files.TextHandler),
        (r'/api/delete', files.DeleteHandler),
        (r'/api/zip', files.ZipHandler),
        (r'/api/visibility', files.VisibilityHandler),
        (r'/api/mkdir', files.MkdirHandler),
        # 用户接口
        (r'/api/me', user.MeHandler),
        (r'/api/password', user.PasswordHandler),
        (r'/api/display-name', user.DisplayNameHandler),
        # 公告接口（全局公告，管理员维护）
        (r'/api/notice', share.NoticeHandler),
        (r'/api/notice/upload', share.NoticeUploadHandler),
        (r'/notice_img/([^/]+)', share.NoticeImgHandler),
        # 管理接口
        (r'/admin/api/users', admin.UsersHandler),
        (r'/admin/api/user/add', admin.UserAddHandler),
        (r'/admin/api/user/batch', admin.UserBatchAddHandler),
        (r'/admin/api/user/update', admin.UserUpdateHandler),
        (r'/admin/api/user/password', admin.UserPasswordHandler),
        (r'/admin/api/user/delete', admin.UserDeleteHandler),
        (r'/admin/api/logs', admin.LogsHandler),
        (r'/admin/api/recycle', admin.RecycleHandler),
        (r'/admin/api/site', admin.SiteHandler),
        (r'/admin/api/reset', admin.ResetHandler),
        # 文件分享链接（HMAC 无存储；访客只能下载查看，不能修改）
        (r'/s/f/([^/]+)/([0-9a-f]{64})', share.FileShareHandler),
    ]
    return tornado.web.Application(handlers, **settings)


def lan_ip():
    """探测本机在局域网中的 IP（用于打印访问地址）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


def main():
    config.load()
    db.init()
    cleanup_stale_tmp()
    app = make_app()
    port = config.CFG['port']
    print('=' * 54)
    print('  %s 已启动' % db.site_title())
    print('  本机访问   : http://127.0.0.1:%d' % port)
    print('  局域网访问 : http://%s:%d' % (lan_ip(), port))
    if db.count_users() == 0:
        print('  首次运行：请打开上方地址，在网页上完成管理员初始化')
    print('  共享根目录 : %s' % config.CFG['root_dir'])
    print('  配置文件   : %s' % os.path.join(config.CFG['base_dir'], 'setup.ini'))
    print('=' * 54)
    app.listen(port, address=config.CFG['host'])
    tornado.ioloop.IOLoop.current().start()


if __name__ == '__main__':
    main()
