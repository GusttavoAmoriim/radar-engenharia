# Publicar no GitHub (coleta, página e avisos automáticos)

Resultado: a cada 3 horas o GitHub coleta os concursos, valida os editais, manda os avisos no Telegram e atualiza uma página que você abre no celular. Seu computador não precisa ficar ligado.

A página é pública (qualquer pessoa com o endereço vê). Ela mostra só dados de fontes oficiais. Não há login nem edição: é uma lista para consulta.

## 1. Criar o repositório
Em github.com, **New repository**. Nome: `radar-engenharia`. Marque **Public**. Não marque README nem .gitignore.

## 2. Enviar o projeto
Precisa do Git (`winget install --id Git.Git -e`; abra um terminal novo). Na pasta `D:\radar-engenharia`:

    git init
    git add .
    git status

Confira que `.env` e a pasta `dados` **não** aparecem na lista. Depois:

    git commit -m "Radar Engenharia"
    git branch -M main
    git remote add origin https://github.com/SEU-USUARIO/radar-engenharia.git
    git push -u origin main

## 3. Telegram (opcional, para receber avisos no celular)
1. No Telegram, fale com **@BotFather**, envie `/newbot` e guarde o token.
2. Mande "oi" para o seu bot novo. Abra `https://api.telegram.org/bot<TOKEN>/getUpdates` e copie o número de `"chat":{"id":...}`.
3. No repositório: **Settings → Secrets and variables → Actions → New repository secret**. Crie `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.

## 4. Ligar a página
**Settings → Pages → Build and deployment → Source: GitHub Actions**.

## 5. Primeira execução
Aba **Actions → Coletar e publicar → Run workflow**. Quando ficar verde, o endereço da página aparece no fim da execução (`https://SEU-USUARIO.github.io/radar-engenharia/`). Salve na tela inicial do celular.

Se der erro de permissão ao gravar o banco: **Settings → Actions → General → Workflow permissions → Read and write**.

## Cuidados
- **Pare o radar no computador** depois de publicar: dois bancos (o seu e o do GitHub) saem de sincronia.
- Alguns sites podem recusar pedidos vindos do GitHub. Se uma fonte falhar em toda execução, o painel do Actions mostra o motivo.
- O GitHub pode desativar execuções agendadas de repositório sem atividade por 60 dias. Se parar, abra Actions e clique em habilitar.
- Para testar o Telegram no seu computador: defina as duas variáveis no `.env` e rode `.venv\Scripts\python -m app.cloud testar-telegram`.
