# -*- coding: utf-8 -*-
"""Central de Plantão & Furo — g1 Alto Tietê.

Organização do arquivo:
  1. Configuração e constantes
  2. Utilidades de texto e tempo
  3. Persistência (Store com gravação atômica)
  4. Telegram
  5. Coleta (RSS, X, Instagram, páginas e canais, Direto dos Trens)
  6. Automação em segundo plano (thread única, independente do navegador)
  7. Identidade visual (CSS, fonte, logo)
  8. Interface (abas)
"""

from __future__ import annotations

import base64
import copy
import hashlib
import html
import json
import logging
import os
import random
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

import feedparser
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(
    page_title="Central de Plantão & Furo — g1 Alto Tietê",
    page_icon="🚨",
    layout="wide",
)

# ──────────────────────────────────────────────────────────────────────────
# 1. Configuração e constantes
# ──────────────────────────────────────────────────────────────────────────
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("MONITOR_DATA_DIR") or APP_DIR)
ARQUIVO_DADOS = DATA_DIR / "dados_monitor_g1.json"
PASTAS_ASSETS = [DATA_DIR / "assets", APP_DIR / "assets"]

FUSO_BR = timezone(timedelta(hours=-3))  # Brasil não tem horário de verão
JANELA_MAXIMA = timedelta(minutes=60)  # filtro estrito de 1 hora
ACEITAR_SEM_DATA = True  # só RSS/páginas; X e Instagram SEMPRE exigem data (ver exige_data)
PAUSA_BLOQUEIO_S = 15 * 60  # pausa da fonte após HTTP 401/403/429 ou tela de login
STATUS_BLOQUEIO = (401, 403, 429)
LIMITE_HISTORICO = 500
LIMITE_IDS = 5000
LIMITE_EXIBICAO = 30
URL_DIRETO_TRENS = "https://www.diretodostrens.com.br/"
STATUS_NORMAL = "Operação Normal"
STATUS_ALTERADOS = (
    "Velocidade Reduzida",
    "Operação Parcial",
    "Paralisada",
    "Atividade Programada",
    "Operação Encerrada",
)
LINHAS_ALVO = (
    ("11", "Linha 11-Coral", "Mogi das Cruzes / Suzano / Ferraz"),
    ("12", "Linha 12-Safira", "Itaquaquecetuba / Calmon Viana"),
)
HEADERS_HTTP = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

CAT_SEGURANCA = "🚨 Segurança / Policial"
CAT_TRANSITO = "🚗 Trânsito / Rodovias"
CAT_SERVICOS = "💡 Serviços / Prefeitura"
CAT_GERAL = "📌 Nota Oficial / Geral"
CATEGORIAS = [CAT_SEGURANCA, CAT_TRANSITO, CAT_SERVICOS, CAT_GERAL]

TERMOS_CATEGORIAS = {
    CAT_SEGURANCA: [
        "incêndio", "tiros", "arma", "homicídio", "preso", "operação",
        "polícia", "bombeiros", "acidente", "colisão", "atropelamento",
        "roubo", "furto", "delegacia", "morto", "baleado",
    ],
    CAT_TRANSITO: [
        "trânsito", "interdição", "congestionamento", "rodovia", "marginal",
        "trem", "cptm", "estação", "linha 11", "linha 12", "linha 13",
        "acidente na rodovia", "bloqueio",
    ],
    CAT_SERVICOS: [
        "água", "sabesp", "luz", "energia", "edp", "falta", "escola", "posto",
        "saúde", "UPA", "hospital", "greve", "paralisação", "buraco",
        "enchente", "alagamento", "falta de energia",
    ],
}

LOGRADOUROS_URBANOS = [
    "Narciso Yague Guimarães", "Carlos Ferreira Lopes",
    "Francisco Ribeiro Nogueira", "Adhemar de Barros",
    "Voluntário Fernando Pinheiro Franco", "Lourenço de Souza Franco",
    "Coronel Cardoso de Siqueira", "Dom Antônio Cândido de Alvarenga",
    "Antônio Cândido Vieira", "Tenente Manoel Alves dos Anjos",
    "Antônio Marques Figueira", "Armando Salles de Oliveira", "Avenida Brasil",
    "Marcos de Paula Eduardo", "Francisco Rodrigues Filho",
    "João Batista Fitipaldi", "Barão do Rio Branco", "Armando de Ré",
    "Estrada Pau a Pique", "Emancipação", "Ítalo Adami", "Uberaba",
    "João Fernandes da Silva", "Pedro da Cunha Albuquerque Lopes",
    "Alberto Hinoto", "Corta Rabicho", "Estrada da Figueira", "Expedicionários",
    "João Manoel", "Armando Colângelo", "Mário Covas", "Major Benjamin",
    "Syrio Libanes", "XV de Novembro", "Governador Jânio Quadros",
    "Herman Teles Ribeiro", "Stella Mazzucca", "Carlos de Campos",
    "Estrada dos Bandeirantes", "João Gaspar Delgado", "9 de Julho",
    "Leonor Bolsoni Lopes", "Vital Brasil", "Fernando V. Rossi", "26 de Março",
    "Rua Beatriz", "Custódio Theodoro de Oliveira",
    "Manoel Ferraz de Campos Sales", "Avenida da República",
    "Hyerócleo Vitor de Freitas", "Treze de Maio", "Estrada do Ouro",
    "Gildo Sevá", "Ferdinando Jungers", "Manoel Goulart", "Coronel Domiciano",
    "João Lourenço", "Professor Carvalho Pinto", "Nossa Senhora da Ajuda",
    "Marechal Deodoro", "Sete de Setembro", "Conselheiro Rodrigues Alves",
]

RODOVIAS_REGIONAIS = [
    "SP-66", "Henrique Eroles", "João Afonso de Souza Castellano",
    "Ayrton Senna", "SP-070", "Presidente Dutra", "BR-116", "Rodoanel",
    "SP-21", "Mogi-Dutra", "SP-88", "Mogi-Bertioga", "SP-98",
    "Alfredo Rolim de Moura",
]

PADRAO_DADOS = {
    "cidades": [
        "Mogi das Cruzes", "Suzano", "Itaquaquecetuba", "Arujá",
        "Ferraz de Vasconcelos", "Poá", "Santa Isabel", "Biritiba Mirim",
        "Salesópolis", "Guararema",
    ],
    "urls": [
        "https://g1.globo.com/sp/mogi-das-cruzes-suzano/rss2.xml",
        "https://news.google.com/rss/search?q=Mogi+das+Cruzes+Suzano+Itaquaquecetuba&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        "https://news.google.com/rss/search?q=Alto+Tiet%C3%AA+SP&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    ],
    "perfis_instagram": [],
    "perfis_x": [],
    # Pontes RSS opcionais (reserva do acesso direto). Use {perfil} no endereço.
    "bridges_instagram": [],
    "instagram_sessionid": "",  # cookie de sessão opcional (conta secundária)
    "paginas": [],  # {"nome","url","seletor","baseline_feito"}
    "logradouros": list(LOGRADOUROS_URBANOS),  # ruas, avenidas e bairros
    "rodovias": list(RODOVIAS_REGIONAIS),
    # Espelhos Nitter são testados em ordem; o primeiro que responder vale.
    # Instâncias públicas caem e mudam com frequência: edite na aba Fontes.
    "instancias_nitter": [
        "https://nitter.privacyredirect.com",
        "https://nitter.poast.org",
        "https://nitter.tiekoetter.com",
    ],
    # Posts que citam SÓ rua/rodovia são descartados se citarem uma destas cidades
    # (e nenhuma cidade da lista do Alto Tietê). Evita "Av. Brasil" de outra praça.
    "cidades_excluidas": [
        "Guarulhos", "Campinas", "Santos", "São Bernardo do Campo", "Santo André",
        "São Caetano do Sul", "Osasco", "Barueri", "Carapicuíba", "Diadema",
        "Mauá", "Ribeirão Pires", "Sorocaba", "Jundiaí", "Taubaté",
        "São José dos Campos", "Jacareí", "Ribeirão Preto", "Rio de Janeiro",
        "Brasília", "Belo Horizonte", "Curitiba", "capital paulista",
    ],
    "telegram_token": "",
    "telegram_chat_id": "",
    "telegram_preview": False,  # mostrar pré-visualização do link nas mensagens
    "historico_alertas": [],
    "ids_vistos": [],
    "estado_trens": {},
    "automacao_ativa": False,
    "intervalo_auto": 5,
}

log = logging.getLogger("g1monitor")


def _configurar_log() -> None:
  if log.handlers:
    return
  log.setLevel(logging.INFO)
  try:
    handler = RotatingFileHandler(
        DATA_DIR / "monitor.log", maxBytes=1_000_000, backupCount=3,
        encoding="utf-8",
    )
  except OSError:
    handler = logging.StreamHandler()
  handler.setFormatter(
      logging.Formatter("%(asctime)s %(levelname)s %(message)s")
  )
  log.addHandler(handler)


# ──────────────────────────────────────────────────────────────────────────
# 2. Utilidades de texto e tempo
# ──────────────────────────────────────────────────────────────────────────
def _norm(texto: str) -> str:
  """Minúsculas e sem acentos, para comparar textos de forma tolerante."""
  sem_acento = unicodedata.normalize("NFKD", texto)
  return sem_acento.encode("ascii", "ignore").decode("ascii").lower()


@lru_cache(maxsize=None)
def _padrao(termo: str) -> re.Pattern:
  return re.compile(rf"\b{re.escape(_norm(termo))}\b")


def contem(texto_norm: str, termo: str) -> bool:
  return bool(_padrao(termo).search(texto_norm))


# Apelidos só valem se a cidade canônica estiver cadastrada (regex sobre texto normalizado).
APELIDOS_CIDADES = {
    "mogi das cruzes": (r"\bmogi\b(?!\s+(?:guacu|mirim))",),
    "itaquaquecetuba": (r"\bitaqua\b",),
}


@lru_cache(maxsize=64)
def _regex_termos(termos: tuple[str, ...]) -> tuple[re.Pattern | None, dict[str, str]]:
  """Uma única regex para a lista inteira (bem mais rápido que um regex por termo)."""
  mapa: dict[str, str] = {}
  for termo in termos:
    chave = _norm(termo).strip()
    if chave:
      mapa.setdefault(chave, termo)
  if not mapa:
    return None, {}
  alternativas = "|".join(re.escape(k) for k in sorted(mapa, key=len, reverse=True))
  return re.compile(rf"\b(?:{alternativas})\b"), mapa


def _achar_termo(texto_norm: str, termos) -> str | None:
  padrao, mapa = _regex_termos(tuple(termos))
  achado = padrao.search(texto_norm) if padrao else None
  return mapa[achado.group(0)] if achado else None


def _achar_cidade(texto_norm: str, cidades: list[str]) -> str | None:
  direta = _achar_termo(texto_norm, cidades)
  if direta:
    return direta
  for cidade in cidades:
    for padrao in APELIDOS_CIDADES.get(_norm(cidade).strip(), ()):
      if re.search(padrao, texto_norm):
        return cidade
  return None


def classificar_ocorrencia(texto: str) -> str:
  texto_norm = _norm(texto)
  for categoria, termos in TERMOS_CATEGORIAS.items():
    if any(contem(texto_norm, t) for t in termos):
      return categoria
  return CAT_GERAL


def identificar_local(texto: str, cidades: list[str],
                      logradouros: list[str] | None = None,
                      rodovias: list[str] | None = None,
                      excluidas: list[str] | None = None) -> str | None:
  """Filtro geográfico ESTRITO: só devolve local se o texto citar, explicitamente,
  uma cidade, rua/bairro ou rodovia cadastrados. Nada de "Alto Tietê" genérico.

  Cidade cadastrada vale sempre. Rua ou rodovia sem cidade é descartada quando o
  texto cita uma cidade de fora da região (ver `cidades_excluidas`).
  """
  texto_norm = _norm(texto)
  cidade = _achar_cidade(texto_norm, cidades)
  if cidade:
    return cidade
  achado = None
  rua = _achar_termo(texto_norm, LOGRADOUROS_URBANOS if logradouros is None else logradouros)
  if rua:
    achado = f"Alto Tietê ({rua})"
  else:
    rodovia = _achar_termo(texto_norm, RODOVIAS_REGIONAIS if rodovias is None else rodovias)
    if rodovia:
      achado = f"Alto Tietê ({rodovia})"
  if achado and excluidas and _achar_termo(texto_norm, excluidas):
    return None
  return achado


def gerar_id_unico(texto: str, url: str) -> str:
  """Mesma fórmula da versão anterior: preserva a deduplicação do histórico."""
  return hashlib.md5(f"{texto.strip()}_{url.strip()}".encode("utf-8")).hexdigest()


def item_recente(publicado: datetime | None, aceitar_sem_data: bool | None = None) -> bool:
  """Janela estrita de 1 hora. Sem data: segue a política da fonte (X/Instagram = rejeita)."""
  if publicado is None:
    return ACEITAR_SEM_DATA if aceitar_sem_data is None else aceitar_sem_data
  return datetime.now(timezone.utc) - publicado <= JANELA_MAXIMA


def idade_texto(publicado: datetime | None) -> str:
  if publicado is None:
    return "sem data"
  segundos = int((datetime.now(timezone.utc) - publicado).total_seconds())
  if segundos < 60:
    return "agora"
  if segundos < 3600:
    return f"há {segundos // 60} min"
  if segundos < 86400:
    return f"há {segundos // 3600} h"
  return f"há {segundos // 86400} d"


def rotulo_feed(url: str) -> str:
  if url.startswith("x:"):
    return f"X: @{url[2:]}"
  if url.startswith("ig:"):
    return f"Instagram: @{url[3:]}"
  if url.startswith("pg:"):
    return f"Página: {rotulo_feed(url[3:])}"
  partes = urlparse(url)
  host = partes.netloc.replace("www.", "")
  if "news.google.com" in host:
    termo = parse_qs(partes.query).get("q", [""])[0]
    return f"Google News: {termo}" if termo else host
  caminho = partes.path.rstrip("/")
  return f"{host}{caminho}" if caminho else host


def nome_do_dominio(url: str) -> str:
  try:
    return urlparse(url).netloc.replace("www.", "").split(".")[0].capitalize()
  except Exception:
    return "Portal de Notícias"


# ──────────────────────────────────────────────────────────────────────────
# 3. Persistência
# ──────────────────────────────────────────────────────────────────────────
class Store:
  """Fonte única de verdade, compartilhada por todas as sessões e pela thread.

  Toda mudança em `data` deve ser seguida de `salvar()`.
  """

  def __init__(self, caminho: Path):
    self.caminho = caminho
    self.lock = threading.RLock()
    self.feeds: dict[str, ResultadoFeed] = {}  # estado em memória (não persiste)
    self.data = self._carregar()
    self._ids: list[str] = list(self.data["ids_vistos"])
    self._ids_set: set[str] = set(self._ids)
    for alerta in self.data["historico_alertas"]:  # migra histórico antigo
      self._registrar_id(alerta.get("id_unico"))

  def _carregar(self) -> dict:
    dados = copy.deepcopy(PADRAO_DADOS)
    if self.caminho.exists():
      try:
        dados.update(json.loads(self.caminho.read_text(encoding="utf-8")))
      except (OSError, ValueError) as erro:
        backup = self.caminho.with_name(
            f"{self.caminho.stem}.corrompido-{int(time.time())}.json"
        )
        try:
          self.caminho.replace(backup)
        except OSError:
          pass
        log.error("JSON ilegível (%s). Backup em %s", erro, backup.name)
    for obsoleta in ("itens_rss_proprio", "perfis_facebook", "bridges_facebook",
                     "facebook_token"):  # recursos removidos
      dados.pop(obsoleta, None)
    return dados

  def _registrar_id(self, id_unico: str | None) -> bool:
    if not id_unico or id_unico in self._ids_set:
      return False
    self._ids.append(id_unico)
    self._ids_set.add(id_unico)
    if len(self._ids) > LIMITE_IDS + 500:
      self._ids = self._ids[-LIMITE_IDS:]
      self._ids_set = set(self._ids)
    return True

  def marcar_visto(self, id_unico: str) -> bool:
    """True se o id é inédito (e passa a constar como visto)."""
    with self.lock:
      return self._registrar_id(id_unico)

  def adicionar_alerta(self, alerta: dict) -> None:
    with self.lock:
      self.data["historico_alertas"].insert(0, alerta)
      del self.data["historico_alertas"][LIMITE_HISTORICO:]

  def salvar(self) -> None:
    with self.lock:
      self.data["ids_vistos"] = self._ids[-LIMITE_IDS:]
      conteudo = json.dumps(self.data, ensure_ascii=False, indent=2)
      temporario = self.caminho.with_name(self.caminho.name + ".tmp")
      for tentativa in range(3):
        try:
          temporario.write_text(conteudo, encoding="utf-8")
          os.replace(temporario, self.caminho)
          return
        except OSError as erro:  # antivírus/OneDrive podem travar por instantes
          log.warning("Falha ao salvar (tentativa %d): %s", tentativa + 1, erro)
          time.sleep(0.3)

  def adicionar_item(self, chave: str, valor: str) -> tuple[bool, str]:
    valor = valor.strip()
    if not valor:
      return False, "Digite um valor antes de adicionar."
    with self.lock:
      if valor.lower() in (v.lower() for v in self.data[chave]):
        return False, f"“{valor}” já está na lista."
      self.data[chave].append(valor)
      self.salvar()
    return True, f"“{valor}” adicionado."

  def pagina(self, url: str) -> dict | None:
    return next((p for p in self.data["paginas"] if p["url"] == url), None)

  def adicionar_pagina(self, nome: str, url: str, seletor: str) -> tuple[bool, str]:
    url = url.strip()
    with self.lock:
      if any(p["url"].lower() == url.lower() for p in self.data["paginas"]):
        return False, "Essa página já está cadastrada."
      self.data["paginas"].append({
          "nome": nome.strip() or urlparse(url).netloc.replace("www.", ""),
          "url": url, "seletor": seletor.strip(), "baseline_feito": False,
      })
      self.salvar()
    return True, "Página adicionada. A primeira varredura só registra o que já está publicado."

  def remover_pagina(self, url: str) -> None:
    with self.lock:
      self.data["paginas"] = [p for p in self.data["paginas"] if p["url"] != url]
      self.feeds.pop(f"pg:{url}", None)
      self.salvar()

  def remover_item(self, chave: str, valor: str) -> None:
    with self.lock:
      if valor in self.data[chave]:
        self.data[chave].remove(valor)
        self.feeds.pop(valor, None)
        self.feeds.pop(f"x:{valor}", None)
        self.feeds.pop(f"ig:{valor}", None)
        self.salvar()


@st.cache_resource(show_spinner=False)
def obter_store() -> Store:
  _configurar_log()
  return Store(ARQUIVO_DADOS)


# ──────────────────────────────────────────────────────────────────────────
# 4. Telegram
# ──────────────────────────────────────────────────────────────────────────
def _titulo_limpo(alerta: dict) -> str:
  titulo = (alerta.get("titulo") or "").strip() or "Nova ocorrência"
  fonte = (alerta.get("fonte") or "").strip()
  # Google News acrescenta " - Veículo" ao título; o veículo já aparece abaixo
  if fonte and titulo.lower().endswith(f" - {fonte}".lower()):
    titulo = titulo[: -len(fonte) - 3].rstrip()
  return titulo


def _resumo_limpo(alerta: dict, titulo: str, limite: int = 280) -> str:
  """Resumo sem links, sem o título repetido e sem o nome do veículo sobrando."""
  fonte = (alerta.get("fonte") or "").strip()
  texto = re.sub(r"https?://\S+", "", alerta.get("resumo") or "")
  texto = " ".join(texto.split())
  base = titulo.rstrip("…").strip()
  bruto = (alerta.get("titulo") or "").rstrip("…").strip()
  for prefixo in (bruto, base):  # RSS monta "título - resumo"
    if prefixo and texto.lower().startswith(prefixo.lower()):
      texto = texto[len(prefixo):].lstrip(" -–—:|.")
      break
  if fonte:
    texto = re.sub(rf"\s*[-–—|]?\s*{re.escape(fonte)}\s*$", "", texto, flags=re.I).strip()
  chave = _norm(texto).rstrip(". …")
  if len(chave) < 20 or chave[:40] == _norm(base)[:40]:  # vazio ou repete o título
    return ""
  if len(texto) > limite:
    texto = texto[:limite].rsplit(" ", 1)[0].rstrip(",;:- ") + "…"
  return texto


def texto_mensagem(alerta: dict, formato: str) -> str:
  """formato: 'html' (envio pelo bot), 'whatsapp' ou 'texto' (copiar).

  Layout: título em destaque, resumo limpo, cidade/região e, por último, o link
  amarrado a um texto (no Telegram o endereço fica oculto).
  """
  titulo = _titulo_limpo(alerta)
  resumo = _resumo_limpo(alerta, titulo)
  cidade = alerta.get("cidade", "")
  categoria = alerta.get("categoria", CAT_GERAL)
  fonte = alerta.get("fonte", "Portal de Notícias")
  horario = alerta.get("horario", "")
  url = (alerta.get("url") or "").strip()
  esc = html.escape
  if formato == "html":
    partes = [f"<b>{esc(titulo)}</b>"]
    if resumo:
      partes.append(esc(resumo))
    partes.append(f"📍 <b>{esc(cidade)}</b>  ·  {esc(categoria)}\n📰 {esc(fonte)}  ·  ⏰ {esc(horario)}")
    if url:
      partes.append(f'👉 <a href="{esc(url, quote=True)}">Clique aqui para acessar a matéria completa</a>')
    return "\n\n".join(partes)
  partes = [f"*{titulo}*" if formato == "whatsapp" else titulo]
  if resumo:
    partes.append(resumo)
  partes.append(f"📍 {cidade}  ·  {categoria}\n📰 {fonte}  ·  ⏰ {horario}")
  if url:
    partes.append(f"👉 Matéria completa: {url}")
  return "\n\n".join(partes)


def enviar_telegram(token: str, chat_id: str, texto: str, preview: bool = False) -> tuple[bool, str]:
  if not token or not chat_id:
    return False, "Token ou Chat ID não configurado."
  url = f"https://api.telegram.org/bot{token}/sendMessage"
  for tentativa in range(2):
    try:
      resposta = requests.post(
          url,
          data={"chat_id": chat_id, "text": texto, "parse_mode": "HTML",
                "link_preview_options": json.dumps({"is_disabled": not preview})},
          timeout=10,
      )
      if resposta.status_code == 429 and tentativa == 0:
        espera = resposta.json().get("parameters", {}).get("retry_after", 3)
        time.sleep(min(int(espera), 30))
        continue
      if resposta.ok:
        return True, "Enviado."
      try:
        return False, resposta.json().get("description", f"HTTP {resposta.status_code}")
      except ValueError:
        return False, f"HTTP {resposta.status_code}"
    except requests.RequestException as erro:
      return False, str(erro).replace(token, "***")  # nunca vaza o token
  return False, "Limite de envios do Telegram atingido."


# ──────────────────────────────────────────────────────────────────────────
# 5. Coleta
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class ResultadoFeed:
  url: str
  ok: bool = False
  status: int | None = None
  latencia_ms: int | None = None
  erro: str = ""
  titulo: str = ""
  itens: list[dict] = field(default_factory=list)
  exige_data: bool = False  # X e Instagram: item sem data é descartado
  consultado_em: datetime = field(default_factory=lambda: datetime.now(FUSO_BR))

  @property
  def recentes(self) -> int:
    return sum(1 for i in self.itens
               if item_recente(i["publicado"], not self.exige_data))


@dataclass
class ResumoVarredura:
  novos: int = 0
  trens: int = 0
  feeds_ok: int = 0
  feeds_total: int = 0
  telegram_falhas: int = 0
  erros: list[str] = field(default_factory=list)
  em_andamento: bool = False
  quando: datetime = field(default_factory=lambda: datetime.now(FUSO_BR))


_LOCK_VARREDURA = threading.Lock()


def _data_publicacao(entrada) -> datetime | None:
  bruto = entrada.get("published_parsed") or entrada.get("updated_parsed")
  if not bruto:
    return None
  try:
    return datetime(*bruto[:6], tzinfo=timezone.utc)
  except (TypeError, ValueError):
    return None


def _entrada_para_item(entrada, url_feed: str) -> dict:
  link = (entrada.get("link") or url_feed).strip()
  fonte = (entrada.get("source") or {}).get("title") or nome_do_dominio(link)
  resumo_html = entrada.get("summary", "")
  resumo = BeautifulSoup(resumo_html, "html.parser").get_text(" ", strip=True)
  return {
      "titulo": (entrada.get("title") or "").strip(),
      "link": link,
      "fonte": fonte,
      "publicado": _data_publicacao(entrada),
      "resumo": resumo,
  }


_PAUSAS: dict[str, float] = {}  # host -> epoch até quando a fonte fica em repouso
_LOCK_PAUSAS = threading.Lock()


def _pausa_ate(host: str) -> float | None:
  with _LOCK_PAUSAS:
    ate = _PAUSAS.get(host)
    if ate and ate > time.time():
      return ate
    _PAUSAS.pop(host, None)
    return None


def _pausar(host: str, segundos: float = PAUSA_BLOQUEIO_S) -> None:
  with _LOCK_PAUSAS:
    _PAUSAS[host] = time.time() + min(max(segundos, 60), 3600)
  log.warning("Fonte %s em pausa por %d s (possível bloqueio).", host, segundos)


def pausas_ativas() -> dict[str, float]:
  agora = time.time()
  with _LOCK_PAUSAS:
    return {h: t for h, t in _PAUSAS.items() if t > agora}


def _segundos_retry(resposta) -> float:
  try:
    return float(resposta.headers.get("Retry-After", ""))
  except ValueError:
    return PAUSA_BLOQUEIO_S


def consultar_feed(url: str, proteger: bool = False) -> ResultadoFeed:
  """Baixa e interpreta um feed. Nunca levanta exceção.

  `proteger=True` (X e Instagram): respeita pausa por bloqueio, espaça as
  requisições com um pequeno atraso aleatório e entra em repouso ao receber
  401/403/429 ou ser jogado numa tela de login.
  """
  resultado = ResultadoFeed(url=url)
  host = urlparse(url).netloc
  if proteger:
    ate = _pausa_ate(host)
    if ate:
      resultado.erro = (
          f"{host} em pausa até {datetime.fromtimestamp(ate, FUSO_BR):%H:%M} "
          "para evitar bloqueio."
      )
      return resultado
    time.sleep(random.uniform(0.2, 0.8))
  inicio = time.perf_counter()
  try:
    resposta = requests.get(url, headers=HEADERS_HTTP, timeout=(5, 15))
    resultado.status = resposta.status_code
    resultado.latencia_ms = int((time.perf_counter() - inicio) * 1000)
    if proteger and re.search(r"/(login|checkpoint)\b", resposta.url):
      _pausar(host)
      resultado.erro = "A fonte redirecionou para a tela de login (bloqueio)."
      return resultado
    if resposta.status_code >= 400:
      if proteger and resposta.status_code in STATUS_BLOQUEIO:
        _pausar(host, _segundos_retry(resposta))
      resultado.erro = f"O servidor respondeu HTTP {resposta.status_code}."
      return resultado
    lido = feedparser.parse(resposta.content)
    if lido.bozo and not lido.entries:
      resultado.erro = "A resposta não é um feed RSS/Atom válido."
      return resultado
    resultado.titulo = (lido.feed.get("title") or "").strip()
    resultado.itens = [_entrada_para_item(e, url) for e in lido.entries]
    resultado.ok = True
  except requests.Timeout:
    resultado.erro = "Tempo esgotado: o servidor demorou demais para responder."
  except requests.RequestException as erro:
    resultado.erro = f"Falha de conexão: {erro}"
  except Exception as erro:  # parser inesperado
    resultado.erro = f"Erro ao interpretar o feed: {erro}"
    log.exception("Erro no feed %s", url)
  return resultado


USUARIO_X = re.compile(r"^[A-Za-z0-9_]{1,15}$")


def limpar_usuario_x(bruto: str) -> str:
  """Aceita '@perfil', 'perfil' ou link de x.com / twitter.com."""
  texto = bruto.strip()
  if "/" in texto:
    caminho = [p for p in urlparse(texto if "//" in texto else f"//{texto}").path.split("/") if p]
    texto = caminho[0] if caminho else ""
  return texto.lstrip("@")


def _link_canonico_x(link: str, usuario: str) -> str:
  """Sempre aponta para x.com, assim trocar de instância não gera duplicata."""
  achado = re.search(r"/status/(\d+)", link)
  if achado:
    return f"https://x.com/{usuario}/status/{achado.group(1)}"
  return f"https://x.com/{usuario}"


def consultar_perfil_x(usuario: str, instancias: list[str]) -> ResultadoFeed:
  """Lê o RSS público do perfil via espelhos Nitter, com fallback entre instâncias."""
  chave = f"x:{usuario}"
  falhas: list[str] = []
  ultimo: ResultadoFeed | None = None
  for base in instancias:
    base = base.rstrip("/")
    res = consultar_feed(f"{base}/{usuario}/rss", proteger=True)
    if not res.ok:
      ultimo = res
      falhas.append(f"{urlparse(base).netloc}: {res.erro}")
      continue
    itens = []
    for item in res.itens:
      texto = (item["resumo"] or item["titulo"]).strip()
      curto = texto if len(texto) <= 120 else texto[:117].rstrip() + "…"
      itens.append({
          **item,
          "titulo": curto,
          "texto_completo": texto,
          "link": _link_canonico_x(item["link"], usuario),
          "fonte": f"X (@{usuario})",
          # id estável: trocar de instância Nitter não duplica o post
          "chave_id": (re.search(r"/status/(\d+)", item["link"]) or [None, None])[1],
      })
    res.itens = itens
    res.exige_data = True
    res.url = chave
    res.titulo = f"@{usuario} via {urlparse(base).netloc}"
    return res
  falha = ultimo or ResultadoFeed(url=chave)
  falha.url = chave
  falha.exige_data = True
  falha.ok = False
  falha.erro = (
      "Nenhuma instância respondeu. " + " | ".join(falhas)
      if falhas else "Nenhuma instância Nitter cadastrada."
  )
  return falha


def _canal_telegram(url: str) -> str | None:
  partes = urlparse(url)
  if partes.netloc.replace("www.", "") not in ("t.me", "telegram.me"):
    return None
  caminho = [p for p in partes.path.split("/") if p]
  if caminho and caminho[0] == "s":
    caminho = caminho[1:]
  return caminho[0] if caminho else None


def _data_iso(valor: str | None) -> datetime | None:
  if not valor:
    return None
  try:
    limpo = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", valor.strip().replace("Z", "+00:00"))
    dt = datetime.fromisoformat(limpo)
  except ValueError:
    return None
  return (dt if dt.tzinfo else dt.replace(tzinfo=FUSO_BR)).astimezone(timezone.utc)


def _itens_telegram(soup: BeautifulSoup, canal: str) -> list[dict]:
  itens = []
  for msg in soup.select("div.tgme_widget_message"):
    corpo = msg.select_one(".tgme_widget_message_text")
    texto = corpo.get_text(" ", strip=True) if corpo else ""
    if not texto:  # só foto/vídeo
      continue
    data_el = msg.select_one("a.tgme_widget_message_date")
    post = msg.get("data-post")
    link = (f"https://t.me/{post}" if post
            else (data_el.get("href") if data_el else f"https://t.me/{canal}"))
    tempo = data_el.select_one("time") if data_el else None
    itens.append({
        "titulo": texto if len(texto) <= 120 else texto[:117].rstrip() + "…",
        "texto_completo": texto, "link": link, "resumo": "",
        "fonte": f"Telegram ({canal})",
        "publicado": _data_iso(tempo.get("datetime") if tempo else None),
    })
  return itens


def _itens_html(soup: BeautifulSoup, base_url: str, seletor: str,
                fonte: str) -> list[dict]:
  """Manchetes = links com texto de pelo menos 4 palavras. Usa <time> se houver."""
  from urllib.parse import urljoin

  raiz = soup.select(seletor) if seletor else [soup]
  itens, vistos = [], set()
  for bloco in raiz:
    for a in bloco.find_all("a", href=True):
      href = a["href"].strip()
      if href.startswith(("#", "javascript:", "mailto:", "tel:")):
        continue
      titulo = " ".join(a.get_text(" ", strip=True).split())
      if len(titulo) < 25 or len(titulo.split()) < 4:
        continue
      link = urljoin(base_url, href)
      if link in vistos:
        continue
      vistos.add(link)
      publicado = None
      for pai in list(a.parents)[:3]:
        tempo = pai.find("time", attrs={"datetime": True})
        if tempo:
          publicado = _data_iso(tempo["datetime"])
          break
      itens.append({
          "titulo": titulo[:200], "texto_completo": titulo[:200], "link": link,
          "resumo": "", "fonte": fonte, "publicado": publicado,
      })
      if len(itens) >= 60:
        return itens
  return itens


def consultar_pagina(cfg: dict) -> ResultadoFeed:
  """Lê uma página comum ou um canal público do Telegram. Nunca levanta exceção."""
  url = cfg["url"]
  res = ResultadoFeed(url=f"pg:{url}")
  canal = _canal_telegram(url)
  alvo = f"https://t.me/s/{canal}" if canal else url
  fonte = cfg.get("nome") or urlparse(url).netloc.replace("www.", "")
  inicio = time.perf_counter()
  try:
    resposta = requests.get(alvo, headers=HEADERS_HTTP, timeout=(5, 15))
    res.status = resposta.status_code
    res.latencia_ms = int((time.perf_counter() - inicio) * 1000)
    if resposta.status_code >= 400:
      res.erro = f"O servidor respondeu HTTP {resposta.status_code}."
      return res
    soup = BeautifulSoup(resposta.content, "html.parser")
    if canal:
      itens = _itens_telegram(soup, canal)
    else:
      itens = _itens_html(soup, resposta.url, cfg.get("seletor", ""), fonte)
    if not itens:
      res.erro = (
          "Nenhuma manchete encontrada. A página pode montar o conteúdo com"
          " JavaScript (o painel não executa JS) ou precisar de um seletor CSS."
          if not canal else
          "Nenhuma mensagem de texto encontrada. O canal precisa ser público."
      )
      return res
    res.itens = itens
    res.titulo = soup.title.get_text(strip=True) if soup.title else ""
    res.ok = True
  except requests.Timeout:
    res.erro = "Tempo esgotado: o servidor demorou demais para responder."
  except requests.RequestException as erro:
    res.erro = f"Falha de conexão: {erro}"
  except Exception as erro:  # seletor CSS inválido, HTML inesperado
    res.erro = f"Erro ao interpretar a página: {erro}"
    log.exception("Erro na página %s", url)
  return res


# ── Instagram ────────────────────────────────────────────────────────────
# O Instagram bloqueia leitura anônima com frequência. Estratégia, em ordem:
#   1) acesso direto à API web com cabeçalhos de navegador + cookie de sessão opcional;
#   2) pontes RSS configuradas pelo usuário (RSSHub etc.), se houver;
# com consulta espaçada (uma por vez, com pausa aleatória), cache de 10 min por perfil
# e pausa automática de 15 min no host ao receber 401/403/429 ou tela de login.
IG_HOST = "www.instagram.com"
IG_APP_ID = "936619743392459"  # id público do app web do Instagram
IG_INTERVALO_OK_S = 10 * 60
IG_INTERVALO_FALHA_S = 5 * 60
USUARIO_IG = re.compile(r"^[A-Za-z0-9._]{1,30}$")
HEADERS_NAVEGADOR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/141.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Ch-Ua": '"Chromium";v="141", "Google Chrome";v="141", "Not?A_Brand";v="8"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}
_LOCK_IG = threading.Lock()  # uma consulta ao Instagram por vez


def limpar_usuario_instagram(bruto: str) -> str:
  """Aceita '@perfil', 'perfil' ou link do perfil."""
  texto = bruto.strip()
  if "/" in texto:
    caminho = [p for p in urlparse(texto if "//" in texto else f"//{texto}").path.split("/") if p]
    texto = caminho[0] if caminho else ""
  return texto.lstrip("@")


def _mascarar(texto: str, segredo: str) -> str:
  return texto.replace(segredo, "***") if segredo else texto


def _item_instagram(usuario: str, codigo: str, legenda: str,
                    publicado: datetime | None, link: str | None = None) -> dict:
  return {
      "titulo": legenda if len(legenda) <= 120 else legenda[:117].rstrip() + "…",
      "texto_completo": legenda, "resumo": "",
      "link": link or f"https://www.instagram.com/p/{codigo}/",
      "fonte": f"Instagram (@{usuario})",
      "publicado": publicado,
      "chave_id": codigo,  # id estável, independente do caminho usado para ler
  }


def _consultar_instagram_direto(usuario: str, sessionid: str) -> ResultadoFeed:
  res = ResultadoFeed(url=f"ig:{usuario}", exige_data=True)
  ate = _pausa_ate(IG_HOST)
  if ate:
    res.erro = (f"Instagram em pausa até {datetime.fromtimestamp(ate, FUSO_BR):%H:%M} "
                "para evitar bloqueio.")
    return res
  login_msg = ("O Instagram pediu login. Cadastre o cookie de sessão de uma conta "
               "secundária na aba Fontes, em Instagram.")
  inicio = time.perf_counter()
  try:
    with requests.Session() as sessao:
      sessao.headers.update(HEADERS_NAVEGADOR)
      if sessionid:
        sessao.cookies.set("sessionid", sessionid, domain=".instagram.com")
      try:  # aquecimento: o site entrega os cookies csrftoken/mid como um navegador
        sessao.get(f"https://{IG_HOST}/", timeout=(5, 15), headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none", "Upgrade-Insecure-Requests": "1",
        })
      except requests.RequestException:
        pass  # o aquecimento é opcional
      time.sleep(random.uniform(0.8, 2.0))
      resp = sessao.get(
          f"https://{IG_HOST}/api/v1/users/web_profile_info/",
          params={"username": usuario}, timeout=(5, 15), allow_redirects=False,
          headers={
              "Accept": "*/*", "X-IG-App-ID": IG_APP_ID,
              "X-CSRFToken": sessao.cookies.get("csrftoken", ""),
              "X-Requested-With": "XMLHttpRequest",
              "Referer": f"https://{IG_HOST}/{usuario}/",
              "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors",
              "Sec-Fetch-Site": "same-origin",
          },
      )
    res.status = resp.status_code
    res.latencia_ms = int((time.perf_counter() - inicio) * 1000)
    if resp.status_code in (301, 302, 303, 307, 308):
      _pausar(IG_HOST)
      res.erro = login_msg
      return res
    if resp.status_code in STATUS_BLOQUEIO:
      _pausar(IG_HOST, _segundos_retry(resp))
      res.erro = (f"O Instagram recusou o acesso (HTTP {resp.status_code}). "
                  "Fonte em pausa por 15 min. " + ("" if sessionid else login_msg))
      return res
    if resp.status_code == 404:
      res.erro = "Perfil não encontrado."
      return res
    if resp.status_code >= 400:
      res.erro = f"O servidor respondeu HTTP {resp.status_code}."
      return res
    try:
      corpo = resp.json()
    except ValueError:
      _pausar(IG_HOST)
      res.erro = "Resposta inesperada (provável tela de verificação). " + login_msg
      return res
    perfil = (corpo.get("data") or {}).get("user")
    if not perfil:
      res.erro = "Perfil indisponível: privado, inexistente ou exige login."
      return res
    arestas = (perfil.get("edge_owner_to_timeline_media") or {}).get("edges", [])
    for aresta in arestas:
      no = aresta.get("node") or {}
      codigo = no.get("shortcode")
      legendas = (no.get("edge_media_to_caption") or {}).get("edges") or []
      legenda = ((legendas[0].get("node") or {}).get("text") or "").strip() if legendas else ""
      if not codigo or not legenda:
        continue
      ts = no.get("taken_at_timestamp")
      publicado = datetime.fromtimestamp(ts, timezone.utc) if ts else None
      res.itens.append(_item_instagram(usuario, codigo, legenda, publicado))
    res.titulo = f"@{usuario} (acesso direto" + (", com sessão)" if sessionid else ")")
    res.ok = True
  except requests.Timeout:
    res.erro = "Tempo esgotado: o Instagram demorou demais para responder."
  except requests.RequestException as erro:
    res.erro = _mascarar(f"Falha de conexão: {erro}", sessionid)
  except Exception as erro:  # formato da resposta mudou
    res.erro = f"Formato inesperado da resposta do Instagram: {type(erro).__name__}"
    log.exception("Erro no Instagram @%s", usuario)
  return res


def _itens_instagram_ponte(itens: list[dict], usuario: str) -> list[dict]:
  saida = []
  for item in itens:
    legenda = max((item["resumo"] or "", item["titulo"] or ""), key=len).strip()
    achado = re.search(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)", item["link"])
    if not legenda or not achado:
      continue
    saida.append(_item_instagram(usuario, achado.group(1), legenda, item["publicado"]))
  return saida


def consultar_instagram(usuario: str, store: "Store", forcar: bool = False) -> ResultadoFeed:
  """Perfil do Instagram. Nunca levanta exceção e nunca insiste depois de um bloqueio."""
  chave = f"ig:{usuario}"
  anterior = store.feeds.get(chave)
  if anterior and not forcar:  # evita martelar o Instagram a cada varredura
    idade = (datetime.now(FUSO_BR) - anterior.consultado_em).total_seconds()
    if idade < (IG_INTERVALO_OK_S if anterior.ok else IG_INTERVALO_FALHA_S):
      return anterior
  sessionid = (store.data.get("instagram_sessionid") or "").strip()
  with _LOCK_IG:
    res = _consultar_instagram_direto(usuario, sessionid)
  if res.ok:
    return res
  falhas = [f"acesso direto: {res.erro}"]
  for modelo in store.data.get("bridges_instagram", []):
    url = modelo.replace("{perfil}", quote_plus(usuario))
    ponte = consultar_feed(url, proteger=True)
    if ponte.ok:
      ponte.itens = _itens_instagram_ponte(ponte.itens, usuario)
      ponte.url, ponte.exige_data = chave, True
      ponte.titulo = f"@{usuario} via {urlparse(url).netloc}"
      return ponte
    falhas.append(f"{urlparse(url).netloc}: {ponte.erro}")
  res.erro = " | ".join(falhas)
  return res


def consultar_fonte(chave: str, store: "Store", forcar: bool = False) -> ResultadoFeed:
  """Feed RSS, perfil do X ('x:'), Instagram ('ig:') ou página/canal ('pg:')."""
  if chave.startswith("x:"):
    return consultar_perfil_x(chave[2:], list(store.data["instancias_nitter"]))
  if chave.startswith("ig:"):
    return consultar_instagram(chave[3:], store, forcar)
  if chave.startswith("pg:"):
    cfg = store.pagina(chave[3:])
    if cfg is None:
      return ResultadoFeed(url=chave, erro="Página removida da lista.")
    return consultar_pagina(cfg)
  return consultar_feed(chave)


def novo_alerta(*, id_unico, cidade, categoria, fonte, titulo, resumo, url,
                quando: datetime | None = None) -> dict:
  momento = (quando or datetime.now(FUSO_BR)).astimezone(FUSO_BR)
  return {
      "id_unico": id_unico,
      "horario": momento.strftime("%H:%M:%S"),
      "data_hora": momento.isoformat(timespec="seconds"),
      "cidade": cidade,
      "categoria": categoria,
      "fonte": fonte,
      "titulo": titulo,
      "resumo": resumo,
      "url": url,
  }


def _status_linha(texto: str, numero: str) -> str | None:
  """Status da linha, lendo só o trecho entre 'Linha N' e a próxima 'Linha'.

  Devolve None quando a página não traz nenhuma linha (layout mudou ou erro),
  para não confundir falha de leitura com 'voltou ao normal'.
  """
  marcas = list(re.finditer(r"Linha\s*(\d+)", texto, re.IGNORECASE))
  if not marcas:
    return None
  trechos = []
  for i, marca in enumerate(marcas):
    if marca.group(1) != numero:
      continue
    fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
    trechos.append(texto[marca.end():min(fim, marca.end() + 300)])
  corpo = " ".join(trechos).lower()
  for status in STATUS_ALTERADOS:
    if status.lower() in corpo:
      return status
  return STATUS_NORMAL


def verificar_trens(store: Store, resumo: ResumoVarredura) -> list[dict]:
  """Linhas 11 e 12: só gera alerta quando o status MUDA para algo diferente de normal."""
  alertas: list[dict] = []
  try:
    resposta = requests.get(URL_DIRETO_TRENS, headers=HEADERS_HTTP, timeout=10)
    resposta.raise_for_status()
    texto = BeautifulSoup(resposta.text, "html.parser").get_text(" ")
  except Exception as erro:
    resumo.erros.append(f"Direto dos Trens: {erro}")
    return alertas

  with store.lock:
    estados = store.data.setdefault("estado_trens", {})
    for numero, nome, regiao in LINHAS_ALVO:
      status = _status_linha(texto, numero)
      if status is None:
        continue
      anterior = estados.get(numero, STATUS_NORMAL)
      if status == anterior:
        continue
      estados[numero] = status
      if status == STATUS_NORMAL:  # voltou ao normal: atualiza, não notifica
        continue
      agora = datetime.now(FUSO_BR)
      alertas.append(novo_alerta(
          id_unico=gerar_id_unico(
              f"diretodostrens_{numero}_{status}_{agora:%Y%m%d%H%M}",
              URL_DIRETO_TRENS,
          ),
          cidade=f"Alto Tietê ({nome})",
          categoria=CAT_TRANSITO,
          fonte="Direto dos Trens",
          titulo=f"A {nome} está com {status}",
          resumo=(
              f"Monitoramento CPTM: A {nome} ({regiao}) apresenta alteração de"
              f" status '{status}' no Direto dos Trens."
          ),
          url=URL_DIRETO_TRENS,
          quando=agora,
      ))
  return alertas


def _notificar(store: Store, alerta: dict, resumo: ResumoVarredura) -> None:
  token = store.data.get("telegram_token", "")
  chat = store.data.get("telegram_chat_id", "")
  if not (token and chat):
    return
  ok, mensagem = enviar_telegram(
      token, chat, texto_mensagem(alerta, "html"),
      preview=bool(store.data.get("telegram_preview")),
  )
  if not ok:
    resumo.telegram_falhas += 1
    log.warning("Telegram falhou: %s", mensagem)
  time.sleep(0.4)  # respeita o limite do Telegram em rajadas


def _fechar_varredura(store: Store, resumo: ResumoVarredura, novos: list[dict]):
  novos.sort(key=lambda a: a["data_hora"])  # mais antigos primeiro no Telegram
  for alerta in novos:
    store.adicionar_alerta(alerta)
    _notificar(store, alerta, resumo)
  resumo.novos = len(novos)
  store.salvar()


def _texto_item(item: dict) -> str:
  texto = item.get("texto_completo") or f"{item['titulo']} - {item['resumo']}"
  return texto.strip()


def _linha_de_base(store: Store, res: ResultadoFeed) -> None:
  """1ª leitura de uma página sem datas: marca o que já existe como visto,
  para não disparar dezenas de alertas antigos."""
  cfg = store.pagina(res.url[3:])
  if not cfg or cfg.get("baseline_feito"):
    return
  for item in res.itens:
    if item["publicado"] is None:
      store.marcar_visto(gerar_id_unico(_texto_item(item), item["link"]))
  cfg["baseline_feito"] = True


def avaliar_itens(store: Store, itens: list[dict], cidades: list[str],
                  novos: list[dict], *, exige_data: bool = False) -> None:
  """Pipeline ÚNICO de filtragem, igual para toda fonte (RSS, X, Instagram, páginas…).

  Ordem: 1) janela de 1 hora  2) menção explícita a cidade/bairro/rua/rodovia
  3) id_unico inédito (persistido em dados_monitor_g1.json). Só o que passa nas
  três etapas vira alerta, aparece no painel e vai ao Telegram.
  """
  logradouros = store.data.get("logradouros")
  rodovias = store.data.get("rodovias")
  excluidas = store.data.get("cidades_excluidas")
  for item in itens:
    if not item_recente(item["publicado"], not exige_data):
      continue
    texto = _texto_item(item)
    if len(texto) <= 15:
      continue
    local = identificar_local(texto, cidades, logradouros, rodovias, excluidas)
    if not local:  # genérico, de outra praça ou sem menção explícita: descarta
      continue
    id_unico = gerar_id_unico(item.get("chave_id") or texto, item["link"])
    if not store.marcar_visto(id_unico):
      continue
    novos.append(novo_alerta(
        id_unico=id_unico, cidade=local,
        categoria=classificar_ocorrencia(texto), fonte=item["fonte"],
        titulo=item["titulo"], resumo=texto[:350], url=item["link"],
        quando=item["publicado"],
    ))


def _coletar_novos(store: Store, res: ResultadoFeed, cidades: list[str],
                   novos: list[dict]) -> None:
  avaliar_itens(store, res.itens, cidades, novos, exige_data=res.exige_data)


def varrer_portais(store: Store) -> ResumoVarredura:
  """Trens + RSS, X, Instagram e páginas. Seguro para chamar da UI ou da thread."""
  if not _LOCK_VARREDURA.acquire(blocking=False):
    return ResumoVarredura(em_andamento=True)
  resumo = ResumoVarredura()
  try:
    with store.lock:
      fontes = (
          list(store.data["urls"])
          + [f"x:{u}" for u in store.data["perfis_x"]]
          + [f"ig:{u}" for u in store.data["perfis_instagram"]]
          + [f"pg:{p['url']}" for p in store.data["paginas"]]
      )
      cidades = list(store.data["cidades"])
    resumo.feeds_total = len(fontes)

    novos = verificar_trens(store, resumo)
    resumo.trens = len(novos)
    for alerta in novos:
      store.marcar_visto(alerta["id_unico"])

    with ThreadPoolExecutor(max_workers=4) as pool:
      resultados = list(pool.map(lambda c: consultar_fonte(c, store), fontes))
    for res in resultados:
      store.feeds[res.url] = res
      if not res.ok:
        resumo.erros.append(f"{rotulo_feed(res.url)}: {res.erro}")
        continue
      resumo.feeds_ok += 1
      if res.url.startswith("pg:"):
        _linha_de_base(store, res)
      _coletar_novos(store, res, cidades, novos)
    _fechar_varredura(store, resumo, novos)
  except Exception as erro:
    log.exception("Falha na varredura")
    resumo.erros.append(f"Erro inesperado: {erro}")
  finally:
    _LOCK_VARREDURA.release()
  return resumo


# ──────────────────────────────────────────────────────────────────────────
# 6. Automação em segundo plano
# ──────────────────────────────────────────────────────────────────────────
class Automacao:
  """Uma única thread por processo. Continua rodando com o navegador fechado
  e sem congelar a interface (a versão anterior usava time.sleep na página)."""

  def __init__(self, store: Store):
    self.store = store
    self.ultimo_fim: float | None = None
    self.ultimo_resumo: ResumoVarredura | None = None
    self._thread = threading.Thread(
        target=self._loop, name="varredura-automatica", daemon=True
    )
    self._thread.start()

  @property
  def ativo(self) -> bool:
    return bool(self.store.data.get("automacao_ativa"))

  @property
  def intervalo_s(self) -> int:
    return max(1, int(self.store.data.get("intervalo_auto", 5))) * 60

  @property
  def proxima(self) -> float | None:
    if not self.ativo:
      return None
    return 0.0 if self.ultimo_fim is None else self.ultimo_fim + self.intervalo_s

  def executar(self) -> ResumoVarredura:
    resumo = varrer_portais(self.store)
    if not resumo.em_andamento:
      self.ultimo_fim = time.time()
      self.ultimo_resumo = resumo
    return resumo

  def _loop(self) -> None:
    while True:
      time.sleep(2)
      try:
        proxima = self.proxima
        if proxima is not None and time.time() >= proxima:
          self.executar()
      except Exception:
        log.exception("Falha no ciclo automático")


@st.cache_resource(show_spinner=False)
def obter_automacao() -> Automacao:
  return Automacao(obter_store())


# ──────────────────────────────────────────────────────────────────────────
# 7. Identidade visual
# ──────────────────────────────────────────────────────────────────────────
PALETAS = {
    "light": {
        "bg": "#F4F5F7", "surface": "#FFFFFF", "border": "#E1E4E8",
        "text": "#1F2933", "muted": "#667085", "chip": "#EEF0F3",
        "blue": "#0669DE", "blue-dark": "#0B4DA2", "blue-soft": "#E8F1FD",
        "red": "#C4170C", "red-soft": "#FDECEA", "green": "#1B7F3B",
        "green-soft": "#E6F4EA",
    },
    "dark": {
        "bg": "#12151A", "surface": "#1B2027", "border": "#2B323C",
        "text": "#E6E9EE", "muted": "#9AA4B2", "chip": "#262D37",
        "blue": "#4C9AFF", "blue-dark": "#7DB4FF", "blue-soft": "#162A44",
        "red": "#FF6B5E", "red-soft": "#3A1B19", "green": "#4CC38A",
        "green-soft": "#16301F",
    },
}

CSS_BASE = """
.stApp{background:var(--g1-bg);color:var(--g1-text)}
html,body,.stApp,.stApp p,.stApp li,.stApp label,.stApp h1,.stApp h2,.stApp h3,
.stApp h4,.stApp button,.stApp input,.stApp textarea,.stApp a,
.stApp [data-baseweb]{font-family:var(--g1-font)}
.stApp h1,.stApp h2,.stApp h3{color:var(--g1-text);font-weight:700;letter-spacing:-.01em}
.block-container{max-width:1180px;padding:1.2rem 1.2rem 3rem}
header[data-testid="stHeader"]{background:transparent}
footer{visibility:hidden}

.g1-header{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;
 gap:14px 20px;padding:18px 22px;margin-bottom:14px;background:var(--g1-surface);
 border:1px solid var(--g1-border);border-top:4px solid var(--g1-red);border-radius:10px}
.g1-brand{display:flex;align-items:center;gap:16px;min-width:0}
.g1-logo{height:clamp(34px,6vw,52px);width:auto;max-width:46vw;display:block}
.g1-wordmark{display:flex;align-items:center;gap:8px;flex-shrink:0}
.g1-wordmark b{background:var(--g1-red);color:#fff;font-weight:800;font-size:1.6rem;
 line-height:1;padding:6px 12px 9px;border-radius:8px;letter-spacing:-.03em}
.g1-wordmark span{font-weight:600;font-size:1rem;color:var(--g1-text)}
.g1-titles h1{font-size:clamp(1.1rem,2.6vw,1.55rem);margin:0;padding:0;line-height:1.2}
.g1-titles p{margin:3px 0 0;color:var(--g1-muted);font-size:.92rem}
.g1-pill{display:inline-flex;align-items:center;gap:8px;padding:6px 13px;border-radius:999px;
 font-size:.85rem;font-weight:600;background:var(--g1-chip);color:var(--g1-muted)}
.g1-pill.live{background:var(--g1-red-soft);color:var(--g1-red)}
.g1-dot{width:8px;height:8px;border-radius:50%;background:currentColor}
.g1-pill.live .g1-dot{animation:g1pulse 1.8s ease-in-out infinite}
@keyframes g1pulse{50%{opacity:.25}}
@media (prefers-reduced-motion:reduce){.g1-pill.live .g1-dot{animation:none}}

.stTabs [data-baseweb="tab-list"]{gap:2px;border-bottom:1px solid var(--g1-border);flex-wrap:wrap}
.stTabs [data-baseweb="tab"]{font-weight:600;padding:10px 16px;color:var(--g1-muted)}
.stTabs [aria-selected="true"]{color:var(--g1-blue)}
.stTabs [data-baseweb="tab-highlight"]{background:var(--g1-red);height:3px}

button[kind="primary"],button[kind="primaryFormSubmit"]{background:var(--g1-blue);
 border-color:var(--g1-blue);color:#fff;font-weight:600}
button[kind="primary"]:hover,button[kind="primaryFormSubmit"]:hover{
 background:var(--g1-blue-dark);border-color:var(--g1-blue-dark);color:#fff}
button[kind="secondary"],button[kind="secondaryFormSubmit"]{border-color:var(--g1-border);font-weight:500}

[data-testid="stVerticalBlockBorderWrapper"]{background:var(--g1-surface);
 border-color:var(--g1-border);border-radius:10px}
[data-testid="stVerticalBlockBorderWrapper"]:has(.g1-urgente){border-left:4px solid var(--g1-red)}
[data-testid="stExpander"]{border-color:var(--g1-border);border-radius:10px;background:var(--g1-surface)}

.g1-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:8px 0 14px}
.g1-stat{background:var(--g1-surface);border:1px solid var(--g1-border);border-radius:10px;padding:11px 14px}
.g1-stat b{display:block;font-size:1.5rem;font-weight:700;line-height:1.2}
.g1-stat span{color:var(--g1-muted);font-size:.85rem}
.g1-stat.alerta b{color:var(--g1-red)}

.g1-meta{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;margin-bottom:8px}
.g1-chip{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.78rem;
 font-weight:600;background:var(--g1-chip);color:var(--g1-text)}
.g1-chip.urgente{background:var(--g1-red-soft);color:var(--g1-red)}
.g1-chip.info{background:var(--g1-blue-soft);color:var(--g1-blue)}
.g1-chip.ok{background:var(--g1-green-soft);color:var(--g1-green)}
.g1-chip.erro{background:var(--g1-red-soft);color:var(--g1-red)}
.g1-time{color:var(--g1-muted);font-size:.82rem;margin-left:auto}
.g1-title{display:block;font-size:1.08rem;font-weight:700;line-height:1.35;
 color:var(--g1-text)!important;text-decoration:none}
.g1-title:hover{color:var(--g1-blue)!important;text-decoration:underline}
.g1-resumo{margin:6px 0 2px;color:var(--g1-muted);font-size:.93rem;line-height:1.5;max-width:75ch}
"""


@st.cache_resource(show_spinner=False)
def _fontes_css() -> tuple[str, bool]:
  """Embute os arquivos GloboTypo de assets/fonts como @font-face."""
  pesos = [("semibold", 600), ("demibold", 600), ("extrabold", 800),
           ("black", 900), ("bold", 700), ("medium", 500), ("light", 300),
           ("thin", 100)]
  formatos = {".woff2": "woff2", ".woff": "woff", ".otf": "opentype",
              ".ttf": "truetype"}
  mimes = {".woff2": "font/woff2", ".woff": "font/woff",
           ".otf": "font/otf", ".ttf": "font/ttf"}
  regras = []
  for pasta in PASTAS_ASSETS:
    diretorio = pasta / "fonts"
    if not diretorio.is_dir():
      continue
    for arquivo in sorted(diretorio.iterdir()):
      extensao = arquivo.suffix.lower()
      if extensao not in formatos:
        continue
      nome = arquivo.stem.lower()
      peso = next((p for chave, p in pesos if chave in nome), 400)
      estilo = "italic" if ("italic" in nome or "oblique" in nome) else "normal"
      dados = base64.b64encode(arquivo.read_bytes()).decode("ascii")
      regras.append(
          '@font-face{font-family:"GloboTypo";font-display:swap;'
          f"font-weight:{peso};font-style:{estilo};"
          f'src:url(data:{mimes[extensao]};base64,{dados}) format("{formatos[extensao]}")}}'
      )
    if regras:
      break
  return "".join(regras), bool(regras)


@st.cache_resource(show_spinner=False)
def _logo_uri() -> str | None:
  mimes = {".svg": "image/svg+xml", ".png": "image/png",
           ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
  for pasta in PASTAS_ASSETS:
    if not pasta.is_dir():
      continue
    for arquivo in sorted(pasta.glob("logo*")):
      if arquivo.suffix.lower() in mimes:
        dados = base64.b64encode(arquivo.read_bytes()).decode("ascii")
        return f"data:{mimes[arquivo.suffix.lower()]};base64,{dados}"
  return None


def tema_atual() -> str:
  try:
    return "dark" if st.context.theme.type == "dark" else "light"
  except Exception:
    return "light"


@st.cache_resource(show_spinner=False)
def _css(tema: str) -> str:
  fontes, _ = _fontes_css()
  familia = (
      '"GloboTypo","Globotipo",system-ui,-apple-system,"Segoe UI",Roboto,'
      "Helvetica,Arial,sans-serif"
  )
  variaveis = "".join(f"--g1-{k}:{v};" for k, v in PALETAS[tema].items())
  return f"{fontes}:root{{{variaveis}--g1-font:{familia}}}{CSS_BASE}"


def _html(texto: str) -> str:
  """Remove indentação para o Markdown não tratar o HTML como bloco de código."""
  return "".join(linha.strip() for linha in texto.splitlines())


def cabecalho(auto: Automacao) -> None:
  logo = _logo_uri()
  if logo:
    marca = f'<img class="g1-logo" src="{logo}" alt="g1 Alto Tietê">'
  else:
    marca = '<div class="g1-wordmark"><b>g1</b><span>Alto Tietê</span></div>'
  if auto.ativo:
    pill = '<span class="g1-pill live"><span class="g1-dot"></span>Varredura automática ativa</span>'
  else:
    pill = '<span class="g1-pill"><span class="g1-dot"></span>Varredura automática desligada</span>'
  st.markdown(_html(f"""
    <div class="g1-header">
      <div class="g1-brand">{marca}
        <div class="g1-titles"><h1>Central</h1>
        <p>Cobertura em tempo real do Alto Tietê</p></div>
      </div>{pill}
    </div>"""), unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────
# 8. Interface
# ──────────────────────────────────────────────────────────────────────────
PAUTAS = {
    CAT_SEGURANCA: [
        "Confirmar com PM, Polícia Civil, Bombeiros ou Samu: local exato, horário, número de vítimas e estado de saúde.",
        "Checar na delegacia responsável se há boletim de ocorrência, suspeitos presos ou linha de investigação.",
        "Buscar imagens e testemunhas e verificar se há vias interditadas ou risco para outras pessoas.",
        "Pedir nota oficial de {orgao} e das corporações envolvidas.",
    ],
    CAT_TRANSITO: [
        "Consultar a operadora (CPTM/ViaMobilidade), a concessionária da rodovia ou o órgão de trânsito: causa, trecho afetado e previsão de normalização.",
        "Verificar rotas alternativas, desvios e se há ônibus de apoio.",
        "Conferir se há feridos ou acidente associado (PM Rodoviária, Bombeiros).",
        "Pedir imagens de câmeras, passageiros ou motoristas no local.",
    ],
    CAT_SERVICOS: [
        "Contatar a concessionária (Sabesp, EDP) ou {orgao}: causa, bairros afetados e previsão de retorno.",
        "Perguntar quantas pessoas ou imóveis são afetados e se há atendimento alternativo (caminhão-pipa, UPA, escolas).",
        "Verificar se a Defesa Civil emitiu alerta ou recomendação.",
        "Ouvir moradores e registrar desde quando o problema ocorre.",
    ],
    CAT_GERAL: [
        "Confirmar a informação na fonte original: nota oficial, assessoria de imprensa ou {orgao}.",
        "Verificar se outros veículos já confirmaram e se há dados novos.",
        "Identificar personagens e especialistas que possam contextualizar.",
        "Levantar o impacto para a população e os próximos desdobramentos.",
    ],
}


def perguntas_apuracao(alerta: dict) -> str:
  base = alerta.get("cidade", "").split(" (")[0]
  if not base or base.startswith("@") or base == "Alto Tietê":
    orgao = "a prefeitura da cidade citada"
  else:
    orgao = f"a Prefeitura de {base}"
  itens = [
      "O que aconteceu, onde, quando e quem está envolvido? Há confirmação oficial?"
  ] + PAUTAS.get(alerta.get("categoria"), PAUTAS[CAT_GERAL])
  return "\n".join(f"{i}. {t.format(orgao=orgao)}" for i, t in enumerate(itens, 1))


def _card_html(alerta: dict) -> str:
  esc = html.escape
  categoria = alerta.get("categoria", CAT_GERAL)
  classe_cat = "urgente" if categoria == CAT_SEGURANCA else "info"
  marcador = '<span class="g1-urgente"></span>' if categoria == CAT_SEGURANCA else ""
  titulo = alerta.get("titulo") or alerta.get("resumo", "")[:90] or "Sem título"
  return _html(f"""
    <div class="g1-meta">{marcador}
      <span class="g1-chip {classe_cat}">{esc(categoria)}</span>
      <span class="g1-chip">🏙️ {esc(alerta.get("cidade", ""))}</span>
      <span class="g1-chip">📰 {esc(alerta.get("fonte", "Portal de Notícias"))}</span>
      <span class="g1-time">⏰ {esc(alerta.get("horario", ""))}</span>
    </div>
    <a class="g1-title" href="{esc(alerta.get("url", "#"), quote=True)}" target="_blank" rel="noopener">{esc(titulo)}</a>
    <p class="g1-resumo">{esc(alerta.get("resumo", ""))}</p>""")


def _mostrar_resumo(resumo: ResumoVarredura) -> None:
  if resumo.em_andamento:
    st.info("Já existe uma varredura em andamento. Aguarde alguns segundos.")
    return
  if resumo.novos:
    st.success(f"{resumo.novos} novo(s) alerta(s) capturado(s).")
  else:
    st.info("Varredura concluída. Sem novidades no momento.")
  if resumo.telegram_falhas:
    st.warning(
        f"{resumo.telegram_falhas} mensagem(ns) não chegou(aram) ao Telegram."
        " Confira o token e o Chat ID na aba Telegram & automação."
    )
  if resumo.erros:
    with st.expander(f"⚠️ {len(resumo.erros)} fonte(s) com falha nesta varredura"):
      for erro in resumo.erros:
        st.caption(f"• {erro}")


def _limpar_historico() -> None:
  store = obter_store()
  with store.lock:
    store.data["historico_alertas"] = []  # os ids já vistos permanecem
    store.salvar()


def _painel_feed() -> None:
  """Lista de alertas. Roda como fragmento: atualiza sozinha sem recarregar a página."""
  store = obter_store()
  historico = list(store.data["historico_alertas"])
  hoje = datetime.now(FUSO_BR).strftime("%Y-%m-%d")
  de_hoje = sum(1 for a in historico if a.get("data_hora", "").startswith(hoje))
  urgentes = sum(1 for a in historico if a.get("categoria") == CAT_SEGURANCA)
  feeds_ok = sum(1 for r in store.feeds.values() if r.ok)
  st.markdown(_html(f"""
    <div class="g1-stats">
      <div class="g1-stat"><b>{len(historico)}</b><span>alertas no histórico</span></div>
      <div class="g1-stat"><b>{de_hoje}</b><span>capturados hoje</span></div>
      <div class="g1-stat alerta"><b>{urgentes}</b><span>segurança / policial</span></div>
      <div class="g1-stat"><b>{feeds_ok}/{len(_fontes_ativas(store))}</b><span>feeds respondendo</span></div>
    </div>"""), unsafe_allow_html=True)

  locais = sorted({*store.data["cidades"], *(a.get("cidade", "") for a in historico)} - {""})
  f1, f2, f3 = st.columns([2, 2, 3])
  cidade = f1.selectbox("Município / local", ["Todas as cidades"] + locais, key="f_cidade")
  categoria = f2.selectbox("Categoria", ["Todas as categorias"] + CATEGORIAS, key="f_cat")
  busca = f3.text_input("Buscar no título ou resumo", key="f_busca", placeholder="Ex.: Linha 11, Sabesp, rodovia")

  if not historico:
    st.info("Nenhum alerta ainda. Clique em “Varrer agora” ou ative a varredura automática.")
    return
  filtrados = [
      a for a in historico
      if (cidade == "Todas as cidades" or a.get("cidade") == cidade)
      and (categoria == "Todas as categorias" or a.get("categoria") == categoria)
      and (not busca or _norm(busca) in _norm(f"{a.get('titulo', '')} {a.get('resumo', '')}"))
  ]
  if not filtrados:
    st.warning("Nenhuma ocorrência com esses filtros. Remova um filtro para ver mais resultados.")
    return

  token = store.data.get("telegram_token", "")
  chat = store.data.get("telegram_chat_id", "")
  for idx, alerta in enumerate(filtrados[:LIMITE_EXIBICAO]):
    chave = alerta.get("id_unico") or str(idx)
    with st.container(border=True):
      st.markdown(_card_html(alerta), unsafe_allow_html=True)
      b1, b2, b3, _ = st.columns([1, 1, 1, 2])
      with b1.popover("📋 Copiar"):
        st.caption("WhatsApp")
        st.code(texto_mensagem(alerta, "whatsapp"), language=None, wrap_lines=True)
        st.caption("Telegram")
        st.code(texto_mensagem(alerta, "texto"), language=None, wrap_lines=True)
      with b2.popover("🧭 Pauta"):
        st.markdown("**Perguntas de apuração**")
        st.markdown(perguntas_apuracao(alerta))
      if b3.button("📤 Enviar", key=f"envia_{chave}", help="Envia este alerta ao seu chat do Telegram"):
        ok, msg = enviar_telegram(token, chat, texto_mensagem(alerta, "html"),
                                  preview=bool(store.data.get("telegram_preview")))
        st.toast("Enviado ao Telegram." if ok else f"Não enviado: {msg}", icon="✅" if ok else "⚠️")
  if len(filtrados) > LIMITE_EXIBICAO:
    st.caption(f"Mostrando {LIMITE_EXIBICAO} de {len(filtrados)}. Use os filtros para refinar.")


def aba_feed(store: Store, auto: Automacao) -> None:
  b1, b2, _ = st.columns([2, 2, 2])
  if b1.button("🔍 Varrer agora", type="primary", key="btn_varrer"):
    with st.spinner("Consultando todas as fontes e o Direto dos Trens…"):
      _mostrar_resumo(auto.executar())
  with b2.popover("🗑️ Limpar histórico"):
    st.caption("Remove os cartões da tela. Matérias já capturadas não serão reenviadas.")
    st.button("Confirmar limpeza", on_click=_limpar_historico, key="btn_limpar")

  intervalo = "45s" if auto.ativo else None
  st.fragment(_painel_feed, run_every=intervalo)()


def _fontes_ativas(store: Store) -> list[str]:
  return (
      list(store.data["urls"])
      + [f"x:{u}" for u in store.data["perfis_x"]]
      + [f"ig:{u}" for u in store.data["perfis_instagram"]]
      + [f"pg:{p['url']}" for p in store.data["paginas"]]
  )


def _k(chave: str) -> str:
  """Sufixo curto e estável para chaves de widgets."""
  return hashlib.md5(chave.encode("utf-8")).hexdigest()[:10]


def _linhas(texto: str) -> list[str]:
  vistos, saida = set(), []
  for linha in texto.splitlines():
    termo = linha.strip()
    if termo and termo.lower() not in vistos:
      vistos.add(termo.lower())
      saida.append(termo)
  return saida


def _testar_todos(store: Store) -> None:
  with ThreadPoolExecutor(max_workers=4) as pool:
    for res in pool.map(lambda c: consultar_fonte(c, store, forcar=True), _fontes_ativas(store)):
      store.feeds[res.url] = res


def _cartao_fonte(store: Store, chave: str, titulo: str, detalhe: str = "",
                  remover: tuple | None = None) -> None:
  """Uma fonte com status ao vivo, últimas matérias, teste e remoção."""
  res = store.feeds.get(chave)
  icone = "⏳" if res is None else ("🟢" if res.ok else "🔴")
  with st.expander(f"{icone} {titulo}"):
    if detalhe:
      st.code(detalhe, language=None, wrap_lines=True)
    if res is None:
      st.caption("Ainda não testada. Clique em “Testar” ou aguarde a próxima varredura.")
    else:
      m1, m2, m3, m4 = st.columns(4)
      m1.metric("HTTP", res.status or "—")
      m2.metric("Resposta", f"{res.latencia_ms} ms" if res.latencia_ms is not None else "—")
      m3.metric("Itens na fonte", len(res.itens))
      m4.metric("Dentro de 1 hora", res.recentes)
      st.caption(f"Última checagem: {res.consultado_em:%d/%m %H:%M:%S}"
                 + (f" · {res.titulo}" if res.titulo else ""))
      if not res.ok:
        st.error(res.erro)
      for item in res.itens[:8]:
        local = identificar_local(
            _texto_item(item), store.data["cidades"], store.data["logradouros"],
            store.data["rodovias"], store.data["cidades_excluidas"],
        )
        selo = "🟢" if item_recente(item["publicado"], not res.exige_data) else "⚪"
        nome = html.escape(item["titulo"] or "(sem título)")
        nome = re.sub(r"([\[\]])", r"\\\1", nome)
        st.markdown(
            f"{selo} [{nome}]({item['link']})  \n"
            f"<small>{html.escape(item['fonte'])} · {idade_texto(item['publicado'])} · "
            f"🏙️ {html.escape(local) if local else 'fora da base (seria descartada)'}</small>",
            unsafe_allow_html=True)
      if res.itens:
        st.caption("🟢 dentro da janela de 1 hora · ⚪ fora da janela · 🏙️ resultado do filtro geográfico")
    b1, b2, _ = st.columns([1, 1, 3])
    if b1.button("🔄 Testar", key=f"teste_{_k(chave)}"):
      with st.spinner("Testando…"):
        store.feeds[chave] = consultar_fonte(chave, store, forcar=True)
      st.rerun()
    if remover:
      b2.button("🗑️ Remover", key=f"rem_{_k(chave)}", on_click=remover[0], args=remover[1:])


def _resumo_fontes(store: Store) -> None:
  for host, ate in pausas_ativas().items():
    st.warning(f"⏸️ {host} em pausa até {datetime.fromtimestamp(ate, FUSO_BR):%H:%M} "
               "(proteção contra bloqueio). Volta sozinho.")
  fontes = _fontes_ativas(store)
  ok = sum(1 for c in fontes if store.feeds.get(c) and store.feeds[c].ok)
  falha = sum(1 for c in fontes if store.feeds.get(c) and not store.feeds[c].ok)
  pend = len(fontes) - ok - falha
  c1, c2 = st.columns([3, 2])
  c1.markdown(_html(f"""
    <div class="g1-meta">
      <span class="g1-chip">🗂️ {len(fontes)} fonte(s)</span>
      <span class="g1-chip ok">🟢 {ok} funcionando</span>
      <span class="g1-chip erro">🔴 {falha} com falha</span>
      <span class="g1-chip">⏳ {pend} não testada(s)</span>
    </div>"""), unsafe_allow_html=True)
  if fontes and c2.button("🔄 Testar todas as fontes", type="primary", key="btn_testar_todos"):
    with st.spinner("Testando as fontes…"):
      _testar_todos(store)
    st.rerun()


def _sub_rss(store: Store) -> None:
  with st.form("form_url", clear_on_submit=True):
    nova = st.text_input("Endereço do feed", placeholder="https://…/rss")
    if st.form_submit_button("Adicionar feed", type="primary"):
      if urlparse(nova.strip()).scheme not in ("http", "https"):
        st.error("Use um endereço completo, começando com http:// ou https://")
      else:
        ok, msg = store.adicionar_item("urls", nova)
        (st.success if ok else st.warning)("Feed adicionado." if ok else msg)
  with st.form("form_gnews", clear_on_submit=True):
    termo = st.text_input("Ou crie uma busca no Google News", placeholder="Ex.: Guararema")
    if st.form_submit_button("Criar feed da busca"):
      if termo.strip():
        url = (f"https://news.google.com/rss/search?q={quote_plus(termo.strip())}"
               "+when:1d&hl=pt-BR&gl=BR&ceid=BR:pt-419")
        ok, msg = store.adicionar_item("urls", url)
        (st.success if ok else st.warning)("Feed criado." if ok else msg)
  if not store.data["urls"]:
    st.info("Nenhum feed RSS cadastrado.")
  for url in list(store.data["urls"]):
    _cartao_fonte(store, url, rotulo_feed(url), url, (store.remover_item, "urls", url))


def _sub_x(store: Store) -> None:
  x1, x2 = st.columns(2)
  with x1:
    with st.form("form_x", clear_on_submit=True):
      novo = st.text_input("Novo perfil do X", placeholder="Ex.: BombeirosPMESP ou link do perfil")
      if st.form_submit_button("Adicionar perfil", type="primary"):
        usuario = limpar_usuario_x(novo)
        if not USUARIO_X.match(usuario):
          st.error("Nome de usuário inválido. Use até 15 letras, números ou _.")
        else:
          ok, msg = store.adicionar_item("perfis_x", usuario)
          (st.success if ok else st.warning)(msg)
  with x2:
    with st.form("form_nitter", clear_on_submit=True):
      nova = st.text_input("Nova instância Nitter", placeholder="https://nitter.exemplo.com",
                           help="Testadas em ordem. Se uma cair, a próxima assume. Instâncias "
                                "públicas mudam com frequência: troque as que pararem de responder.")
      if st.form_submit_button("Adicionar instância"):
        if urlparse(nova.strip()).scheme not in ("http", "https"):
          st.error("Use um endereço completo, começando com http:// ou https://")
        else:
          ok, msg = store.adicionar_item("instancias_nitter", nova.strip().rstrip("/"))
          (st.success if ok else st.warning)(msg)
    for i, base in enumerate(list(store.data["instancias_nitter"])):
      a, b = st.columns([5, 1])
      a.write(f"{i + 1}. {urlparse(base).netloc}")
      b.button("✕", key=f"del_n_{i}", help="Remover esta instância",
               on_click=store.remover_item, args=("instancias_nitter", base))
  if not store.data["perfis_x"]:
    st.info("Nenhum perfil do X cadastrado.")
  ordem = "\n".join(f"{b.rstrip('/')}/{{perfil}}/rss" for b in store.data["instancias_nitter"])
  for usuario in list(store.data["perfis_x"]):
    _cartao_fonte(store, f"x:{usuario}", f"@{usuario}",
                  ordem.replace("{perfil}", usuario) or "Nenhuma instância Nitter cadastrada.",
                  (store.remover_item, "perfis_x", usuario))


def _sub_instagram(store: Store) -> None:
  st.caption(
      "O Instagram bloqueia leitura anônima com frequência. O painel lê com cabeçalhos de navegador, "
      "espaça as consultas (no máximo uma a cada 10 min por perfil) e pausa 15 min sozinho se for "
      "bloqueado. A forma mais estável é informar o cookie de sessão de uma conta secundária, abaixo."
  )
  with st.form("form_ig", clear_on_submit=True):
    novo = st.text_input("Novo perfil do Instagram", placeholder="Ex.: diariodesuzano ou link do perfil")
    if st.form_submit_button("Adicionar perfil", type="primary"):
      usuario = limpar_usuario_instagram(novo)
      if not USUARIO_IG.match(usuario):
        st.error("Nome de usuário inválido. Use letras, números, ponto ou _.")
      else:
        ok, msg = store.adicionar_item("perfis_instagram", usuario)
        (st.success if ok else st.warning)(msg)
  if not store.data["perfis_instagram"]:
    st.info("Nenhum perfil do Instagram cadastrado.")
  for usuario in list(store.data["perfis_instagram"]):
    _cartao_fonte(store, f"ig:{usuario}", f"@{usuario}", f"https://www.instagram.com/{usuario}/",
                  (store.remover_item, "perfis_instagram", usuario))
  with st.expander("🔐 Estabilidade: cookie de sessão e pontes RSS"):
    with st.form("form_ig_sessao"):
      sessao = st.text_input(
          "Cookie “sessionid” (opcional)", value=store.data.get("instagram_sessionid", ""),
          type="password",
          help="No navegador logado: F12 → Aplicativo (Application) → Cookies → instagram.com → "
               "copie o valor de sessionid. Use uma conta secundária: o Instagram pode restringir "
               "contas usadas em automação. O cookie expira e precisa ser renovado de tempos em tempos.")
      if st.form_submit_button("Salvar cookie"):
        with store.lock:
          store.data["instagram_sessionid"] = sessao.strip()
          store.salvar()
        st.success("Cookie salvo. Clique em “Testar” em um perfil para validar.")
    st.caption("O cookie fica no arquivo dados_monitor_g1.json. Não compartilhe esse arquivo.")
    with st.form("form_ponte_ig", clear_on_submit=True):
      nova = st.text_input("Nova ponte RSS (reserva)", placeholder="https://seu-rsshub/instagram/user/{perfil}",
                           help="Usada se o acesso direto falhar. Use {perfil} no lugar do nome do perfil.")
      if st.form_submit_button("Adicionar ponte"):
        if urlparse(nova.strip()).scheme not in ("http", "https") or "{perfil}" not in nova:
          st.error("Use um endereço completo (http/https) contendo {perfil}.")
        else:
          ok, msg = store.adicionar_item("bridges_instagram", nova.strip())
          (st.success if ok else st.warning)(msg)
    for i, modelo in enumerate(list(store.data["bridges_instagram"])):
      a, b = st.columns([5, 1])
      a.write(f"{i + 1}. {urlparse(modelo).netloc}")
      b.button("✕", key=f"del_bi_{i}", help="Remover esta ponte",
               on_click=store.remover_item, args=("bridges_instagram", modelo))


def _sub_paginas(store: Store) -> None:
  st.caption(
      "Acompanhe páginas que não têm RSS (como a sala de imprensa da Sabesp) e canais públicos do "
      "Telegram (t.me/nomedocanal). Em páginas comuns, o painel lê as manchetes (links com pelo menos "
      "4 palavras). Na primeira leitura ele só registra o que já está publicado e passa a avisar "
      "apenas do que for novo."
  )
  with st.form("form_pagina", clear_on_submit=True):
    c1, c2 = st.columns([1, 2])
    nome = c1.text_input("Nome", placeholder="Ex.: Sabesp, notícias")
    url = c2.text_input("Endereço da página ou do canal", placeholder="https://… ou https://t.me/nomedocanal")
    st.caption("Só gera alerta se o texto citar uma cidade, rua ou rodovia cadastradas.")
    with st.expander("Opções avançadas"):
      seletor = st.text_input("Seletor CSS (opcional)", placeholder="Ex.: main article, .lista-noticias",
                              help="Restringe a leitura a uma parte da página. Útil para ignorar menus e rodapé.")
    if st.form_submit_button("Adicionar página", type="primary"):
      if urlparse(url.strip()).scheme not in ("http", "https"):
        st.error("Use um endereço completo, começando com http:// ou https://")
      else:
        ok, msg = store.adicionar_pagina(nome, url, seletor)
        (st.success if ok else st.warning)(msg)
  if not store.data["paginas"]:
    st.info("Nenhuma página cadastrada.")
  for cfg in list(store.data["paginas"]):
    nota = ("seletor: " + cfg["seletor"] + " · " if cfg.get("seletor") else "") + (
        "linha de base registrada" if cfg.get("baseline_feito") else "aguardando a 1ª varredura")
    _cartao_fonte(store, f"pg:{cfg['url']}", cfg["nome"], f"{cfg['url']}\n({nota})",
                  (store.remover_pagina, cfg["url"]))


def _sub_locais(store: Store) -> None:
  c1, c2 = st.columns([1, 2])
  with c1:
    st.subheader("🏙️ Cidades")
    with st.form("form_cidade", clear_on_submit=True):
      nova = st.text_input("Nova cidade", placeholder="Ex.: Poá")
      if st.form_submit_button("Adicionar", type="primary"):
        ok, msg = store.adicionar_item("cidades", nova)
        (st.success if ok else st.warning)(msg)
    for i, cidade in enumerate(list(store.data["cidades"])):
      a, b = st.columns([5, 1])
      a.write(cidade)
      b.button("✕", key=f"del_c_{i}", help=f"Remover {cidade}",
               on_click=store.remover_item, args=("cidades", cidade))
  with c2:
    st.subheader("🛣️ Ruas, bairros e rodovias")
    st.caption(
        "Um nome por linha. Todo conteúdo só é aceito se citar explicitamente uma cidade cadastrada "
        "ou um destes nomes (útil para os Bombeiros, que citam a rua em vez da cidade). Remova nomes "
        "que existam em outras cidades, como “Avenida Brasil” ou “Sete de Setembro”, para evitar "
        "falsos alertas. Pode incluir bairros."
    )
    with st.form("form_locais"):
      a, b = st.columns(2)
      ruas = a.text_area("Ruas, avenidas e bairros", value="\n".join(store.data["logradouros"]), height=300)
      rodovias = b.text_area("Rodovias e estradas", value="\n".join(store.data["rodovias"]), height=300)
      fora = st.text_area(
          "Cidades de fora (descartam posts que citam só rua/rodovia)",
          value="\n".join(store.data["cidades_excluidas"]), height=120)
      if st.form_submit_button("Salvar listas", type="primary"):
        with store.lock:
          store.data["logradouros"] = _linhas(ruas)
          store.data["rodovias"] = _linhas(rodovias)
          store.data["cidades_excluidas"] = _linhas(fora)
          store.salvar()
        st.success(f"Salvo: {len(store.data['logradouros'])} ruas/bairros e {len(store.data['rodovias'])} rodovias.")


def aba_fontes(store: Store) -> None:
  """Tudo sobre fontes num só lugar: cadastro, status ao vivo e base geográfica."""
  _resumo_fontes(store)
  t_rss, t_x, t_ig, t_pg, t_loc = st.tabs([
      f"🔗 Feeds RSS ({len(store.data['urls'])})",
      f"𝕏 X ({len(store.data['perfis_x'])})",
      f"📸 Instagram ({len(store.data['perfis_instagram'])})",
      f"🌐 Páginas e canais ({len(store.data['paginas'])})",
      "🏙️ Cidades e locais",
  ])
  with t_rss:
    _sub_rss(store)
  with t_x:
    _sub_x(store)
  with t_ig:
    _sub_instagram(store)
  with t_pg:
    _sub_paginas(store)
  with t_loc:
    _sub_locais(store)


def _salvar_automacao() -> None:
  store = obter_store()
  with store.lock:
    store.data["automacao_ativa"] = bool(st.session_state.get("tgl_auto"))
    store.data["intervalo_auto"] = int(st.session_state.get("sld_intervalo", 5))
    store.salvar()


def _status_automacao_corpo() -> None:
  auto = obter_automacao()
  if not auto.ativo:
    st.info("A varredura automática está desligada.")
    return
  proxima = auto.proxima or 0
  falta = max(0, int(proxima - time.time()))
  st.success(f"Ativa: a cada {auto.store.data['intervalo_auto']} min. "
             f"Próxima varredura em {falta // 60} min {falta % 60:02d} s.")
  resumo = auto.ultimo_resumo
  if resumo:
    st.caption(f"Última: {resumo.quando:%H:%M:%S}, {resumo.novos} novo(s), "
               f"{resumo.feeds_ok}/{resumo.feeds_total} feeds ok"
               + (f", {len(resumo.erros)} falha(s)" if resumo.erros else ""))


def aba_telegram(store: Store, auto: Automacao) -> None:
  col_tg, col_auto = st.columns(2)

  with col_tg:
    st.subheader("📲 Bot do Telegram")
    with st.form("form_telegram"):
      token = st.text_input("Token do bot", value=store.data["telegram_token"], type="password")
      chat = st.text_input("Chat ID", value=store.data["telegram_chat_id"])
      preview = st.checkbox(
          "Mostrar pré-visualização (cartão) do link nas mensagens",
          value=bool(store.data.get("telegram_preview")),
          help="Desligado, a mensagem fica enxuta: só título, resumo, local e o link oculto.")
      if st.form_submit_button("Salvar configurações", type="primary"):
        with store.lock:
          store.data["telegram_token"] = token.strip()
          store.data["telegram_chat_id"] = chat.strip()
          store.data["telegram_preview"] = bool(preview)
          store.salvar()
        st.success("Configurações salvas.")
    if st.button("Enviar mensagem de teste", key="btn_teste_tg"):
      ok, msg = enviar_telegram(
          store.data["telegram_token"], store.data["telegram_chat_id"],
          "✅ <b>Central de Plantão g1 Alto Tietê</b>\nConexão com o Telegram funcionando.",
      )
      (st.success if ok else st.error)("Mensagem de teste enviada." if ok else f"Não enviado: {msg}")
    st.caption("O token fica no arquivo dados_monitor_g1.json. Não compartilhe esse arquivo.")

  with col_auto:
    st.subheader("🔄 Varredura automática")
    st.toggle("Ativar varredura em segundo plano", value=store.data["automacao_ativa"],
              key="tgl_auto", on_change=_salvar_automacao)
    st.slider("Intervalo entre varreduras (minutos)", 1, 60,
              value=int(store.data["intervalo_auto"]), key="sld_intervalo",
              on_change=_salvar_automacao)
    st.fragment(_status_automacao_corpo, run_every="5s")()
    if st.button("▶️ Executar uma varredura agora", key="btn_exec_auto"):
      with st.spinner("Varrendo…"):
        _mostrar_resumo(auto.executar())

  st.divider()
  with st.popover("⏻ Encerrar aplicativo"):
    st.caption("Para o servidor e a varredura automática. Para voltar, abra o aplicativo de novo.")
    if st.button("Encerrar agora", key="btn_encerrar"):
      os._exit(0)


def main() -> None:
  store = obter_store()
  auto = obter_automacao()
  st.markdown(f"<style>{_css(tema_atual())}</style>", unsafe_allow_html=True)
  cabecalho(auto)

  t1, t2, t3 = st.tabs([
      "📡 Feed em tempo real",
      "🗂️ Fontes",
      "📲 Telegram & automação",
  ])
  with t1:
    aba_feed(store, auto)
  with t2:
    aba_fontes(store)
  with t3:
    aba_telegram(store, auto)


main()
