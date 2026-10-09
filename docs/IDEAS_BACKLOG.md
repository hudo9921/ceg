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

---

## ✨ 3. Experiência Visual Premium & Micro-interações de Luxo

### 🎴 3.1. Efeito Foil Holográfico 3D & Tilt nos Photocards
- **Contexto:** Simular a sensação física de segurar um photocard raro (POB, Lucky Draw) sob a luz do ambiente.
- **Mecânica:**
  - Inclinação tridimensional sutil no hover via CSS `perspective` e coordenadas de mouse (`rotateX`, `rotateY`).
  - Camada de brilho furta-cor com gradiente arco-íris e `mix-blend-mode: color-dodge` que se desloca dinamicamente acompanhando a posição do cursor.
- **Status:** Guardado para implementação futura.

### 💡 3.2. Spotlight Borders (Bordas de Holofote no Cursor)
- **Contexto:** Elevar o acabamento de cards de CEG, Caixas e painéis gerenciais no estilo Linear/Raycast.
- **Mecânica:** As bordas dos cards possuem iluminação dinâmica que se acende suavemente apenas no ponto focal mais próximo do cursor do mouse, criando um rastro luminoso elegante.
- **Status:** Guardado para implementação futura.

### 🔢 3.3. Odômetro Rolante de Dígitos (Rolling Numbers)
- **Contexto:** Atualização visual sofisticada de valores monetários (R$), contadores de slots e ocupação de sets.
- **Mecânica:** Os números não alternam bruscamente de valor; os dígitos deslizam verticalmente com física de amortecimento estilo odômetro de relógio de luxo.
- **Status:** Guardado para implementação futura.

### 📳 3.4. Micro-haptics no Mobile (Vibração Tátil)
- **Contexto:** Feedback tátil nativo ao usar a plataforma pelo smartphone.
- **Mecânica:** Utilizar a Web Vibration API (`navigator.vibrate(8-10ms)`) em momentos chave de interação: confirmação de reserva de slot, cópia de chave Pix e seleção de itens na Caixinha.
- **Status:** Guardado para implementação futura.

### ⌨️ 3.5. Command Palette Global (`Ctrl + K` / `Cmd + K`)
- **Contexto:** Atalho universal para power users e organizadoras navegarem instantaneamente entre qualquer grupo, integrante, CEG ou remessa.
- **Mecânica:** Modal flutuante estilo Spotlight com busca difusa instantânea, comandos de atalho rápido e navegação 100% por teclado.
- **Status:** Guardado para implementação futura.

### 🎬 3.6. View Transitions API (Morfismo Fluido entre Telas)
- **Contexto:** Eliminar o piscar de recarregamento ao navegar entre a Vitrine da Home e a Página de Detalhe da CEG.
- **Mecânica:** Transição morphing nativa onde a imagem do card de capa viaja suavemente até o topo da tela de detalhe.
- **Status:** Guardado para implementação futura.

### 🎉 3.7. Partículas de Confetti Y2K / Sparkles
- **Contexto:** Celebrar a vitória de conseguir um slot concorrido no Segundo Zero.
- **Mecânica:** Explosão minimalista e elegante de estrelinhas pastéis cintilantes via `canvas-confetti` ultraleve ao concluir a reserva com sucesso.
- **Status:** Guardado para implementação futura.

### 🔊 3.8. Micro-sonoplastia Opcional (Audio Feedback Tátil)
- **Contexto:** Reforçar a sensação tátil da interface com sons de alta fidelidade e volume ultrassuave (estilo Apple Pay / Nintendo Switch).
- **Mecânica:** Efeito sonoro de "tick" suave em abas e "chime" discreto ao confirmar pagamentos, com controle liga/desliga obrigatório no perfil.
- **Status:** Guardado para implementação futura.

---

## 🛍️ 4. Experiência do Participante / Joiner

### 📍 4.1. Linha do Tempo Visual do Photocard ("Onde está meu item?")
- **Contexto:** Reduzir a ansiedade dos colecionadores durante os 2 a 4 meses de espera entre o pagamento na Ásia e a entrega física no Brasil.
- **Mecânica:**
  - Substituir o status textual estático por uma régua de progresso visual estilo Shopee/Amazon em cada CEG no painel do participante (`/me/`):
    `[Reserva Confirmada]` ➔ `[Comprado na Ásia]` ➔ `[A caminho do Brasil (Caixa #X)]` ➔ `[Na Alfândega]` ➔ `[Chegou na GOM (Em triagem)]` ➔ `[Guardado na Caixinha / Enviado]`.
  - O participante acompanha visualmente onde está o lote sem precisar perguntar no WhatsApp.
- **Status:** Guardado para implementação futura.

### 📦 4.2. O "Cofre da Caixinha" com Solicitação de Envio com 1 Clique
- **Contexto:** Facilitar a vida do colecionador que acumula dezenas de photocards na caixinha para economizar no frete nacional.
- **Mecânica:**
  - Uma aba dedicada chamada **"Meu Cofre / Minha Caixinha"** com visualização em grid de todos os photocards já fisicamente em posse da GOM.
  - Botão destacado: **"📦 Solicitar Envio da Minha Caixinha"**.
  - Modal com conferência do endereço cadastrado, seleção da modalidade de envio (Mini Envios, PAC, Sedex) e envio automático da solicitação para a fila de empacotamento da GOM.
- **Status:** Guardado para implementação futura.

### 💖 4.3. "Alerta de Bias" & Lista de Desejos (Wishlist / ISO)
- **Contexto:** Ajudar colecionadores a conseguirem vagas concorridas dos seus integrantes favoritos antes que esgotem no Segundo Zero.
- **Mecânica:**
  - No perfil do usuário, permitir selecionar seus grupos e integrantes favoritos (*Bias*).
  - Destaque visual na vitrine e filtros dedicados (*"Apenas meus Bias"*).
  - Notificação prioritária quando uma nova CEG do grupo abrir ou quando um slot do integrante for cancelado/liberado em repescagem.
- **Status:** Guardado para implementação futura.

### 📱 4.4. Notificações Ativas de Prazos (WhatsApp & E-mail)
- **Contexto:** Lembrar participantes distraídos dos prazos de pagamentos das fases subsequentes (Frete Internacional e Taxa Aduaneira) para evitar calotes involuntários.
- **Mecânica:**
  - Disparos automáticos e personalizados via bot de WhatsApp ou e-mail nos marcos temporais da CEG:
    - Abertura de prazo de Frete Internacional / Taxa com valor individual e Pix.
    - Lembrete de 24h antes do vencimento.
    - Notificação com código de rastreio nacional quando a caixa ou pacote for postado.
- **Status:** Guardado para implementação futura.

---

## ⚡ 5. Eficiência Operacional para a GOM / Admin

### 🏷️ 5.1. "Mesa de Triagem & Packing List" (Separação Física de Photocards)
- **Contexto:** Auxiliar a organizadora no momento mais caótico da operação: quando a remessa internacional chega com 200 a 400 photocards misturados e precisam ser empacotados sem erros de troca de integrantes.
- **Mecânica:**
  - **Ficha por Photocard:** Busca rápida onde a admin digita/seleciona o card em mãos e a tela mostra exatamente quem comprou cada unidade (ex: *"1 para @ana, 1 para @carol"*).
  - **Packing List com Checkbox:** Ao empacotar o envelope de um participante, uma lista conferível com checkboxes de todos os photocards e brindes que devem estar dentro daquele envio antes de lacrar o plástico bolha.
- **Status:** Guardado para implementação futura.

### 🚨 5.2. Régua de Cobrança Automática & Repescagem de Inadimplentes
- **Contexto:** Eliminar o desgaste diário da organizadora de mandar dezenas de mensagens manuais de cobrança e agilizar a liberação de vagas presas por caloteiros.
- **Mecânica:**
  - Botão de disparo em lote *"Cobrar Inadimplentes da Fase X"* que envia mensagem direta formatada via WhatsApp com valores, chave Pix e link de envio do comprovante.
  - Temporizador de tolerância (ex: 24h/48h): se não houver resposta ou pagamento, a admin ativa **"Liberar Repescagem"**, que reabre o slot como disponível no site e notifica a lista de espera.
- **Status:** Guardado para implementação futura.

### 🔗 5.3. Importador Rápido de Anúncios Asiáticos (Mercari Japan, Bunjang, Neokyo)
- **Contexto:** Agilizar a criação de CEGs de lotes usados e photocards raros garimpados em marketplaces japoneses e coreanos.
- **Mecânica:**
  - No formulário de criação de CEG/Item, campo *"Importar por Link"*.
  - A organizadora cola o link do Mercari/Bunjang; o backend realiza web scraping dos metadados públicos trazendo imagem principal em alta resolução, título do produto e preço original em Iene (¥) ou Won (₩), aplicando automaticamente a conversão cambial do dia para Reais (R$).
- **Status:** Guardado para implementação futura.


