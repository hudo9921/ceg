/**
 * Gera static/js/lucide-subset.min.js só com os ícones usados no projeto.
 *
 * O pacote completo tem ~2.400 ícones (≈490 KB). Coletamos de forma propositalmente ampla
 * toda string entre aspas que tenha cara de nome de ícone em templates, código Python
 * (views/models que devolvem nomes de ícone) e scripts — inclusive expressões Alpine como
 * `:data-lucide="ok ? 'check' : 'clock'"` — e mantemos as que existem no Lucide.
 * Sobrar um ícone custa ~300 bytes; faltar um some com ele da tela, então erramos para mais.
 *
 * Mantém a mesma API global usada nos templates: window.lucide.createIcons({ attrs }).
 */
import { build } from 'esbuild';
import { mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { icons } from 'lucide';

const ROOTS = [
    { dir: 'templates', ext: '.html' },
    { dir: 'apps', ext: '.py', skip: /(^|[\\/])(tests?[^\\/]*\.py|migrations)([\\/]|$)/ },
    { dir: 'static/src', ext: '.js' },
];
const OUT_DIR = 'static/js';
const ENTRY = 'node_modules/.cache/lucide-entry.mjs';

function* walk(dir, ext, skip) {
    for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (skip && skip.test(path)) continue;
        if (statSync(path).isDirectory()) yield* walk(path, ext, skip);
        else if (path.endsWith(ext)) yield path;
    }
}

const toPascal = (kebab) => kebab.split('-').map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join('');

const used = new Set();
for (const { dir, ext, skip } of ROOTS) {
    for (const file of walk(dir, ext, skip)) {
        const text = readFileSync(file, 'utf8');
        for (const match of text.matchAll(/["']([a-z][a-z0-9]*(?:-[a-z0-9]+)*)["']/g)) {
            const pascal = toPascal(match[1]);
            if (icons[pascal]) used.add(pascal);
        }
    }
}

const names = [...used].sort();
mkdirSync('node_modules/.cache', { recursive: true });
writeFileSync(ENTRY, `import { createIcons, ${names.join(', ')} } from 'lucide';
const icons = { ${names.join(', ')} };
window.lucide = {
    icons,
    createIcons: (options = {}) => createIcons({ ...options, icons: options.icons || icons }),
};
`);

mkdirSync(OUT_DIR, { recursive: true });
const result = await build({
    entryPoints: [ENTRY],
    bundle: true,
    minify: true,
    format: 'iife',
    target: ['es2018'],
    outfile: `${OUT_DIR}/lucide-subset.min.js`,
    metafile: true,
    logLevel: 'warning',
});
const bytes = Object.values(result.metafile.outputs)[0].bytes;
console.log(`lucide-subset: ${names.length} ícones, ${(bytes / 1024).toFixed(0)} KB`);
