"""Tecla global: segure uma tecla em QUALQUER janela, fale e solte. Quem grava é o servidor, pelo microfone
padrão do Windows. Só observamos a tecla escolhida: nada do que você digita é lido, guardado ou enviado."""
import threading
import numpy as np

TAXA = 16000           # taxa que o Whisper espera
ATRASO = 0.15          # a tecla precisa ficar apertada por 0,15 s para valer (toques rápidos são ignorados)
FOLGA = 0.2            # continua gravando um instante depois de soltar, para não cortar a última palavra
MAX_SEG, MIN_SEG = 30, 0.5


def _base(nome: str) -> str:
    for b in ("ctrl", "alt", "shift"):
        if nome.startswith(b):
            return b
    return nome


def _bip(freq: int):
    def tocar():
        try:
            import winsound
            winsound.Beep(freq, 70)
        except Exception:
            pass
    threading.Thread(target=tocar, daemon=True).start()


class TeclaGlobal:
    def __init__(self, configuracao: str, ao_comecar, ao_terminar, ao_cancelar, bip=True, atraso=ATRASO, folga=FOLGA):
        partes = [p.strip().lower() for p in configuracao.split("+") if p.strip()]
        self.tecla, self.mods = partes[-1], set(partes[:-1])   # ex.: "ctrl_r", "f9", "ctrl+space"
        self.ao_comecar, self.ao_terminar, self.ao_cancelar = ao_comecar, ao_terminar, ao_cancelar
        self.bip, self.atraso, self.folga = bip, atraso, folga
        self.apertadas, self.gravando, self.pedacos, self.fluxo = set(), False, [], None
        self.taxa, self._timer, self._limite = TAXA, None, None
        self._trava = threading.RLock()

    # ----- eventos de teclado (chamados pelo pynput, ou pelos testes) -----
    def _combinacao_ok(self) -> bool:
        return all(any(a == m or _base(a) == m for a in self.apertadas) for m in self.mods)

    def pressionou(self, nome: str):
        with self._trava:
            self.apertadas.add(nome)
            if nome == self.tecla and self._combinacao_ok() and not self.gravando and self._timer is None:
                self._timer = threading.Timer(self.atraso, self._comecar)
                self._timer.daemon = True
                self._timer.start()

    def soltou(self, nome: str):
        with self._trava:
            self.apertadas.discard(nome)
            if nome == self.tecla or _base(nome) in self.mods:
                if self._timer:                      # soltou antes do tempo: era só um toque
                    self._timer.cancel()
                    self._timer = None
                if self.gravando:
                    t = threading.Timer(self.folga, self._terminar)
                    t.daemon = True
                    t.start()

    # ----- gravação -----
    def _cb(self, dados, frames, tempo, status):
        self.pedacos.append(dados.copy())

    def _comecar(self):
        import sounddevice as sd
        with self._trava:
            self._timer = None
            if self.gravando or self.tecla not in self.apertadas:
                return
            self.pedacos = []
            try:
                try:
                    self.taxa = TAXA
                    self.fluxo = sd.InputStream(samplerate=TAXA, channels=1, dtype="float32", callback=self._cb)
                except Exception:                    # microfone que não aceita 16 kHz: grava na taxa dele e converte depois
                    self.taxa = int(sd.query_devices(None, "input")["default_samplerate"])
                    self.fluxo = sd.InputStream(samplerate=self.taxa, channels=1, dtype="float32", callback=self._cb)
                self.fluxo.start()
            except Exception as e:
                print("[voz] não consegui abrir o microfone:", repr(e)[:200])
                self.fluxo = None
                return
            self.gravando = True
            self._limite = threading.Timer(MAX_SEG, self._terminar)
            self._limite.daemon = True
            self._limite.start()
        if self.bip:
            _bip(900)
        self.ao_comecar()

    def _terminar(self):
        with self._trava:
            if not self.gravando:
                return
            self.gravando = False
            self._limite.cancel()
            self.fluxo.stop()
            self.fluxo.close()
            self.fluxo = None
            audio = np.concatenate(self.pedacos)[:, 0] if self.pedacos else np.zeros(0, dtype="float32")
        if self.taxa != TAXA and len(audio):
            alvo = int(len(audio) * TAXA / self.taxa)
            audio = np.interp(np.linspace(0, len(audio) - 1, alvo), np.arange(len(audio)), audio).astype("float32")
        if self.bip:
            _bip(600)
        if len(audio) / TAXA >= MIN_SEG:
            self.ao_terminar(audio)
        else:
            self.ao_cancelar()

    def iniciar(self):
        from pynput import keyboard as kb

        def nome(k):
            return k.name if isinstance(k, kb.Key) else (getattr(k, "char", None) or "").lower()
        self._escuta = kb.Listener(on_press=lambda k: self.pressionou(nome(k)), on_release=lambda k: self.soltou(nome(k)))
        self._escuta.daemon = True
        self._escuta.start()
