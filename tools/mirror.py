"""
amara.cbmcc.cn 整站镜像（中英双语）。页面结构：服务端只返回一个壳 HTML，正文由
Head.js/Body.js（document.write）注入，再由视差/轮播等插件在运行时改写 DOM。
因此这里保存「原始壳 HTML + 原始 Head/Body.js」并只改写其中的 URL，本地打开时插件从
与原站相同的初始状态运行（保存渲染后的 DOM 会让插件二次初始化，例如首页视差背景被清空）。
Chromium 渲染仅用于发现链接和收集页面实际加载的资源。

原站语言靠 cookie yibu_language 切换、URL 不变；静态化后：
  英文  site/<页面路径>        （/、/gy、/cp ...）
  中文  site/cn/<页面路径>     （/cn/、/cn/gy ...）
  外域资源 site/_ext/<host>/<路径>
页面上的 CN/EN 切换按钮改为直接跳到另一语言的同一页面。
本地预览： cd site && python3 -m http.server 8000
"""
import asyncio, hashlib, html as htmllib, json, os, re
from urllib.parse import urljoin, urlparse, urldefrag, unquote
from playwright.async_api import async_playwright

START = "http://amara.cbmcc.cn/"
SITE_HOSTS = {"amara.cbmcc.cn"}
LANGS = {"en-us": "", "zh-cn": "/cn"}  # 语言 -> 本地路径前缀
OUT = os.environ.get("OUT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
MAX_PAGES = int(os.environ.get("MAX_PAGES", "2000"))
CONCURRENCY = 2
SKIP_EXT = (".zip", ".rar", ".exe", ".mp4")  # 大文件不自动抓，可按需去掉

resources = {}                           # 原始URL -> 本地路径（根相对，以 / 开头）
pages_done = {l: {} for l in LANGS}      # 语言 -> {页面URL -> 本地路径}
html_store = {l: {} for l in LANGS}
failed = []
dead = set()        # 原站返回 4xx/5xx 的页面
frame_html = {}     # iframe 本地路径 -> 原始 HTML
frame_local = {}    # 解码后的 iframe URL -> 本地路径
loaders = {}        # Head/Body.js 原始URL -> 语言（每页每语言一份）

# 语言切换：在捕获阶段拦截，先于建站平台自己的 handler（它会 POST 到已不存在的后端）
LANG_SWITCH_JS = """<script>(function(){
var P=%s;
document.addEventListener('click',function(e){
  var a=e.target.closest&&e.target.closest('.w-language-link[languageculture]');
  if(!a)return; e.preventDefault(); e.stopImmediatePropagation();
  var to=P[a.getAttribute('languageculture').toLowerCase()]; if(to===undefined)return;
  var path=location.pathname, cur=P[%s];
  if(cur&&path.indexOf(cur+'/')===0)path=path.slice(cur.length);
  location.href=to+path;
},true);})();</script>"""


def local_path(url, is_page=False, prefix=""):
    p = urlparse(url)
    host = p.hostname or ""
    path = p.path or "/"
    if path.endswith("/"):
        path += "index.html"
    elif is_page and not os.path.splitext(path)[1]:
        path += "/index.html"
    if p.query:
        h = hashlib.md5(p.query.encode()).hexdigest()[:8]
        root, ext = os.path.splitext(path)
        path = f"{root}__{h}{ext}"
    path = re.sub(r'[<>:"|?*]', "_", path)
    return prefix + path if host in SITE_HOSTS else f"/_ext/{host}{path}"


def page_href(lp):
    """页面本地文件路径 -> 链接用的 URL（/gy/index.html -> /gy/）"""
    return lp[:-len("index.html")] if lp.endswith("/index.html") else lp


def write(lp, data):
    fp = os.path.join(OUT, lp.lstrip("/"))
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "wb") as f:
        f.write(data)


def norm_page(url):
    url = urldefrag(url)[0]
    p = urlparse(url)
    if p.scheme not in ("http", "https") or p.hostname not in SITE_HOSTS:
        return None
    if p.path.lower().endswith(SKIP_EXT):
        return None
    return p._replace(scheme="http").geturl()


URL_RE = re.compile(r'(?:https?:)?//[A-Za-z0-9.\-]+(?::\d+)?/[^\s"\'()<>\\]*')
ASSET_RE = re.compile(r'(?:https?:)?//[A-Za-z0-9.\-]+/[^\s"\'()<>\\&]*?'
                      r'\.(?:png|jpe?g|gif|webp|svg|ico|woff2?|ttf|eot|otf|css|js)(?=[\s"\'()<>\\&?]|$)',
                      re.I)
CSS_URL_RE = re.compile(r'url\(\s*(["\']?)([^"\')]+)\1\s*\)')
# 站内相对链接 href="/gy"、href="/productinfo/1.html"
# 也匹配 JS 字符串里转义过的 href=\"/gy\"
HREF_RE = re.compile(r'(href=(?:\\)?["\'])(/(?!/)[^"\'#\\]*)((?:\\)?["\'#])')
MAP_SRC_RE = re.compile(r'(src=\\")(/admin/map/.*?)(\\")')
# 阿里在线客服挂件（依赖建站平台后端 API，脱离平台后不可用）
CHAT_RES = [re.compile(r'\\u003cscript\\u003e(?:(?!\\u003c).)*?window\.SEED_CONFIG(?:(?!\\u003c).)*?\\u003c/script\\u003e', re.S),
            re.compile(r'\\u003cscript(?:(?!\\u003c).)*?msea-fe/seed(?:(?!\\u003c).)*?\\u003c/script\\u003e', re.S)]


def lookup(full, pages=None):
    for k in (full, full.replace("https://", "http://"), full.replace("http://", "https://")):
        if k in resources:
            return resources[k]
        pk = norm_page(k)
        if pages is not None and pk and pk in pages:
            return page_href(pages[pk])
    return None


def rewrite_text(text, pages=None):
    """把文本中出现的已抓取资源/页面 URL 改为本地路径。"""
    def repl(m):
        raw = m.group(0)
        # 内联 style 里的 url(&quot;...&quot;)：实体不属于 URL，切掉后再查
        tail = ""
        cut = re.search(r"&(quot|#34|#39|apos|gt|lt);", raw)
        if cut:
            raw, tail = raw[:cut.start()], raw[cut.start():]
        full = ("http:" + raw if raw.startswith("//") else raw).replace("&amp;", "&")
        return (lookup(full, pages) or raw) + tail
    return URL_RE.sub(repl, text)


def rewrite_hrefs(html, pages, prefix):
    """站内根相对链接加语言前缀（只改确实抓到的页面）。"""
    if not prefix:
        return html
    def repl(m):
        full = norm_page(urljoin(START, m.group(2).replace("&amp;", "&")))
        if full and full in pages:
            return m.group(1) + page_href(pages[full]) + m.group(3)
        return m.group(0)
    return HREF_RE.sub(repl, html)


def map_src(raw):
    """Body.js 里 JS 转义 + HTML 实体编码的 iframe 地址 -> 本地保存的 iframe 页面。"""
    url = urljoin(START, htmllib.unescape(json.loads('"' + raw + '"')))
    return frame_local.get(unquote(url), raw)


def rewrite_css(text, css_url):
    def repl(m):
        ref = m.group(2).strip()
        if ref.startswith("data:"):
            return m.group(0)
        full = urljoin(css_url, ref)
        return f"url({m.group(1)}{resources.get(full) or full}{m.group(1)})"
    return CSS_URL_RE.sub(repl, text)


async def fetch_missing(ctx, urls):
    """渲染时没请求到的资源（未用到的字体/背景图、懒加载图等）补抓。"""
    for u in urls:
        if u in resources:
            continue
        try:
            r = await ctx.request.get(u, timeout=30000)
            if r.ok:
                lp = local_path(u)
                write(lp, await r.body())
                resources[u] = lp
        except Exception as e:
            failed.append((u, str(e)))


async def crawl_page(ctx, lang, url, queue, seen):
    page = await ctx.new_page()
    captured = []

    async def on_response(resp):
        u = resp.url
        if u.startswith("data:") or resp.request.resource_type == "document" or resp.status >= 300:
            return
        try:
            captured.append((u, resp.headers.get("content-type", ""), await resp.body()))
        except Exception:
            pass

    page.on("response", on_response)
    try:
        for attempt in range(4):
            resp = await page.goto(url, wait_until="networkidle", timeout=60000)
            if not resp or resp.status < 500:
                break
            # 5xx 多为 CDN 限流/抖动，退避重试，避免误判为死链
            print(f"[{lang}] {resp.status} 重试 {attempt + 1}: {url}", flush=True)
            captured.clear()
            await asyncio.sleep(5 * (attempt + 1))
        if resp and resp.status >= 400:
            # 原站本身就是死链（如导航里指向已删页面），不落地，部署后同样 404
            print(f"[{lang}] 跳过 {resp.status}: {url}", flush=True)
            dead.add(url)
            await page.close()
            return
        # 滚动到底触发懒加载
        await page.evaluate("""async () => {
            for (let y = 0; y < document.body.scrollHeight; y += 600) {
                window.scrollTo(0, y); await new Promise(r => setTimeout(r, 150));
            }
            window.scrollTo(0, 0);
        }""")
        await page.wait_for_load_state("networkidle", timeout=30000)
        # 内嵌的建站平台页面（联系页高德地图 /admin/map/...）：存原始 HTML，iframe 改指本地
        for fr in page.frames:
            fu = fr.url
            if fr is page.main_frame or urlparse(fu).hostname not in SITE_HOSTS or fu in resources:
                continue
            r = await ctx.request.get(fu, timeout=30000)
            if r.ok:
                lp = local_path(fu, is_page=True)
                resources[fu] = lp
                frame_local[unquote(fu)] = lp
                frame_html[lp] = await r.text()
        links = await page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)")
        # 原始壳 HTML（服务端返回、未经任何 JS 处理）
        html = await resp.text()
    except Exception as e:
        failed.append((f"[{lang}] {url}", str(e)))
        await page.close()
        return
    await page.close()

    css_list = []
    for u, ct, body in captured:
        if u in resources:
            continue
        lp = local_path(u)
        resources[u] = lp
        if "cdn-static-pages" in u:
            loaders[u] = lang
        if "css" in ct or u.split("?")[0].endswith(".css"):
            css_list.append((u, lp, body))
        else:
            write(lp, body)
    for u, lp, body in css_list:
        text = body.decode("utf-8", "ignore")
        refs = [urljoin(u, m.group(2).strip()) for m in CSS_URL_RE.finditer(text)
                if not m.group(2).strip().startswith("data:")]
        await fetch_missing(ctx, refs)
        write(lp, rewrite_css(text, u).encode())

    pages_done[lang][url] = local_path(url, is_page=True, prefix=LANGS[lang])
    html_store[lang][url] = html

    for l in links:
        n = norm_page(l)
        if n and n not in seen and len(seen) < MAX_PAGES:
            seen.add(n)
            await queue.put(n)
    print(f"[{lang} {len(pages_done[lang])}/{len(seen)}] {url}  资源{len(captured)}", flush=True)


async def crawl_lang(browser, lang):
    ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
    await ctx.add_cookies([{"name": "yibu_language", "value": lang,
                            "domain": h, "path": "/"} for h in SITE_HOSTS])
    queue, seen = asyncio.Queue(), {START}
    await queue.put(START)

    async def worker():
        while True:
            url = await queue.get()
            try:
                await crawl_page(ctx, lang, url, queue, seen)
            finally:
                queue.task_done()

    tasks = [asyncio.create_task(worker()) for _ in range(CONCURRENCY)]
    await queue.join()
    for t in tasks:
        t.cancel()
    return ctx


async def main():
    os.makedirs(OUT, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = None
        for lang in LANGS:
            ctx = await crawl_lang(browser, lang)

        # 补抓：页面/JS 文本里出现、但渲染时没触发请求的静态资源（懒加载、隐藏 tab 等）
        texts = [h for store in html_store.values() for h in store.values()] + list(frame_html.values())
        for u, lp in resources.items():
            if lp.split("?")[0].endswith(".js"):
                fp = os.path.join(OUT, lp.lstrip("/"))
                if os.path.exists(fp):
                    with open(fp, encoding="utf-8", errors="ignore") as f:
                        texts.append(f.read())
        missing = set()
        for t in texts:
            for m in ASSET_RE.finditer(t):
                raw = m.group(0)
                full = "https:" + raw if raw.startswith("//") else raw
                if not lookup(full):
                    missing.add(full)
        print(f"补抓遗漏资源 {len(missing)} 个", flush=True)
        await fetch_missing(ctx, sorted(missing))
        await browser.close()

    # 全部抓完后统一改写（此时页面映射完整）
    lang_map = json.dumps(LANGS)
    for lang, store in html_store.items():
        pages, prefix = pages_done[lang], LANGS[lang]
        for url, html in store.items():
            html = rewrite_hrefs(rewrite_text(html, pages), pages, prefix)
            html = html.replace("mailto:name@example.com", "mailto:Amara@cbmai.com.cn")
            html = html.replace("</head>", LANG_SWITCH_JS % (lang_map, json.dumps(lang)) + "</head>", 1)
            write(pages[url], html.encode("utf-8"))
    for lp, html in frame_html.items():
        write(lp, rewrite_text(html).encode("utf-8"))
    for u, lang in loaders.items():
        lp = resources[u]
        with open(os.path.join(OUT, lp.lstrip("/")), encoding="utf-8") as f:
            js = f.read()
        pages, prefix = pages_done[lang], LANGS[lang]
        js = js.replace('\\u0026', '&')  # JS 字符串里 \\u0026 即 &，统一后 URL 才能匹配到本地资源
        js = rewrite_hrefs(rewrite_text(js, pages), pages, prefix)
        js = MAP_SRC_RE.sub(lambda m: m.group(1) + map_src(m.group(2)) + m.group(3), js)
        for r in CHAT_RES:
            js = r.sub("", js)
        # 原站邮件按钮链接是建站模板占位符，未替换成真实邮箱
        js = js.replace("mailto:name@example.com", "mailto:Amara@cbmai.com.cn")
        write(lp, js.encode("utf-8"))
    for u, lp in list(resources.items()):
        if u in loaders:
            continue
        if lp.split("?")[0].endswith(".js"):
            fp = os.path.join(OUT, lp.lstrip("/"))
            if os.path.exists(fp):
                with open(fp, encoding="utf-8", errors="ignore") as f:
                    write(lp, rewrite_text(f.read()).encode("utf-8"))

    with open(os.path.join(OUT, "_manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"pages": pages_done, "resources": resources, "failed": failed,
                   "dead_links_on_origin": sorted(dead)},
                  f, ensure_ascii=False, indent=1)
    print("完成：" + "，".join(f"{l} 页面 {len(p)}" for l, p in pages_done.items())
          + f"，资源 {len(resources)}，失败 {len(failed)}")


if __name__ == "__main__":
    asyncio.run(main())
