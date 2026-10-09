#!/usr/bin/env python3
"""
Coletor do Diário Oficial da União (Seção 1) para atos da Anvisa:
  - 4ª Diretoria / Gerência-Geral de Inspeção e Fiscalização Sanitária (GGFIS)
  - 2ª Diretoria / Gerência-Geral de Medicamentos (GGMED)

Fonte: INLABS (Imprensa Nacional), que entrega a edição do dia em XML.
Cadastro gratuito: https://inlabs.in.gov.br
Credenciais via variáveis de ambiente INLABS_EMAIL e INLABS_SENHA.

Uso:
    python scripts/coletar.py              # últimos 3 dias
    python scripts/coletar.py --dias 30    # reprocessa últimos 30 dias
    python scripts/coletar.py --inicio 2026-09-01 --fim 2026-09-30
    python scripts/coletar.py --pasta ./xml_local   # lê XMLs/ZIPs já baixados (teste)
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
import zipfile
from datetime import date, datetime, timedelta
from html import unescape
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from zoneinfo import ZoneInfo

import requests

RAIZ = Path(__file__).resolve().parent.parent
ARQ_DADOS = RAIZ / "docs" / "dados.json"
ARQ_FEED = RAIZ / "docs" / "feed.xml"

LOGIN_URL = "https://inlabs.in.gov.br/logar.php"
DOWNLOAD_URL = "https://inlabs.in.gov.br/index.php"
EDICOES = ["DO1", "DO1E"]  # Seção 1 e edições extras da Seção 1
RETENCAO_DIAS = 180        # quanto histórico manter no dados.json
TEXTO_MAX = 1500           # caracteres do texto guardados por ato
SITE_URL = os.environ.get("SITE_URL", "")

# ---------------------------------------------------------------------------
# Regras de seleção e classificação (ajuste aqui se a Anvisa mudar os nomes)
# Os textos são comparados sem acento, em minúsculas.
# ---------------------------------------------------------------------------
ORGAO_ANVISA = "agencia nacional de vigilancia sanitaria"
UNIDADES = {
    "GGFIS": ["4a diretoria", "gerencia-geral de inspecao e fiscalizacao sanitaria"],
    "GGMED": ["2a diretoria", "gerencia-geral de medicamentos"],
}
RE_SUSPENSAO = re.compile(r"suspen|proib|recolh|interdi|apreens")
RE_APROVACAO = re.compile(
    r"\bdefer|registr|aprova|nova concentra|nova forma|nova indica|renovac"
)
RE_NEGATIVA = re.compile(r"indefer|cancelament|cancelar|arquiv")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def unidade_do_ato(categoria: str):
    c = norm(categoria)
    if ORGAO_ANVISA not in c:
        return None
    for sigla, marcas in UNIDADES.items():
        if any(m in c for m in marcas):
            return sigla
    return None


def classificar(unidade: str, titulo: str, ementa: str, texto: str) -> str:
    base = norm(" ".join([titulo, ementa, texto[:3000]]))
    if unidade == "GGFIS":
        return "suspensao" if RE_SUSPENSAO.search(base) else "outros"
    if unidade == "GGMED":
        if RE_APROVACAO.search(base) and not RE_NEGATIVA.search(base):
            return "aprovacao"
        return "outros"
    return "outros"


# ---------------------------------------------------------------------------
# Download (INLABS)
# ---------------------------------------------------------------------------
HEADERS_INLABS = {"origem": "736372697074"}


def abrir_sessao(email: str, senha: str) -> requests.Session:
    s = requests.Session()
    s.post(
        LOGIN_URL,
        data={"email": email, "password": senha},
        headers=HEADERS_INLABS,
        timeout=60,
    )
    if not s.cookies.get("inlabs_session_cookie"):
        raise RuntimeError(
            "Login no INLABS falhou. Confira INLABS_EMAIL e INLABS_SENHA."
        )
    return s


def baixar_zip(s: requests.Session, dia: date, edicao: str):
    iso = dia.isoformat()
    r = s.get(
        DOWNLOAD_URL,
        params={"p": iso, "dl": f"{iso}-{edicao}.zip"},
        headers=HEADERS_INLABS,
        timeout=180,
    )
    if r.status_code == 200 and r.content[:2] == b"PK":
        return r.content
    return None  # sem edição nesse dia (fim de semana, feriado, sem extra)


# ---------------------------------------------------------------------------
# Leitura dos XMLs
# ---------------------------------------------------------------------------
def limpar_html(html: str) -> str:
    html = re.sub(r"</(p|div|tr|li)>", "\n", html or "", flags=re.I)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    txt = unescape(re.sub(r"<[^>]+>", " ", html))
    linhas = [re.sub(r"[ \t\u00a0]+", " ", l).strip() for l in txt.splitlines()]
    return "\n".join(l for l in linhas if l)


def texto_de(no, tag: str) -> str:
    el = no.find(f".//{tag}")
    return limpar_html(el.text or "") if el is not None else ""


def data_iso(pub_date: str) -> str:
    try:
        return datetime.strptime(pub_date.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return pub_date


def processar_xml(conteudo: bytes, edicao: str):
    try:
        raiz = ET.fromstring(conteudo)
    except ET.ParseError:
        return []
    atos = []
    for art in raiz.iter("article"):
        categoria = art.get("artCategory", "")
        unidade = unidade_do_ato(categoria)
        if not unidade:
            continue
        titulo = texto_de(art, "Identifica") or art.get("name", "")
        ementa = texto_de(art, "Ementa")
        texto = texto_de(art, "Texto")
        ident = art.get("id") or hashlib.sha1(
            (titulo + texto[:200]).encode("utf-8")
        ).hexdigest()[:16]
        atos.append(
            {
                "id": str(ident),
                "data": data_iso(art.get("pubDate", "")),
                "edicao": edicao,
                "unidade": unidade,
                "categoria": classificar(unidade, titulo, ementa, texto),
                "tipo": art.get("artType", ""),
                "titulo": titulo,
                "ementa": ementa,
                "texto": texto[:TEXTO_MAX],
                "truncado": len(texto) > TEXTO_MAX,
                "pagina": art.get("numberPage", ""),
                "pdf": art.get("pdfPage", ""),
                "orgao": categoria,
            }
        )
    return atos


def processar_zip(dados: bytes, edicao: str):
    atos = []
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        for nome in z.namelist():
            if nome.lower().endswith(".xml"):
                atos += processar_xml(z.read(nome), edicao)
    return atos


# ---------------------------------------------------------------------------
# Saída
# ---------------------------------------------------------------------------
def carregar_existentes():
    if ARQ_DADOS.exists():
        try:
            return json.loads(ARQ_DADOS.read_text(encoding="utf-8")).get("itens", [])
        except json.JSONDecodeError:
            pass
    return []


def gerar_feed(itens):
    agora = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime(
        "%a, %d %b %Y %H:%M:%S %z"
    )
    partes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel>',
        "<title>Anvisa no DOU: suspensões e aprovações</title>",
        f"<link>{xml_escape(SITE_URL or 'https://www.in.gov.br')}</link>",
        "<description>Atos da 4ª Diretoria/GGFIS e da 2ª Diretoria/GGMED no Diário Oficial da União</description>",
        "<language>pt-BR</language>",
        f"<lastBuildDate>{agora}</lastBuildDate>",
    ]
    for it in itens[:60]:
        rotulo = {"suspensao": "Suspensão", "aprovacao": "Aprovação"}.get(
            it["categoria"], "Outros"
        )
        partes.append(
            "<item>"
            f"<title>{xml_escape(rotulo + ': ' + it['titulo'])}</title>"
            f"<link>{xml_escape(it['pdf'] or 'https://www.in.gov.br')}</link>"
            f"<guid isPermaLink=\"false\">{xml_escape(it['id'])}</guid>"
            f"<description>{xml_escape(it['ementa'] or it['texto'][:400])}</description>"
            "</item>"
        )
    partes.append("</channel></rss>")
    ARQ_FEED.write_text("\n".join(partes), encoding="utf-8")


def salvar(itens_novos):
    por_id = {i["id"]: i for i in carregar_existentes()}
    for i in itens_novos:
        por_id[i["id"]] = i
    limite = (date.today() - timedelta(days=RETENCAO_DIAS)).isoformat()
    itens = [i for i in por_id.values() if i["data"] >= limite]
    itens.sort(key=lambda i: (i["data"], str(i["pagina"]).zfill(6)), reverse=True)
    saida = {
        "atualizado_em": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(
            timespec="minutes"
        ),
        "itens": itens,
    }
    ARQ_DADOS.write_text(
        json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    gerar_feed(itens)
    return len(itens)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=3)
    ap.add_argument("--inicio")
    ap.add_argument("--fim")
    ap.add_argument("--pasta", help="processa XML/ZIP locais em vez de baixar")
    a = ap.parse_args()

    novos = []
    if a.pasta:
        for p in sorted(Path(a.pasta).rglob("*")):
            if p.suffix.lower() == ".zip":
                novos += processar_zip(p.read_bytes(), "DO1")
            elif p.suffix.lower() == ".xml":
                novos += processar_xml(p.read_bytes(), "DO1")
    else:
        email, senha = os.environ.get("INLABS_EMAIL"), os.environ.get("INLABS_SENHA")
        if not email or not senha:
            sys.exit("Defina INLABS_EMAIL e INLABS_SENHA.")
        fim = date.fromisoformat(a.fim) if a.fim else date.today()
        inicio = (
            date.fromisoformat(a.inicio)
            if a.inicio
            else fim - timedelta(days=a.dias - 1)
        )
        s = abrir_sessao(email, senha)
        d = inicio
        while d <= fim:
            for ed in EDICOES:
                z = baixar_zip(s, d, ed)
                if z:
                    achados = processar_zip(z, ed)
                    print(f"{d} {ed}: {len(achados)} atos relevantes")
                    novos += achados
            d += timedelta(days=1)

    total = salvar(novos)
    print(f"Coletados agora: {len(novos)} | Total no arquivo: {total}")


if __name__ == "__main__":
    main()
