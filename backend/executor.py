import os
import glob
import json

from backend.catalog import TableMetadata
from backend.indexes.sequential import SequentialFile
from backend.indexes.rtree import RTreeIndex
from backend.indexes.hash import ExtendibleHashing
from backend.indexes.heapFileIndex import HeapFile

from backend.external.external_hashing import ExternalHashing
from backend.external.external_sort import ExternalSort
from backend.indexes.bplusTree import BPlusTree

from .visualizer import save_spatial_plot

class Executor:
    def __init__(self, data_dir="backend/data"):
        self.catalog = {}  # registro de las tablas creadas
        self.data_dir = data_dir

        self.catalog_file = os.path.join(self.data_dir, "system_catalog.json")

        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        self._load_system_catalog()

    def _save_system_catalog(self): #Persiste el estado de todas las tablas en un archivo JSON
        data_to_save = {name: meta.to_dict() for name, meta in self.catalog.items()}
        with open(self.catalog_file, 'w') as f:
            json.dump(data_to_save, f, indent=4)

    def _load_system_catalog(self): # Lee el archivo JSON y reconstruye los objetos en memoria
        if os.path.exists(self.catalog_file):
            with open(self.catalog_file, 'r') as f:
                raw_data = json.load(f)
                for name, table_data in raw_data.items():
                    meta = TableMetadata.from_dict(table_data)
                    
                    # Re-instancia el índice físico
                    meta.primary_index = self._get_index_instance(
                        meta.index_tech, meta, meta.key_column
                    )
                    
                    self.catalog[name] = meta
            print(f"[SYSTEM] Catálogo cargado: {list(self.catalog.keys())}")

    def execute(self, ast):
        if not ast:
            return None
        
        if ast['statement'] == 'CREATE':
            return self.execute_create(ast)
        elif ast['statement'] == 'SELECT':
            return self.execute_select(ast)
        elif ast['statement'] == 'INSERT':
            return self.execute_insert(ast)
        elif ast['statement'] == 'DELETE':
            return self.execute_delete(ast)
        elif ast['statement'] == 'DROP':
            return self.execute_drop(ast)
        elif ast['statement'] == 'UPDATE':
            return self.execute_update(ast)
    
    def _get_index_instance(self, tech_name, meta, key_column):
        tech = tech_name.upper() if tech_name else 'NONE'
        
        if tech == 'SEQUENTIAL':
            return SequentialFile(meta, key_column, self.data_dir)
        if tech == "HASH":
            return ExtendibleHashing(meta, key_column, self.data_dir)
        if tech == 'BTREE':
            return BPlusTree(meta, key_column, self.data_dir)
        if tech == 'RTREE':
            return RTreeIndex(meta, key_column, self.data_dir)
        elif tech == 'NONE':
            return HeapFile(meta, key_column, self.data_dir)
        else:
            raise ValueError(f"Técnica no soportada: {tech}")

    def execute_create(self, ast):
        table_name = ast['table']

        key_column = None
        tech_name = None
        for col in ast['columns']:
            if col.get('index'):
                key_column = col['name']
                tech_name = col['index']
                break
        
        if not key_column: # Asume que la primera columna es el índice
            key_column = ast['columns'][0]['name']

        meta = TableMetadata(table_name, ast['columns'], key_column=key_column, index_tech=tech_name)

        # Instancia el gestor físico y lo guarda en el catálogo
        primary_index = self._get_index_instance(tech_name, meta, key_column)
        meta.primary_index = primary_index
        self.catalog[table_name] = meta
        
        print(f"[OK] Tabla {table_name} creada con índice {primary_index.__class__.__name__}.")
        
        self._save_system_catalog()
        file_path = ast.get('file')
        delimiter_char = ast.get('delimiter', ',')

        total_reads = 0
        total_writes = 0

        if file_path:
            full_path = os.path.join("dataset", file_path)
            if os.path.exists(full_path):
                print(f"Delegando carga masiva a {primary_index.__class__.__name__}...")
                
                # Reiniciar contadores antes del bulk_load
                primary_index.disk_reads = 0
                primary_index.disk_writes = 0
                
                primary_index.bulk_load(full_path, delimiter = delimiter_char)
                
                total_reads = primary_index.disk_reads
                total_writes = primary_index.disk_writes
                
                print(f"[OK] Carga masiva completada.")

                self._save_system_catalog()
            else:
                print(f"[ERROR] Archivo {full_path} no encontrado.")

        return {
            "message": f"Tabla {table_name} creada correctamente.",
            "diskReads": total_reads,
            "diskWrites": total_writes
        }
        
    def execute_insert(self, ast):
        table_name = ast['table']
        if table_name not in self.catalog:
            print(f"[ERROR] La tabla {table_name} no existe.")
            return
         
        meta = self.catalog[table_name]
        raw_values = ast['values']
        parsed_values = []
        
        for i, col in enumerate(meta.columns):
            val = raw_values[i]
            tipo = col['type'].upper()
            
            if tipo == 'VARCHAR':
                parsed_values.append(str(val).encode('utf-8'))
            elif tipo == 'INT':
                parsed_values.append(int(val))
            elif tipo == 'FLOAT':
                parsed_values.append(float(val))
            else:
                parsed_values.append(val)
        
        record_tuple = tuple(parsed_values) + (False,)
        
        index = meta.primary_index
        index.disk_reads, index.disk_writes = 0, 0 
        
        index.add(record_tuple)
        
        print(f"[OK] Registro insertado exitosamente.")
        print(f"-> Accesos a disco: {index.disk_reads} reads, {index.disk_writes} writes.")

        return {
            "message": "Registro insertado exitosamente.",
            "diskReads": index.disk_reads,
            "diskWrites": index.disk_writes
        }

    def execute_update(self, ast):
            table_name = ast['table']
            if table_name not in self.catalog:
                print(f"[ERROR] La tabla {table_name} no existe.")
                return

            meta = self.catalog[table_name]
            index = meta.primary_index
            
            # 1. Obtener la llave a buscar
            key_to_update = ast['condition']['key']
            index.disk_reads, index.disk_writes = 0, 0
            
            # 2. Buscar el registro actual (lectura física)
            raw_record = index.search(key_to_update)
            if not raw_record:
                print(f"[INFO] Registro con llave {key_to_update} no encontrado para actualizar.")
                return
                
            # raw_record es una tupla estática en Python, la pasamos a lista para modificarla
            record_list = list(raw_record)
            
            # 3. Modificar los valores según el AST
            set_columns = ast['set'] 
            
            for col_name, new_val in set_columns.items():
                # Buscar el índice de la columna en la metadata de la tabla
                col_idx = -1
                col_type = None
                for i, col in enumerate(meta.columns):
                    if col['name'] == col_name:
                        col_idx = i
                        col_type = col['type'].upper()
                        break
                        
                if col_idx != -1:
                    # Castear el valor de texto del SQL a los bits que guarda python
                    if col_type == 'VARCHAR':
                        parsed_val = str(new_val).encode('utf-8')
                    elif col_type == 'INT':
                        parsed_val = int(new_val)
                    elif col_type == 'FLOAT':
                        parsed_val = float(new_val)
                    else:
                        parsed_val = new_val
                        
                    record_list[col_idx] = parsed_val
            
            modified_record_tuple = tuple(record_list)
            
            # 4. Borrado lógico del original
            index.remove(key_to_update)
            
            # 5. Insertar la tupla modificada
            index.add(modified_record_tuple)
            
            print(f"[OK] Registro con llave '{key_to_update}' actualizado con éxito.")
            print(f"-> Accesos a disco: {index.disk_reads} reads, {index.disk_writes} writes.")

    def execute_delete(self, ast):
        table_name = ast['table']
        if table_name not in self.catalog: 
            return {
                "message": f"La tabla {table_name} no existe.",
                "diskReads": 0,
                "diskWrites": 0
            }
        
        key_to_delete = ast['condition']['key']
        index = self.catalog[table_name].primary_index
        
        index.disk_reads, index.disk_writes = 0, 0 
        
        success = index.remove(key_to_delete)
        
        if success:
            msg = "[OK] Registro eliminado."
            print(f"{msg} Reads: {index.disk_reads}, Writes: {index.disk_writes}")
        else:
            msg = f"[INFO] Registro con llave {key_to_delete} no encontrado."
            print(msg)

        return {
            "message": msg,
            "diskReads": index.disk_reads,
            "diskWrites": index.disk_writes
        }
        
    def execute_select(self, ast):
        table_name = ast['table']
        if table_name not in self.catalog: 
            raise Exception(f"La tabla {table_name} no existe en el catálogo.")

        cond = ast['condition']
        index = self.catalog[table_name].primary_index
        index.disk_reads = 0 
        meta = self.catalog[table_name]
        
        columns = [col['name'] for col in meta.columns]
        rows = []
        raw_results_list = []
        plot_base64 = None
        total_reads = 0
        
        if cond['action'] == 'search':
            raw_result = index.search(cond['key'])
            if raw_result:
                raw_results_list.append(raw_result)
            total_reads = index.disk_reads
            
        elif cond['action'] == 'rangeSearch':
            raw_results_list = index.rangeSearch(cond['begin_key'], cond['end_key'])
            total_reads = index.disk_reads
        
        elif cond['action'] in ['knn', 'range_spatial']:
            point = cond['point']
            param = cond['param']
            is_knn = (cond['action'] == 'knn')
            
            if is_knn:
                raw_results_list = index.knn_search(point, param)
            else:
                raw_results_list = index.rangeSearch(point, param)
            
            total_reads = getattr(index, 'disk_reads', 0)
            if hasattr(index, 'data_storage'):
                total_reads += getattr(index.data_storage, 'disk_reads', 0)
            
            if raw_results_list:
                clean_rows = [meta.clean_tuple(r) for r in raw_results_list]
                
                spatial_col_idx = 0
                for i, col in enumerate(meta.columns):
                    if col['name'] == index.key_column:
                        spatial_col_idx = i
                        break
                        
                result = save_spatial_plot(
                    target_point=point, 
                    clean_results=clean_rows,
                    spatial_col_idx=spatial_col_idx, 
                    search_type="KNN" if is_knn else "RANGE", 
                    param=param,
                    data_dir=getattr(self, 'data_dir', 'backend/data')
                )
                
                if result:
                    if isinstance(result, tuple):
                        img_path, plot_html = result
                        plot_base64 = plot_html
                    else:
                        img_path = result
                        plot_base64 = None

        elif cond['action'] == 'groupby':
            group_col = cond['column']
            
            group_key_index = 0
            for i, col in enumerate(meta.columns): # en qué posición está la columna que debo agrupar?
                if col['name'] == group_col:
                    group_key_index = i
                    break
                    
            hasher = ExternalHashing(
                recordformat=meta.struct_format,
                pagesize=self.PAGE_SIZE if hasattr(self, 'PAGE_SIZE') else 4096,
                buffersize=2 * 1024 * 1024 # 2MB para RAM
            )
            
            #! Manda al archivo físico (Por ahora solo lo soportan Sequential File y Heap File)
            target_file = getattr(index, 'main_file', None) # Sequential
            if not target_file:
                target_file = getattr(index, 'bin_file_path', None) # Heap
                if not target_file:
                    raise Exception("El índice actual no soporta agrupación directa.")
                
            print(f"Ejecutando External Hashing GROUP BY en columna: {group_col}...")
            stats = hasher.externalhashgroupby(target_file, group_key_index)
            
            columns = [group_col, "COUNT"] # Definimos las cabeceras de la tabla resultante
            
            for key, count in stats["result"].items():
                rows.append((key, count)) 
                
            total_reads = stats["pagesread"]

        if cond['action'] != 'groupby':
            order_by_col = ast.get('order_by')
            
            if order_by_col and raw_results_list:
                print(f"Ejecutando External Sort (ORDER BY) en columna: {order_by_col}...")
                
                sort_key_index = 0
                for i, col in enumerate(meta.columns):
                    if col['name'] == order_by_col:
                        sort_key_index = i
                        break
                
                temp_in = os.path.join(getattr(self, 'data_dir', 'backend/data'), "temp_order_in.dat")
                temp_out = os.path.join(getattr(self, 'data_dir', 'backend/data'), "temp_order_out.dat")
                
                self._volcar_a_temporal(raw_results_list, meta, temp_in)
                
                sorter = ExternalSort(
                    record_format=meta.struct_format,
                    page_size=getattr(self, 'PAGE_SIZE', 4096),
                    buffer_size=2 * 1024 * 1024
                )
                stats = sorter.external_sort(temp_in, temp_out, sort_key_index)
                total_reads += stats['pages_read']
                
                raw_results_list = self._leer_desde_temporal(temp_out, meta)
                
                if os.path.exists(temp_in): os.remove(temp_in)
                if os.path.exists(temp_out): os.remove(temp_out)

            # clean tuple
            for r in raw_results_list:
                rows.append(meta.clean_tuple(r))

        return {
            "columns": columns,
            "rows": rows,
            "diskReads": total_reads,
            "diskWrites": 0,
            "plot": plot_base64
        }

    # Auxiliares

    def _parse_csv_row(self, row, columns): # Convierte los strings del CSV a tipos reales de Python antes de pasarlos al index
        parsed = []
        for i, col in enumerate(columns):
            val = row[i].strip()
            tipo = col['type'].upper()
            if tipo == 'INT': parsed.append(int(val))
            elif tipo == 'FLOAT': parsed.append(float(val))
            elif tipo == 'VARCHAR': parsed.append(val.encode('utf-8'))
        
        # is_deleted (False) de Sequential
        parsed.append(False) 
        return tuple(parsed)
    
    def execute_drop(self, ast):
        table_name = ast['table']
        
        if table_name not in self.catalog:
            print(f"[ERROR] La tabla '{table_name}' no existe en el catálogo.")
            return
            
        print(f"Eliminando tabla '{table_name}' y sus archivos físicos...")
        
        pattern = os.path.join(self.data_dir, f"{table_name}_*.dat")
        files_to_delete = glob.glob(pattern)
        
        for file_path in files_to_delete:
            try:
                os.remove(file_path)
                print(f" -> Archivo borrado: {os.path.basename(file_path)}")
            except Exception as e:
                print(f" -> [Advertencia] No se pudo borrar {file_path}: {e}")
                
        del self.catalog[table_name]
        
        self._save_system_catalog()
        
        print(f"[OK] Tabla '{table_name}' eliminada completamente del sistema.")

    def _volcar_a_temporal(self, records, meta, filepath, page_size=4096):
        import struct
        records_per_page = (page_size - 16) // meta.record_size
        with open(filepath, 'wb') as f:
            chunk = []
            for r in records:
                chunk.append(r)
                if len(chunk) == records_per_page:
                    header = struct.pack('i 12x', len(chunk))
                    data = b''.join(struct.pack(meta.struct_format, *c) for c in chunk)
                    padding = b'\x00' * (page_size - 16 - len(data))
                    f.write(header + data + padding)
                    chunk = []
            if chunk:
                header = struct.pack('i 12x', len(chunk))
                data = b''.join(struct.pack(meta.struct_format, *c) for c in chunk)
                padding = b'\x00' * (page_size - 16 - len(data))
                f.write(header + data + padding)

    def _leer_desde_temporal(self, filepath, meta, page_size=4096):
        import struct, os
        resultados = []
        if not os.path.exists(filepath): return resultados
        
        with open(filepath, 'rb') as f:
            while True:
                page = f.read(page_size)
                if not page: break
                
                num_records = struct.unpack('i 12x', page[:16])[0]
                for i in range(num_records):
                    offset = 16 + i * meta.record_size
                    rec_bytes = page[offset : offset + meta.record_size]
                    resultados.append(struct.unpack(meta.struct_format, rec_bytes))
        return resultados
