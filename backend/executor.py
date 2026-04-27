import os
import glob
import json

from backend.catalog import TableMetadata
from backend.indexes.sequential import SequentialFile
from backend.indexes.rtree import RTreeIndex

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
            return
        
        if ast['statement'] == 'CREATE':
            self.execute_create(ast)
        elif ast['statement'] == 'SELECT':
            self.execute_select(ast)
        elif ast['statement'] == 'INSERT':
            self.execute_insert(ast)
        elif ast['statement'] == 'DELETE':
            self.execute_delete(ast)
        elif ast['statement'] == 'DROP':
            self.execute_drop(ast)
    
    def _get_index_instance(self, tech_name, meta, key_column):
        tech = tech_name.upper() if tech_name else 'SEQUENTIAL'
        
        if tech == 'SEQUENTIAL':
            return SequentialFile(meta, key_column, self.data_dir)
        #TODO: elif tech == 'HASH':
        #TODO: elif tech == 'BTREE':
        if tech == 'RTREE':
            return RTreeIndex(meta, key_column, self.data_dir)
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
        
        file_path = ast.get('file')
        delimiter_char = ast.get('delimiter', ',')

        if file_path:
            full_path = os.path.join("dataset", file_path)
            if os.path.exists(full_path):
                print(f"Delegando carga masiva a {primary_index.__class__.__name__}...")
                
                primary_index.bulk_load(full_path, delimiter = delimiter_char)
                
                print(f"[OK] Carga masiva completada.")

                self._save_system_catalog()
            else:
                print(f"[ERROR] Archivo {full_path} no encontrado.")

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

    def execute_delete(self, ast):
        table_name = ast['table']
        if table_name not in self.catalog: return
        
        key_to_delete = ast['condition']['key']
        index = self.catalog[table_name].primary_index
        
        index.disk_reads, index.disk_writes = 0, 0 
        
        success = index.remove(key_to_delete)
        if success:
            print(f"[OK] Registro eliminado. Reads: {index.disk_reads}, Writes: {index.disk_writes}")
        else:
            print(f"[INFO] Registro con llave {key_to_delete} no encontrado.")

    def execute_select(self, ast):
        table_name = ast['table']
        if table_name not in self.catalog: return

        cond = ast['condition']
        index = self.catalog[table_name].primary_index
        index.disk_reads = 0 
        meta = self.catalog[table_name]
        
        if cond['action'] == 'search':
            raw_result = index.search(cond['key'])
            print(f"\nResultado de la búsqueda:")
            
            if raw_result:
                clean_result = meta.clean_tuple(raw_result)
                print(clean_result)
            else:
                print("No encontrado.")
                
            print(f"-> Accesos a disco de lectura: {index.disk_reads}")
            
        elif cond['action'] == 'rangeSearch':
            raw_results = index.rangeSearch(cond['begin_key'], cond['end_key'])
            print(f"\nResultados por rango ({len(raw_results)} filas):")
            
            for r in raw_results:
                print(meta.clean_tuple(r))
                
            print(f"-> Accesos a disco de lectura: {index.disk_reads}")
        
        elif cond['action'] in ['knn', 'range_spatial']:
            point = cond['point']
            param = cond['param']
            is_knn = (cond['action'] == 'knn')
            
            tipo_txt = f"KNN ({param} vecinos)" if is_knn else f"Radio ({param} unidades)"
            print(f"\nEjecutando Búsqueda por {tipo_txt} alrededor de {point}...")
            
            if is_knn:
                raw_results = index.knn_search(point, param)
            else:
                raw_results = index.rangeSearch(point, param)
            
            total_reads = index.disk_reads + index.data_storage.disk_reads
            
            if raw_results:
                clean_results_list = []
                for r in raw_results:
                    clean = meta.clean_tuple(r)
                    clean_results_list.append(clean)
                    print(clean)
                    
                # Generacion de imagen
                spatial_col_idx = 0
                for i, col in enumerate(meta.columns):
                    if col['name'] == index.key_column:
                        spatial_col_idx = i
                        break
                        
                img_path = save_spatial_plot(
                    target_point=point, 
                    clean_results=clean_results_list, 
                    spatial_col_idx=spatial_col_idx, 
                    search_type="KNN" if is_knn else "RANGE", 
                    param=param,
                    data_dir=self.data_dir
                )
                print(f"-> Gráfico guardado en: {img_path}")
            else:
                print("No se encontraron resultados en esa área.")
                
            print(f"-> Accesos a disco de lectura R-Tree y Secuencial: {total_reads}")

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