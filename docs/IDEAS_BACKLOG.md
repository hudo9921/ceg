# 💡 Backlog de Ideias Futuras — ValCegs Manager

> **Regra:** Novas ideias são adicionadas a este documento **apenas quando expressamente solicitado pelo usuário**. Brainstorms e discussões gerais não devem ser inseridos automaticamente.

---

## 🎨 1. Estúdio de Recorte de Photocards

### ⚡ 1.1. Reconhecimento / Criação Automática de Quadrados por Integrante
- **Contexto:** Ao abrir o estúdio de recorte com a foto/template da CEG, permitir que o sistema já crie automaticamente os quadrados de recorte pré-posicionados para cada integrante do set, cabendo à admin apenas pequenos ajustes se necessário.
- **Caminhos a avaliar quando formos implementar:**
  1. **Auto-Grade (Grid Presets):** Cálculo matemático instantâneo no navegador para templates de lojas (ex: 2x2, 2x3, 2x4, etc.), dividindo a imagem em células proporcionais de photocard (`2:3`).
  2. **Detecção com IA (Gemini Flash Vision):** Análise multimodal para identificar a posição dos cards e ler nomes dos integrantes no banner.
- **Status:** Guardado para implementação futura.

---

## 📄 2. Paginação do Sistema

### 🛍️ 2.1. Área do Participante (`/me/` — Minhas Compras)
- **Abordagem Escolhida:** **Abordagem 1 — Paginação Client-side Reativa no Alpine.js**.
- **Premissa Fundamental:** Todas as informações precisam permanecer carregadas no estado da página para que métricas consolidadas (Total a Pagar, contagens de pendentes/pagos), Semáforo de Prazos, Central de Pagamento Rápido (Quick Pix) e busca instantânea por integrante continuem 100% funcionais sem recarregamento de tela.
- **Mecânica de Implementação:**
  - O Alpine.js mantém todos os grupos de CEG no componente, mas restringe a renderização visual do grid (ex: exibindo lotes de 12 ou 18 pastas por vez).
  - Controles na base da estante: navegação de páginas (`« Anterior | Página X de Y | Próxima »`) ou botão *"📂 Carregar mais 12 CEGs"*.
  - Ao usar a busca por integrante ou filtros de status/grupo, o filtro é aplicado sobre toda a base e a visualização é resetada para a página 1 dos resultados.
- **Status:** Guardado para implementação futura.

### 🌐 2.2. Página Pública de CEGs (Catálogo / Feed)
- **Abordagem Escolhida:** **Paginação padrão por tipo/status de CEG**.
- **Premissa Fundamental:** Organização limpa por ciclo de vida da CEG e paginação tradicional para manter a página rápida e com URLs compartilháveis.
- **Mecânica de Implementação:**
  - Divisão estruturada por status/tipo:
    - **🟢 Abertas:** Foco em conversão imediata, exibidas em destaque (grid paginado caso haja muitas ativas).
    - **⏰ Agendadas:** Exibição cronológica por data de abertura.
    - **📁 Encerradas / Concluídas:** Histórico com paginação server-side via Django `Paginator` (ex: 12 a 18 CEGs por página com parâmetros `?page=X`), preservando links diretos e SEO.
- **Status:** Guardado para implementação futura.
