import os
import struct
import csv
from .base import BaseIndex 
from backend.catalog import PAGE_SIZE

class HeapFile(BaseIndex): 
    def __init__(self, table_meta, key_column=None, data_dir="backend/data"):
        super().__init__(table_meta, key_column, data_dir)
        self.bin_file_path = os.path.join(self.data_dir, f"{table_meta.name}_heap.dat")
        
        self.key_index = 0
        if self.key_column:
            for i, col in enumerate(self.table_meta.columns):
                if col['name'] == self.key_column:
                    self.key_index = i
                    break
        
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            
        if not os.path.exists(self.bin_file_path):
            open(self.bin_file_path, 'wb').close()

    def add(self, record_tuple, is_bulk=False):
        # Inserta un registro al final del archivo
        record_bytes = struct.pack(self.table_meta.struct_format, *record_tuple)
        tamano = os.path.getsize(self.bin_file_path)
        
        with open(self.bin_file_path, 'r+b' if tamano > 0 else 'wb') as f:
            if tamano == 0:
                page_data = bytearray(record_bytes)
                self._flush_page(f, 0, page_data, 1)
            else:
                num_pages = tamano // self.PAGE_SIZE
                last_page_offset = (num_pages - 1) * self.PAGE_SIZE
                f.seek(last_page_offset)
                page_data = bytearray(f.read(self.PAGE_SIZE))
                self.disk_reads += 1
                
                num_records = struct.unpack('i 12x', page_data[:16])[0]
                
                if num_records < self.table_meta.block_factor: # Hay espacio
                    offset = 16 + (num_records * self.table_meta.record_size)
                    page_data[offset : offset + self.table_meta.record_size] = record_bytes
                    self._flush_page(f, last_page_offset, page_data[16 : offset + self.table_meta.record_size], num_records + 1)
                else:
                    new_page_data = bytearray(record_bytes)
                    self._flush_page(f, num_pages * self.PAGE_SIZE, new_page_data, 1)

    def search(self, key_value): # Scan completo
        tamano = os.path.getsize(self.bin_file_path)
        if tamano == 0: return None
        
        total_pages = tamano // self.PAGE_SIZE
        
        with open(self.bin_file_path, 'rb') as f:
            for i in range(total_pages):
                f.seek(i * self.PAGE_SIZE)
                page_data = f.read(self.PAGE_SIZE)
                self.disk_reads += 1
                
                num_records = struct.unpack('i 12x', page_data[:16])[0]
                
                for j in range(num_records):
                    offset = 16 + (j * self.table_meta.record_size)
                    record_bytes = page_data[offset : offset + self.table_meta.record_size]
                    record_tuple = struct.unpack(self.table_meta.struct_format, record_bytes)
                    
                    key = record_tuple[self.key_index]
                    is_deleted = record_tuple[-1]
                    
                    if key == key_value and not is_deleted:
                        return record_tuple
        return None

    def rangeSearch(self, begin_key, end_key): # Scan completo
        resultados = []
        tamano = os.path.getsize(self.bin_file_path)
        if tamano == 0: return resultados
        
        total_pages = tamano // self.PAGE_SIZE
        
        with open(self.bin_file_path, 'rb') as f:
            for i in range(total_pages):
                f.seek(i * self.PAGE_SIZE)
                page_data = f.read(self.PAGE_SIZE)
                self.disk_reads += 1
                
                num_records = struct.unpack('i 12x', page_data[:16])[0]
                
                for j in range(num_records):
                    offset = 16 + (j * self.table_meta.record_size)
                    record_bytes = page_data[offset : offset + self.table_meta.record_size]
                    record_tuple = struct.unpack(self.table_meta.struct_format, record_bytes)
                    
                    key = record_tuple[self.key_index]
                    is_deleted = record_tuple[-1]
                    
                    if begin_key <= key <= end_key and not is_deleted:
                        resultados.append(record_tuple)
        return resultados
    
    def remove(self, key_value): # Busca el registro y le aplica borrado lógico
        tamano = os.path.getsize(self.bin_file_path)
        if tamano == 0: return False
        
        total_pages = tamano // self.PAGE_SIZE
        
        with open(self.bin_file_path, 'r+b') as f:
            for i in range(total_pages):
                page_offset = i * self.PAGE_SIZE
                f.seek(page_offset)
                page_data = bytearray(f.read(self.PAGE_SIZE))
                self.disk_reads += 1
                
                num_records = struct.unpack('i 12x', page_data[:16])[0]
                
                for j in range(num_records):
                    rec_offset = 16 + (j * self.table_meta.record_size)
                    record_bytes = page_data[rec_offset : rec_offset + self.table_meta.record_size]
                    record_tuple = list(struct.unpack(self.table_meta.struct_format, record_bytes))
                    
                    key = record_tuple[self.key_index]
                    is_deleted = record_tuple[-1]
                    
                    if key == key_value and not is_deleted:
                        record_tuple[-1] = True
                        new_record_bytes = struct.pack(self.table_meta.struct_format, *record_tuple)
                        
                        f.seek(page_offset + rec_offset)
                        f.write(new_record_bytes)
                        self.disk_writes += 1
                        return True
        return False

    def bulk_load(self, csv_path, delimiter = ','):
        if os.path.exists(self.bin_file_path):
            os.remove(self.bin_file_path)
            
        current_page_records = 0
        current_page_data = bytearray()
        page_counter = 0
        
        with open(csv_path, 'r', encoding='utf-8') as csv_file:
            csv_reader = csv.reader(csv_file, delimiter=delimiter)
            next(csv_reader, None) 
            
            with open(self.bin_file_path, 'wb') as bin_file:
                for row in csv_reader:
                    parsed_values = self._parse_row(row, self.table_meta.columns)
                    
                    try:
                        record_bytes = struct.pack(self.table_meta.struct_format, *parsed_values)
                    except struct.error as e:
                        print(f"Error empaquetando fila {row}: {e}")
                        continue
                        
                    current_page_data.extend(record_bytes)
                    current_page_records += 1
                    
                    if current_page_records == self.table_meta.block_factor:
                        offset = page_counter * self.PAGE_SIZE
                        self._flush_page(bin_file, offset, current_page_data, current_page_records)
                        
                        current_page_data = bytearray() 
                        current_page_records = 0
                        page_counter += 1
                        
                if current_page_records > 0:
                    offset = page_counter * self.PAGE_SIZE
                    self._flush_page(bin_file, offset, current_page_data, current_page_records)
                    
        print(f"Carga masiva completada. Total escrituras: {self.disk_writes}")

    def _flush_page(self, f, offset, raw_records_data, num_records):
        f.seek(offset)
        header = struct.pack('i 12x', num_records)
        full_page = header + raw_records_data
        padding_size = self.PAGE_SIZE - len(full_page)
        full_page += b'\x00' * padding_size
        f.write(full_page)
        self.disk_writes += 1

    def _parse_row(self, row, columns):
        parsed = []
        raw_idx = 0
        for col in columns:
            val = row[raw_idx].strip() if raw_idx < len(row) else ''
            tipo = col['type'].upper()
            
            if tipo == 'INT':
                parsed.append(int(val))
            elif tipo == 'FLOAT':
                parsed.append(float(val))
            elif tipo == 'VARCHAR':
                encoded = val.encode('utf-8')
                parsed.append(encoded)
            elif tipo == 'BOOLEAN':
                es_verdadero = val.upper() in ('TRUE', '1', 'T', 'YES', 'Y')
                parsed.append(es_verdadero)
            elif tipo == 'DATE':
                parsed.append(val[:10].encode('utf-8'))
            elif tipo == 'POINT':
                parsed.append(float(row[raw_idx]))
                parsed.append(float(row[raw_idx + 1]))
                raw_idx += 1 
                
            raw_idx += 1
            
        parsed.append(False) # is_deleted = False
        return parsed
    
    def knn_search(self, point, k):
        return NotImplementedError("KNN no soportado en Heap")