// 镜像站不需要建站平台的图片域名改写 Service Worker。
// 访问过原站的浏览器已注册旧 SW：这里替换为自注销版本，激活后清理缓存并注销自身。
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys()
      .then(function (keys) { return Promise.all(keys.map(function (k) { return caches.delete(k); })); })
      .then(function () { return self.registration.unregister(); })
  );
});
