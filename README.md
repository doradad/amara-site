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

## 服务器首次部署（从 GitHub）

### 1. 服务器生成部署密钥

```bash
# 安装依赖
yum install -y git nginx || apt install -y git nginx
systemctl enable --now nginx

# 生成部署密钥
ssh-keygen -t ed25519 -f ~/.ssh/amara_deploy -N "" -C "amara-deploy"
cat ~/.ssh/amara_deploy.pub
# 复制打印出来的公钥
```

在 GitHub repo → Settings → Deploy keys → Add deploy key，粘贴公钥，标题随意，**不要勾选 write access**。

### 2. 配置 SSH 并克隆

```bash
# 配置 SSH 使用部署密钥
cat >> ~/.ssh/config <<'EOF'
Host github-amara
  HostName github.com
  User git
  IdentityFile ~/.ssh/amara_deploy
EOF

# 克隆到网站目录（如果 /var/www/amara 已存在且不为空，先改名）
git clone github-amara:doradad/amara-site.git /var/www/amara
```

### 3. 启用 Nginx

```bash
cp /var/www/amara/deploy/nginx/amara.conf /etc/nginx/conf.d/amara.conf
nginx -t && systemctl reload nginx
curl -I -H 'Host: amara.cbmcc.cn' http://127.0.0.1/    # 应返回 200
```

阿里云控制台：安全组放行 80 和 443 端口。

## 切换域名

1. 先在自己电脑 hosts 加 `<服务器IP> amara.cbmcc.cn` 验证全站，验证完删掉。
2. 大陆服务器需该域名已在阿里云完成 ICP 备案接入，否则 80/443 会被拦截。
3. DNS 把 `amara` 记录从建站平台的 CNAME 改为 A 记录指向服务器 IP。
4. HTTPS：`certbot --nginx -d amara.cbmcc.cn`（或在阿里云申请免费证书后配置 443）。

## 日常更新

本地修改 `site/` 下文件后：

```bash
git commit -am "说明" && git push origin main
```

服务器上拉取更新：

```bash
cd /var/www/amara && git pull
```

静态文件立即生效。如果改了 `deploy/nginx/amara.conf`，还需执行：

```bash
cp deploy/nginx/amara.conf /etc/nginx/conf.d/ && nginx -t && systemctl reload nginx
```
