import shutil
import os
import struct
import math
import csv

from .base import BaseIndex
from backend.external.external_sort import ExternalSort

class SequentialFile(BaseIndex):
    def __init__(self, table_meta, key_column, data_dir="backend/data"):
        super().__init__(table_meta, key_column, data_dir)
        
        self.main_file = os.path.join(self.data_dir, f"{table_meta.name}_main.dat")
        self.aux_file = os.path.join(self.data_dir, f"{table_meta.name}_aux.dat")
        
        for f in [self.main_file, self.aux_file]:
            if not os.path.exists(f):
                open(f, 'wb').close()
        
        self.total_main_records = self._count_main_records()

    def search(self, key_value): # Búsqueda binaria adaptada a nivel de página
        if not os.path.exists(self.main_file):
            return None
            
        tamano_main = os.path.getsize(self.main_file)
        if tamano_main == 0:
            return self._search_in_aux(key_value)
            
        num_pages = tamano_main // self.PAGE_SIZE
        l = 0
        u = num_pages - 1
        
        with open(self.main_file, 'rb') as f:
            while u >= l:
                mid_page_idx = (l + u) // 2
                
                # Lee una sola página de disco
                f.seek(mid_page_idx * self.PAGE_SIZE)
                page_data = f.read(self.PAGE_SIZE)
                self.disk_reads += 1
                
                # Header de la página (16 bytes) con la cantidad de registros
                header = struct.unpack('i 12x', page_data[:16])
                num_records_in_page = header[0]
                
                if num_records_in_page == 0:
                    break 
                    
                # Primer y último registro de esta página en ram
                first_record_data = page_data[16 : 16 + self.table_meta.record_size]
                first_record = struct.unpack(self.table_meta.struct_format, first_record_data)
                first_key = first_record[0] #TODO: Aquí asumo que la llave es la primera columna para simplificar. Debería soportar más que eso
                
                offset_last = 16 + ((num_records_in_page - 1) * self.table_meta.record_size)
                last_record_data = page_data[offset_last : offset_last + self.table_meta.record_size]
                last_record = struct.unpack(self.table_meta.struct_format, last_record_data)
                last_key = last_record[0]
                
                # Búsqueda binaria a través de pagina
                if key_value < first_key:
                    u = mid_page_idx - 1
                elif key_value > last_key:
                    l = mid_page_idx + 1
                else:
                    # Búsqueda ya que sabemos que está aquí
                    for i in range(num_records_in_page):
                        offset = 16 + (i * self.table_meta.record_size)
                        record_bytes = page_data[offset : offset + self.table_meta.record_size]
                        record_tuple = struct.unpack(self.table_meta.struct_format, record_bytes)
                        
                        # Extraemos el booleano is_deleted (asumiendo que es el último elemento de la tupla)
                        is_deleted = record_tuple[-1] 
                        record_key = record_tuple[0]
                        
                        if record_key == key_value and not is_deleted:
                            return record_tuple
                    
                    break 
                    
        # Busca en auxiliar
        return self._search_in_aux(key_value)

    def _search_in_aux(self, key_value):   # Búsqueda lineal en el archivo auxiliar leyendo página por página.
        tamano_aux = os.path.getsize(self.aux_file)
        if tamano_aux == 0:
            return None
            
        num_pages = tamano_aux // self.PAGE_SIZE
        
        with open(self.aux_file, 'rb') as f:
            for page_idx in range(num_pages):
                page_data = f.read(self.PAGE_SIZE)
                self.disk_reads += 1
                
                header = struct.unpack('i 12x', page_data[:16])
                num_records_in_page = header[0]
                
                for i in range(num_records_in_page):
                    offset = 16 + (i * self.table_meta.record_size)
                    record_bytes = page_data[offset : offset + self.table_meta.record_size]
                    record_tuple = struct.unpack(self.table_meta.struct_format, record_bytes)
                    
                    if record_tuple[0] == key_value and not record_tuple[-1]:
                        return record_tuple
        return None
    
    def add(self, record_tuple, is_bulk = False):   
        record_bytes = struct.pack(self.table_meta.struct_format, *record_tuple) # Empaquetamos la tupla a bytes
        
        tamano_aux = os.path.getsize(self.aux_file)
        
        with open(self.aux_file, 'r+b' if tamano_aux > 0 else 'wb') as f:
            if tamano_aux == 0: # Si está vacío crea la primer página
                page_data = bytearray()
                page_data.extend(record_bytes)
                self._write_page(f, 0, page_data, 1) 
            else:
                # Leer la última página
                num_pages = tamano_aux // self.PAGE_SIZE
                last_page_idx = num_pages - 1
                
                f.seek(last_page_idx * self.PAGE_SIZE)
                page_data = bytearray(f.read(self.PAGE_SIZE))
                self.disk_reads += 1
                
                header = struct.unpack('i 12x', page_data[:16])
                num_records = header[0]
                
                if num_records < self.table_meta.block_factor:
                    # Hay espacio en la página actual, la sobreescribimos
                    offset_insercion = 16 + (num_records * self.table_meta.record_size)
                    page_data[offset_insercion : offset_insercion + self.table_meta.record_size] = record_bytes
                    
                    # Actualizamos el header y escribimos la página de vuelta
                    self._write_page(f, last_page_idx * self.PAGE_SIZE, page_data[16:], num_records + 1)
                else:
                    # La última página está llena, creamos una nueva al final del archivo
                    new_page_data = bytearray()
                    new_page_data.extend(record_bytes)
                    self._write_page(f, num_pages * self.PAGE_SIZE, new_page_data, 1)

        if is_bulk:
            return

        # Vemos si es necesario reconstruir
        total_aux_records = self._count_aux_records()
        
        if self.total_main_records > 0:
            #limite_k_dinamico = max(10, int(math.log2(self.total_main_records)))
            limite_k_dinamico = max(self.table_meta.block_factor * 5, int(math.sqrt(self.total_main_records)))
        else:
            limite_k_dinamico = 10
            
        if total_aux_records >= limite_k_dinamico:
            print(f"Límite dinámico K ({limite_k_dinamico}) alcanzado en archivo auxiliar. Iniciando Reconstrucción...")
            self._rebuild()

    def _write_page(self, f, offset, raw_records_data, num_records):
        # Helper para escribir una página exacta
        f.seek(offset)
        header = struct.pack('i 12x', num_records)
        full_page = header + raw_records_data
        
        padding_size = self.PAGE_SIZE - len(full_page)
        full_page += b'\x00' * padding_size
        
        f.write(full_page)
        self.disk_writes += 1
    
    def _write_page_simple(self, f_out, records):
        # Helper auxiliar para escribir páginas rápidamente durante la transcripción
        header = struct.pack('i 12x', len(records))
        data = b''.join(struct.pack(self.table_meta.struct_format, *r) for r in records)
        padding = b'\x00' * (self.PAGE_SIZE - 16 - len(data))
        f_out.write(header + data + padding)
        
    def _count_aux_records(self):
        # Cuenta los registros leyendo solo los headers de las páginas auxiliares
        tamano = os.path.getsize(self.aux_file)
        if tamano == 0: return 0
        
        total = 0
        with open(self.aux_file, 'rb') as f:
            for i in range(tamano // self.PAGE_SIZE):
                f.seek(i * self.PAGE_SIZE)
                header = f.read(16)
                self.disk_reads += 1
                total += struct.unpack('i 12x', header)[0]
        return total
    
    def _count_main_records(self): #Cuenta los registros en el main file leyendo solo los headers
        tamano = os.path.getsize(self.main_file)
        if tamano == 0: return 0
        
        total = 0
        with open(self.main_file, 'rb') as f:
            for i in range(tamano // self.PAGE_SIZE):
                f.seek(i * self.PAGE_SIZE)
                header = f.read(16)
                total += struct.unpack('i 12x', header)[0]
        return total
    
    def remove(self, key_value):
        # Busca el registro, lo marca como eliminado y sobreescribe la página
        tamano_main = os.path.getsize(self.main_file) # Verifica en el archivo principal
        if tamano_main > 0:
            l, u = 0, (tamano_main // self.PAGE_SIZE) - 1
            with open(self.main_file, 'r+b') as f:
                while u >= l:
                    mid = (l + u) // 2
                    f.seek(mid * self.PAGE_SIZE)
                    page_data = bytearray(f.read(self.PAGE_SIZE))
                    self.disk_reads += 1
                    
                    num_records = struct.unpack('i 12x', page_data[:16])[0]
                    if num_records == 0: break
                    
                    first_key = struct.unpack(self.table_meta.struct_format, page_data[16 : 16 + self.table_meta.record_size])[0]
                    last_offset = 16 + ((num_records - 1) * self.table_meta.record_size)
                    last_key = struct.unpack(self.table_meta.struct_format, page_data[last_offset : last_offset + self.table_meta.record_size])[0]
                    
                    if key_value < first_key:
                        u = mid - 1
                    elif key_value > last_key:
                        l = mid + 1
                    else:
                        # La llave está aquí
                        for i in range(num_records):
                            offset = 16 + (i * self.table_meta.record_size)
                            record_bytes = page_data[offset : offset + self.table_meta.record_size]
                            record_tuple = list(struct.unpack(self.table_meta.struct_format, record_bytes))
                            
                            if record_tuple[0] == key_value and not record_tuple[-1]:
                                # is_deleted se pasa a True
                                record_tuple[-1] = True
                                new_bytes = struct.pack(self.table_meta.struct_format, *record_tuple)
                                
                                page_data[offset : offset + self.table_meta.record_size] = new_bytes
                                
                                f.seek(mid * self.PAGE_SIZE)
                                f.write(page_data)
                                self.disk_writes += 1
                                return True
                        break

        # Busca en el archivo auxiliar si no estaba en el archivo principal
        tamano_aux = os.path.getsize(self.aux_file)
        if tamano_aux > 0:
            with open(self.aux_file, 'r+b') as f:
                for i in range(tamano_aux // self.PAGE_SIZE):
                    f.seek(i * self.PAGE_SIZE)
                    page_data = bytearray(f.read(self.PAGE_SIZE))
                    self.disk_reads += 1
                    
                    num_records = struct.unpack('i 12x', page_data[:16])[0]
                    for j in range(num_records):
                        offset = 16 + (j * self.table_meta.record_size)
                        record_bytes = page_data[offset : offset + self.table_meta.record_size]
                        record_tuple = list(struct.unpack(self.table_meta.struct_format, record_bytes))
                        
                        if record_tuple[0] == key_value and not record_tuple[-1]:
                            record_tuple[-1] = True
                            new_bytes = struct.pack(self.table_meta.struct_format, *record_tuple)
                            page_data[offset : offset + self.table_meta.record_size] = new_bytes
                            
                            f.seek(i * self.PAGE_SIZE)
                            f.write(page_data)
                            self.disk_writes += 1
                            return True
        return False
    
    def rangeSearch(self, begin_key, end_key):
        resultados = []
        
        # Búsqueda en Main File
        tamano_main = os.path.getsize(self.main_file)
        if tamano_main > 0:
            total_pages = tamano_main // self.PAGE_SIZE
            start_page = 0
            
            # Por búsqueda binaria
            low = 0
            high = total_pages - 1
            
            while low <= high:
                mid = (low + high) // 2
                with open(self.main_file, 'rb') as f:
                    f.seek(mid * self.PAGE_SIZE)
                    page_data = f.read(self.PAGE_SIZE)
                    self.disk_reads += 1
                    
                    num_records = struct.unpack('i 12x', page_data[:16])[0]
                    if num_records == 0: break
                    
                    offset_first = 16
                    first_record = struct.unpack(self.table_meta.struct_format, page_data[offset_first : offset_first + self.table_meta.record_size])
                    first_key = first_record[0]
                    
                    offset_last = 16 + ((num_records - 1) * self.table_meta.record_size)
                    last_record = struct.unpack(self.table_meta.struct_format, page_data[offset_last : offset_last + self.table_meta.record_size])
                    last_key = last_record[0]
                    
                    if last_key < begin_key:
                        low = mid + 1
                    elif first_key > begin_key:
                        high = mid - 1
                    else:
                        # El begin_key debería estar dentro de esta página
                        start_page = mid
                        break
            else: # Si no hubo coincidencia exacta, low apunta a la página más cercana
                start_page = min(low, total_pages - 1)

            # Escaneo Secuencial sobre la página
            with open(self.main_file, 'rb') as f:
                terminar_busqueda = False
                
                for i in range(start_page, total_pages):
                    if terminar_busqueda: break 
                    
                    f.seek(i * self.PAGE_SIZE)
                    page_data = f.read(self.PAGE_SIZE)
                    self.disk_reads += 1 
                    
                    num_records = struct.unpack('i 12x', page_data[:16])[0]
                    
                    for j in range(num_records):
                        offset = 16 + (j * self.table_meta.record_size)
                        record_bytes = page_data[offset : offset + self.table_meta.record_size]
                        record_tuple = struct.unpack(self.table_meta.struct_format, record_bytes)
                        
                        key = record_tuple[0]
                        is_deleted = record_tuple[-1]
                        
                        if key > end_key:
                            terminar_busqueda = True
                            break 
                            
                        if not is_deleted and begin_key <= key <= end_key:
                            resultados.append(record_tuple)


        # Aux File
        tamano_aux = os.path.getsize(self.aux_file)
        if tamano_aux > 0:
            with open(self.aux_file, 'rb') as f:
                for i in range(tamano_aux // self.PAGE_SIZE):
                    f.seek(i * self.PAGE_SIZE)
                    page_data = f.read(self.PAGE_SIZE)
                    self.disk_reads += 1
                    
                    num_records = struct.unpack('i 12x', page_data[:16])[0]
                    
                    for j in range(num_records):
                        offset = 16 + (j * self.table_meta.record_size)
                        record_bytes = page_data[offset : offset + self.table_meta.record_size]
                        record_tuple = struct.unpack(self.table_meta.struct_format, record_bytes)
                        
                        key = record_tuple[0]
                        is_deleted = record_tuple[-1]
                        
                        if not is_deleted and begin_key <= key <= end_key:
                            resultados.append(record_tuple)

        # Ordenamos porque los datos del aux_file pueden estar intercalados lógicamente
        resultados.sort(key=lambda x: x[0])
        return resultados
    
    def _rebuild(self):  # Reconstruye el archivo secuencial fusionando el main y el aux sin desbordar la memoria
        # main_file + aux_file -> heap temporal
        temp_heap_file = os.path.join(self.data_dir, f"{self.table_meta.name}_temp_rebuild.dat")
        with open(temp_heap_file, 'wb') as f_out:
            for file_to_read in [self.main_file, self.aux_file]:
                if os.path.getsize(file_to_read) > 0:
                    with open(file_to_read, 'rb') as f_in:
                        shutil.copyfileobj(f_in, f_out)
        
        # Ordenamiento externo
        sorter = ExternalSort(
            record_format=self.table_meta.struct_format, 
            page_size=self.PAGE_SIZE, 
            buffer_size=2 * 1024 * 1024 
        )
        sorter.external_sort(temp_heap_file, self.main_file, sort_key_index=0)
        
        os.remove(temp_heap_file)
        open(self.aux_file, 'wb').close() 
        print("Reconstrucción finalizada.")
    
    def bulk_load(self, csv_path, delimiter = ','): # Implementación de carga masiva
        #! Fase 1
        temp_heap_file = os.path.join(self.data_dir, f"{self.table_meta.name}_temp_heap.dat")
        
        # CSV -> Binario temporal
        current_page_records = []
        with open(csv_path, 'r', encoding='utf-8') as f_in, open(temp_heap_file, 'wb') as f_out:
            reader = csv.reader(f_in, delimiter=delimiter)
            next(reader, None)
            
            for row in reader:
                parsed_row = self._parse_row(row, self.table_meta.columns)
                current_page_records.append(parsed_row)
                
                if len(current_page_records) == self.table_meta.block_factor:
                    self._write_page_simple(f_out, current_page_records)
                    current_page_records = []
                    
            if current_page_records:
                self._write_page_simple(f_out, current_page_records)

        #! Fase 2
        sorter = ExternalSort(
            record_format=self.table_meta.struct_format, 
            page_size=self.PAGE_SIZE, 
            buffer_size=2 * 1024 * 1024  # 2 MB de memoria RAM al buffer
        )
        
        #TODO: Asumimos que la llave primaria es la columna 0. Si no, calculalo dinámicamente.
        stats = sorter.external_sort(temp_heap_file, self.main_file, sort_key_index=0)
        
        os.remove(temp_heap_file)
        open(self.aux_file, 'wb').close() # El auxiliar empieza vacío
        
        self.disk_reads += stats['pages_read']
        self.disk_writes += stats['pages_written']
        
        print(f"[OK] Carga masiva completada en {stats['time_total_sec']}s.")

    def _parse_row(self, row, columns):
        # Convierte los strings del CSV a int, float o bytes según la metadata
        parsed = []
        csv_index = 0
        
        for col in self.table_meta.columns:
            tipo = col['type'].upper()
            
            if tipo == 'POINT':
                #! Consumimos dos columnas consecutivas del archivo csv
                x_val = float(row[csv_index].strip())
                y_val = float(row[csv_index + 1].strip())
                
                #Agrega de forma plana para que struct.pack('ff') funcione
                parsed.append(x_val)
                parsed.append(y_val)
                csv_index += 2
            else:
                # Consumo normal de una sola columna CSV
                val = row[csv_index].strip()
                if tipo == 'INT': parsed.append(int(val))
                elif tipo == 'FLOAT': parsed.append(float(val))
                elif tipo == 'VARCHAR': parsed.append(val.encode('utf-8'))
                csv_index += 1

        parsed.append(False)
        return parsed
    
    def knn_search(self, point, k):
        return NotImplementedError("KNN no soportado en Sequential")