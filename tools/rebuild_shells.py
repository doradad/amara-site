"""
离线修复：把主栏目页（data-type=1，正文由 Head/Body.js 注入）从「渲染后 DOM」改回
「原始壳 HTML + Head/Body.js」，避免视差/轮播插件在本地二次初始化（首页背景图闪一下就消失）。
只使用已下载的数据，不访问原站。用法： OUT=<站点目录> python3 rebuild_shells.py
"""
import json, os, re
import mirror as M

OUT = M.OUT
man = json.load(open(os.path.join(OUT, "_manifest.json"), encoding="utf-8"))
M.resources.update(man["resources"])
for lang, pages in man["pages"].items():
    M.pages_done[lang].update(pages)
for u, lp in M.resources.items():
    if "/admin/map/" in u and "amara.cbmcc.cn" in u:
        M.frame_local[M.unquote(u)] = lp


def read(lp):
    with open(os.path.join(OUT, lp.lstrip("/")), encoding="utf-8") as f:
        return f.read()


# (页面id, 语言, Head|Body) -> (原始URL, 本地路径)
loader_lp = {}
for u, lp in M.resources.items():
    m = re.search(r"/cdn-static-pages/pages/pc/(\d+)_(en-us|zh-cn)\.html\.(Head|Body)\.js", u)
    if m:
        loader_lp[(m.group(1), m.group(2), m.group(3))] = (u, lp)

done_loaders = set()
for lang, pages in M.pages_done.items():
    prefix = M.LANGS[lang]
    for url, lp in pages.items():
        html = read(lp)
        if html.lstrip().startswith("<!DOCTYPE html><html class='smart-design-mode'><head><script src="):
            print(f"[{lang}] 已是壳，跳过 {lp}")
            continue
        m = re.search(r'id="pageinfo" value="(\d+)" data-type="1"', html)
        if not m:
            continue  # 详情页：服务端直出正文，无 Head/Body.js，保持不变
        pid = m.group(1)
        head_u, head_lp = loader_lp[(pid, lang, "Head")]
        body_u, body_lp = loader_lp[(pid, lang, "Body")]
        title = re.search(r"<title>.*?</title>", html, re.S).group(0)
        shell = ("<!DOCTYPE html><html class='smart-design-mode'>"
                 f"<head><script src='{head_lp}'></script>{title}</head>"
                 f"<body id='smart-body' area='main' ><script src='{body_lp}'></script></body></html>")
        shell = shell.replace("</head>", M.LANG_SWITCH_JS % (json.dumps(M.LANGS), json.dumps(lang)) + "</head>", 1)
        M.write(lp, shell.encode("utf-8"))
        print(f"[{lang}] 壳 {lp}  <- 页面 {pid}")

        # Head/Body.js 按所属语言改写（同语言的 / 与 /sy 共用一份，只处理一次）
        for u, jlp in ((head_u, head_lp), (body_u, body_lp)):
            if jlp in done_loaders:
                continue
            done_loaders.add(jlp)
            js = M.rewrite_text(read(jlp).replace('\\u0026', '&'), pages)
            js = M.rewrite_hrefs(js, pages, prefix)
            js = M.MAP_SRC_RE.sub(lambda mm: mm.group(1) + M.map_src(mm.group(2)) + mm.group(3), js)
            for r in M.CHAT_RES:
                js = r.sub("", js)
            M.write(jlp, js.encode("utf-8"))

print(f"完成：改写 Head/Body.js {len(done_loaders)} 个")
