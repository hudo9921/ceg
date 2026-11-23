# static/vendor

Bibliotecas de terceiros servidas pelo próprio site (a CSP não permite scripts de CDNs).
Cada arquivo é o build oficial da versão no nome, conferido contra o hash SRI publicado:

| Arquivo | Origem | Alteração |
| :--- | :--- | :--- |
| `alpinejs-3.14.9.min.js` | npm `alpinejs@3.14.9/dist/cdn.min.js` | nenhuma |
| `lucide-1.78.0.min.js` | npm `lucide@1.78.0/dist/umd/lucide.min.js` | removida a linha `//# sourceMappingURL` |
| `cropperjs-1.5.13.min.js` / `.min.css` | cdnjs `cropperjs/1.5.13` | nenhuma |
| `chartjs-4.4.1.umd.min.js` | npm `chart.js@4.4.1/dist/chart.umd.min.js` | removida a linha `//# sourceMappingURL` |

A linha de source map é removida porque o `.map` não é distribuído e o
`CompressedManifestStaticFilesStorage` do WhiteNoise falha no `collectstatic` quando a
referência aponta para um arquivo inexistente.

Para atualizar: baixe a nova versão, confira o hash SRI oficial, renomeie com a versão,
remova a linha de source map se houver e atualize as referências `{% static %}`.
