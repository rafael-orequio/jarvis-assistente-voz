"""Tarefas e plano do dia guardados em arquivos markdown (a pasta vault/ também abre no Obsidian)."""
import datetime as dt
import pathlib
import re
import threading
import unicodedata

VAULT = pathlib.Path(__file__).parent / "vault"
ARQUIVO = VAULT / "tarefas.md"
PLANOS = VAULT / "plano-do-dia"
_trava = threading.Lock()  # as ferramentas rodam em threads; a trava evita escrever ao mesmo tempo
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]
DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


def inicializar():
    PLANOS.mkdir(parents=True, exist_ok=True)
    if not ARQUIVO.exists():
        ARQUIVO.write_text("# Tarefas\n\n", encoding="utf-8")


def data_extenso(d=None) -> str:
    d = d or dt.date.today()
    return f"{DIAS[d.weekday()]}, {d.day} de {MESES[d.month - 1]} de {d.year} (formato {d.isoformat()})"


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _limpa(s: str) -> str:
    return " ".join(s.replace("|", "-").split())


def _ler() -> list:
    if not ARQUIVO.exists():  # se o arquivo sumir, recomeça do zero em vez de dar erro
        return []
    tarefas = []
    for linha in ARQUIVO.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^- \[( |x)\] (.*)$", linha)
        if not m:
            continue
        partes = [p.strip() for p in m.group(2).split(" | ")]
        t = {"feita": m.group(1) == "x", "titulo": partes[0], "prazo": "", "materia": ""}
        for p in partes[1:]:
            if ": " in p:
                chave, valor = p.split(": ", 1)
                t[_norm(chave)] = valor
        tarefas.append(t)
    return tarefas


def _salvar(tarefas: list):
    linhas = ["# Tarefas", ""]
    for t in tarefas:
        extras = []
        if t.get("prazo"):
            extras.append(f"prazo: {t['prazo']}")
        if t.get("materia"):
            extras.append(f"matéria: {t['materia']}")
        if t.get("criada"):
            extras.append(f"criada: {t['criada']}")
        if t.get("concluida"):
            extras.append(f"concluída: {t['concluida']}")
        linhas.append(f"- [{'x' if t['feita'] else ' '}] " + " | ".join([t["titulo"]] + extras))
    ARQUIVO.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def _situacao(t: dict, hoje: dt.date) -> str:
    if not t["prazo"]:
        return "sem prazo"
    d = dt.date.fromisoformat(t["prazo"])
    return "atrasada" if d < hoje else "hoje" if d == hoje else "futura"


def _fmt(prazo: str) -> str:
    return dt.date.fromisoformat(prazo).strftime("%d/%m") if prazo else ""


def _achar(tarefas: list, trecho: str) -> list:
    palavras = _norm(trecho).split()
    return [t for t in tarefas if not t["feita"] and all(p in _norm(t["titulo"]) for p in palavras)]


def _prazo_valido(prazo: str):
    try:
        return dt.date.fromisoformat(prazo) if prazo else None
    except ValueError:
        return False


def resumo() -> dict:
    """Números e próximas tarefas para o painel do HUD."""
    hoje = dt.date.today()
    with _trava:
        pendentes = sorted((t for t in _ler() if not t["feita"]), key=lambda t: (t["prazo"] or "9999-99-99", t["titulo"]))
        arq = PLANOS / f"{hoje.isoformat()}.md"
        linhas = arq.read_text(encoding="utf-8").splitlines() if arq.exists() else []
    sit = [_situacao(t, hoje) for t in pendentes]
    return {"pendentes": len(pendentes), "atrasadas": sit.count("atrasada"), "hoje": sit.count("hoje"),
            "proximas": [{"titulo": t["titulo"], "prazo": _fmt(t["prazo"]), "situacao": s}
                         for t, s in list(zip(pendentes, sit))[:4]],
            "plano": [re.sub(r"^\d+\.\s*", "", l) for l in linhas if re.match(r"^\d+\.\s", l)]}


def criar_ferramentas(coletados: list) -> list:
    """Devolve as ferramentas de tarefas/plano que o Gemini pode chamar."""

    def adicionar_tarefa(titulo: str, prazo: str = "", materia: str = "", criar_mesmo_assim: bool = False) -> dict:
        """Adiciona uma tarefa pendente. O prazo é opcional e deve estar no formato AAAA-MM-DD
        (converta 'sexta' ou 'amanhã' usando a data de hoje). Preencha a matéria somente se o usuário a
        mencionar; caso contrário, deixe vazia. Se já houver uma tarefa pendente com o mesmo título mas
        outro prazo, a ferramenta avisa em vez de duplicar: pergunte ao usuário se quer mudar o prazo
        (alterar_prazo) ou criar outra; só use criar_mesmo_assim=True se ele confirmar."""
        if _prazo_valido(prazo) is False:
            return {"erro": "prazo inválido; use AAAA-MM-DD"}
        titulo = _limpa(titulo)
        titulo = titulo[:1].upper() + titulo[1:]  # primeira letra maiúscula
        with _trava:
            tarefas = _ler()
            for t in tarefas:
                if t["feita"] or _norm(t["titulo"]) != _norm(titulo):
                    continue
                if t["prazo"] == prazo:  # pedido repetido (por exemplo, numa nova tentativa do modelo reserva)
                    print(f"[tarefas] já existia: {t['titulo']!r}")
                    return {"ok": True, "observacao": "a tarefa já existia", "titulo": t["titulo"]}
                if not criar_mesmo_assim:
                    print(f"[tarefas] título repetido com outro prazo: {t['titulo']!r} ({t['prazo'] or 'sem prazo'})")
                    return {"ok": False, "observacao": "já existe uma tarefa pendente com esse título e outro prazo",
                            "titulo": t["titulo"], "prazo_existente": t["prazo"] or "sem prazo"}
            tarefas.append({"feita": False, "titulo": titulo, "prazo": prazo, "materia": _limpa(materia),
                            "criada": dt.date.today().isoformat()})
            _salvar(tarefas)
        print(f"[tarefas] adicionada: {titulo!r} (prazo: {prazo or 'sem prazo'}, matéria: {materia or '-'})")
        return {"ok": True, "titulo": titulo, "prazo": prazo}

    def listar_tarefas(filtro: str = "hoje") -> dict:
        """Lista tarefas pendentes. Filtros: 'hoje' (de hoje e atrasadas), 'semana' (próximos 7 dias e
        atrasadas), 'atrasadas' ou 'todas'."""
        hoje = dt.date.today()
        f = _norm(filtro)
        with _trava:
            pendentes = [t for t in _ler() if not t["feita"]]
        def sit(t): return _situacao(t, hoje)
        if f == "hoje":
            itens = [t for t in pendentes if sit(t) in ("hoje", "atrasada")]
        elif f == "semana":
            limite = hoje + dt.timedelta(days=7)
            itens = [t for t in pendentes if t["prazo"] and dt.date.fromisoformat(t["prazo"]) <= limite]
        elif f == "atrasadas":
            itens = [t for t in pendentes if sit(t) == "atrasada"]
        else:
            f, itens = "todas", pendentes
        itens.sort(key=lambda t: (t["prazo"] or "9999-99-99", t["titulo"]))
        lista = [{"titulo": t["titulo"], "prazo": t["prazo"], "materia": t["materia"], "situacao": sit(t)} for t in itens]
        coletados.append(("tarefas", {"titulo": f, "itens": [
            {"titulo": x["titulo"], "prazo": _fmt(x["prazo"]), "situacao": x["situacao"]} for x in lista]}))
        print(f"[tarefas] listadas ({f}): {len(lista)}")
        return {"filtro": f, "total": len(lista), "tarefas": lista}

    def concluir_tarefa(trecho_do_titulo: str) -> dict:
        """Marca como concluída a tarefa pendente cujo título contém as palavras informadas."""
        with _trava:
            tarefas = _ler()
            achadas = _achar(tarefas, trecho_do_titulo)
            if not achadas:
                return {"erro": "nenhuma tarefa pendente combina",
                        "pendentes": [t["titulo"] for t in tarefas if not t["feita"]][:10]}
            if len(achadas) > 1:
                return {"erro": "mais de uma tarefa combina; peça ao usuário para especificar",
                        "opcoes": [t["titulo"] for t in achadas]}
            achadas[0].update(feita=True, concluida=dt.date.today().isoformat())
            _salvar(tarefas)
        print(f"[tarefas] concluída: {achadas[0]['titulo']!r}")
        return {"ok": True, "concluida": achadas[0]["titulo"]}

    def alterar_prazo(trecho_do_titulo: str, novo_prazo: str) -> dict:
        """Muda o prazo de uma tarefa pendente. O novo prazo deve estar no formato AAAA-MM-DD."""
        if not _prazo_valido(novo_prazo):
            return {"erro": "prazo inválido; use AAAA-MM-DD"}
        with _trava:
            tarefas = _ler()
            achadas = _achar(tarefas, trecho_do_titulo)
            if len(achadas) != 1:
                return {"erro": "preciso de exatamente uma tarefa", "opcoes": [t["titulo"] for t in achadas]}
            achadas[0]["prazo"] = novo_prazo
            _salvar(tarefas)
        print(f"[tarefas] prazo alterado: {achadas[0]['titulo']!r} -> {novo_prazo}")
        return {"ok": True, "titulo": achadas[0]["titulo"], "novo_prazo": novo_prazo}

    def salvar_plano_do_dia(prioridades: list[str], observacoes: str = "") -> dict:
        """Salva o plano de hoje: as prioridades em ordem (normalmente as 3 principais) e observações.
        Deixe as observações vazias se não houver nada relevante; não escreva 'nenhuma observação'."""
        prioridades = [_limpa(p) for p in prioridades if p.strip()]
        hoje = dt.date.today()
        texto = [f"# Plano do dia — {data_extenso(hoje).split(' (')[0]}", "", "## Prioridades"]
        texto += [f"{i}. {p}" for i, p in enumerate(prioridades, 1)]
        if observacoes.strip():
            texto += ["", "## Observações", observacoes.strip()]
        with _trava:
            (PLANOS / f"{hoje.isoformat()}.md").write_text("\n".join(texto) + "\n", encoding="utf-8")
        coletados.append(("plano", {"prioridades": prioridades, "observacoes": observacoes.strip()}))
        print(f"[tarefas] plano do dia salvo: {len(prioridades)} prioridades")
        return {"ok": True, "prioridades": prioridades}

    def ler_plano_do_dia() -> dict:
        """Lê o plano de hoje, se já tiver sido salvo."""
        arq = PLANOS / f"{dt.date.today().isoformat()}.md"
        with _trava:
            if not arq.exists():
                return {"mensagem": "ainda não há plano salvo para hoje"}
            linhas = arq.read_text(encoding="utf-8").splitlines()
        prioridades = [re.sub(r"^\d+\.\s*", "", l) for l in linhas if re.match(r"^\d+\.\s", l)]
        obs = "\n".join(linhas[linhas.index("## Observações") + 1:]).strip() if "## Observações" in linhas else ""
        coletados.append(("plano", {"prioridades": prioridades, "observacoes": obs}))
        return {"prioridades": prioridades, "observacoes": obs}

    return [adicionar_tarefa, listar_tarefas, concluir_tarefa, alterar_prazo, salvar_plano_do_dia, ler_plano_do_dia]
