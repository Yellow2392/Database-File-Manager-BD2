import os
import struct
import pickle
import csv
from .base import BaseIndex
from backend.catalog import PAGE_SIZE

class ExtendibleHashing(BaseIndex):
    
    def __init__(self, table_meta, key_column, data_dir="backend/data"):
        # Llamada exacta al constructor padre para heredar rutas y metadatos
        super().__init__(table_meta, key_column, data_dir)
        
        # Definición de rutas siguiendo el patrón de SequentialFile
        self.data_file = os.path.join(self.data_dir, f"{table_meta.name}_hash_buckets.dat")
        self.dir_file = os.path.join(self.data_dir, f"{table_meta.name}_hash_dir.dat")
        
        self.PAGE_SIZE = PAGE_SIZE
        
        self.record_format = self._build_struct_format()
        self.record_size = struct.calcsize(self.record_format)
        
        self.header_format = 'ii' # local_depth, record_count
        self.header_size = struct.calcsize(self.header_format)
        self.MAX_RECORDS = (self.PAGE_SIZE - self.header_size) // self.record_size
        
        # Estado del Directorio
        self.global_depth = 0
        self.directory = []

        #Calcular la posición del índice de la llave primaria en el registro
        self.key_index = 0
        for i, col in enumerate(self.table_meta.columns):
            if col['name'] == key_column:
                self.key_index = i
                break
        
        if not os.path.exists(self.data_file):
            self._initialize_empty_hash()
        else:
            self._load_directory()


    def _build_struct_format(self):
            """Genera el formato struct basado en el catálogo."""
            fmt = ''
            for col in self.table_meta.columns:
                col_type = col['type'].upper()
                if col_type == 'INT':
                    fmt += 'i'
                elif col_type.startswith('VARCHAR'):
                    if '(' in col_type:
                        size = int(col_type.split('(')[1].split(')')[0])
                    else:
                        size = 50 
                    fmt += f'{size}s'
                elif col_type == 'FLOAT':
                    fmt += 'f'
            fmt += '?' # Lápida (is_deleted)
            return fmt


    def _initialize_empty_hash(self):
        with open(self.data_file, 'wb') as f:
            pass 
            
        # El directorio inicial apunta a la página 0
        self.directory = [0]
        self.global_depth = 0
        
        # Formatear y escribir la página 0 vacía
        empty_bucket_data = struct.pack(self.header_format, 0, 0)
        empty_bucket_data = empty_bucket_data.ljust(self.PAGE_SIZE, b'\x00')
        self._write_page(0, empty_bucket_data)
        self._save_directory()


    def _read_page(self, page_id):
        
        self.disk_reads += 1

        with open(self.data_file, 'rb') as f:
            f.seek(page_id * self.PAGE_SIZE)
            return f.read(self.PAGE_SIZE)


    def _write_page(self, page_id, data):

        self.disk_writes += 1

        if len(data) != self.PAGE_SIZE:
            data = data.ljust(self.PAGE_SIZE, b'\x00')

        with open(self.data_file, 'r+b') as f:
            f.seek(page_id * self.PAGE_SIZE)
            f.write(data)


    def _save_directory(self):
        with open(self.dir_file, 'wb') as f:
            pickle.dump({'global_depth': self.global_depth, 'directory': self.directory}, f)


    def _load_directory(self):
        
        with open(self.dir_file, 'rb') as f:
            data = pickle.load(f)
            self.global_depth = data['global_depth']
            self.directory = data['directory']

    
#############################################  
#MÉTODOS AUXILIARES DE TRANSFORMACIÓN Y HASH
#############################################  

    def _get_hash(self, key, depth):
        if isinstance(key, str):
            h = hash(key)
        else:
            h = int(key)
            
        if depth == 0:
            return 0
        return h & ((1 << depth) - 1)


    def _prepare_record_for_pack(self, record):
        packed_rec = []
        for val in record:
            if isinstance(val, str):
                packed_rec.append(val.encode('utf-8'))
            else:
                packed_rec.append(val)
        return tuple(packed_rec)


    def _allocate_new_page(self):
        file_size = os.path.getsize(self.data_file)
        return file_size // self.PAGE_SIZE


    def _unpack_page(self, raw_data, count):
        records = []
        offset = self.header_size
        for _ in range(count):
            rec = struct.unpack_from(self.record_format, raw_data, offset)
            records.append(list(rec)) 
            offset += self.record_size
        return records


    def _pack_and_write_page(self, page_id, local_depth, count, records):
        data = struct.pack(self.header_format, local_depth, count)
        for rec in records:
            data += struct.pack(self.record_format, *rec)
        self._write_page(page_id, data)  
    
    
#############################################  
#MÉTODOS HEREDADOS DE LA INTERFAZ BASEINDEX
############################################# 

    def add(self, record, is_bulk=False):
        #Extraer la llave y calcular el ID de la página
        key = record[self.key_index]
        dir_index = self._get_hash(key, self.global_depth)
        page_id = self.directory[dir_index]

        raw_data = self._read_page(page_id)
        local_depth, count = struct.unpack_from(self.header_format, raw_data, 0)
        
        records = self._unpack_page(raw_data, count)

        #Buscar un espacio por borrado lógico (Lápida == True)
        free_slot_index = -1
        for i, rec in enumerate(records):
            if rec[-1] == True: 
                free_slot_index = i
                break

        #Intentar insertar
        prepared_record = self._prepare_record_for_pack(record)
        
        if free_slot_index != -1:
            #Hay una lápida -> Sobreescribimos
            records[free_slot_index] = prepared_record
        elif count < self.MAX_RECORDS:
            #Hay espacio físico libre
            records.append(prepared_record)
            count += 1
        else:
            #DESBORDAMIENTO
            self._split(page_id, records, local_depth)
            
            #Reintentar la inserción de forma recursiva
            self.add(record, is_bulk)
            return

        self._pack_and_write_page(page_id, local_depth, count, records)
        
        # Si no es carga masiva, aseguramos el directorio
        if not is_bulk:
            self._save_directory()


    def _split(self, page_id, records, local_depth):
        #Verificar si se duplica el directorio
        if local_depth == self.global_depth:
            self.directory.extend(self.directory) 
            self.global_depth += 1
            
        new_local_depth = local_depth + 1
        new_page_id = self._allocate_new_page()
        
        #Contenedores para redistribuir la data
        bucket_0_records = []
        bucket_1_records = []
        
        #Redistribuir basándonos en el nuevo bit de profundidad
        for rec in records:
            key_val = rec[self.key_index]
            if isinstance(key_val, bytes):
                key_val = key_val.decode('utf-8').rstrip('\x00')
                
            new_hash = self._get_hash(key_val, new_local_depth)
            
            #Si el bit es 1, se va a la nueva página. Si es 0, se queda en la original.
            if (new_hash >> local_depth) & 1:
                bucket_1_records.append(rec)
            else:
                bucket_0_records.append(rec)

        if len(bucket_0_records) == self.MAX_RECORDS or len(bucket_1_records) == self.MAX_RECORDS:
            raise Exception("Colisión extrema de Hash. Revisa si estás insertando Primary Keys duplicadas.")

        # Actualizar los punteros en el directorio
        for i in range(len(self.directory)):
            if self.directory[i] == page_id:
                if (i >> local_depth) & 1:
                    self.directory[i] = new_page_id
                    
        #Escribir ambas páginas físicas
        self._pack_and_write_page(page_id, new_local_depth, len(bucket_0_records), bucket_0_records)
        self._pack_and_write_page(new_page_id, new_local_depth, len(bucket_1_records), bucket_1_records)
        
        #Guardar el nuevo estado del directorio
        self._save_directory()


    def bulk_load(self, file_path, delimiter=','):
   
        try:
            with open(file_path, mode='r', encoding='utf-8') as f:
                reader = csv.reader(f, delimiter=delimiter)
                
                header = next(reader, None)
                
                for row_num, row in enumerate(reader, start=2):
                    if not row:
                        continue
                        
                    if len(row) != len(self.table_meta.columns):
                        raise Exception(f"Desajuste de columnas en el CSV en la fila {row_num}.")

                    parsed_record = []
                    
                    for i, col_meta in enumerate(self.table_meta.columns):
                        col_name = col_meta['name']
                        tipo = col_meta['type'].upper()
                        
                        try:
                            val = row[i].strip()
                            #print(f"  -> Columna '{col_name}' | Valor Raw: '{val}' | Tipo: {tipo}", end=" ")
                            
                            if tipo == 'INT':
                                parsed_val = int(val)
                                parsed_record.append(parsed_val)
                                
                            elif tipo == 'FLOAT':
                                parsed_val = float(val)
                                parsed_record.append(parsed_val)
                                
                            else: # VARCHAR
                                parsed_record.append(val)
                                
                        except ValueError as e:
                            raise Exception(f"Error de tipo de dato en Fila {row_num}, Columna '{col_name}': {str(e)}")
                        except IndexError as e:
                            raise Exception(f"Fila {row_num} incompleta.")
                    
                    parsed_record.append(False)
                    tuple_record = tuple(parsed_record)
                    
                    try:
                        self.add(tuple_record, is_bulk=True)
                    except Exception as e:
                         raise Exception(f"Fallo crítico al insertar fila {row_num} en la estructura Hash.")

            self._save_directory()
            
        except FileNotFoundError:
            print(f"[ERROR] No se pudo encontrar el archivo CSV en la ruta: {file_path}")
            raise
        except Exception as e:
            print(f"\n[ERROR GENERAL - BULK LOAD] La carga se abortó en el proceso: {str(e)}")
            raise


    def search(self, search_key):
        
        # Encontrar el índice en el directorio
        dir_index = self._get_hash(search_key, self.global_depth)
        
        # Obtenemos el ID de la página física
        page_id = self.directory[dir_index]

        raw_data = self._read_page(page_id)
        
        local_depth, count = struct.unpack_from(self.header_format, raw_data, 0)
        
        # Desempaquetamos los bytes en una lista de listas 
        records = self._unpack_page(raw_data, count)

    # Buscamos en los registros de la página
        for rec in records:
            # Si las llaves coinciden...
            if rec[self.key_index] == search_key:
                # Revisamos la lápida (el último elemento del registro)
                if rec[-1] == False:
                    return tuple(rec) # Está vivo, lo retornamos normal
                else:
                    # ¡Lo encontró pero está muerto!
                    raise Exception(f"Registro eliminado en el pasado, en tabla {self.table_meta.name}.")

        # Si el bucle termina y nunca hubo coincidencia de llave...
        raise Exception(f"Registro no encontrado en tabla {self.table_meta.name}.")
        #return None


    def rangeSearch(self, start_key, end_key):
        """
        No soporta rangeSearch. 
        """
        raise NotImplementedError("El índice Extendible Hashing no soporta búsquedas por rango.")

    
    def remove(self, search_key):
       
        #Calculamos el Hash y ubicamos la página exacta en el directorio
        dir_index = self._get_hash(search_key, self.global_depth)
        page_id = self.directory[dir_index]

        raw_data = self._read_page(page_id)
        
        local_depth, count = struct.unpack_from(self.header_format, raw_data, 0)
        records = self._unpack_page(raw_data, count)

        #Buscamos el registro secuencialmente dentro del bucket en RAM
        for i, rec in enumerate(records):
            rec_key = rec[self.key_index]
            
            if isinstance(rec_key, bytes):
                rec_key = rec_key.decode('utf-8').rstrip('\x00')
                
            if rec_key == search_key and rec[-1] == False:
                records[i][-1] = True
                
                self._pack_and_write_page(page_id, local_depth, count, records)
                
                return True 
                
        # Si termina el bucle y no retornó True, el registro no existía o ya estaba borrado
        return False
        pass

    def knn_search(self, point, k):
        return NotImplementedError("KNN no soportado en Sequential")
    