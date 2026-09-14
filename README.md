# ✨ K-pop CEG Manager (Sistema de Gestão de Compras em Grupo)

Plataforma web para gerenciar e organizar **Compras em Grupo (CEGs)** de itens de K-pop (photocards, inclusões, álbuns), substituindo formulários manuais e planilhas por um sistema centralizado de reservas (*claims*), consulta para participantes e métricas para o organizador.

---

## 🚀 Funcionalidades Principais

* **Hierarquia Flexível:**
  $$\text{Grupo} \rightarrow \text{Era} \rightarrow \text{CEG} \rightarrow \text{Sets (Instâncias 1 a } X) \rightarrow \text{Slots de Itens}$$
  Atende desde solistas (com 2 a 3 variações de cards) até grupos massivos (como tripleS com 24 integrantes) ou units e inclusões avulsas.
* **Reserva Única (*Claim*) com Proteção de Concorrência:**
  Controle transacional atômico (`select_for_update`) que impede *race conditions* no segundo zero de abertura. Cada slot físico em um Set só pode ser pego por 1 pessoa.
* **Agendamento e Modo Standby (*Hype & Countdown*):**
  Permite cadastrar a CEG com antecedência com data e hora exatas de abertura (`opens_at`). A página pública exibe regras, preços e um cronômetro regressivo em tempo real; os botões de reserva só destravam no segundo zero.
* **Consulta Sem Senha via WhatsApp (OTP):**
  O participante acessa suas reservas e histórico informando apenas o número do WhatsApp. O sistema gera e envia um código de 6 dígitos temporário (10 min).
* **Gestão de Pagamentos Manual:**
  A reserva entra como pendente (`PENDING`), o participante realiza o pagamento Pix conforme a chave indicada, e o organizador confirma o status com 1 clique no Django Admin ou no painel.
* **Inteligência e Analítica de Vendas:**
  - Ranking de integrantes mais disputados (taxa de reserva e esgotamento).
  - Taxa de preenchimento dos Sets para saber quando fechar pedidos com fornecedores.
  - Faturamento consolidado por Era e por CEG.

---

## 🛠️ Tecnologias Utilizadas

- **Backend:** Python 3.11 + Django 5.2 + Django REST Framework
- **Banco de Dados:** SQLite (com suporte a transações e timeout de concorrência)
- **Frontend:** Django Templates + Tailwind CSS + Alpine.js (reatividade leve, sem build complexo)
- **WhatsApp Gateway:** Adapter modular (Mock/Console para desenvolvimento + suporte a Evolution API e Z-API)

---

## 📦 Como Executar o Projeto Localmente

### 1. Pré-requisitos
- Python 3.11 instalado

### 2. Ativação do Ambiente Virtual e Dependências
```bash
# No Windows PowerShell
.\.venv\Scripts\Activate.ps1
# Ou chame diretamente o executável do venv:
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Executar Migrações e Carregar Dados de Demonstração
```bash
# Aplica as tabelas no SQLite
.\.venv\Scripts\python.exe manage.py migrate

# Cria dados de teste com TWICE, tripleS, slots e superusuário admin
.\.venv\Scripts\python.exe manage.py seed_ceg_data
```

> [!NOTE]
> O comando `seed_ceg_data` cria automaticamente:
> - Superusuário do Django Admin: **login:** `admin` | **senha:** `admin123`
> - CEG Aberta: `CEG POB Makestar 2.0 — With YOU-th` (TWICE, com 2 Sets)
> - CEG Standby (Countdown): `CEG POB Withmuu — ASSEMBLE24` (tripleS, 24 membros, abre em 2h30)

### 4. Iniciar o Servidor de Desenvolvimento
```bash
.\.venv\Scripts\python.exe manage.py runserver
```

Acesse no navegador:
- **Página Inicial:** [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Vitrine TWICE (Aberta):** [http://127.0.0.1:8000/ceg/ceg-pob-makestar-with-you-th/](http://127.0.0.1:8000/ceg/ceg-pob-makestar-with-you-th/)
- **Vitrine tripleS (Standby / Countdown):** [http://127.0.0.1:8000/ceg/ceg-pob-withmuu-assemble24/](http://127.0.0.1:8000/ceg/ceg-pob-withmuu-assemble24/)
- **Consulta via WhatsApp (OTP):** [http://127.0.0.1:8000/me/login/](http://127.0.0.1:8000/me/login/)
- **Painel de Métricas:** [http://127.0.0.1:8000/analytics/](http://127.0.0.1:8000/analytics/)
- **Django Admin:** [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

---

## 🧪 Como Executar a Suíte de Testes Automatizados

Para rodar todos os testes de concorrência, standby, OTP e views:
```bash
.\.venv\Scripts\python.exe manage.py test
```

---

## 📱 Configuração do WhatsApp Gateway

No arquivo `.env` ou nas variáveis de ambiente:

### Modo Console Mock (Padrão para Dev):
```env
WHATSAPP_PROVIDER=console
```
*As mensagens com os códigos de 6 dígitos são impressas diretamente no terminal do servidor.*

### Evolution API:
```env
WHATSAPP_PROVIDER=evolution
EVOLUTION_API_URL=http://localhost:8080
EVOLUTION_API_KEY=sua_chave_aqui
EVOLUTION_INSTANCE_NAME=ceg-bot
```

### Z-API:
```env
WHATSAPP_PROVIDER=zapi
ZAPI_INSTANCE_ID=seu_instance_id
ZAPI_TOKEN=seu_token
ZAPI_CLIENT_TOKEN=seu_client_token
```
