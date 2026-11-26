#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把有道云笔记导出的 Markdown 批量转成 PDF。

- 图片按相对路径读取后内嵌为 base64，PDF 自包含，不会裂图
- 使用本机 Chrome 无头模式打印，无需安装 pandoc / LaTeX / 额外 Python 包

用法：
    python md2pdf.py <笔记目录> <输出目录>
"""

import base64
import html
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

CSS = """
@page { size: A4; margin: 16mm 15mm 15mm 15mm; }
* { box-sizing: border-box; }
body { font-family: "Microsoft YaHei", "PingFang SC", sans-serif; font-size: 11pt;
       line-height: 1.9; color: #1f2328; margin: 0; }
h1 { font-size: 17pt; margin: 0 0 10px; padding-bottom: 10px; border-bottom: 2px solid #1f6feb;
     color: #0b2e59; line-height: 1.4; }
h2 { font-size: 13.5pt; margin: 20px 0 8px; padding-left: 9px; border-left: 4px solid #1f6feb;
     color: #0b2e59; page-break-after: avoid; }
h3 { font-size: 12pt; margin: 16px 0 6px; color: #24303f; page-break-after: avoid; }
p { margin: 8px 0; text-align: justify; }
ul, ol { margin: 8px 0 8px 22px; padding: 0; }
li { margin: 4px 0; }
img { max-width: 100%; display: block; margin: 10px auto; }
code { font-family: Consolas, monospace; font-size: 9.6pt; background: #eff2f5;
       padding: 1px 4px; border-radius: 3px; }
pre { background: #f6f8fa; border: 1px solid #e1e6eb; border-radius: 4px; padding: 10px 12px;
      margin: 10px 0; page-break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 9pt; white-space: pre-wrap; word-break: break-all; }
table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 10pt; }
th { background: #eef3f9; border: 1px solid #d0d7de; padding: 6px 9px; text-align: left; }
td { border: 1px solid #d0d7de; padding: 6px 9px; vertical-align: top; }
tr { page-break-inside: avoid; }
blockquote { margin: 10px 0; padding: 8px 12px; background: #fbf7e8;
             border-left: 4px solid #d4a72c; color: #4a3f1d; }
hr { border: none; border-top: 1px solid #d8dee4; margin: 18px 0; }
a { color: #1f6feb; text-decoration: none; }
"""


def data_uri(path):
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        return "data:%s;base64,%s" % (mime, base64.b64encode(f.read()).decode())


def inline(text, md_dir):
    """行内语法：图片、链接、行内代码、粗体"""
    text = html.escape(text, quote=False)

    def img_repl(m):
        alt, src = m.group(1), html.unescape(m.group(2))
        if re.match(r"^(https?:|data:)", src):
            return '<img src="%s" alt="%s"/>' % (src, alt)
        p = os.path.normpath(os.path.join(md_dir, src))
        if os.path.exists(p):
            return '<img src="%s" alt="%s"/>' % (data_uri(p), alt)
        return '<span style="color:#a32d2d">[图片缺失: %s]</span>' % html.escape(src)

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", img_repl, text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return text


def is_table_sep(line):
    s = line.strip()
    return bool(re.fullmatch(r"\|[\s:\-\|]+\|", s)) and "-" in s


def convert(md_text, md_dir):
    lines = md_text.replace("\r\n", "\n").split("\n")
    out, i, n = [], 0, len(lines)
    bullet = re.compile(r"^[·•]\s+")

    while i < n:
        line = lines[i]
        s = line.strip()

        if not s:
            i += 1
            continue

        if s.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>%s</code></pre>" % html.escape("\n".join(buf)))
            continue

        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            lvl = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lvl, inline(m.group(2), md_dir), lvl))
            i += 1
            continue

        if re.fullmatch(r"-{3,}|\*{3,}", s):
            out.append("<hr/>")
            i += 1
            continue

        if s.startswith("|") and i + 1 < n and is_table_sep(lines[i + 1]):
            heads = [c.strip() for c in s.strip("|").split("|")]
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            t = ["<table><thead><tr>"]
            t += ["<th>%s</th>" % inline(h, md_dir) for h in heads]
            t.append("</tr></thead><tbody>")
            for r in rows:
                t.append("<tr>" + "".join("<td>%s</td>" % inline(c, md_dir) for c in r) + "</tr>")
            t.append("</tbody></table>")
            out.append("".join(t))
            continue

        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>%s</blockquote>" % inline(" ".join(buf), md_dir))
            continue

        if re.match(r"^\d+\.\s+", s):
            out.append("<ol>")
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                out.append("<li>%s</li>" % inline(re.sub(r"^\d+\.\s+", "", lines[i].strip()), md_dir))
                i += 1
            out.append("</ol>")
            continue

        if re.match(r"^[-*+]\s+", s) or bullet.match(s):
            out.append("<ul>")
            while i < n:
                cur = lines[i].strip()
                if not (re.match(r"^[-*+]\s+", cur) or bullet.match(cur)):
                    break
                item = re.sub(r"^([-*+]|[·•])\s+", "", cur)
                out.append("<li>%s</li>" % inline(item, md_dir))
                i += 1
            out.append("</ul>")
            continue

        buf = []
        while i < n:
            cur = lines[i].strip()
            if (not cur or cur.startswith(("#", "```", "|", ">"))
                    or re.match(r"^[-*+]\s+", cur) or bullet.match(cur)
                    or re.match(r"^\d+\.\s+", cur) or re.fullmatch(r"-{3,}|\*{3,}", cur)):
                break
            buf.append(cur)
            i += 1
        out.append("<p>%s</p>" % inline(" ".join(buf), md_dir))

    return "\n".join(out)


def md_to_pdf(md_path, pdf_path, tmp_dir):
    md_dir = os.path.dirname(md_path)
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    body = convert(md_text, md_dir)
    title = os.path.splitext(os.path.basename(md_path))[0]
    if not re.match(r"^\s*#\s", md_text):
        body = "<h1>%s</h1>\n%s" % (html.escape(title), body)

    page = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<title>%s</title><style>%s</style></head><body>%s</body></html>'
            % (html.escape(title), CSS, body))

    html_path = os.path.join(tmp_dir, "page.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page)

    raw_pdf = os.path.join(tmp_dir, "out.pdf")
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
           "--user-data-dir=" + os.path.join(tmp_dir, "profile"),
           "--print-to-pdf=" + raw_pdf,
           "file:///" + html_path.replace("\\", "/")]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=120)

    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    shutil.move(raw_pdf, pdf_path)
    return os.path.getsize(pdf_path)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "."
    dst = sys.argv[2] if len(sys.argv) > 2 else "pdf"
    ok = fail = 0
    for root, _, files in os.walk(src):
        for name in sorted(files):
            if not name.lower().endswith(".md"):
                continue
            md_path = os.path.join(root, name)
            rel = os.path.relpath(md_path, src)
            pdf_path = os.path.join(dst, os.path.splitext(rel)[0] + ".pdf")
            tmp_dir = tempfile.mkdtemp(prefix="md2pdf_")
            try:
                size = md_to_pdf(md_path, pdf_path, tmp_dir)
                print("OK   %6.0f KB  %s" % (size / 1024, rel))
                ok += 1
            except Exception as e:
                print("FAIL %s  ->  %s" % (rel, e))
                fail += 1
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
    print("\n完成：成功 %d，失败 %d" % (ok, fail))


if __name__ == "__main__":
    main()
