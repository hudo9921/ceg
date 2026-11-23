import re
from pathlib import Path

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import reverse

TEMPLATES_DIR = Path(settings.BASE_DIR) / 'templates'
# Único script externo tolerado: o Play CDN do Tailwind, e só no modo de desenvolvimento.
EXTERNAL_SCRIPT_RE = re.compile(r'<script[^>]+src="https?://(?!cdn\.tailwindcss\.com/)', re.I)
EXTERNAL_STYLESHEET_RE = re.compile(
    r'<link[^>]+rel="stylesheet"[^>]+href="https?://(?!fonts\.googleapis\.com/)', re.I)


def directives(response):
    header = response.headers['Content-Security-Policy']
    return {part.split()[0]: part.split()[1:] for part in header.split('; ') if part}


class ContentSecurityPolicyTests(TestCase):
    def test_csp_restricts_script_origins_and_framing(self):
        csp = directives(self.client.get(reverse('home')))
        self.assertEqual(csp['frame-ancestors'], ["'none'"])
        self.assertEqual(csp['object-src'], ["'none'"])
        self.assertEqual(csp['base-uri'], ["'self'"])
        self.assertEqual(csp['form-action'], ["'self'"])
        self.assertEqual(csp['connect-src'], ["'self'"])
        external = [s for s in csp['script-src'] if s.startswith('http')]
        self.assertLessEqual(set(external), {'https://cdn.tailwindcss.com'})

    @override_settings(TAILWIND_MODE='build')
    def test_production_mode_uses_compiled_css_and_no_external_scripts(self):
        res = Client().get(reverse('home'))
        csp = directives(res)
        self.assertEqual([s for s in csp['script-src'] if s.startswith('http')], [])
        html = res.content.decode()
        self.assertIn('css/tailwind.css', html)
        self.assertNotIn('cdn.tailwindcss.com', html)

    def test_permissions_policy_disables_sensitive_apis(self):
        res = self.client.get(reverse('home'))
        self.assertIn('camera=()', res.headers['Permissions-Policy'])

    def test_templates_load_no_third_party_scripts(self):
        """Bibliotecas JS/CSS ficam em static/vendor; nada de CDN externo nos templates."""
        offenders = []
        for path in TEMPLATES_DIR.rglob('*.html'):
            text = path.read_text(encoding='utf-8')
            if EXTERNAL_SCRIPT_RE.search(text) or EXTERNAL_STYLESHEET_RE.search(text):
                offenders.append(str(path.relative_to(TEMPLATES_DIR)))
        self.assertEqual(offenders, [])
