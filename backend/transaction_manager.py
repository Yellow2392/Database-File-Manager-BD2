import threading
import time
from datetime import datetime

class TransactionManager:
    def __init__(self, executor):
        self.executor = executor
        self.record_locks = {}
        self._manager_lock = threading.Lock()
        self.log = []

    def _log(self, tx_id, msg, status):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        linea = f"[{timestamp}] [TX-{tx_id}] {msg.ljust(35)} | {status}"
        self.log.append(linea)
        print(linea)

    def _get_lock(self, tx_id, key):
        self._log(tx_id, f"Solicitando Lock para ID {key}", "WAITING")
        with self._manager_lock:
            if key not in self.record_locks:
                self.record_locks[key] = threading.Lock()
        
        lock = self.record_locks[key]
        if not lock.acquire(blocking=False):
            self._log(tx_id, f"Conflicto en ID {key}", "CONFLICT (Esperando...)")
            lock.acquire()
        self._log(tx_id, f"Lock adquirido en ID {key}", "LOCKED")

    def _release_lock(self, tx_id, key):
        if key in self.record_locks:
            self.record_locks[key].release()
            self._log(tx_id, f"Lock liberado en ID {key}", "RELEASED")

    def _extract_keys_from_ast(self, ast):  # Espía al AST para saber qué registros se van a modificar
        keys = []
        stmt = ast.get('statement')
        
        if stmt == 'INSERT':
            # TODO: Asumimos que la PK siempre es el primer valor del INSERT
            keys.append(ast['values'][0])
        elif stmt == 'DELETE':
            keys.append(ast['condition']['key'])
        elif stmt == 'UPDATE':
            keys.append(ast['condition']['key'])
        # Los SELECT puros usualmente usan shared locks, pero para esta simplificación podemos dejarlos pasar sin bloqueo exclusivo
        
        return keys

    def execute_transaction(self, tx_id, ast_list): # Recibe una lista de ASTs (una transacción completa) y los ejecuta garantizando el aislamiento (Isolation)
        self._log(tx_id, "Iniciando Transacción", "BEGIN")
        locked_keys = []
        
        try:
            # Adquiere locks
            for ast in ast_list:
                keys = self._extract_keys_from_ast(ast)
                for k in keys:
                    if k not in locked_keys:
                        self._get_lock(tx_id, k)
                        locked_keys.append(k)

            time.sleep(0.5)

            # Delega al executor real
            for ast in ast_list:
                stmt = ast.get('statement')
                self._log(tx_id, f"Ejecutando {stmt}", "EXECUTING")
                
                self.executor.execute(ast)
                
            self._log(tx_id, "Todas las operaciones exitosas", "SUCCESS")

        except Exception as e:
            self._log(tx_id, f"Error en ejecución: {e}", "ROLLBACK")
        finally:
            # Libera locks al hacer commit
            for k in locked_keys:
                self._release_lock(tx_id, k)
            self._log(tx_id, "Transacción Finalizada", "COMMIT")