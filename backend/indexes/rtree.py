import os
import struct
import csv
import math
import heapq 
import itertools

from .base import BaseIndex
from .sequential import SequentialFile

class Point:
    def __init__(self, x, y, pk=None):
        self.x = float(x)
        self.y = float(y)
        self.pk = pk 

    def distance_to(self, other):
        dx = self.x - other.x
        dy = self.y - other.y
        return math.sqrt(dx * dx + dy * dy)

class MBB:
    def __init__(self, min_x, min_y, max_x, max_y):
        self.min_x = float(min_x)
        self.min_y = float(min_y)
        self.max_x = float(max_x)
        self.max_y = float(max_y)

    def area(self):
        return (self.max_x - self.min_x) * (self.max_y - self.min_y)
        
    def distance_to(self, p: Point):
        dx = max(self.min_x - p.x, 0.0, p.x - self.max_x)
        dy = max(self.min_y - p.y, 0.0, p.y - self.max_y)
        return math.sqrt(dx * dx + dy * dy)
    
class RTreeIndex(BaseIndex):
    def __init__(self, table_meta, key_column, data_dir="backend/data"):
        super().__init__(table_meta, key_column, data_dir)
        # El archivo de nodos del R-Tree
        self.tree_file = os.path.join(self.data_dir, f"{table_meta.name}_rtree.dat")
        
        # El sequential manejará los datos pesados
        self.data_storage = SequentialFile(table_meta, key_column, data_dir)
        
        self.M = 200 # maxEntries
        self.m = self.M // 2
        
        # Formato de cabecera: is_leaf (?), num_entries (i), padding (11x)
        self.header_fmt = '=? i 11x' 
        # Formato de entrada: min_x, min_y, max_x, max_y (ffff), pointer/pk (i)
        self.entry_fmt = '=f f f f i' 
        self.entry_size = struct.calcsize(self.entry_fmt) # 20 bytes
        
        if not os.path.exists(self.tree_file) or os.path.getsize(self.tree_file) == 0:
            self._initialize_empty_tree()

    def _initialize_empty_tree(self): # Crea el nodo root (pagina 0) vacío como hoja
        with open(self.tree_file, 'wb') as f:
            header = struct.pack(self.header_fmt, True, 0)
            page = header + (b'\x00' * (self.PAGE_SIZE - 16))
            f.write(page)
            self.disk_writes += 1

    def _read_node(self, page_id): # Lee una página de disco y devuelve sus datos desglosados
        with open(self.tree_file, 'rb') as f:
            f.seek(page_id * self.PAGE_SIZE)
            page_data = f.read(self.PAGE_SIZE)
            self.disk_reads += 1
            
            is_leaf, num_entries = struct.unpack(self.header_fmt, page_data[:16])
            
            entries = []
            for i in range(num_entries):
                offset = 16 + (i * self.entry_size)
                entry_bytes = page_data[offset : offset + self.entry_size]
                min_x, min_y, max_x, max_y, pointer = struct.unpack(self.entry_fmt, entry_bytes)
                
                # Si es hoja, el puntero es el PK. Si es interno, el puntero es otro page_id.
                entries.append({
                    'mbb': MBB(min_x, min_y, max_x, max_y),
                    'pointer': pointer 
                })
                
            return is_leaf, entries

    def _write_node(self, page_id, is_leaf, entries): #Empaqueta y escribe una pagina al disco
        with open(self.tree_file, 'r+b') as f:
            f.seek(page_id * self.PAGE_SIZE)
            
            header = struct.pack(self.header_fmt, is_leaf, len(entries))
            page_data = bytearray(header)
            
            for entry in entries:
                mbb = entry['mbb']
                entry_bytes = struct.pack(self.entry_fmt, mbb.min_x, mbb.min_y, mbb.max_x, mbb.max_y, entry['pointer'])
                page_data.extend(entry_bytes)
                
            padding = self.PAGE_SIZE - len(page_data)
            page_data.extend(b'\x00' * padding)
            
            f.write(page_data)
            self.disk_writes += 1

    def knn_search(self, target_point_tuple, k):
        target = Point(target_point_tuple[0], target_point_tuple[1])
        
        # Min-Heap 
        counter = itertools.count() # Evita empates en distancias
        pq = []

        root_page = self._get_root_page_id()
        
        # Distancia a la raíz para empezar
        heapq.heappush(pq, (0.0, next(counter), True, root_page, None)) 
        
        pks_encontrados = []
        
        while pq and len(pks_encontrados) < k:
            dist, _, is_node, id_val, obj = heapq.heappop(pq)
            
            if is_node:
                page_id = id_val
                is_leaf, entries = self._read_node(page_id)
                
                if is_leaf:
                    # Si es hoja, las entradas son puntos
                    for entry in entries:
                        mbb = entry['mbb']
                        # Como es un punto, min_x = max_x
                        p = Point(mbb.min_x, mbb.min_y, entry['pointer'])
                        d = p.distance_to(target)
                        heapq.heappush(pq, (d, next(counter), False, p.pk, p))
                else:
                    # Si es interno, cual es la distancia a los MBBs hijos?
                    for entry in entries:
                        mbb = entry['mbb']
                        child_page_id = entry['pointer']
                        d = mbb.distance_to(target)
                        heapq.heappush(pq, (d, next(counter), True, child_page_id, mbb))
            else:
                # Si es un punto real -> se agrega a resultados
                pk_val = id_val
                pks_encontrados.append(pk_val)
                
        resultados_completos = []
        for pk in pks_encontrados:
            # Busca la data pesada en el archivo secuencial
            tupla_data = self.data_storage.search(pk)
            if tupla_data:
                resultados_completos.append(tupla_data)
                
        return resultados_completos
    
    def rangeSearch(self, target_point_tuple, radius):
        target = Point(target_point_tuple[0], target_point_tuple[1])
        pks_encontrados = []
        
        root_page = self._get_root_page_id()
        stack = [root_page]
        
        while stack:
            page_id = stack.pop()
            is_leaf, entries = self._read_node(page_id)
            
            for entry in entries:
                mbb = entry['mbb']
                
                # Intercepta al circulo?
                if mbb.distance_to(target) <= radius:
                    
                    if is_leaf:
                        # Distancia exacta del punto al centro
                        p = Point(mbb.min_x, mbb.min_y)
                        if p.distance_to(target) <= radius:
                            pks_encontrados.append(entry['pointer'])
                    else:
                        # Si es un nodo interno, hay que explorar esa pagina hija
                        child_page_id = entry['pointer']
                        stack.append(child_page_id)
                        
        # Mapeo logico en sequential file
        resultados_completos = []
        for pk in pks_encontrados:
            tupla_data = self.data_storage.search(pk)
            if tupla_data:
                resultados_completos.append(tupla_data)
                
        return resultados_completos
    
    def bulk_load(self, csv_path, delimiter=','):
        open(self.tree_file, 'wb').close() # limpia archivos
        open(self.data_storage.main_file, 'wb').close() # limpia secuencial
        
        entries_hojas = []
        
        idx_x, idx_y = self._get_spatial_indices()

        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter=delimiter)
            next(reader, None) 
            
            for row in reader:
                parsed_row = self.data_storage._parse_row(row, self.table_meta.columns)
                
                # Asume que la llave primaria está en la posición 0
                pk = parsed_row[0] 
                
                # Inserta en el secuencial
                self.data_storage.add(parsed_row, is_bulk=True)
                
                # Extraemos X e Y manualmente para el RTree
                x = parsed_row[idx_x] 
                y = parsed_row[idx_y]
                
                entries_hojas.append({
                    'mbb': MBB(x, y, x, y), # Es un punto, min y max son iguales
                    'pointer': pk # Apunta al registro del SequentialFile
                })
                
        # Reconstruye para que quede ordenado
        if hasattr(self.data_storage, '_rebuild'):
            self.data_storage._rebuild()
        
        # Se reserva la página 0
        self.next_page_id = 1 
        root_page_id, _ = self._str_pack(entries_hojas, is_leaf=True)
        
        with open(self.tree_file, 'r+b') as f:
            f.seek(0)
            f.write(struct.pack('i', root_page_id) + (b'\x00' * 4092))
            
        print(f"[OK] R-Tree guardado en disco. Raíz ubicada en la página física {root_page_id}.")

    def _get_root_page_id(self): # Lee para saber dónde empieza el árbol
        with open(self.tree_file, 'rb') as f:
            f.seek(0)
            return struct.unpack('i', f.read(4))[0]
        
    def _str_pack(self, entries, is_leaf): 
        # Si los elementos caben en una sola página
        if len(entries) <= self.M:
            return self._write_node_to_disk(entries, is_leaf)

        P = math.ceil(len(entries) / self.M) # paginas necesarias
        S = math.ceil(math.sqrt(P)) # franjas

        entries.sort(key=lambda e: (e['mbb'].min_x + e['mbb'].max_x) / 2) # ordenado por X

        next_level_entries = []
        slice_size = S * self.M

        # Procesa franjas verticals
        for i in range(0, len(entries), slice_size):
            vertical_slice = entries[i : i + slice_size]            
            vertical_slice.sort(key=lambda e: (e['mbb'].min_y + e['mbb'].max_y) / 2) # Ordena la franja por Y

            # Agrupa en bloques de tamaño M
            for j in range(0, len(vertical_slice), self.M):
                node_entries = vertical_slice[j : j + self.M]

                page_id, node_mbb = self._write_node_to_disk(node_entries, is_leaf)

                # Crea el puntero que el nodo padre usará para apuntar a esta página
                next_level_entries.append({
                    'mbb': node_mbb,
                    'pointer': page_id
                })

        # Se arma el nivel superior
        return self._str_pack(next_level_entries, is_leaf=False)

    def _write_node_to_disk(self, entries, is_leaf):
        page_id = self.next_page_id
        self.next_page_id += 1

        # Bounding box global de este nodo
        min_x = min(e['mbb'].min_x for e in entries)
        min_y = min(e['mbb'].min_y for e in entries)
        max_x = max(e['mbb'].max_x for e in entries)
        max_y = max(e['mbb'].max_y for e in entries)
        node_mbb = MBB(min_x, min_y, max_x, max_y)

        with open(self.tree_file, 'r+b' if page_id > 0 else 'wb') as f:
            f.seek(page_id * self.PAGE_SIZE)
            # Header del nodo
            header = struct.pack(self.header_fmt, is_leaf, len(entries))
            page_data = bytearray(header)

            # Contenido de cada entrada
            for entry in entries:
                mbb = entry['mbb']
                entry_bytes = struct.pack(self.entry_fmt, mbb.min_x, mbb.min_y, mbb.max_x, mbb.max_y, entry['pointer'])
                page_data.extend(entry_bytes)

            padding = self.PAGE_SIZE - len(page_data)
            page_data.extend(b'\x00' * padding)
            
            f.write(page_data)
            self.disk_writes += 1

        return page_id, node_mbb
    
    def _get_spatial_indices(self):
        # Calcula en qué posiciones de la tupla parseada se encuentran las coordenadas x, y de la columna indexada
        tuple_index = 0
        
        for col in self.table_meta.columns:
            if col['name'] == self.key_column:
                return tuple_index, tuple_index + 1
                
            if col['type'].upper() == 'POINT':
                tuple_index += 2 # Los point ocupan 2 posiciones
            else:
                tuple_index += 1  # Los demas ocupan 1 posicion
                
        raise ValueError(f"Columna índice '{self.key_column}' no encontrada en la metadata.")
    
    def add(self, record_tuple, is_bulk=False):
        return NotImplementedError("INSERT no soportado en RTree")
    
    def search(self, key_value):
        return NotImplementedError("SELECT puntual no soportado en RTree")

    def remove(self, key_value):
        return NotImplementedError("REMOVE no soportado en RTree")