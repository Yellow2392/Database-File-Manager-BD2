import struct

# Tamaño fijo de la página de disco
PAGE_SIZE = 4096

# Mapeo de tipos SQL
TYPE_MAP = {
    'INT': {'fmt': 'i', 'size': 4},
    'FLOAT': {'fmt': 'f', 'size': 4},
    'VARCHAR': {'fmt': '50s', 'size': 50}, # Se asume tamaño fijo de 50 bytes para VARCHAR
    'POINT': {'fmt': 'ff', 'size': 8} # TODO: Revisar el manejo de POINT. Por ahora está como un tipo mapeable
}

class TableMetadata:
    def __init__(self, name, columns, key_column=None, index_tech=None):
        self.name = name
        self.columns = columns # Lista de diccionarios del parser

        self.key_column = key_column
        self.index_tech = index_tech
        
        self.struct_format = '=' 
        
        for col in self.columns:
            t = col['type'].upper()
            self.struct_format += TYPE_MAP[t]['fmt']
            
        # is_deleted (columna oculta)
        self.struct_format += '?'
        
        self.record_size = struct.calcsize(self.struct_format)
        
        # El factor de bloque
        self.block_factor = (PAGE_SIZE - 16) // self.record_size # 16 bytes de "Header" de página para metadata

    def clean_tuple(self, raw_tuple): # Formateo limpio para la tupla
        if not raw_tuple:
            return None
            
        cleaned = []
        for i, col in enumerate(self.columns):
            val = raw_tuple[i]
            tipo = col['type'].upper()
            
            if tipo == 'VARCHAR':
                cleaned.append(val.decode('utf-8').rstrip('\x00'))
            elif tipo == 'FLOAT':
                cleaned.append(round(val, 2))
            else:
                cleaned.append(val)
                
        return tuple(cleaned)

    def to_dict(self): # JSON para guardar estado de la metadata
        return {
            "name": self.name,
            "columns": self.columns,
            "key_column": self.key_column,
            "index_tech": self.index_tech
        }

    @classmethod
    def from_dict(cls, data): # Cargado del JSON para la metadata
        return cls(
            name=data["name"],
            columns=data["columns"],
            key_column=data["key_column"],
            index_tech=data["index_tech"]
        )