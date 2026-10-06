# 💡 Backlog de Ideias & Roadmap Futuro — ValCegs Manager

> **Propósito:** Registro centralizado de melhorias, inovações e ideias concebidas durante o desenvolvimento, para consulta, priorização e implementação em sprints futuras.

---

## 🎨 1. Estúdio de Recorte & Automação Visual

### ⚡ 1.1. Auto-Grade Inteligente (Grid Presets Matemáticos)
- **O que é:** Divisão automática da imagem da CEG em uma grade de $N$ colunas/linhas na proporção oficial de photocard (`2:3`), baseada no número de integrantes da CEG (ex: 2x2 para 4 membros, 2x3 para 5-6 membros, 2x4 para 8 membros).
- **Como funciona:** Um botão `⚡ Auto-Grade` no estúdio calcula instantaneamente as coordenadas das células sobre a imagem, com sliders opcionais de margem externa e espaçamento entre cards. O admin só precisa fazer micro-ajustes se necessário.
- **Complexidade:** Baixa | **Impacto:** Alto (economiza até 80% do tempo em templates de lojas como Weverse, Makestar, Soundwave).
- **Status:** 💡 Ideia Aprovada para Futuro.

### 🤖 1.2. Detecção Semântica de Photocards com Gemini Flash
- **O que é:** Uso da visão multimodal do Gemini Flash para analisar o banner da CEG, identificar as caixas delimitadoras de cada photocard (mesmo em layouts irregulares ou inclinados) e ler os nomes dos integrantes escritos na imagem.
- **Como funciona:** O admin clica em `✨ Detectar com IA`. O Gemini processa a imagem em ~1s e devolve as coordenadas já associadas a cada membro da CEG.
- **Complexidade:** Média | **Impacto:** Muito Alto (reconhece templates complexos e ignora marcas d'água automaticamente).
- **Status:** 💡 Ideia Aprovada para Futuro.

### 👤 1.3. Detecção Automática de Rostos (Face Detection)
- **O que é:** Detecção facial no navegador (via MediaPipe ou FaceDetector API) para quando o banner não for um template de loja, mas sim um teaser oficial com o grupo inteiro reunido no cenário.
- **Como funciona:** Localiza os rostos, ordena da esquerda para a direita e enquadra cada integrante na proporção 2:3 com margem adequada para busto e cabeça.
- **Complexidade:** Média | **Impacto:** Médio.
- **Status:** 💡 Ideia Registrada.

### 📦 1.4. Exportação em Lote de Photocards Recortados (.ZIP)
- **O que é:** Botão para o organizador baixar um pacote comprimido com as fotos individuais já nomeadas por integrante (ex: `karina_photocard.webp`, `winter_photocard.webp`), facilitando o envio para redes sociais ou anúncios.
- **Complexidade:** Baixa | **Impacto:** Médio.
- **Status:** 💡 Ideia Registrada.

---

## 📦 2. Logística, Caixas & Envios Nacionais

### 🚚 2.1. Cotação Automática de Frete Nacional (Melhor Envio / Correios API)
- **O que é:** Integração para calcular em tempo real o valor do frete para o participante quando ele for pedir o envio da "Caixinha", gerando etiquetas de envio com código de barras diretamente pelo painel administrativo.
- **Complexidade:** Média | **Impacto:** Alto.
- **Status:** 💡 Ideia Registrada.

### 📲 2.2. Disparo Automático de Mensagens no WhatsApp (Z-API / Baileys)
- **O que é:** Notificação proativa via WhatsApp quando:
  1. A Caixa da CEG muda de status (ex: "Chegou no Brasil!").
  2. Um prazo Pix está a 24 horas de vencer.
  3. O pacote nacional for postado com o link de rastreio.
- **Complexidade:** Média/Alta | **Impacto:** Muito Alto.
- **Status:** 💡 Ideia Registrada.

---

## 👥 3. Experiência do Participante & Comunidade

### ⭐ 3.1. Radar de Bias / Lista de Desejos (Wishlist)
- **O que é:** O participante define seus integrantes favoritos (bias) no seu perfil `/me/`. Quando uma nova CEG é aberta contendo slots dessa bias, ele recebe um aviso prioritário.
- **Complexidade:** Baixa/Média | **Impacto:** Alto engajamento.
- **Status:** 💡 Ideia Registrada.

### 🎴 3.2. Binder Virtual / Álbum de Colecionador
- **O que é:** Uma visualização em estilo "pasta de photocards" no perfil do participante, exibindo todos os photocards que ele já comprou e recebeu com acabamento holográfico interativo.
- **Complexidade:** Baixa | **Impacto:** Alto apelo visual e fidelização.
- **Status:** 💡 Ideia Registrada.

---

## 📊 Matriz de Priorização (Esforço x Impacto)

```
        ▲ ALTO
        │
        │   [1.1 Auto-Grade]         [1.2 IA Gemini Flash]
        │                            [2.2 WhatsApp Notificações]
IMPACTO │   [3.1 Radar de Bias]
        │   [3.2 Binder Virtual]     [2.1 Cotação Melhor Envio]
        │   [1.4 Download ZIP]       [1.3 Face Detection]
        │
        └─────────────────────────────────────────────►
          BAIXO                   ESFORÇO         ALTO
```
