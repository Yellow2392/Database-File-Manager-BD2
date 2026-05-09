import os
import glob
import json

from backend.catalog import TableMetadata
from backend.indexes.sequential import SequentialFile
from backend.indexes.rtree import RTreeIndex
from backend.indexes.hash import ExtendibleHashing
from backend.indexes.heapFileIndex import HeapFile

from backend.external.external_hashing import ExternalHashing
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
    
    def _get_index_instance(self, tech_name, meta, key_column):
        tech = tech_name.upper() if tech_name else 'NONE'
        
        if tech == 'SEQUENTIAL':
            return SequentialFile(meta, key_column, self.data_dir)
        elif tech == "HASH":                                      
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
        
        print(f"[OK] Tabla {table_name} creada con índice  {primary_index.__class__.__name__}.")
        


        
        ####################################################
        #GUARDAR CATALOGO EN CREACION DE TABLA SINH BULKLOAD
        ####################################################
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
        plot_base64 = None
        total_reads = 0
        
        if cond['action'] == 'search':
            raw_result = index.search(cond['key'])
            if raw_result:
                clean_result = meta.clean_tuple(raw_result)
                rows.append(clean_result)
            total_reads = index.disk_reads
            
        elif cond['action'] == 'rangeSearch':
            raw_results = index.rangeSearch(cond['begin_key'], cond['end_key'])
            for r in raw_results:
                rows.append(meta.clean_tuple(r))
            total_reads = index.disk_reads
        
        elif cond['action'] in ['knn', 'range_spatial']:
            point = cond['point']
            param = cond['param']
            is_knn = (cond['action'] == 'knn')
            
            if is_knn:
                raw_results = index.knn_search(point, param)
            else:
                raw_results = index.rangeSearch(point, param)
            
            total_reads = getattr(index, 'disk_reads', 0)
            if hasattr(index, 'data_storage'):
                total_reads += getattr(index.data_storage, 'disk_reads', 0)
            
            if raw_results:
                for r in raw_results:
                    clean = meta.clean_tuple(r)
                    rows.append(clean)
                    
                # Generacion de imagen
                spatial_col_idx = 0
                for i, col in enumerate(meta.columns):
                    if col['name'] == index.key_column:
                        spatial_col_idx = i
                        break
                        
                result = save_spatial_plot(
                    target_point=point, 
                    clean_results=rows, 
                    spatial_col_idx=spatial_col_idx, 
                    search_type="KNN" if is_knn else "RANGE", 
                    param=param,
                    data_dir=self.data_dir
                )
                
                # Manejo de retorno dual: (filepath, html_string)
                if result:
                    if isinstance(result, tuple):
                        img_path, plot_html = result
                        plot_base64 = plot_html  # Enviamos el HTML interactivo
                    else:
                        # Compatibilidad con versiones anteriores si solo retorna filepath
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