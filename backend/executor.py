from backend.catalog import TableMetadata
from backend.storage import StorageManager
import os

class Executor:
    def __init__(self):
        self.storage_mgr = StorageManager()
        self.catalog = {}  # Memoria temporal de las tablas que existen

    def execute(self, ast):
        if ast['statement'] == 'CREATE':
            self.execute_create(ast)
        # elif ast['statement'] == 'SELECT':
        # elif ast['statement'] == 'INSERT':
        # elif ast['statement'] == 'DELETE':

    def execute_create(self, ast):
        table_name = ast['table']
        columns = ast['columns']
        file_path = ast['file']
        
        print(f"--> Ejecutando CREATE TABLE {table_name}...")
        
        # Registro de metadata
        meta = TableMetadata(table_name, columns)
        self.catalog[table_name] = meta
        
        print(f"Tamaño de registro: {meta.record_size} bytes")
        print(f"Factor de Bloque (Registros por página): {meta.block_factor}")
        
        # Ejecutar bulk_load si hay FROM FILE
        if file_path:
            # Asumiendo que el parser trajo el nombre puro, ej "data.csv"
            full_path = os.path.join("dataset", file_path)
            
            if os.path.exists(full_path):
                print(f"Iniciando carga masiva desde {full_path}...")
                self.storage_mgr.bulk_load_csv(meta, full_path)
            else:
                print(f"ERROR: No se encontró el archivo {full_path}")