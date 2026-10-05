"""Thread-safe bridge between Flask and the native desktop main loop."""
import queue
import threading
import time


class Runtime:
    def __init__(self):
        self.requests = queue.Queue(maxsize=1)
        self.lock = threading.Lock()
        self.desktop = False
        self.dialog_open = False
        self.snoozed_until = 0
        self.description = 'Popup indisponível · inicie com python app.py em uma sessão gráfica'
        self.idle_available = False
        self.context_available = False
        self.pending_idle = False
        self.error = ''
        self.shutdown_requested = threading.Event()
        self.last_answer = 0

    def request_dialog(self):
        with self.lock:
            if not self.desktop:
                raise ValueError('O popup requer uma sessão gráfica. Inicie com python app.py; no Linux, instale python3-tk se necessário.')
            if not self.requests.empty():
                return
            self.requests.put_nowait('manual')

    def snapshot(self):
        with self.lock:
            return dict(desktop=self.desktop, dialog_open=self.dialog_open,
                        description=self.description, idle_available=self.idle_available,
                        context_available=self.context_available, pending_idle=self.pending_idle,
                        snoozed=self.snoozed_until > time.time(), error=self.error,
                        snoozed_until=self.snoozed_until)
