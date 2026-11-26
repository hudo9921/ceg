{% load static %}/* Service worker do CegManager (apps/avisos): só mostra notificações push e abre a página ao tocar. Sem cache offline. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
    let data = {};
    try { data = event.data ? event.data.json() : {}; } catch (e) { data = { title: 'CegManager', body: event.data ? event.data.text() : '' }; }
    event.waitUntil(self.registration.showNotification(data.title || 'CegManager', {
        body: data.body || '',
        icon: '{% static "img/push-icon-96.png" %}',
        badge: '{% static "img/push-badge-72.png" %}',
        tag: data.tag || undefined,
        data: { url: data.url || '/' },
    }));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const url = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin).href;
    event.waitUntil((async () => {
        const abertas = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
        for (const c of abertas) {
            if (c.url === url && 'focus' in c) return c.focus();
        }
        return self.clients.openWindow(url);
    })());
});
