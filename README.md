# lic-web-sapatas — Painel de Licenças do DIMSAPATAS ULTIMATE

Painel web de gerenciamento de licenças, acessível via browser (desktop e celular).

## Estrutura

```
lic-web-sapatas/
├── app.py               ← Backend Flask (API + painel web)
├── templates/
│   ├── login.html       ← Tela de login
│   └── index.html       ← Painel principal
├── requirements.txt
├── render.yaml          ← Deploy no Render
├── licence.json         ← JSON inicial para upload no Dropbox
└── README.md
```

## Deploy — Passo a Passo

### 1. Criar pasta no Dropbox

No site do Dropbox, crie o caminho:
```
/DIMSAPATAS/LICENCE/
```
Faça upload do arquivo `licence.json` para essa pasta.

---

### 2. Criar repositório no GitHub

```bash
cd C:\
mkdir lic-web-sapatas
cd lic-web-sapatas
# copie os arquivos aqui (app.py, templates/, requirements.txt, render.yaml)
git init
git add .
git commit -m "lic-web-sapatas inicial"
git remote add origin https://github.com/engmarciocunha/lic-web-sapatas.git
git push -u origin main
```

---

### 3. Criar Web Service no Render

1. Acesse [render.com](https://render.com) → **New → Web Service**
2. Conecte o repositório `lic-web-sapatas`
3. Configurações:
   - **Name:** `lic-web-sapatas`
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Plan:** Free

4. Em **Environment Variables**, adicione:

| Variável | Valor |
|---|---|
| `PAINEL_SENHA` | sua senha do painel |
| `SAP_VERSAO_ATUAL` | `1.0.0` |
| `SAP_DOWNLOAD_URL` | (URL quando tiver) |
| `DBX_APP_KEY` | chave do app Dropbox |
| `DBX_APP_SECRET` | secret do app Dropbox |
| `DBX_REFRESH_TOKEN` | refresh token do Dropbox |

> Use as mesmas credenciais Dropbox do DIMBLOCOS/DIMHOLLOW
> (o mesmo app Dropbox pode acessar qualquer pasta)

5. Clique em **Create Web Service**

---

### 4. Atualizar licenca.py do DIMSAPATAS

O `licenca.py` do DIMSAPATAS já aponta para:
```
https://servidor-licencas-atpg.onrender.com/validar
```

Se quiser usar o `lic-web-sapatas` como servidor principal, mude para:
```
https://lic-web-sapatas.onrender.com/validar
```

---

## URL do painel após deploy

```
https://lic-web-sapatas.onrender.com
```

Login com a senha definida em `PAINEL_SENHA`.

---

## Chaves geradas

O servidor gera chaves com prefixo `DIM-SAP-`:
```
DIM-SAP-0001       ← chave base (o que você entrega ao cliente)
DIM-SAP-0001-A     ← chave completa (gerada na 1ª ativação)
DIM-SAP-0001-B     ← 2º dispositivo, se limite_dispositivos ≥ 2
```
