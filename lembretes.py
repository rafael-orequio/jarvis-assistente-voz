"""Lembretes, timers e avisos de prazo. Ficam em vault/lembretes.md (texto simples, editável à mão)."""
import datetime as dt
import hashlib
import json
import os
import re
import threading
import unicodedata
import uuid

import tarefas

FMT = "%Y-%m-%d %H:%M:%S"
HORA_AVISO = os.getenv("JARVIS_AVISO_PRAZOS", "09:00").strip()  # HH:MM; vazio ou "off" desliga
_trava = threading.Lock()
_ultimo_aviso = None  # data (texto) do último aviso de prazos, guardada também em vault/avisos.json


def _arq():
    return tarefas.VAULT / "lembretes.md"


def _estado():
    return tarefas.VAULT / "avisos.json"


def inicializar():
    tarefas.VAULT.mkdir(parents=True, exist_ok=True)
    if not _arq().exists():
        _arq().write_text("# Lembretes\n\n", encoding="utf-8")


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _limpa(s: str) -> str:
    return " ".join(s.replace("|", "-").split())


def _quando(txt: str):
    for f in (FMT, "%Y-%m-%d %H:%M"):
        try:
            return dt.datetime.strptime(txt, f)
        except ValueError:
            pass
    return None


def _duracao(seg: int) -> str:
    h, r = divmod(seg, 3600)
    m, s = divmod(r, 60)
    partes = []
    if h:
        partes.append(f"{h} hora{'s' if h > 1 else ''}")
    if m:
        partes.append(f"{m} minuto{'s' if m > 1 else ''}")
    if s:
        partes.append(f"{s} segundo{'s' if s > 1 else ''}")
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]


# ---------- arquivo ----------
def _ler() -> list:
    if not _arq().exists():
        return []
    itens = []
    for linha in _arq().read_text(encoding="utf-8").splitlines():
        m = re.match(r"^- \[( |x)\] (\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?) \| (.*)$", linha)
        quando = _quando(m.group(2)) if m else None
        if not quando:
            continue
        partes = [p.strip() for p in m.group(3).split(" | ")]
        it = {"feito": m.group(1) == "x", "quando": quando, "texto": partes[0], "tipo": "lembrete", "id": ""}
        for p in partes[1:]:
            if ": " in p:
                k, v = p.split(": ", 1)
                it[_norm(k).strip()] = v.strip()
        if not it["id"]:  # linha escrita à mão: cria um id estável
            it["id"] = hashlib.md5(f"{quando}{it['texto']}".encode()).hexdigest()[:8]
        itens.append(it)
    return itens


def _salvar(itens: list):
    linhas = ["# Lembretes", ""]
    for it in itens:
        extras = [f"tipo: {it['tipo']}", f"id: {it['id']}"]
        for k in ("criado", "disparado"):
            if it.get(k):
                extras.append(f"{k}: {it[k]}")
        linhas.append(f"- [{'x' if it['feito'] else ' '}] {it['quando']:{FMT}} | " + " | ".join([it["texto"]] + extras))
    _arq().write_text("\n".join(linhas) + "\n", encoding="utf-8")


def _adicionar(texto: str, quando: dt.datetime, tipo: str):
    agora = dt.datetime.now().replace(microsecond=0)
    with _trava:
        itens = _ler()
        for it in itens:  # evita duplicar um pedido repetido (por exemplo, numa nova tentativa do modelo reserva)
            if (not it["feito"] and it["tipo"] == tipo and _norm(it["texto"]) == _norm(texto)
                    and abs((it["quando"] - quando).total_seconds()) < 90):
                return it, False
        novo = {"feito": False, "quando": quando, "texto": texto, "tipo": tipo,
                "id": uuid.uuid4().hex[:8], "criado": agora.strftime(FMT)}
        itens.append(novo)
        itens.sort(key=lambda i: i["quando"])
        _salvar(itens)
    return novo, True


# ---------- o que o vigia usa ----------
def _falado(it: dict, agora: dt.datetime) -> str:
    if it["tipo"] == "timer":
        return it["texto"]
    texto = f"Senhor, lembrete: {it['texto']}."
    if (agora - it["quando"]).total_seconds() > 120:  # ficou pendente (computador desligado ou sem aba aberta)
        dia = "" if it["quando"].date() == agora.date() else f" de {it['quando']:%d/%m}"
        texto += f" Era para as {it['quando']:%H:%M}{dia}."
    return texto


def vencidos(agora=None) -> list:
    agora = agora or dt.datetime.now()
    with _trava:
        return [dict(it, falado=_falado(it, agora)) for it in _ler() if not it["feito"] and it["quando"] <= agora]


def marcar_disparado(id_: str):
    with _trava:
        itens = _ler()
        for it in itens:
            if it["id"] == id_:
                it["feito"], it["disparado"] = True, dt.datetime.now().strftime(FMT)
        _salvar(itens)


def proximos(n: int = 4) -> list:
    """Próximos lembretes pendentes, para o painel do HUD."""
    with _trava:
        pend = sorted((i for i in _ler() if not i["feito"]), key=lambda i: i["quando"])
    return [{"texto": i["texto"], "tipo": i["tipo"], "quando_ms": int(i["quando"].timestamp() * 1000)} for i in pend[:n]]


def som():
    """Sem aba aberta, pelo menos toca um som (desligue com JARVIS_ALERTA_SOM=0)."""
    if os.getenv("JARVIS_ALERTA_SOM", "1") == "0":
        return

    def tocar():
        try:
            import winsound
            for freq in (880, 1100, 880):
                winsound.Beep(freq, 180)
        except Exception:
            pass
    threading.Thread(target=tocar, daemon=True).start()


# ---------- aviso diário de prazos ----------
def _lista(ts: list) -> str:
    ts = list(dict.fromkeys(ts))  # títulos repetidos aparecem uma vez só
    return ", ".join(ts[:3]) + (f" e mais {len(ts) - 3}" if len(ts) > 3 else "")


def _montar_aviso(p: dict):
    if not (p["atrasadas"] or p["hoje"] or p["amanha"]):
        return None
    partes = ["Senhor, atenção aos prazos."]
    if p["atrasadas"]:
        partes.append(f"Atrasadas: {_lista(p['atrasadas'])}.")
    if p["hoje"]:
        partes.append(f"Para hoje: {_lista(p['hoje'])}.")
    if p["amanha"]:
        partes.append(f"Para amanhã: {_lista(p['amanha'])}.")
    return " ".join(partes)


def aviso_de_prazos(agora=None):
    """Devolve o texto do aviso de prazos uma vez por dia, a partir da hora configurada (ou None)."""
    global _ultimo_aviso
    if HORA_AVISO.lower() in ("", "off", "0"):
        return None
    try:
        hora = dt.datetime.strptime(HORA_AVISO, "%H:%M").time()
    except ValueError:
        return None
    agora = agora or dt.datetime.now()
    hoje = agora.date().isoformat()
    if _ultimo_aviso is None:
        try:
            _ultimo_aviso = json.loads(_estado().read_text(encoding="utf-8")).get("prazos", "")
        except Exception:
            _ultimo_aviso = ""
    if _ultimo_aviso == hoje or agora.time() < hora or agora.hour >= 22:
        return None
    _ultimo_aviso = hoje
    try:
        _estado().write_text(json.dumps({"prazos": hoje}), encoding="utf-8")
    except Exception:
        pass
    return _montar_aviso(tarefas.prazos_do_dia(agora.date()))


# ---------- ferramentas que o Gemini pode chamar ----------
def criar_ferramentas(coletados: list) -> list:
    def registra(texto: str) -> dict:
        print(f"[lembretes] {texto}")
        coletados.append(("acao", {"texto": texto}))
        return {"ok": True, "feito": texto}

    def criar_lembrete(texto: str, em_minutos: int = 0, quando: str = "") -> dict:
        """Cria um lembrete que o JARVIS fala sozinho na hora marcada. Para 'daqui a X minutos' use em_minutos
        (converta horas em minutos). Para um horário específico, use quando no formato AAAA-MM-DDTHH:MM, horário
        local, convertendo 'amanhã às 9h' ou 'sexta às 15h' a partir da data e da hora de agora. O texto diz
        o que lembrar (por exemplo, 'beber água')."""
        agora = dt.datetime.now().replace(microsecond=0)
        if em_minutos and em_minutos > 0:
            due = agora + dt.timedelta(minutes=em_minutos)
        elif quando:
            try:
                due = dt.datetime.fromisoformat(quando.strip().replace(" ", "T")).replace(tzinfo=None)
            except ValueError:
                return {"erro": "horário inválido; use AAAA-MM-DDTHH:MM"}
        else:
            return {"erro": "informe em_minutos ou quando"}
        if due <= agora:
            return {"erro": "esse horário já passou"}
        if due > agora + dt.timedelta(days=366):
            return {"erro": "o horário está longe demais (máximo de 1 ano)"}
        item, novo = _adicionar(_limpa(texto), due, "lembrete")
        if not novo:
            return {"ok": True, "observacao": "esse lembrete já existia", "quando": f"{item['quando']:%d/%m às %H:%M}"}
        return registra(f"Lembrete para {due:%d/%m às %H:%M}: {item['texto']}")

    def criar_timer(minutos: int = 0, segundos: int = 0, nome: str = "") -> dict:
        """Cria um timer (contagem regressiva). Informe minutos e/ou segundos; nome é opcional (por exemplo, 'macarrão').
        Máximo de 24 horas."""
        total = max(0, minutos) * 60 + max(0, segundos)
        if total <= 0:
            return {"erro": "informe a duração do timer"}
        if total > 24 * 3600:
            return {"erro": "o máximo é de 24 horas"}
        due = dt.datetime.now().replace(microsecond=0) + dt.timedelta(seconds=total)
        nome = _limpa(nome)
        texto = f"O timer de {nome} terminou." if nome else f"O timer de {_duracao(total)} terminou."
        item, novo = _adicionar(texto, due, "timer")
        if not novo:
            return {"ok": True, "observacao": "esse timer já existia"}
        return registra(f"Timer de {_duracao(total)}{(' (' + nome + ')') if nome else ''} começou")

    def listar_lembretes() -> dict:
        """Lista os lembretes e timers pendentes."""
        agora = dt.datetime.now()
        with _trava:
            pend = sorted((i for i in _ler() if not i["feito"]), key=lambda i: i["quando"])
        lista = [{"texto": i["texto"], "tipo": i["tipo"], "quando": f"{i['quando']:%d/%m às %H:%M}",
                  "faltam": _duracao(max(1, int((i["quando"] - agora).total_seconds()))) if i["quando"] > agora else "vencido"}
                 for i in pend]
        coletados.append(("tarefas", {"titulo": "lembretes", "itens": [
            {"titulo": i["texto"], "prazo": i["quando"], "situacao": "futura"} for i in lista]}))
        return {"total": len(lista), "lembretes": lista}

    def cancelar_lembrete(trecho_do_texto: str) -> dict:
        """Cancela o lembrete ou timer pendente cujo texto contém as palavras informadas."""
        palavras = _norm(trecho_do_texto).split()
        with _trava:
            itens = _ler()
            achados = [i for i in itens if not i["feito"] and all(p in _norm(i["texto"]) for p in palavras)]
            if not achados:
                return {"erro": "nenhum lembrete pendente combina", "pendentes": [i["texto"] for i in itens if not i["feito"]][:10]}
            if len(achados) > 1:
                return {"erro": "mais de um combina; peça ao usuário para especificar", "opcoes": [i["texto"] for i in achados]}
            itens.remove(achados[0])
            _salvar(itens)
        return registra(f"Cancelado: {achados[0]['texto']}")

    return [criar_lembrete, criar_timer, listar_lembretes, cancelar_lembrete]
