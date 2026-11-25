/*
 * Tema único do Tailwind (fonte da verdade).
 * - Navegador (DEBUG / TAILWIND_MODE=cdn): define `tailwind.config` para o Play CDN.
 * - Node (build de produção): exportado para tailwind.config.js.
 */
(function (root) {
    var config = {
        darkMode: 'class',
        theme: {
            extend: {
                fontFamily: {
                    sans: ['Outfit', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
                    mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
                    // Fonte de destaque do tema ativo (claro: M PLUS Rounded 1c; escuro: Chakra Petch) — static/css/ui.css
                    display: ['var(--ui-font-display)'],
                },
                // Raios do tema ativo (claro arredondado, escuro reto)
                borderRadius: {
                    'ui-card': 'var(--ui-r-card)',
                    'ui-ctl': 'var(--ui-r-ctl)',
                    'ui-pill': 'var(--ui-r-pill)',
                    'ui-media': 'var(--ui-r-media)',
                },
                screens: {
                    'xs': '480px',
                },
                colors: {
                    // Cores semânticas do tema ativo (trocam sozinhas no modo escuro) — static/css/ui.css
                    ui: {
                        bg: 'var(--ui-bg)',
                        surface: 'var(--ui-surface)',
                        'surface-2': 'var(--ui-surface-2)',
                        line: 'var(--ui-line)',
                        text: 'var(--ui-text)',
                        muted: 'var(--ui-muted)',
                        accent: 'var(--ui-accent)',
                        'accent-text': 'var(--ui-accent-text)',
                        'accent-soft': 'var(--ui-accent-soft)',
                        danger: 'var(--ui-danger)',
                        warn: 'var(--ui-warn)',
                        ok: 'var(--ui-ok)',
                    },
                    kpop: {
                        50: '#fdf2f8',
                        100: '#fce7f3',
                        200: '#fbcfe8',
                        300: '#f9a8d4',
                        400: '#f472b6',
                        500: '#ec4899',
                        600: '#db2777',
                        700: '#be185d',
                        800: '#9d174d',
                        900: '#831843',
                    },
                    pastel: {
                        pink: '#FFE5EC',
                        rose: '#FFC2D1',
                        deeprose: '#FB6F92',
                        sky: '#E0F2FE',
                        blue: '#BAE6FD',
                        lavender: '#F3E8FF',
                        lilac: '#E9D5FF',
                        peach: '#FFEDD5',
                        mint: '#DCFCE7'
                    },
                    // Paleta Bipolar: Soft Y2K (Modo Claro) e Cyber-Luxury (Modo Escuro)
                    cyber: {
                        obsidian: '#0B0A0F',
                        surface: '#14121B',
                        elevated: '#1A1724',
                        silver: '#E2E8F0',
                        neon: '#F472B6',
                        electric: '#C084FC',
                        ice: '#38BDF8',
                        border: 'rgba(255, 255, 255, 0.08)'
                    },
                    y2k: {
                        bg: '#F8F7FA',
                        surface: '#FFFFFF',
                        text: '#1E1B26',
                        lavender: '#E9D5FF',
                        mint: '#CCFBF1',
                        blush: '#FCE7F3',
                        butter: '#FEF9C3',
                        border: 'rgba(233, 213, 255, 0.6)'
                    }
                },
                boxShadow: {
                    'glass': '0 8px 32px 0 rgba(0, 0, 0, 0.37)',
                    'glow': '0 0 35px -5px var(--era-accent, rgba(244,114,182,0.35))',
                    'cyber': '0 0 15px -3px rgba(192, 132, 252, 0.25)',
                    'y2k': '0 4px 20px -2px rgba(233, 213, 255, 0.4)'
                },
                animation: {
                    'pulse-subtle': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite'
                }
            }
        }
    };
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = config;
    } else if (root.tailwind) {
        root.tailwind.config = config;
    }
})(typeof window !== 'undefined' ? window : globalThis);
