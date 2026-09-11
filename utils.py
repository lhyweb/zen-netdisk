# -*- coding: utf-8 -*-
"""工具函数：路径安全、文件名消毒、HMAC 分享校验、编码检测、内容类型、zip 打包等。
   所有对外暴露文件路径的接口都必须经过 safe_join，这是本工具最重要的防线。"""
import os
import re
import hmac
import hashlib
import urllib.parse

import config


def safe_join(root, rel):
    """把相对路径 rel 安全拼接到 root 下；任何越界 / 非法输入返回 None。
       root 为共享根目录绝对路径；rel 为 '/' 分隔的相对路径。"""
    if rel is None:
        return root
    if not isinstance(rel, str):
        return None
    if '\x00' in rel:
        return None
    rel = rel.replace('\\', '/').strip('/')
    if rel in ('', '.'):
        return root
    parts = rel.split('/')
    # 拒绝 ..、空段、绝对路径
    if any(p in ('..', '') for p in parts):
        return None
    root_abs = os.path.abspath(root)
    p = os.path.abspath(os.path.join(root_abs, *parts))
    if os.path.commonpath([root_abs, p]) != root_abs:
        return None
    return p


def sanitize_name(name):
    """上传文件名消毒：取 basename、去非法字符与 Windows 保留名、禁止 '_' 开头（防写入系统目录）。"""
    if not name:
        return ''
    name = name.replace('\\', '/')
    if '/' in name:
        name = name.rsplit('/', 1)[-1]
    name = name.strip().strip('. ')
    if not name or name.startswith('_'):
        return ''
    bad = '<>:"/\\|?*'
    name = ''.join(ch for ch in name if ch not in bad and ord(ch) >= 32).strip()
    if not name:
        return ''
    reserved = {'CON', 'PRN', 'AUX', 'NUL',
                'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
                'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'}
    if name.rsplit('.', 1)[0].upper() in reserved:
        return ''
    return name


# ---------------- 文件分享链接（HMAC，无任何额外存储） ----------------

def hmac_token(msg):
    """以服务器密钥对消息计算 HMAC-SHA256（hex）。"""
    return hmac.new(config.CFG['secret_key'].encode('utf-8'),
                    msg.encode('utf-8'), hashlib.sha256).hexdigest()


def share_link(rel):
    """生成文件的分享链接：/s/f/<URL编码的相对路径>/<HMAC>。"""
    return '/s/f/' + urllib.parse.quote(rel, safe='') + '/' + hmac_token(rel)


def verify_share(rel, token):
    """校验分享链接令牌是否有效（常数时间比较，防时序攻击）。"""
    return hmac.compare_digest(token, hmac_token(rel))


# ---------------- 文本编码与内容类型 ----------------

def detect_encoding(b):
    if b.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'
    for enc in ('utf-8', 'gb18030', 'gbk'):
        try:
            b.decode(enc)
            return enc
        except Exception:
            pass
    return 'latin-1'


_TEXT_EXTS = {'txt', 'md', 'log', 'py', 'js', 'html', 'htm', 'css', 'json', 'xml',
              'c', 'cpp', 'h', 'java', 'sh', 'yml', 'yaml', 'ini', 'conf', 'csv', 'sql', 'bat'}
_IMAGE_EXTS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'ico'}


def _ext(name):
    return name.rsplit('.', 1)[-1].lower() if '.' in name else ''


def content_type(name):
    ext = _ext(name)
    if ext in _IMAGE_EXTS:
        return {
            'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
            'gif': 'image/gif', 'webp': 'image/webp', 'bmp': 'image/bmp',
            'svg': 'image/svg+xml', 'ico': 'image/x-icon'}[ext]
    if ext == 'pdf':
        return 'application/pdf'
    if ext in _TEXT_EXTS:
        return 'text/plain; charset=utf-8'
    return 'application/octet-stream'


def preview_type(name):
    """返回可预览类型：image / pdf / text / none。"""
    ext = _ext(name)
    if ext in _IMAGE_EXTS:
        return 'image'
    if ext == 'pdf':
        return 'pdf'
    if ext in _TEXT_EXTS:
        return 'text'
    return 'none'


def rfc5987(name):
    """RFC 5987 中文文件名编码（Content-Disposition 用，避免下载名乱码）。"""
    return urllib.parse.quote(name)


# ---------------- 目录遍历 / zip ----------------

def walk_files_under(root, rel):
    """返回 rel 目录下所有文件的相对路径列表（跳过 '_' 开头的系统/隐藏项）。"""
    p = safe_join(root, rel)
    if p is None:
        return []
    if os.path.isfile(p):
        return [rel]
    out = []
    for dirpath, dirnames, filenames in os.walk(p):
        dirnames[:] = [d for d in dirnames if not d.startswith('_')]
        for fn in filenames:
            if fn.startswith('_'):
                continue
            out.append(os.path.relpath(os.path.join(dirpath, fn), root).replace('\\', '/'))
    return out


# ---------------- 公告富文本白名单过滤（防 XSS） ----------------

_ALLOWED_TAGS = {'b', 'strong', 'i', 'em', 'u', 'h1', 'h2', 'h3', 'h4',
                 'p', 'br', 'ul', 'ol', 'li', 'blockquote'}
_TAG_RE = re.compile(r'<([^>]+)>')


def sanitize_html(html):
    """公告页正文白名单过滤：只保留少量标签，img 仅允许本站 _notice 图片，其余一律转义。"""
    import html as htmlmod
    if not html:
        return ''
    out = []
    i = 0
    while i < len(html):
        if html[i] != '<':
            j = html.find('<', i)
            if j == -1:
                out.append(htmlmod.escape(html[i:]))
                break
            out.append(htmlmod.escape(html[i:j]))
            i = j
            continue
        # 处理标签
        j = html.find('>', i)
        if j == -1:
            out.append(htmlmod.escape(html[i:]))
            break
        raw = html[i + 1:j]
        inner = raw.strip()
        is_end = inner.startswith('/')
        tname = inner[1:].strip() if is_end else inner.split()[0].strip().lower()
        if tname in _ALLOWED_TAGS:
            if tname == 'br':
                out.append('<br>')
            elif is_end:
                out.append('</%s>' % tname)
            elif tname == 'img':
                m = re.search(r'src=["\']([^"\']*)["\']', inner)
                if m and m.group(1).startswith('/notice_img/'):
                    out.append('<img src="%s">' % htmlmod.escape(m.group(1), quote=True))
                # 非法的 img 直接丢弃
            else:
                out.append('<%s>' % tname)
        else:
            out.append(htmlmod.escape('<' + raw + '>'))
        i = j + 1
    return ''.join(out)
