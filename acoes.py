"""Ações que o JARVIS pode fazer no PC. Só existe o que está listado aqui: não há comando livre,
nada de apagar, fechar ou desligar. Sites e pastas vêm de listas fixas; só a busca usa texto do usuário."""
import ctypes
import os
import pathlib
import platform
import psutil
import shutil
import subprocess
import time
import unicodedata
import webbrowser
from urllib.parse import quote_plus

PASTA_PROJETO = pathlib.Path(__file__).parent
NO_WINDOWS = platform.system() == "Windows"

SITES = {  # nome -> (como falar, endereço)
    "youtube": ("YouTube", "https://www.youtube.com"),
    "claude": ("Claude", "https://claude.ai"),
    "gemini": ("Gemini", "https://gemini.google.com"),
    "chatgpt": ("ChatGPT", "https://chatgpt.com"),
    "netflix": ("Netflix", "https://www.netflix.com"),
    "calendario": ("Calendário", "https://calendar.google.com"),
}
PASTAS = {  # nome -> endereço de pasta do Windows (funciona mesmo com OneDrive)
    "downloads": "shell:Downloads", "documentos": "shell:Personal", "area de trabalho": "shell:Desktop",
    "imagens": "shell:My Pictures", "videos": "shell:My Video", "musicas": "shell:My Music",
}
APELIDOS = {
    "vs code": "vscode", "vscode": "vscode", "visual studio code": "vscode", "code": "vscode",
    "spotify": "spotify", "calculadora": "calculadora", "calc": "calculadora",
    "calendario": "calendario", "agenda": "calendario", "google agenda": "calendario",
    "youtube": "youtube", "you tube": "youtube", "claude": "claude", "gemini": "gemini",
    "chatgpt": "chatgpt", "chat gpt": "chatgpt", "gpt": "chatgpt", "netflix": "netflix",
    "pastas": "pastas", "explorador": "pastas", "explorador de arquivos": "pastas",
}
TECLAS = {"volume_mais": 0xAF, "volume_menos": 0xAE, "mudo": 0xAD, "play_pause": 0xB3, "proxima": 0xB0, "anterior": 0xB1}
FECHAVEIS = {  # só o que não tem trabalho a perder (o VS Code fica de fora: pode ter arquivo não salvo)
    "spotify": ["Spotify.exe"],
    "calculadora": ["CalculatorApp.exe", "Calculator.exe", "win32calc.exe"],
}
_recentes: dict = {}
_pendentes: dict = {}  # fechamentos esperando o "sim" do usuário


def _norm(s: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn").split())


def _repetido(chave: str, janela: float = 8.0) -> bool:
    """Ignora a mesma ação repetida em poucos segundos (por exemplo, numa nova tentativa do modelo reserva)."""
    agora = time.time()
    if agora - _recentes.get(chave, 0) < janela:
        return True
    _recentes[chave] = agora
    return False


def _tecla(nome: str, vezes: int = 1):
    for _ in range(vezes):
        ctypes.windll.user32.keybd_event(TECLAS[nome], 0, 0, 0)  # aperta
        ctypes.windll.user32.keybd_event(TECLAS[nome], 0, 2, 0)  # solta
        time.sleep(0.02)


def _abrir_vscode() -> bool:
    exe = shutil.which("code") or str(pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Microsoft VS Code/Code.exe")
    try:
        if exe.lower().endswith((".cmd", "code")) and shutil.which("code"):
            subprocess.Popen(["cmd", "/c", "code"], creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.startfile(exe)
        return True
    except Exception:
        return False


def criar_ferramentas(coletados: list, turno: int = 0) -> list:
    """Ferramentas de PC que o Gemini pode chamar. 'turno' conta as mensagens do usuário (usado na confirmação)."""

    def registra(texto: str) -> dict:
        print(f"[pc] {texto}")
        coletados.append(("acao", {"texto": texto}))
        return {"ok": True, "feito": texto}

    def abrir_programa(nome: str) -> dict:
        """Abre um programa ou site da lista permitida: Visual Studio Code, Spotify, Calculadora, Calendário,
        YouTube, Claude, Gemini, ChatGPT, Netflix ou o Explorador de Arquivos (pastas). Os sites abrem em nova
        aba do navegador."""
        chave = APELIDOS.get(_norm(nome))
        if not chave:
            return {"erro": "programa não permitido", "disponiveis": ["Visual Studio Code", "Spotify", "Calculadora",
                    "Calendário", "YouTube", "Claude", "Gemini", "ChatGPT", "Netflix", "Pastas"]}
        if _repetido("abrir:" + chave):
            return {"ok": True, "observacao": "já foi aberto agora há pouco"}
        try:
            if chave in SITES:
                webbrowser.open(SITES[chave][1])
                return registra(f"Abrindo {SITES[chave][0]}")
            if not NO_WINDOWS:
                return {"erro": "disponível só no Windows"}
            if chave == "vscode":
                return registra("Abrindo o Visual Studio Code") if _abrir_vscode() else {"erro": "não encontrei o VS Code"}
            if chave == "spotify":
                try:
                    os.startfile("spotify:")
                except Exception:
                    webbrowser.open("https://open.spotify.com")
                return registra("Abrindo o Spotify")
            if chave == "calculadora":
                subprocess.Popen(["calc.exe"])
                return registra("Abrindo a Calculadora")
            subprocess.Popen(["explorer.exe"])
            return registra("Abrindo o Explorador de Arquivos")
        except Exception as e:
            return {"erro": f"não consegui abrir: {e}"}

    def fechar_programa(nome: str) -> dict:
        """Fecha o Spotify ou a Calculadora. Exige confirmação do usuário: na primeira chamada a ferramenta só
        registra o pedido e responde 'precisa_confirmar'; então pergunte em voz se ele quer mesmo fechar e espere a
        resposta. Só chame de novo depois que o usuário disser sim, em uma nova mensagem. O VS Code e os sites
        (YouTube, Netflix etc.) não podem ser fechados por aqui."""
        chave = APELIDOS.get(_norm(nome))
        if chave not in FECHAVEIS:
            return {"erro": "só consigo fechar o Spotify e a Calculadora; o VS Code pode ter trabalho não salvo "
                            "e os sites ficam no navegador"}
        pedido = _pendentes.get(chave)
        if not pedido or pedido["turno"] >= turno or time.time() - pedido["t"] > 60:
            _pendentes[chave] = {"turno": turno, "t": time.time()}
            print(f"[pc] fechar {chave}: aguardando confirmação")
            return {"precisa_confirmar": True,
                    "instrucao": f"Pergunte ao usuário se quer mesmo fechar o {nome}. Não chame esta ferramenta "
                                 "de novo até ele responder."}
        del _pendentes[chave]  # confirmado numa mensagem posterior à do pedido
        if not NO_WINDOWS:
            return {"erro": "disponível só no Windows"}
        alvos = {n.lower() for n in FECHAVEIS[chave]}
        if not any((p.info["name"] or "").lower() in alvos for p in psutil.process_iter(["name"])):
            return {"erro": "esse programa não está aberto"}
        for exe in FECHAVEIS[chave]:
            subprocess.run(["taskkill", "/F", "/IM", exe], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return registra(f"Fechando {nome}")

    def abrir_pasta(nome: str) -> dict:
        """Abre uma pasta no Explorador: downloads, documentos, área de trabalho, imagens, vídeos, músicas
        ou 'projeto' (a pasta do JARVIS)."""
        n = _norm(nome)
        if not NO_WINDOWS:
            return {"erro": "disponível só no Windows"}
        try:
            if n in ("projeto", "projeto jarvis", "jarvis"):
                os.startfile(PASTA_PROJETO)
            elif n in PASTAS:
                subprocess.Popen(["explorer.exe", PASTAS[n]])
            else:
                return {"erro": "pasta não permitida", "disponiveis": list(PASTAS) + ["projeto"]}
        except Exception as e:
            return {"erro": f"não consegui abrir: {e}"}
        return registra(f"Abrindo a pasta {nome}")

    def pesquisar_na_web(consulta: str) -> dict:
        """Pesquisa no Google, em nova aba do navegador."""
        if _repetido("busca:" + _norm(consulta)):
            return {"ok": True, "observacao": "a busca já foi aberta"}
        webbrowser.open("https://www.google.com/search?q=" + quote_plus(consulta.strip()[:200]))
        return registra(f"Pesquisando no Google: {consulta.strip()[:60]}")

    def pesquisar_no_youtube(consulta: str) -> dict:
        """Pesquisa no YouTube, em nova aba do navegador."""
        if _repetido("yt:" + _norm(consulta)):
            return {"ok": True, "observacao": "a busca já foi aberta"}
        webbrowser.open("https://www.youtube.com/results?search_query=" + quote_plus(consulta.strip()[:200]))
        return registra(f"Pesquisando no YouTube: {consulta.strip()[:60]}")

    def controlar_volume(acao: str, quantidade: int = 5) -> dict:
        """Controla o volume do Windows. Ações: 'aumentar', 'diminuir' ou 'silenciar' (liga/desliga o mudo).
        Cada unidade de quantidade muda cerca de 2% (padrão 5, máximo 25)."""
        if not NO_WINDOWS:
            return {"erro": "disponível só no Windows"}
        a, q = _norm(acao), max(1, min(25, int(quantidade)))
        if a.startswith("aument"):
            _tecla("volume_mais", q)
        elif a.startswith("diminu") or a.startswith("abaix"):
            _tecla("volume_menos", q)
        elif a.startswith("silenc") or a == "mudo":
            _tecla("mudo")
        else:
            return {"erro": "use aumentar, diminuir ou silenciar"}
        return registra(f"Volume: {a}")

    def controlar_midia(acao: str) -> dict:
        """Controla a música ou o vídeo que estiver tocando. Ações: 'pausar_ou_tocar', 'proxima' ou 'anterior'."""
        if not NO_WINDOWS:
            return {"erro": "disponível só no Windows"}
        a = _norm(acao)
        if a.startswith(("paus", "toc", "play", "retom")):
            _tecla("play_pause")
        elif a.startswith(("prox", "avanc")):
            _tecla("proxima")
        elif a.startswith(("anter", "volt")):
            _tecla("anterior")
        else:
            return {"erro": "use pausar_ou_tocar, proxima ou anterior"}
        return registra(f"Mídia: {a}")

    return [abrir_programa, fechar_programa, abrir_pasta, pesquisar_na_web, pesquisar_no_youtube, controlar_volume, controlar_midia]
