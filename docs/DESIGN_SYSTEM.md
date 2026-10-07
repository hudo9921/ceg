# DESIGN_SYSTEM.md — Diretrizes de Visão Artística, UI & UX Specification

> **Status:** Especificação Oficial de Design & UI/UX (Outubro/2026).  
> **Propósito:** Bússola estética e guia de engenharia visual para desenvolvedores, designers e agentes de IA que atuarem na evolução da plataforma **ValCegs Manager**.

---

## 🌟 1. Filosofia Emocional & Conceito Central

### 1.1. A Alma do Produto: O "Binder Tátil" encontra o "Streaming Moderno"
Colecionar photocards de K-pop é uma experiência profundamente física e emocional:
- O som do plástico do *sleeve*, o peso de um *toploader* rígido, o cuidado ao organizar um fichário (*binder*) de 9 bolsos por integrante, a estética de *deco stickers* e a adrenalina do momento em que um lote abre no "Segundo Zero".
- O **ValCegs Manager** não pode se parecer com uma planilha de Excel ou um ERP cinzento. Cada photocard na tela deve parecer um **ativo palpável, protegido em acrílico, colecionável e precioso**.
- Ao mesmo tempo, a plataforma de compras em grupo precisa da eficiência e fluidez das melhores interfaces do mundo: a navegação horizontal contínua de plataformas de música (**Deezer**, **Spotify**) e a precisão técnica e densidade limpa de ferramentas de engenharia (**Linear**, **Raycast**).

### 1.2. Os Três Mandamentos Visuais
1. **Dignidade ao Objeto:** Nenhum banner ou foto de integrante é espremido, esticado ou cortado sem intenção. A foto é o coração da venda.
2. **Clareza Financeira Imediata:** Toda informação de dinheiro (preço, frete internacional, taxa aduaneira) deve ter contraste impecável, tipografia mono-espaçada e feedback visual instantâneo.
3. **Fluidez Sem Degraus:** Transições de layout (como abrir uma pasta de CEG) devem respeitar proporções matemáticas rígidas para nunca quebrar o alinhamento da estante.

---

## 🎨 2. A Paleta Bipolar: Soft Y2K vs. Cyber-Luxury

A aplicação possui duas identidades cromáticas completas e intencionais. Não se trata de uma simples inversão de contraste, mas de **duas atmosferas distintas**:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   🌞 SOFT Y2K (Modo Claro)                             │
│   Nostalgia dos anos 2000, Dreamcore, Álbuns Físicos, Papelaria Deluxe │
├────────────────────────────────────────────────────────────────────────┤
│ • Fundo Base:       #F8F7FA (Off-white leitoso, nunca branco puro #FFF)│
│ • Superfícies:      #FFFFFF (Branco acrílico com borda translúcida)    │
│ • Textos Primários: #1E1B26 (Chumbo profundo, nunca preto 100%)        │
│ • Textos Secundários: #64748B (Slate médio com excelente legibilidade) │
│ • Lavanda Y2K:      #E9D5FF (Acentos suaves e pílulas ativas)          │
│ • Blush / Pink:     #FCE7F3 (Identidade feminina e fofa do K-pop)      │
│ • Menta / Sky:      #CCFBF1 e #E0F2FE (Badges de status informativos)  │
│ • Manteiga / Âmbar: #FEF9C3 (Avisos de prazo e destaque)               │
│ • Bordas Padrão:    rgba(233, 213, 255, 0.6) ou border-slate-200       │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│                   🌙 CYBER-LUXURY (Modo Escuro)                        │
│   Estética Kwangya / aespa, Vidro Acrílico Escurecido, Luzes de Neon   │
├────────────────────────────────────────────────────────────────────────┤
│ • Fundo Base:       #0B0A0F (Obsidiana cósmica com subtom violeta)     │
│ • Superfícies:      #14121B (Vidro acrílico fumê com backdrop-blur)    │
│ • Cartões Elevados: #1A1724 (Superfícies interativas com hover)        │
│ • Textos Primários: #E2E8F0 (Prata metálico de alto contraste)         │
│ • Textos Secundários: #94A3B8 (Cinza suave para metadados)             │
│ • Neon Pink:        #F472B6 (Ponto focal elétrico para botões e claims)│
│ • Roxo Elétrico:    #C084FC (Acentos de liderança GOM e badges VIP)    │
│ • Azul Gelo:        #38BDF8 (Rastreio internacional e remessas)        │
│ • Bordas Padrão:    rgba(255, 255, 255, 0.08) ou dark:border-slate-800 │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🔤 3. Tipografia & Ritmo Visual

A tipografia deve guiar os olhos do usuário de forma intuitiva, separando o entusiasmo visual dos dados financeiros críticos:

| Uso | Família / Classe Tailwind | Comportamento & Justificativa |
| :--- | :--- | :--- |
| **Títulos de CEG & Banners** | `font-black tracking-tight` | Letras condensadas e expressivas que comunicam impacto de lançamento e novidade. |
| **Nomes de Bias & Grupos** | `font-bold text-xs sm:text-sm` | Leitura ágil em telas pequenas, peso suficiente para se destacar sobre cards. |
| **Valores & Preços (R$)** | `font-mono font-black tabular-nums` | **Obrigatório:** Dígitos mono-espaçados evitam que colunas financeiras "pulem" ou tremam durante atualizações reativas de valores. |
| **Metadados & Badges** | `text-[10px] sm:text-[11px] font-bold uppercase tracking-wider` | Formato pílula com tracking espaçado para leitura técnica rápida (ex: `POB WITHMUU`, `REGULAR`, `SET 02`). |

---

## 📐 4. Geometria dos Componentes & Metáforas Físicas

### 4.1. O Card Toploader do Photocard (Proporção Áurea `2:3`)
- **Proporção Rigorosa:** Sempre utilizar proporção matemática `aspect-[2/3]` (55mm x 85mm), padrão universal do K-pop.
- **Cantos Arredondados:** `rounded-2xl` (16px) no card externo e `rounded-xl` (12px) nas fotos internas.
- **Borda de Toploader:** Borda acrílica sutil (`border border-slate-200/80 dark:border-white/10`) simulando a proteção plástica de colecionador.
- **Camada de Informação:** A foto do integrante deve ocupar os 75% superiores com visibilidade desobstruída. O rodapé inferior (25%) abriga o nome do membro, o valor financeiro e os botões de ação rápida.

### 4.2. A Técnica do Ambient Blur (Banners Panorâmicos)
Banners oficiais de comebacks são horizontais (16:9 ou 21:9), enquanto os cards do sistema são verticais (2:3):
- **O Erro Comum:** Cortar os rostos dos integrantes com `object-cover` nas laterais.
- **O Padrão ValCegs:**
  1. A imagem principal é renderizada centralizada e completa via `object-contain`.
  2. Ao fundo, uma cópia ampliada e desfocada da mesma foto preenche as margens verticais:
     ```html
     <div class="absolute inset-0 overflow-hidden">
         <img src="{{ foto }}" class="w-full h-full object-cover blur-md scale-110 opacity-70 dark:opacity-40" />
         <div class="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent"></div>
     </div>
     ```
  3. Resultado: Profundidade tridimensional imersiva sem cortar nenhum integrante.

### 4.3. Pasta Fechada vs. Gatefold Album Aberto
No painel do participante (`/me/`), os cards de CEGs funcionam como pastas colecionáveis:
- **Pasta Fechada (`aspect-[2/3]` em 1 coluna):**
  - Ocupa o mesmo espaço de um photocard comum no grid denso (até 6 colunas).
  - Exibe a capa consolidada, contagem de slots reservados e semáforo financeiro daquela compra.
- **Gatefold Album Aberto (`aspect-[4/3]` em `col-span-2`):**
  - Ao ser clicada, a pasta se desdobra horizontalmente ocupando **2 colunas**.
  - **Fórmula Matemática:** Como $2 \times \text{Largura} \div 1.5 \times \text{Largura} = 4/3$, a altura vertical da pasta dupla aberta coincide **rigorosamente** com a altura dos cards `2:3` vizinhos.
  - O grid nunca quebra ou empurra cards para linhas desniveladas.

---

## 🧭 5. Layout, Densidade & Navegação

### 5.1. Desktop: Sidebar Deezer / Linear
- Largura recolhida: `w-16` / `lg:pl-20`.
- Fixa, translúcida (`backdrop-blur-xl bg-white/80 dark:bg-cyber-obsidian/90`).
- Menu de gestão administrativa da GOM em **acordeão inline**: ao clicar em "Gestão", os subitens abrem empurrando os links inferiores para baixo suavemente, sem drawers sobrepostos que cobrem o conteúdo.

### 5.2. Mobile: Dock Flutuante Godly
- Barra flutuante ancorada na parte inferior da tela (`bottom-4 inset-x-4`), suspensa a 16px da borda física do aparelho.
- Cantos extremamente suaves (`rounded-full` ou `rounded-3xl`) com sombra de elevação acrílica (`shadow-2xl border border-white/20 dark:border-white/10`).
- Ícones com área de toque mínima de **44px x 44px** para garantir ergonomia com uma mão só.

### 5.3. Trilhos de Streaming com Navegação Tripla
Na Home, as CEGs são apresentadas em carrosséis temáticos por artista/grupo:
1. **Setas Direcionais:** Botões flutuantes redondos com ícones Lucide `chevron-left` e `chevron-right` para cliques precisos.
2. **Scroll Vertical para Horizontal (`@wheel`):** Ao passar o cursor sobre o carrossel, a rodinha do mouse rola os cards para os lados automaticamente sem prender a página.
3. **Clique e Arraste (*Drag-to-Scroll*):** O usuário pode clicar com o mouse e arrastar a esteira livremente como se estivesse usando uma tela touch.
4. **Mobile *Peek-a-boo*:** O último card visível na direita sempre deixa 15% de sua largura aparente, sinalizando visualmente que há mais itens a descobrir.

---

## 🚦 6. Semáforo Financeiro & Design de Feedback

### 6.1. O Semáforo Triplo Padronizado
Todas as pendências financeiras do sistema seguem uma linguagem universal:

```
🟢 VERDE ESMERALDA (bg-emerald-500, text-emerald-600, border-emerald-300)
   Significado: Quitado, 100% pago, liberado na Caixinha, remessa entregue.
   Sensação: Alívio, segurança, sucesso.

🟡 ÂMBAR / ROSA (bg-pink-500 ou bg-amber-500, text-pink-600)
   Significado: Pagamento pendente regular (item em prazo normal, frete em cálculo).
   Sensação: Atenção amigável, ação necessária no tempo do usuário.

🔴 CARMIM / ROSE (bg-rose-600, text-rose-600, border-rose-300)
   Significado: Prazo crítico vencendo em menos de 24h, item bloqueado por falta de taxa.
   Sensação: Urgência, ação imediata antes do cancelamento do slot.
```

### 6.2. Micro-interações de Pagamento (Quick Pix em 1 Clique)
- Ao clicar em qualquer botão de Pix, o sistema executa a cópia instantânea para a área de transferência (`navigator.clipboard.writeText`), alterando temporariamente o ícone para um check verde com o texto *"Chave Copiada!"*.
- Um **Toast Flutuante** sobe suavemente no topo/rodapé da tela confirmando o valor exato e o nome do titular, desaparecendo após 3 segundos sem recarregar a página.

---

## 🎭 7. Física de Movimento, Animação & Transições

1. **Escala Elástica no Toque / Clique:**
   - Todo card, botão ou pílula interativa deve responder com feedback tátil:
     `hover:scale-[1.015] active:scale-[0.98] transition-all duration-200 ease-out`.
2. **Modais Acrílicos com Backdrop Blur:**
   - Modais nunca devem surgir com telas opacas pretas sólidas.
   - Utilizar sempre `bg-slate-950/80 backdrop-blur-md` com animação de entrada suave (`scale-95 opacity-0` ➔ `scale-100 opacity-100`).
3. **Prevenção de FOUC (Flash of Unstyled Color):**
   - Script inline ultrarrápido no topo do `<head>` que verifica o `color-theme` no `localStorage` antes mesmo do primeiro frame de pintura do HTML, eliminando qualquer flash branco no modo escuro.

---

## 📱 8. Ergonomia Mobile-First & Zonas do Polegar

1. **A Zona Verde (Alcance Natural):**
   - Ações frequentes (adicionar ao carrinho, copiar Pix, mudar de aba, navegar no dock) residem nos 35% inferiores da tela do celular.
2. **Bottom Sheets em vez de Modais no Mobile:**
   - Ao tocar em um photocard no celular, em vez de abrir um modal centralizado no meio da tela (que exige esticar o polegar até o topo para fechar), o sistema abre uma **Gaveta (Bottom Sheet)** que sobe suavemente da base da tela com o botão "Comprar" posicionado exatamente onde o dedo já está apoiado.

---

## 🛠️ 9. Glossário de Tokens Tailwind para Uso Diário

Para manter a consistência visual em qualquer novo template ou componente, utilize estes padrões prontos:

| Elemento | Classes do Modo Claro (Y2K) | Classes do Modo Escuro (Cyber-Luxury) |
| :--- | :--- | :--- |
| **Card Principal** | `bg-white border border-slate-200 shadow-sm` | `dark:bg-slate-900 dark:border-slate-800` |
| **Input / Campo de Busca** | `bg-slate-50 border border-slate-200 text-slate-900 focus:ring-pink-500/30` | `dark:bg-slate-800 dark:border-slate-700 dark:text-white` |
| **Botão Primário (CTA)** | `bg-gradient-to-r from-pink-500 to-rose-500 text-white shadow-md shadow-pink-500/20` | `hover:from-pink-600 hover:to-rose-600 active:scale-[0.98]` |
| **Botão Secundário / Cancelar** | `bg-slate-100 text-slate-700 hover:bg-slate-200 border border-slate-200` | `dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700` |
| **Pílula Ativa (Filtro)** | `bg-pink-100 text-pink-700 border border-pink-200 font-bold` | `dark:bg-pink-950/60 dark:text-pink-300 dark:border-pink-900/60` |
| **Badge de Sucesso (Pago)** | `bg-emerald-50 text-emerald-800 border border-emerald-200 font-bold` | `dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800` |
| **Badge de Alerta (Urgente)** | `bg-rose-50 text-rose-800 border border-rose-200 font-black` | `dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-800` |
| **Ícones Lucide** | Traço uniforme `stroke-[1.75]` | Traço uniforme `stroke-[1.75]` |
