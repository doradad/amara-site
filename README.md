# AMARA 官网静态站（amara.cbmcc.cn）

原站由建站平台托管，本仓库是其中英双语静态镜像，用 Nginx 直接托管。

```
site/                   网站根目录（英文 /，中文 /cn/）
deploy/nginx/amara.conf        生产 Nginx 配置
deploy/nginx/amara.local.conf  本地 Docker 测试配置
deploy/post-receive     服务器 git 钩子：push 即部署
tools/mirror.py         重新从原站抓取（需 Playwright）
tools/rebuild_shells.py 离线修复主栏目页结构
```

## 本地预览

```bash
docker run -d --name amara-local -p 8080:80 \
  -v "$PWD/site":/usr/share/nginx/html:ro \
  -v "$PWD/deploy/nginx/amara.local.conf":/etc/nginx/conf.d/default.conf:ro \
  -v "$PWD/deploy/logs":/var/log/nginx nginx:alpine
# 访问 http://localhost:8080/ ，404 记录在 deploy/logs/404.log
```

## 服务器首次部署（git push 方式）

服务器上（root 或 sudo）：

```bash
# 1. 安装
yum install -y git nginx || apt install -y git nginx
systemctl enable --now nginx

# 2. bare 仓库 + 网站目录
mkdir -p /srv/git/amara.git /var/www/amara
git init --bare -b main /srv/git/amara.git
# 3. 把本仓库 deploy/post-receive 内容放到：
vi /srv/git/amara.git/hooks/post-receive && chmod +x /srv/git/amara.git/hooks/post-receive
# 若用非 root 用户 push，把两个目录 chown 给该用户
```

本地：

```bash
git remote add prod root@<服务器IP>:/srv/git/amara.git
git push prod main          # 首次约 140MB
```

服务器上启用 Nginx 配置：

```bash
cp /var/www/amara/deploy/nginx/amara.conf /etc/nginx/conf.d/amara.conf
nginx -t && systemctl reload nginx
curl -I -H 'Host: amara.cbmcc.cn' http://127.0.0.1/    # 应 200
```

阿里云控制台：安全组放行 80（和 443）。

## 切换域名

1. 先在自己电脑 hosts 加 `<服务器IP> amara.cbmcc.cn` 验证全站，验证完删掉。
2. 大陆服务器需该域名已在阿里云完成 ICP 备案接入，否则 80/443 会被拦截。
3. DNS 把 `amara` 记录从建站平台的 CNAME 改为 A 记录指向服务器 IP。
4. HTTPS：`certbot --nginx -d amara.cbmcc.cn`（或在阿里云申请免费证书后配置 443）。

## 日常更新

```bash
# 改 site/ 下文件后
git commit -am "说明" && git push prod main   # 推送即生效
```
