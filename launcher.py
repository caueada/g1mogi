# -*- coding: utf-8 -*-
"""Ponto de entrada do executável: sobe o Streamlit e abre o navegador."""
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

PORTA = 8501
URL = f"http://localhost:{PORTA}"


def pasta_dados() -> Path:
  """Onde ficam JSON, log e assets: ao lado do .exe (ou do script em dev)."""
  if getattr(sys, "frozen", False):
    return Path(sys.executable).parent
  return Path(__file__).resolve().parent


def pasta_recursos() -> Path:
  """Onde o PyInstaller descompacta o app.py embutido."""
  return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def porta_em_uso(porta: int) -> bool:
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.settimeout(0.5)
    return s.connect_ex(("127.0.0.1", porta)) == 0


def abrir_navegador_quando_pronto() -> None:
  for _ in range(120):  # até ~60 s
    if porta_em_uso(PORTA):
      webbrowser.open(URL)
      return
    time.sleep(0.5)


def main() -> None:
  dados = pasta_dados()
  os.chdir(dados)
  os.environ["MONITOR_DATA_DIR"] = str(dados)

  # Sem console (--noconsole) stdout/stderr são None e o Streamlit falharia.
  if sys.stdout is None or sys.stderr is None:
    log = open(dados / "launcher.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log

  if porta_em_uso(PORTA):  # já está rodando: só abre a página
    webbrowser.open(URL)
    return

  threading.Thread(target=abrir_navegador_quando_pronto, daemon=True).start()

  from streamlit.web import bootstrap

  bootstrap.run(
      str(pasta_recursos() / "app.py"),
      False,
      [],
      {
          "server.headless": True,
          "server.address": "127.0.0.1",
          "server.port": PORTA,
          "server.fileWatcherType": "none",
          "global.developmentMode": False,  # obrigatório em app congelado
          "browser.gatherUsageStats": False,
          "theme.primaryColor": "#0669DE",
      },
  )


if __name__ == "__main__":
  main()
