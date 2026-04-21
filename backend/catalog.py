import struct

# Tamaño fijo de la página de disco
PAGE_SIZE = 8192

# Mapeo de tipos SQL
TYPE_MAP = {
    'INT': {'fmt': 'i', 'size': 4},
    'FLOAT': {'fmt': 'f', 'size': 4},
    'VARCHAR': {'fmt': '50s', 'size': 50}, # Se asume tamaño fijo de 50 bytes para VARCHAR
    'POINT': {'fmt': 'ff', 'size': 8} # El tipo POINT son dos floats (x, y) -> 8 bytes
}

class TableMetadata:
    def __init__(self, name, columns):
        self.name = name
        self.columns = columns # Lista de diccionarios del parser: [{'name': 'DNI', 'type': 'INT', ...}]
        
        # Calcular el formato exacto del struct y el tamaño total del registro
        self.struct_format = ''
        self.record_size = 0
        
        for col in self.columns:
            t = col['type'].upper()
            self.struct_format += TYPE_MAP[t]['fmt']
            self.record_size += TYPE_MAP[t]['size']
            
        # El factor de bloque
        self.block_factor = (PAGE_SIZE - 16) // self.record_size # 16 bytes de "Header" de página para metadata