import os
import struct
import csv
from .base import BaseIndex 
from backend.catalog import PAGE_SIZE

class HeapFile(BaseIndex): # Estructura baseline en caso no haya índice asignado
    def __init__(self, table_meta, key_column=None, data_dir="backend/data"):
        self.table_meta = table_meta
        self.data_dir = data_dir
        self.bin_file_path = os.path.join(self.data_dir, f"{table_meta.name}_heap.dat")
        
        self.disk_writes = 0 
        self.disk_reads = 0 
        
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            
        if not os.path.exists(self.bin_file_path):
            open(self.bin_file_path, 'wb').close()

    def add(self, record_tuple, is_bulk = False): #  Inserta un registro al final del archivo 
        record_bytes = struct.pack(self.table_meta.struct_format, *record_tuple)
        tamano = os.path.getsize(self.bin_file_path)
        
        with open(self.bin_file_path, 'r+b' if tamano > 0 else 'wb') as f:
            if tamano == 0:
                page_data = bytearray(record_bytes)
                self._flush_page(f, 0, page_data, 1)
            else:
                num_pages = tamano // PAGE_SIZE
                last_page_offset = (num_pages - 1) * PAGE_SIZE
                f.seek(last_page_offset)
                page_data = bytearray(f.read(PAGE_SIZE))
                self.disk_reads += 1
                
                num_records = struct.unpack('i 12x', page_data[:16])[0]
                
                if num_records < self.table_meta.block_factor: # Hay espacio, agregamos aquí
                    offset = 16 + (num_records * self.table_meta.record_size)
                    page_data[offset : offset + self.table_meta.record_size] = record_bytes
                    self._flush_page(f, last_page_offset, page_data[16:], num_records + 1)
                else:
                    # Está llena, creamos nueva página
                    new_page_data = bytearray(record_bytes)
                    self._flush_page(f, num_pages * PAGE_SIZE, new_page_data, 1)

    def search(self, key_value):
        # TODO
        return

    def rangeSearch(self, begin_key, end_key):
        # TODO
        return
    
    def remove(self, key_value):
        # TODO
        return

    def bulk_load(self, csv_path): # Lee un CSV y lo guarda en disco empaquetado en paginas binarias
        bin_file_path = os.path.join(self.data_dir, f"{self.table_meta.name}.dat")
        
        if os.path.exists(bin_file_path): # Si existe se limpia
            os.remove(bin_file_path)
            
        current_page_records = 0
        current_page_data = bytearray()
        
        with open(csv_path, 'r', encoding='utf-8') as csv_file:
            csv_reader = csv.reader(csv_file, delimiter=';') # TODO: Delimitador hardcodeado. Colocar soporte dentro de la misma consulta
            next(csv_reader, None) 
            
            with open(bin_file_path, 'wb') as bin_file:
                for row in csv_reader:
                    # Datos de texto -> tipo correcto de Python
                    parsed_values = self._parse_row(row, self.table_meta.columns)
                    
                    try:
                        record_bytes = struct.pack(self.table_meta.struct_format, *parsed_values)
                    except struct.error as e:
                        print(f"Error empaquetando fila {row}: {e}")
                        continue
                        
                    # registro -> pagina actual en RAM
                    current_page_data.extend(record_bytes)
                    current_page_records += 1
                    
                    # Si la pagina se lleno (alcanzó el factor de bloque), la escribimos a disco
                    if current_page_records == self.table_meta.block_factor:
                        self._flush_page(bin_file, current_page_data, current_page_records)
                        
                        current_page_data = bytearray() # Reinicia la pagina
                        current_page_records = 0
                        
                if current_page_records > 0:
                    self._flush_page(bin_file, current_page_data, current_page_records)
                    
        print(f"Carga masiva completada. Total de accesos a disco (escrituras): {self.disk_writes}")

    def _flush_page(self, f, offset, raw_records_data, num_records):
        f.seek(offset)
        header = struct.pack('i 12x', num_records)
        full_page = header + raw_records_data
        padding_size = PAGE_SIZE - len(full_page)
        full_page += b'\x00' * padding_size
        f.write(full_page)
        self.disk_writes += 1

    def _parse_row(self, row, columns):
        parsed = []
        for i, col in enumerate(columns):
            val = row[i].strip()
            tipo = col['type'].upper()
            
            if tipo == 'INT':
                parsed.append(int(val))
            elif tipo == 'FLOAT':
                parsed.append(float(val))
            elif tipo == 'VARCHAR':
                encoded = val.encode('utf-8')
                parsed.append(encoded)
            elif tipo == 'POINT':
                # TODO: Verificar este caso
                pass 
        parsed.append(False) # is_deleted = False
        return parsed