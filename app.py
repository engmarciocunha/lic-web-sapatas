"""
app.py — Servidor de licenças do DIMSAPATAS ULTIMATE
Painel web + API de validação para clientes

Rotas públicas (cliente):
  GET  /versao    → versão atual e URL de download
  POST /validar   → ativa ou verifica licença

Painel web (Márcio):
  GET/POST /login
  GET      /
  GET      /api/licencas
  POST     /api/licencas
  PUT      /api/licencas/<chave_base>
  DELETE   /api/licencas/<chave_base>
  DELETE   /api/licencas/<chave_base>/sublicencas/<chave_sub>
  POST     /api/licencas/<chave_base>/sublicencas/<chave_sub>/limpar
"""

import os
import json
import random
import string
from datetime import date, datetime, timezone
from functools import wraps

import requests
from flask import (Flask, request, jsonify, render_template,
                   redirect, url_for, session)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-mude-em-prod")

# ── Configuração ──────────────────────────────────────────────────────────────

PAINEL_SENHA     = os.environ.get("PAINEL_SENHA", "trocar123")
VERSAO_ATUAL     = os.environ.get("SAP_VERSAO_ATUAL", "1.0.0")
DOWNLOAD_URL     = os.environ.get("SAP_DOWNLOAD_URL", "")

DBX_APP_KEY      = os.environ.get("DBX_APP_KEY", "")
DBX_APP_SECRET   = os.environ.get("DBX_APP_SECRET", "")
DBX_REFRESH_TOKEN = os.environ.get("DBX_REFRESH_TOKEN", "")

# Caminho do JSON de licenças no Dropbox (produto separado do DIMBLOCOS)
CAMINHO_DBX = "/DIMSAPATAS/LICENCE/licence.json"

PREFIXO_CHAVE = "DIM-SAP-"
PLACEHOLDERS_ENV = {"", "PREENCHER", "CHANGE_ME", "TROCAR", "TROCAR123"}


def _erro_dropbox(exc: Exception) -> str:
    resp = getattr(exc, "response", None)
    if resp is not None:
        texto = getattr(resp, "text", "") or ""
        if texto:
            try:
                body = resp.json()
                erro = body.get("error") or body.get("error_summary") or texto
                if getattr(resp, "status_code", None) == 400 and "oauth2/token" in str(resp.url):
                    return f"Credenciais Dropbox inválidas ou ausentes ({erro}). Configure DBX_APP_KEY, DBX_APP_SECRET e DBX_REFRESH_TOKEN no Render."
            except Exception:
                pass
            return texto[:500]
    return str(exc)


def _env_configurada(valor: str) -> bool:
    return str(valor or "").strip().upper() not in PLACEHOLDERS_ENV


def _validar_config_dropbox() -> None:
    faltando = [
        nome for nome, valor in {
            "DBX_APP_KEY": DBX_APP_KEY,
            "DBX_APP_SECRET": DBX_APP_SECRET,
            "DBX_REFRESH_TOKEN": DBX_REFRESH_TOKEN,
        }.items()
        if not _env_configurada(valor)
    ]
    if faltando:
        raise RuntimeError(
            "Configure as variáveis Dropbox no Render: " + ", ".join(faltando)
        )


def _json_nao_encontrado(exc: Exception) -> bool:
    resp = getattr(exc, "response", None)
    return (
        resp is not None
        and getattr(resp, "status_code", None) == 409
        and "not_found" in (getattr(resp, "text", "") or "")
    )


def _dados_vazios() -> dict:
    return {"licencas": []}


def _normalizar_data(valor: str) -> str:
    valor = str(valor or "").strip()
    if not valor:
        raise ValueError("Informe a data de expiração.")

    try:
        return date.fromisoformat(valor).isoformat()
    except ValueError:
        raise ValueError("Data de expiração inválida. Use AAAA-MM-DD.")


def _normalizar_limite(valor) -> int:
    try:
        limite = int(valor)
    except (TypeError, ValueError):
        raise ValueError("Limite de dispositivos inválido.")
    if limite < 1 or limite > 26:
        raise ValueError("Limite de dispositivos deve ficar entre 1 e 26.")
    return limite


def _normalizar_ativo(valor) -> bool:
    if isinstance(valor, str):
        return valor.strip().lower() in {"1", "true", "sim", "s", "yes", "on"}
    return bool(valor)


# ── Dropbox helpers ───────────────────────────────────────────────────────────

def _get_access_token() -> str:
    _validar_config_dropbox()
    r = requests.post(
        "https://api.dropbox.com/oauth2/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": DBX_REFRESH_TOKEN,
            "client_id":     DBX_APP_KEY,
            "client_secret": DBX_APP_SECRET,
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _garantir_pasta_dropbox(token: str, caminho_arquivo: str) -> None:
    partes = [p for p in caminho_arquivo.strip("/").split("/")[:-1] if p]
    caminho = ""
    for parte in partes:
        caminho += "/" + parte
        r = requests.post(
            "https://api.dropboxapi.com/2/files/create_folder_v2",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"path": caminho, "autorename": False},
            timeout=10,
        )
        if r.status_code == 409:
            continue
        r.raise_for_status()


def ler_json() -> dict:
    token = _get_access_token()
    r = requests.post(
        "https://content.dropboxapi.com/2/files/download",
        headers={
            "Authorization":    f"Bearer {token}",
            "Dropbox-API-Arg":  json.dumps({"path": CAMINHO_DBX}),
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def salvar_json(dados: dict) -> bool:
    token = _get_access_token()
    _garantir_pasta_dropbox(token, CAMINHO_DBX)
    payload = json.dumps(dados, indent=2, ensure_ascii=False).encode("utf-8")
    r = requests.post(
        "https://content.dropboxapi.com/2/files/upload",
        headers={
            "Authorization":   f"Bearer {token}",
            "Content-Type":    "application/octet-stream",
            "Dropbox-API-Arg": json.dumps({
                "path":        CAMINHO_DBX,
                "mode":        "overwrite",
                "autorename":  False,
            }),
        },
        data=payload,
        timeout=10,
    )
    r.raise_for_status()
    return True


# ── Auth painel ───────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("sap_auth"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    erro = ""
    if request.method == "POST":
        if request.form.get("senha") == PAINEL_SENHA:
            session["sap_auth"] = True
            return redirect(url_for("index"))
        erro = "Senha incorreta."
    return render_template("login.html", erro=erro, produto="DIMSAPATAS")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── Painel web ────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return render_template("index.html", produto="DIMSAPATAS")


# ── Rotas públicas (cliente) ──────────────────────────────────────────────────

@app.route("/versao", methods=["GET"])
def versao():
    return jsonify({"versao": VERSAO_ATUAL, "download_url": DOWNLOAD_URL})


@app.route("/validar", methods=["POST"])
def validar():
    """
    Valida ou ativa a licença de um cliente DIMSAPATAS.

    Payload JSON:
        chave        : str   — chave_base (1ª ativação) ou chave_completa
        id_maquina   : str   — SHA-256[:24] dos MACs físicos
        macs_fisicos : list  — lista de MACs físicos
        nome_maquina : str   — platform.node()
        primeira_vez : bool
        versao       : str
        produto      : str   — "DIMSAPATAS" (informativo)

    Retorna:
        {"valido": True,  "chave_completa": "DIM-SAP-0001-XXXXXXXXXX-A"}
        {"valido": False, "motivo": "<codigo>"}

    Lógica:
        1. Chave encontrada, ativa e não vencida?
        2. id_maquina bate com o registrado? → aceita
        3. Interseção de MACs não vazia?      → aceita + atualiza id_maquina
        4. Sem interseção, sem espaço         → rejeita
    """
    body          = request.get_json(silent=True) or {}
    chave         = str(body.get("chave",        "")).strip()
    id_maquina    = str(body.get("id_maquina",   "")).strip()
    macs_fisicos  = body.get("macs_fisicos", [])
    nome_maquina  = str(body.get("nome_maquina", "")).strip()
    primeira_vez  = bool(body.get("primeira_vez", False))
    versao_cli    = str(body.get("versao", "")).strip()

    if not chave or not id_maquina:
        return jsonify({"valido": False, "motivo": "payload_incompleto"})

    # Normaliza MACs recebidos
    macs_atuais = sorted(
        m.upper().replace(":", "").replace("-", "")
        for m in macs_fisicos
        if isinstance(m, str) and len(m.replace(":", "").replace("-", "")) == 12
    )

    try:
        dados = ler_json()
    except Exception:
        return jsonify({"valido": False, "motivo": "erro_servidor"}), 500

    agora = datetime.now(timezone.utc).isoformat()

    for lic in dados.get("licencas", []):
        chave_base = lic.get("chave_base", "")

        # Aceita tanto a chave_base quanto qualquer chave_completa (com sufixo letra)
        if not chave.startswith(chave_base):
            continue

        # Licença ativa e não vencida?
        if not lic.get("ativo", False):
            return jsonify({"valido": False, "motivo": "licenca_inativa"})

        try:
            exp = date.fromisoformat(lic["expiracao"])
        except Exception:
            return jsonify({"valido": False, "motivo": "expiracao_invalida"})

        if date.today() > exp:
            return jsonify({"valido": False, "motivo": "licenca_vencida"})

        sublicencas = lic.setdefault("sublicencas", [])
        limite      = lic.get("limite_dispositivos", 1)

        # ── Primeira ativação ─────────────────────────────────────────────────
        if primeira_vez:
            if len(sublicencas) >= limite:
                return jsonify({"valido": False, "motivo": "limite_atingido"})

            # Gera letra de sublicença
            letras_usadas = {s.get("letra", "") for s in sublicencas}
            letra = next(
                (c for c in string.ascii_uppercase if c not in letras_usadas),
                "?"
            )
            chave_completa = f"{chave_base}-{letra}"

            sublicencas.append({
                "letra":         letra,
                "chave_sub":     chave_completa,
                "id_maquina":    id_maquina,
                "macs_registro": macs_atuais,
                "macs_acesso":   macs_atuais,
                "nome_maquina":  nome_maquina,
                "versao":        versao_cli,
                "data_registro": agora,
                "ultimo_acesso": agora,
            })
            salvar_json(dados)
            return jsonify({"valido": True, "chave_completa": chave_completa})

        # ── Execuções subsequentes ────────────────────────────────────────────
        for sub in sublicencas:
            if sub.get("chave_sub", "") != chave:
                continue

            macs_reg = sub.get("macs_registro", [])
            intersec = set(macs_atuais) & set(macs_reg)

            # Caso 1: id_maquina idêntico
            if sub.get("id_maquina", "") == id_maquina:
                sub["ultimo_acesso"] = agora
                sub["macs_acesso"]   = macs_atuais
                sub["versao"]        = versao_cli
                if nome_maquina:
                    sub["nome_maquina"] = nome_maquina
                salvar_json(dados)
                return jsonify({"valido": True, "chave_completa": chave})

            # Caso 2: interseção de MACs (mudança de hardware leve)
            if intersec:
                sub["id_maquina"]  = id_maquina
                sub["ultimo_acesso"] = agora
                sub["macs_acesso"]   = macs_atuais
                sub["versao"]        = versao_cli
                if nome_maquina:
                    sub["nome_maquina"] = nome_maquina
                salvar_json(dados)
                return jsonify({"valido": True, "chave_completa": chave})

            # Caso 3: sem interseção — hardware completamente diferente
            return jsonify({"valido": False, "motivo": "id_nao_reconhecido"})

        # Chave completa não encontrada entre sublicenças
        return jsonify({"valido": False, "motivo": "chave_nao_encontrada"})

    return jsonify({"valido": False, "motivo": "chave_nao_encontrada"})


# ── API REST do painel ────────────────────────────────────────────────────────

def _gerar_chave_base() -> str:
    """Gera DIM-SAP-NNNN onde NNNN é sequencial."""
    try:
        dados = ler_json()
        existentes = [lic.get("chave_base", "") for lic in dados.get("licencas", [])]
        nums = []
        for c in existentes:
            partes = c.split("-")
            if len(partes) >= 3:
                try: nums.append(int(partes[-1]))
                except ValueError: pass
        proximo = max(nums, default=0) + 1
        return f"{PREFIXO_CHAVE}{proximo:04d}"
    except Exception:
        sufixo = "".join(random.choices(string.digits, k=4))
        return f"{PREFIXO_CHAVE}{sufixo}"


@app.route("/api/licencas", methods=["GET"])
@login_required
def api_listar():
    try:
        dados = ler_json()
        return jsonify(dados)
    except Exception as e:
        if _json_nao_encontrado(e):
            return jsonify(_dados_vazios())
        return jsonify({"erro": _erro_dropbox(e)}), 500


@app.route("/api/licencas", methods=["POST"])
@login_required
def api_criar():
    body = request.get_json(silent=True) or {}

    try:
        cliente = str(body.get("cliente", "")).strip()
        if not cliente:
            raise ValueError("Informe o nome do cliente.")
        expiracao = _normalizar_data(body.get("expiracao", ""))
        limite = _normalizar_limite(body.get("limite", 1))
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400

    chave_base = _gerar_chave_base()

    nova = {
        "chave_base":         chave_base,
        "cliente":            cliente,
        "email":              str(body.get("email", "")).strip(),
        "telefone":           str(body.get("telefone", "")).strip(),
        "expiracao":          expiracao,
        "limite_dispositivos": limite,
        "ativo":              _normalizar_ativo(body.get("ativo", True)),
        "sublicencas":        [],
        "data_criacao":       datetime.now(timezone.utc).isoformat(),
    }

    try:
        dados = ler_json()
    except Exception as e:
        if not _json_nao_encontrado(e):
            return jsonify({"erro": "Erro ao ler arquivo de licenças.", "detalhe": _erro_dropbox(e)}), 500
        dados = _dados_vazios()

    try:
        dados.setdefault("licencas", []).append(nova)
        salvar_json(dados)
    except Exception as e:
        return jsonify({"erro": "Erro ao salvar no Dropbox.", "detalhe": _erro_dropbox(e)}), 500

    return jsonify({"ok": True, "chave_base": chave_base}), 201


@app.route("/api/licencas/<chave_base>", methods=["PUT"])
@login_required
def api_editar(chave_base):
    body = request.get_json(silent=True) or {}

    try:
        dados = ler_json()
    except Exception as e:
        return jsonify({"erro": "Erro ao ler arquivo de licenças.", "detalhe": _erro_dropbox(e)}), 500

    for lic in dados.get("licencas", []):
        if lic.get("chave_base") == chave_base:
            try:
                if "cliente"   in body: lic["cliente"]             = str(body["cliente"]).strip()
                if "email"     in body: lic["email"]               = str(body["email"]).strip()
                if "telefone"  in body: lic["telefone"]            = str(body["telefone"]).strip()
                if "expiracao" in body: lic["expiracao"]           = _normalizar_data(body["expiracao"])
                if "limite"    in body: lic["limite_dispositivos"] = _normalizar_limite(body["limite"])
                if "ativo"     in body: lic["ativo"]               = _normalizar_ativo(body["ativo"])
            except ValueError as e:
                return jsonify({"erro": str(e)}), 400

            try:
                salvar_json(dados)
            except Exception as e:
                return jsonify({"erro": "Erro ao salvar no Dropbox.", "detalhe": _erro_dropbox(e)}), 500
            return jsonify({"ok": True})

    return jsonify({"erro": "Licença não encontrada"}), 404


@app.route("/api/licencas/<chave_base>", methods=["DELETE"])
@login_required
def api_deletar(chave_base):
    dados = ler_json()
    antes = len(dados.get("licencas", []))
    dados["licencas"] = [l for l in dados["licencas"] if l.get("chave_base") != chave_base]
    if len(dados["licencas"]) == antes:
        return jsonify({"erro": "Não encontrada"}), 404
    salvar_json(dados)
    return jsonify({"ok": True})


@app.route("/api/licencas/<chave_base>/sublicencas/<chave_sub>", methods=["DELETE"])
@login_required
def api_deletar_sub(chave_base, chave_sub):
    dados = ler_json()
    for lic in dados.get("licencas", []):
        if lic.get("chave_base") == chave_base:
            antes = len(lic.get("sublicencas", []))
            lic["sublicencas"] = [s for s in lic.get("sublicencas", []) if s.get("chave_sub") != chave_sub]
            if len(lic["sublicencas"]) == antes:
                return jsonify({"erro": "Sublicença não encontrada"}), 404
            salvar_json(dados)
            return jsonify({"ok": True})
    return jsonify({"erro": "Licença não encontrada"}), 404


@app.route("/api/licencas/<chave_base>/sublicencas/<chave_sub>/limpar", methods=["POST"])
@login_required
def api_limpar_sub(chave_base, chave_sub):
    dados = ler_json()
    for lic in dados.get("licencas", []):
        if lic.get("chave_base") == chave_base:
            for sub in lic.get("sublicencas", []):
                if sub.get("chave_sub") == chave_sub:
                    sub["id_maquina"]    = ""
                    sub["macs_registro"] = []
                    sub["macs_acesso"]   = []
                    salvar_json(dados)
                    return jsonify({"ok": True})
    return jsonify({"erro": "Não encontrada"}), 404


# ── Health check ──────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return "OK", 200


if __name__ == "__main__":
    app.run(debug=True)
