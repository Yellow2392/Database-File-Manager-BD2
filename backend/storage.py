import os
import csv
import struct
from backend.catalog import PAGE_SIZE

class StorageManager:
    def __init__(self, data_dir="backend/data"):
        self.data_dir = data_dir
        self.disk_writes = 0 # Contadores para I/O
        self.disk_reads = 0 
        
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

    def bulk_load_csv(self, table_meta, csv_path):
        # Lee un CSV y lo guarda en disco empaquetado en paginas binarias
        bin_file_path = os.path.join(self.data_dir, f"{table_meta.name}.dat")
        
        if os.path.exists(bin_file_path): # Si existe se limpia
            os.remove(bin_file_path)
            
        current_page_records = 0
        current_page_data = bytearray()
        
        with open(csv_path, 'r', encoding='utf-8') as csv_file:
            csv_reader = csv.reader(csv_file, delimiter=';') # Saltamos la cabecera
            next(csv_reader, None) 
            
            with open(bin_file_path, 'wb') as bin_file:
                for row in csv_reader:
                    # Datos de texto -> tipo correcto de Python
                    parsed_values = self._parse_row(row, table_meta.columns)
                    
                    # Empaqueta los valores
                    try:
                        record_bytes = struct.pack(table_meta.struct_format, *parsed_values)
                    except struct.error as e:
                        print(f"Error empaquetando fila {row}: {e}")
                        continue
                        
                    # Agrega el registro a nuestra pagina actual en RAM
                    current_page_data.extend(record_bytes)
                    current_page_records += 1
                    
                    # Si la pagina se lleno (alcanzó el factor de bloque), la escribimos a disco
                    if current_page_records == table_meta.block_factor:
                        self._flush_page(bin_file, current_page_data, current_page_records)
                        
                        current_page_data = bytearray() # Reinicia la pagina
                        current_page_records = 0
                        
                # Al terminar el archivo, flushear los registros restantes 
                if current_page_records > 0:
                    self._flush_page(bin_file, current_page_data, current_page_records)
                    
        print(f"Carga masiva completada. Total de accesos a disco (escrituras): {self.disk_writes}")

    def _flush_page(self, file_object, page_data, num_records):
        # Escribe una página de exactamente PAGE_SIZE bytes en disco

        header = struct.pack('i 12x', num_records) # Header de 16 bytes para guardar el número de registros
        full_page = header + page_data
        
        # Se rellena con ceros para alcanzar el máximo de página
        padding_size = PAGE_SIZE - len(full_page)
        full_page += b'\x00' * padding_size
        
        # Escritura en disco
        file_object.write(full_page)
        self.disk_writes += 1 

    def _parse_row(self, row, columns):
        # Convierte los strings del CSV a int, float o bytes según la metadata
        parsed = []
        for i, col in enumerate(columns):
            val = row[i].strip()
            tipo = col['type'].upper()
            
            if tipo == 'INT':
                parsed.append(int(val))
            elif tipo == 'FLOAT':
                parsed.append(float(val))
            elif tipo == 'VARCHAR':
                # String de bytes de tamaño fijo
                # Si el string es más corto, struct lo rellenará con null bytes
                encoded = val.encode('utf-8')
                parsed.append(encoded)
            elif tipo == 'POINT':
                # TODO: Verificar este caso
                pass 
        return parsed