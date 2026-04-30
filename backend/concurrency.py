import threading
import time
import os
from datetime import datetime

class TransactionLogger:
    def __init__(self, log_file="backend/data/wal.log"):
        self.log_file = log_file
        if not os.path.exists(self.log_file):
            open(self.log_file, 'w').close()
        
        self.log_lock = threading.Lock() # Lock exclusivo para que los hilos no se pisen al escribir en el log

    def log(self, tx_id, action, resource, details=""):
        # Registramos una entrada en el seguimiento
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] [TX-{tx_id}] {action: <8} | Recurso: {resource: <15} | {details}\n"
        
        with self.log_lock:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
            print(log_entry.strip())


class LockManager:
    def __init__(self):
        self.locks = {} # Guarda un Lock por cada tabla/índice
        self.manager_lock = threading.Lock()

    def acquire_lock(self, resource_name, tx_id, logger):
        # Se intenta obtener el recurso de sección crítica
        with self.manager_lock:
            if resource_name not in self.locks:
                self.locks[resource_name] = threading.Lock()
                
        lock = self.locks[resource_name]
        
        logger.log(tx_id, "WAITING", resource_name, "Esperando bloqueo...")
        lock.acquire() # Aquí el hilo se pausa si otro hilo ya lo tiene
        logger.log(tx_id, "LOCKED", resource_name, "Bloqueo obtenido. Entrando a sección crítica.")

    def release_lock(self, resource_name, tx_id, logger):
        # Libera el bloqueo de un recurso
        if resource_name in self.locks:
            self.locks[resource_name].release()
            logger.log(tx_id, "RELEASE", resource_name, "Bloqueo liberado.")