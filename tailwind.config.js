/** Build de produção do Tailwind (o tema vive em static/src/tailwind.theme.js). */
const theme = require('./static/src/tailwind.theme.js');

module.exports = {
    ...theme,
    // Classes usadas em templates, em strings Python (views/models) e em scripts estáticos.
    content: [
        './templates/**/*.html',
        './apps/**/*.py',
        '!./apps/**/test*.py',
        '!./apps/**/migrations/**',
        './static/src/**/*.js',
    ],
};
