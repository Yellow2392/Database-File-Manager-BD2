import struct
import os
import re
import itertools
from backend.catalog import TYPE_MAP
from .base import BaseIndex
from .heapFile import HeapFile
from backend.external.external_sort import ExternalSort
import csv

class BPlusNode:
    HEADER_FORMAT = 'BBiii'  # node_type, is_root, num_keys, parent_ptr, next_leaf
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    INT_SIZE = struct.calcsize('i')  # para punteros
    PTR_FORMAT = 'i'

    def __init__(
        self,
        key_fmt,
        key_size,
        order,
        page_size,
        node_type=1,
        is_root=0,
        num_keys=0,
        parent_ptr=-1,
        next_leaf=-1
    ):
        # configuración viene del BTreeIndex
        self.key_fmt = key_fmt
        self.key_size = key_size
        self.ORDER = order # máximo número de claves
        self.PAGE_SIZE = page_size

        # metadata del nodo
        self.node_type = node_type  # 0 = interno, 1 = hoja
        self.is_root = is_root
        self.num_keys = num_keys
        self.parent_ptr = parent_ptr
        self.next_leaf = next_leaf

        self.keys = []
        self.pointers = []

    # pack del header
    def pack_header(self):
        return struct.pack(
            self.HEADER_FORMAT,
            self.node_type,
            self.is_root,
            self.num_keys,
            self.parent_ptr,
            self.next_leaf
        )
    # unpack del header
    @staticmethod
    def unpack_header(data):
        return struct.unpack(BPlusNode.HEADER_FORMAT, data)

    # pack del nodo
    def pack(self):
        header_data = self.pack_header()
        chunks = []

        MAX_BODY_SIZE = self.PAGE_SIZE - self.HEADER_SIZE

        if self.node_type == 0:  # nodo interno
            # keys
            for i in range(self.num_keys):
                chunks.append(struct.pack(self.key_fmt, self.keys[i]))

            # padding keys
            chunks.append(b'\x00' * ((self.ORDER - self.num_keys) * self.key_size))

            # punteros
            for i in range(self.num_keys + 1):
                chunks.append(struct.pack('i', self.pointers[i]))

            # padding punteros
            chunks.append(
                b'\x00' * ((self.ORDER + 1 - (self.num_keys + 1)) * self.INT_SIZE)
            )

        else:  # nodo hoja
            for i in range(self.num_keys):
                chunks.append(struct.pack(self.key_fmt, self.keys[i]))
                chunks.append(struct.pack('i', self.pointers[i]))

            current_size = self.num_keys * (self.key_size + self.INT_SIZE)
            padding_size = MAX_BODY_SIZE - current_size

            if padding_size > 0:
                chunks.append(b'\x00' * padding_size)

        # unir todo
        body_data = b''.join(chunks)

        if len(body_data) < MAX_BODY_SIZE: #asegurar que ocupe toda el body
            body_data += b'\x00' * (MAX_BODY_SIZE - len(body_data))

        return header_data + body_data[:MAX_BODY_SIZE] # por si acaso si hay overflow

    # unpack del nodo
    @classmethod
    def unpack(cls, data, key_fmt, key_size, order, page_size):
        header = data[:cls.HEADER_SIZE]
        node_type, is_root, num_keys, parent_ptr, next_leaf = cls.unpack_header(header)

        node = cls(
            key_fmt,
            key_size,
            order,
            page_size,
            node_type,
            is_root,
            num_keys,
            parent_ptr,
            next_leaf
        )

        body = data[cls.HEADER_SIZE:]
        offset = 0

        if node.node_type == 0:  # interno
            # keys
            for _ in range(node.num_keys):
                key, = struct.unpack(node.key_fmt, body[offset:offset + node.key_size])
                node.keys.append(key)
                offset += node.key_size

            offset += (node.ORDER - node.num_keys) * node.key_size

            # punteros
            for _ in range(node.num_keys + 1):
                ptr, = struct.unpack('i', body[offset:offset + cls.INT_SIZE])
                node.pointers.append(ptr)
                offset += cls.INT_SIZE

        else:  # hoja
            for _ in range(node.num_keys):
                key, = struct.unpack(node.key_fmt, body[offset:offset + node.key_size])
                offset += node.key_size

                ptr, = struct.unpack('i', body[offset:offset + cls.INT_SIZE])
                offset += cls.INT_SIZE

                node.keys.append(key)
                node.pointers.append(ptr)
        return node
    

class BPlusTree(BaseIndex):
    HEADER_FORMAT = 'ii'  # root_ptr, total_nodes
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    TEMP_PAGE_HEADER_FORMAT = 'i12x'
    TEMP_PAGE_HEADER_SIZE = struct.calcsize(TEMP_PAGE_HEADER_FORMAT)

    def __init__(self, table_meta, key_column, data_dir="backend/data", sort_buffer_size=128 * 1024 * 1024, heap_chunk_size=20000):
        super().__init__(table_meta, key_column, data_dir)

        # tipo de clave desde metadata
        key_type = None
        for col in table_meta.columns:
            if col["name"] == key_column:
                key_type = col["type"].upper()
                break

        if key_type is None:
            raise ValueError("Key column not found")
        
        self.filename = os.path.join(self.data_dir, f"{self.table_meta.name}_{self.key_column}_bplustree.dat")

        self.key_fmt = TYPE_MAP[key_type]['fmt']
        self.key_size = TYPE_MAP[key_type]['size']
        self.key_type = key_type
        self.sort_buffer_size = sort_buffer_size
        self.heap_chunk_size = heap_chunk_size

        # ORDER basado en PAGE_SIZE
        self.ORDER = (self.PAGE_SIZE - BPlusNode.HEADER_SIZE - BPlusNode.INT_SIZE) // (
            self.key_size + BPlusNode.INT_SIZE
        )

        if self.ORDER < 2:
            raise ValueError("ORDER too small for given PAGE_SIZE and key type")
        
        self.heap_path = os.path.join(self.data_dir,f"{self.table_meta.name}.heap")
        self.heap = HeapFile(
            table_meta=self.table_meta,
            filepath=self.heap_path,
            page_size=self.PAGE_SIZE
        )

        # crear archivo si no existe
        if not os.path.exists(self.filename):
            with open(self.filename, 'wb') as f:
                # header inicial
                root_ptr = self.HEADER_SIZE
                total_nodes = 1

                f.write(struct.pack(self.HEADER_FORMAT, root_ptr, total_nodes))

                # crear nodo raíz vacío
                root = BPlusNode(
                    self.key_fmt,
                    self.key_size,
                    self.ORDER,
                    self.PAGE_SIZE,
                    node_type=1,  # hoja
                    is_root=1
                )

                root.keys = []
                root.pointers = []
                root.num_keys = 0

                f.write(root.pack())

    # header del btreeeee
    def _read_header(self):
        with open(self.filename, 'rb') as f:
            f.seek(0)
            data = f.read(self.HEADER_SIZE)
            return struct.unpack(self.HEADER_FORMAT, data)


    def _write_header(self, root_ptr, total_nodes):
        with open(self.filename, 'r+b') as f:
            f.seek(0)
            f.write(struct.pack(self.HEADER_FORMAT, root_ptr, total_nodes))

    # nodo del btreeeee
    def _read_node(self, offset):
        with open(self.filename, 'rb') as f:
            f.seek(offset)

            data = f.read(self.PAGE_SIZE)

        self.disk_reads += 1
        node = BPlusNode.unpack(
            data,
            self.key_fmt,
            self.key_size,
            self.ORDER,
            self.PAGE_SIZE
        )

        # Post-process VARCHAR keys to decode from bytes to str
        if self.key_type == 'VARCHAR':
            node.keys = [key.decode('utf-8').rstrip('\x00') for key in node.keys]

        return node
    
    def _write_node(self, node, offset):

        # guardar originales
        original_keys = node.keys

        # usar copia normalizada SOLO para pack
        node.keys = [
            self._normalize_key_value(k)
            for k in original_keys
        ]

        with open(self.filename, 'r+b') as f:

            f.seek(0, 2)
            current_size = f.tell()

            if offset + self.PAGE_SIZE > current_size:
                f.write(
                    b'\x00' * (
                        offset + self.PAGE_SIZE - current_size
                    )
                )

            f.seek(offset)
            f.write(node.pack())

        # restaurar originales
        node.keys = original_keys

        self.disk_writes += 1
        
    #comparar claves
    def _is_numeric(self, value):
        return isinstance(value, (int, float)) or (
            isinstance(value, str) and re.fullmatch(r"-?\d+(?:\.\d+)?", value.strip())
        )

    def _normalize_key_value(self, key):
        if key is None:
            return None

        if self.key_type == 'FLOAT':
            try:
                value = float(key)
                normalized, = struct.unpack('f', struct.pack('f', value))
                return normalized
            except Exception:
                return key

        if self.key_type == 'VARCHAR':
            if isinstance(key, bytes):
                return key
            try:
                s = str(key)[:50]  # Truncate to 50 chars
                padded = s.encode('ascii', 'ignore').ljust(50, b'\x00')
                return padded
            except Exception:
                return key

        return key

    def _compare_keys(self, a, b):
        """
        Returns:
            -1 if a < b
            0 if a == b
            1 if a > b
        """
        # None
        if a is None and b is None:
            return 0
        if a is None:
            return -1
        if b is None:
            return 1

        if self.key_type == 'FLOAT':
            a = self._normalize_key_value(a)
            b = self._normalize_key_value(b)

        if self.key_type == 'VARCHAR':
            if isinstance(a, bytes):
                a = a.decode('ascii').rstrip('\x00')
            if isinstance(b, bytes):
                b = b.decode('ascii').rstrip('\x00')
            a = str(a).rstrip('\x00')
            b = str(b).rstrip('\x00')

        # numeric
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return (a > b) - (a < b)

        # Numeric como strings
        try:
            if self._is_numeric(a) and self._is_numeric(b):
                fa = float(str(a))
                fb = float(str(b))
                if self.key_type == 'FLOAT':
                    fa, = struct.unpack('f', struct.pack('f', fa))
                    fb, = struct.unpack('f', struct.pack('f', fb))
                return (fa > fb) - (fa < fb)
        except Exception:
            pass

        # string comparison
        sa = str(a)
        sb = str(b)

        if sa == sb:
            return 0

        return 1 if sa > sb else -1
    

    #busquda binaria
    def _binary_search_internal(self, node, key): # Devuelve el índice del puntero por donde bajar
        left, right = 0, node.num_keys - 1
        result = node.num_keys

        while left <= right:
            mid = (left + right) // 2

            if self._compare_keys(node.keys[mid], key) <= 0:
                left = mid + 1
            else:
                result = mid
                right = mid - 1

        # asegurar índice válido de punteros
        return min(result, len(node.pointers) - 1)
    
    def _binary_search_leaf(self, node, key):

        left, right = 0, node.num_keys - 1
        result = -1

        while left <= right:

            mid = (left + right) // 2

            cmp_value = self._compare_keys(node.keys[mid], key)

            if cmp_value == 0:
                result = mid
                right = mid - 1

            elif cmp_value > 0:
                right = mid - 1

            else:
                left = mid + 1

        return result

    def _min_keys_leaf(self):
        return (self.ORDER + 1) // 2

    def _min_keys_internal(self):
        return (self.ORDER + 2) // 2 - 1

    def _find_first_leaf(self, key): #devuelve nodo hoja donde podria esta la primera key y el indice
        root_ptr, _ = self._read_header()
        node = self._read_node(root_ptr)

        while node.node_type == 0:
            left, right = 0, node.num_keys - 1
            result = node.num_keys

            while left <= right:
                mid = (left + right) // 2

                if self._compare_keys(node.keys[mid], key) < 0:
                    left = mid + 1
                else:
                    result = mid
                    right = mid - 1

            idx = min(result, len(node.pointers) - 1)
            node = self._read_node(node.pointers[idx])

        # calcular índice dentro de la hoja
        left, right = 0, node.num_keys - 1
        result = node.num_keys

        while left <= right:
            mid = (left + right) // 2

            if self._compare_keys(node.keys[mid], key) < 0:
                left = mid + 1
            else:
                result = mid
                right = mid - 1

        return node, result
    
    def search_one(self, key):

        results = self.search_all(key)

        if not results:
            return None

        return results[0]

    def search_all(self, key):
        node, idx = self._find_first_leaf(key)

        results = []

        while True:
            stop = False

            #empezar desde idx soloo en la primera hoja
            start = idx if node else 0

            for i in range(start, node.num_keys):
                k = node.keys[i]
                p = node.pointers[i]

                res = self._compare_keys(k, key)

                if res == 0:
                    results.append(p)

                elif res > 0:
                    stop = True
                    break

            if stop:
                break

            if node.next_leaf == -1:
                break

            node = self._read_node(node.next_leaf)
            idx = 0  # siguientes hojas empiezan desde 0

        return results
    
    def search(self, key_value):
        offsets = self.search_all(key_value)

        if not offsets:
            return None

        records = self.heap.read_many(offsets)
        if not records:
            return None
        return records[0]

    def range_search_1(self, begin_key, end_key):
        if begin_key is None or end_key is None:
            return []

        if self._compare_keys(begin_key, end_key) > 0:
            begin_key, end_key = end_key, begin_key

        node, idx = self._find_first_leaf(begin_key)

        results = []

        while True:
            #idx solo en la primera hoja
            start = idx if node else 0

            for i in range(start, node.num_keys):
                k = node.keys[i]
                p = node.pointers[i]

                if self._compare_keys(k, end_key) > 0:
                    return results

                results.append(p)

            if node.next_leaf == -1:
                break

            node = self._read_node(node.next_leaf)
            idx = 0  #siguientes hojas empiezan desde 0

        return results
    
    def rangeSearch(self, begin_key, end_key):
        offsets = self.range_search_1(begin_key, end_key)

        if not offsets:
            return []

        records = self.heap.read_many(offsets)
        return records


    def insert(self, key, pointer):
        root_ptr, _ = self._read_header()

        result = self._insert_recursive(key, pointer, root_ptr)

        # si hubo split que llegó a la raíz
        if result is not None:
            promoted_key, new_child_ptr = result

            old_root_ptr = root_ptr

            #nueva raiz
            new_root = BPlusNode(
                self.key_fmt,
                self.key_size,
                self.ORDER,
                self.PAGE_SIZE,
                node_type=0,
                is_root=1
            )

            new_root.keys = [promoted_key]
            new_root.pointers = [old_root_ptr, new_child_ptr]
            new_root.num_keys = 1
            new_root.parent_ptr = -1

            #quitando flag de root al antiguo
            old_root = self._read_node(old_root_ptr)
            old_root.is_root = 0
            self._write_node(old_root, old_root_ptr)

            #ofset del nuevo nodo
            _, total_nodes = self._read_header()
            new_root_ptr = self.HEADER_SIZE + total_nodes * self.PAGE_SIZE

            self._write_node(new_root, new_root_ptr)

            # old root ahora apunta a nueva root
            old_root.parent_ptr = new_root_ptr
            self._write_node(old_root, old_root_ptr)

            # nuevo hijo también apunta a nueva root
            new_child = self._read_node(new_child_ptr)

            new_child.parent_ptr = new_root_ptr

            self._write_node(new_child, new_child_ptr)

            # actualizar header
            self._write_header(
                root_ptr=new_root_ptr,
                total_nodes=total_nodes + 1
            )

    def add(self, record_tuple, is_bulk = False):
        offset = self.heap.insert(record_tuple)

        key_idx = None

        for i, col in enumerate(self.table_meta.columns):
            if col["name"] == self.key_column:
                key_idx = i
                break

        key = record_tuple[key_idx]
        self.insert(key, offset)

        return offset

    def _insert_in_leaf(self, node, key, pointer):
        key = self._normalize_key_value(key)

        left, right = 0, node.num_keys

        while left < right:
            mid = (left + right) // 2

            if self._compare_keys(node.keys[mid], key) <= 0:
                left = mid + 1
            else:
                right = mid

        idx = left

        node.keys.insert(idx, key)
        node.pointers.insert(idx, pointer)
        node.num_keys += 1

    def _insert_in_internal(self, node, key, pointer):
        key = self._normalize_key_value(key)

        left, right = 0, node.num_keys

        while left < right:
            mid = (left + right) // 2

            if self._compare_keys(node.keys[mid], key) <= 0:
                left = mid + 1
            else:
                right = mid

        idx = left

        node.keys.insert(idx, key)
        node.pointers.insert(idx + 1, pointer)
        node.num_keys += 1
    
    def _insert_recursive(self, key, pointer, node_ptr):
        node = self._read_node(node_ptr)

        # hoja
        if node.node_type == 1:
            self._insert_in_leaf(node, key, pointer)
            self._write_node(node, node_ptr)

            if node.num_keys > self.ORDER:
                return self._split_leaf(node, node_ptr)

            return None

        #interno
        else:
            child_idx = self._binary_search_internal(node, key)
            child_ptr = node.pointers[child_idx]

            result = self._insert_recursive(key, pointer, child_ptr)

            #si el hijo hizo split
            if result is not None:
                promoted_key, new_child_ptr = result

                self._insert_in_internal(node, promoted_key, new_child_ptr)

                if node.num_keys > self.ORDER:
                    self._write_node(node, node_ptr)
                    return self._split_internal(node, node_ptr)
                else:
                    self._write_node(node, node_ptr)

            return None

    def _split_leaf(self, node, node_ptr):
        mid = node.num_keys // 2

        new_node = BPlusNode(
            self.key_fmt,
            self.key_size,
            self.ORDER,
            self.PAGE_SIZE,
            node_type=1,
            is_root=0
        )

        new_node.parent_ptr = node.parent_ptr

        # reservar espacio en disco
        root_ptr, total_nodes = self._read_header()
        new_node_ptr = self.HEADER_SIZE + total_nodes * self.PAGE_SIZE

        # dividir contenido
        new_node.keys = node.keys[mid:]
        new_node.pointers = node.pointers[mid:]
        new_node.num_keys = len(new_node.keys)
        new_node.next_leaf = node.next_leaf

        #actualizar nodo original
        node.keys = node.keys[:mid]
        node.pointers = node.pointers[:mid]
        node.num_keys = len(node.keys)
        node.next_leaf = new_node_ptr

        #escribir ambos nodos
        self._write_node(node, node_ptr)
        self._write_node(new_node, new_node_ptr)

        #actualizar header (nuevo nodo creado)
        self._write_header(root_ptr, total_nodes + 1)

        #clave promovida
        promoted_key = new_node.keys[0]

        return promoted_key, new_node_ptr

    def _split_internal(self, node, node_ptr):
        mid = node.num_keys // 2
        promoted_key = node.keys[mid]

        #crear nuevo nodo interno
        new_node = BPlusNode(
            self.key_fmt,
            self.key_size,
            self.ORDER,
            self.PAGE_SIZE,
            node_type=0,
            is_root=0
        )

        new_node.parent_ptr = node.parent_ptr

        # reservar espacio
        root_ptr, total_nodes = self._read_header()
        new_node_ptr = self.HEADER_SIZE + total_nodes * self.PAGE_SIZE

        # dividir (mid no se queda en ninguno)
        new_node.keys = node.keys[mid + 1:]
        new_node.pointers = node.pointers[mid + 1:]
        new_node.num_keys = len(new_node.keys)

        # actualizar parent_ptr de hijos movidos
        for child_ptr in new_node.pointers:

            child = self._read_node(child_ptr)

            child.parent_ptr = new_node_ptr

            self._write_node(child, child_ptr)

        # nodo original
        node.keys = node.keys[:mid]
        node.pointers = node.pointers[:mid + 1]
        node.num_keys = len(node.keys)

        # escribir
        self._write_node(node, node_ptr)
        self._write_node(new_node, new_node_ptr)

        # actualizar header
        self._write_header(root_ptr, total_nodes + 1)

        return promoted_key, new_node_ptr
    def delete(self, key):
        root_ptr, total_nodes = self._read_header()

        deleted = self._delete_recursive(key, root_ptr)
        if deleted is None:
            return None

        root = self._read_node(root_ptr)

        # si raíz interna queda vacía -> bajar nivel
        if root.num_keys == 0 and root.node_type == 0:
            new_root_ptr = root.pointers[0]

            # quitar al root antiguo
            root.is_root = 0
            self._write_node(root, root_ptr)

            # marcar nuevo root
            new_root = self._read_node(new_root_ptr)
            new_root.is_root = 1
            new_root.parent_ptr = -1
            self._write_node(new_root, new_root_ptr)

            self._write_header(new_root_ptr, total_nodes)

        return deleted

    def remove(self, key):
        # eliminar del arbol
        offset = self.delete(key)

        if offset is None:
            return None

        # eliminar del heap
        deleted = self.heap.delete(offset)

        if deleted is None:
            return None

        return self.table_meta.clean_tuple(deleted)

    def _delete_recursive(self, key, node_ptr, parent_ptr=None, index_in_parent=None):
        node = self._read_node(node_ptr)

        #hoja
        if node.node_type == 1:
            old_first_key = node.keys[0] if node.num_keys > 0 else None
            node_ptr, node, removed = self._remove_from_leaf(node,key,node_ptr)

            if removed is None:
                return None #no encontrada
            
            new_first_key = node.keys[0] if node.num_keys > 0 else None

            if (
                old_first_key is not None and
                new_first_key is not None and
                self._compare_keys(old_first_key, new_first_key) != 0
            ):
                self._update_parent_separator_after_delete(
                    parent_ptr,
                    index_in_parent,
                    old_first_key,
                    new_first_key
                )

            MIN_KEYS = self._min_keys_leaf()

            if node.num_keys < MIN_KEYS and parent_ptr is not None:
                self._rebalance_leaf(node_ptr, parent_ptr, index_in_parent)
            else:
                self._write_node(node, node_ptr)

            return removed

        #interno
        else:
            #bajar al hijo
            child_idx = self._binary_search_internal(node, key)
            child_ptr = node.pointers[child_idx]

            #llamada recursiva
            deleted = self._delete_recursive(key, child_ptr, node_ptr, child_idx)

            if deleted is None:
                return None

            node = self._read_node(node_ptr)

            MIN_KEYS = self._min_keys_internal()

            if node.num_keys < MIN_KEYS and parent_ptr is not None:
                self._rebalance_internal(node_ptr, parent_ptr, index_in_parent)
            return deleted
        
    def _remove_from_leaf(self, node, key, node_ptr):
        current_node = node
        current_ptr = node_ptr

        while True:

            idx = self._binary_search_leaf(current_node, key)

            if idx != -1:
                removed_pointer = current_node.pointers[idx]

                del current_node.keys[idx]
                del current_node.pointers[idx]
                current_node.num_keys -= 1

                self._write_node(current_node, current_ptr)

                return current_ptr, current_node, removed_pointer

            # si esta hoja ya contiene claves mayores,
            # nunca aparecerá después
            if ( current_node.num_keys > 0 and self._compare_keys(current_node.keys[-1], key) > 0):
                break

            # no hay más hojas
            if current_node.next_leaf == -1:
                break

            next_ptr = current_node.next_leaf
            next_node = self._read_node(next_ptr)

            if (next_node.num_keys > 0 and self._compare_keys(next_node.keys[0], key) > 0):
                break

            current_ptr = next_ptr
            current_node = next_node

        return node_ptr, node, None
    
    def _remove_from_internal(self, node, index): #Elimina la clave y el puntero hijo de un nodo interno en la posición index.
        del node.keys[index]
        del node.pointers[index + 1]
        node.num_keys -= 1

    def _binary_search_internal_leftmost(self, node, key):

        left, right = 0, node.num_keys - 1
        result = node.num_keys

        while left <= right:

            mid = (left + right) // 2
            if self._compare_keys(node.keys[mid], key) < 0:
                left = mid + 1
            else:
                result = mid
                right = mid - 1

        return min(result, len(node.pointers) - 1)

    def _update_parent_separator_after_delete(self, parent_ptr, child_index, old_key, new_key):

        current_parent_ptr = parent_ptr
        current_child_index = child_index

        while current_parent_ptr != -1 and current_parent_ptr is not None:

            parent = self._read_node(current_parent_ptr)

            if current_child_index > 0:
                sep_idx = current_child_index - 1
                if sep_idx < len(parent.keys):
                    parent.keys[sep_idx] = new_key
                    self._write_node(parent, current_parent_ptr)
                break

            old_parent_ptr = current_parent_ptr
            current_parent_ptr = parent.parent_ptr

            if current_parent_ptr == -1:
                break

            grandparent = self._read_node(current_parent_ptr)

            try:
                current_child_index = grandparent.pointers.index(old_parent_ptr)
            except ValueError:
                break

    def _rebalance_leaf(self, node_ptr, parent_ptr, index_in_parent):
        node = self._read_node(node_ptr)
        parent = self._read_node(parent_ptr)

        MIN_KEYS = self._min_keys_leaf()

        #distribuir con hermano izquierdo
        if index_in_parent > 0:
            left_ptr = parent.pointers[index_in_parent - 1]
            left = self._read_node(left_ptr)

            if left.num_keys > MIN_KEYS:
                # mover ultima clave del izquierdo
                key = left.keys.pop(-1)
                ptr = left.pointers.pop(-1)
                left.num_keys -= 1

                node.keys.insert(0, key)
                node.pointers.insert(0, ptr)
                node.num_keys += 1

                # actualizar separador en padre
                parent.keys[index_in_parent - 1] = node.keys[0]

                self._write_node(left, left_ptr)
                self._write_node(node, node_ptr)
                self._write_node(parent, parent_ptr)
                return

        #distribuir con hermano derecho
        if index_in_parent < len(parent.pointers) - 1:
            right_ptr = parent.pointers[index_in_parent + 1]
            right = self._read_node(right_ptr)

            if right.num_keys > MIN_KEYS:
                # mover primera clave del derecho
                key = right.keys.pop(0)
                ptr = right.pointers.pop(0)
                right.num_keys -= 1

                node.keys.append(key)
                node.pointers.append(ptr)
                node.num_keys += 1

                #actualizar padre
                parent.keys[index_in_parent] = right.keys[0]

                self._write_node(right, right_ptr)
                self._write_node(node, node_ptr)
                self._write_node(parent, parent_ptr)
                
                return

        # merge con hermano izquierdo
        if index_in_parent > 0:
            left_ptr = parent.pointers[index_in_parent - 1]
            left = self._read_node(left_ptr)

            left.keys.extend(node.keys)
            left.pointers.extend(node.pointers)
            left.num_keys = len(left.keys)
            left.next_leaf = node.next_leaf

            self._write_node(left, left_ptr)

            self._remove_from_internal(parent, index_in_parent - 1)
            if left.num_keys > 0:
                self._update_parent_separator_after_delete(
                    parent_ptr,
                    index_in_parent - 1,
                    parent.keys[index_in_parent - 1]
                    if index_in_parent - 1 < len(parent.keys)
                    else None,
                    left.keys[0]
                )
            self._write_node(parent, parent_ptr)

        else:
            #merge con hermano derecho
            right_ptr = parent.pointers[index_in_parent + 1]
            right = self._read_node(right_ptr)

            node.keys.extend(right.keys)
            node.pointers.extend(right.pointers)
            node.num_keys = len(node.keys)
            node.next_leaf = right.next_leaf

            self._write_node(node, node_ptr)

            self._remove_from_internal(parent, index_in_parent)
            if node.num_keys > 0:
                self._update_parent_separator_after_delete(
                    parent_ptr,
                    index_in_parent,
                    parent.keys[index_in_parent]
                    if index_in_parent < len(parent.keys)
                    else None,
                    node.keys[0]
                )
            self._write_node(parent, parent_ptr)

    
    def _rebalance_internal(self, node_ptr, parent_ptr, index_in_parent):
        node = self._read_node(node_ptr)
        parent = self._read_node(parent_ptr)

        MIN_KEYS = self._min_keys_internal()

        # redistribuir con hermano izquierdo
        if index_in_parent > 0:
            left_ptr = parent.pointers[index_in_parent - 1]
            left = self._read_node(left_ptr)

            if left.num_keys > MIN_KEYS:
                # tomar del hermano izquierdo
                borrowed_key = left.keys.pop(-1)
                borrowed_ptr = left.pointers.pop(-1)
                left.num_keys -= 1

                # clave del padre baja
                node.keys.insert(0, parent.keys[index_in_parent - 1])
                node.pointers.insert(0, borrowed_ptr)
                borrowed_child = self._read_node(borrowed_ptr)

                borrowed_child.parent_ptr = node_ptr

                self._write_node(borrowed_child, borrowed_ptr)

                node.num_keys += 1

                # actualizar padre
                parent.keys[index_in_parent - 1] = borrowed_key

                self._write_node(left, left_ptr)
                self._write_node(node, node_ptr)
                self._write_node(parent, parent_ptr)
                return

        #redistribuir con hermano derecho
        if index_in_parent < len(parent.pointers) - 1:
            right_ptr = parent.pointers[index_in_parent + 1]
            right = self._read_node(right_ptr)

            if right.num_keys > MIN_KEYS:
                # tomar del hermano derecho
                borrowed_key = right.keys.pop(0)
                borrowed_ptr = right.pointers.pop(0)
                right.num_keys -= 1

                # clave del padre baja
                node.keys.append(parent.keys[index_in_parent])
                node.pointers.append(borrowed_ptr)
                borrowed_child = self._read_node(borrowed_ptr)

                borrowed_child.parent_ptr = node_ptr

                self._write_node(borrowed_child, borrowed_ptr)


                node.num_keys += 1

                # actualizar padre
                parent.keys[index_in_parent] = borrowed_key

                self._write_node(right, right_ptr)
                self._write_node(node, node_ptr)
                self._write_node(parent, parent_ptr)
                return

        #merge con hermano izquierdo
        if index_in_parent > 0:
            left_ptr = parent.pointers[index_in_parent - 1]
            left = self._read_node(left_ptr)

            # clave del padre baja al merge
            left.keys.append(parent.keys[index_in_parent - 1])
            left.keys.extend(node.keys)
            left.pointers.extend(node.pointers)
            left.num_keys = len(left.keys)

            # actualizar parent_ptr de hijos movidos
            for child_ptr in node.pointers:

                child = self._read_node(child_ptr)

                child.parent_ptr = left_ptr

                self._write_node(child, child_ptr)

            self._write_node(left, left_ptr)

            self._remove_from_internal(parent, index_in_parent-1)
            self._write_node(parent, parent_ptr)

        else:
            #merge con hermano derecho
            right_ptr = parent.pointers[index_in_parent + 1]
            right = self._read_node(right_ptr)

            #clave del padre baja
            node.keys.append(parent.keys[index_in_parent])
            node.keys.extend(right.keys)
            node.pointers.extend(right.pointers)
            node.num_keys = len(node.keys)

            # actualizar parent_ptr de hijos movidos
            for child_ptr in right.pointers:

                child = self._read_node(child_ptr)

                child.parent_ptr = node_ptr

                self._write_node(child, child_ptr)

            self._write_node(node, node_ptr)

            self._remove_from_internal(parent, index_in_parent)
            self._write_node(parent, parent_ptr)

    ## para manejar  bulk_load
    def _flush_index_page(self, f, entries):

        pointer_fmt = BPlusNode.PTR_FORMAT
        entry_format = self.key_fmt + pointer_fmt
        packed = bytearray()

        packed.extend(struct.pack(self.TEMP_PAGE_HEADER_FORMAT, len(entries)))

        for key, offset in entries:
            key = self._normalize_key_value(key)

            packed.extend(struct.pack(entry_format, key, offset))

        remaining = self.PAGE_SIZE - len(packed)

        if remaining > 0:
            packed.extend(b'\x00' * remaining)

        f.write(packed)

    def _generate_index_entries(self, rows, temp_path):
        key_idx = None
        for i, col in enumerate(self.table_meta.columns):
            if col["name"] == self.key_column:
                key_idx = i
                break

        pointer_fmt = BPlusNode.PTR_FORMAT
        entry_format = self.key_fmt + pointer_fmt
        entry_size = struct.calcsize(entry_format)

        usable_bytes =  self.PAGE_SIZE - self.TEMP_PAGE_HEADER_SIZE
        max_entries = usable_bytes // entry_size

        buffer = []

        total_entries = 0
    
        heap_chunk = []
        first_chunk = True

        with open(temp_path, 'wb') as f:
            for parsed in rows:
                heap_chunk.append(tuple(parsed))
                # insertar chunk masivo
                if len(heap_chunk) >= self.heap_chunk_size:
                    offsets = self.heap.bulk_insert( heap_chunk,reset=first_chunk)
                    first_chunk = False
                    for record_tuple, offset in zip(heap_chunk, offsets):
                        key = record_tuple[key_idx]
                        buffer.append((key, offset))
                        total_entries += 1
                        if len(buffer) >= max_entries:
                            self._flush_index_page( f,buffer)
                            buffer.clear()
                    heap_chunk.clear()

            # ultimo chunk
            if heap_chunk:
                offsets = self.heap.bulk_insert(heap_chunk,reset=first_chunk)
                for record_tuple, offset in zip(heap_chunk, offsets):
                    key = record_tuple[key_idx]
                    buffer.append((key, offset))
                    total_entries += 1
                    if len(buffer) >= max_entries:
                        self._flush_index_page(f,buffer)
                        buffer.clear()

            # ultimo buffer idx
            if buffer:
                self._flush_index_page(f,buffer)

        return total_entries

    def _iter_index_entries(self, path):

        pointer_fmt = BPlusNode.PTR_FORMAT
        entry_format = self.key_fmt + pointer_fmt
        entry_size = struct.calcsize(entry_format)

        pages_per_buffer = max(1, self.sort_buffer_size // self.PAGE_SIZE)
        buffer_size = pages_per_buffer * self.PAGE_SIZE

        with open(path, 'rb') as f:
            while True:
                buffer = f.read(buffer_size)
                if not buffer:
                    break
                for page_start in range(0,len(buffer), self.PAGE_SIZE):
                    page = buffer[page_start:page_start + self.PAGE_SIZE]

                    if len(page) < self.PAGE_SIZE:
                        break

                    num_records = struct.unpack(self.TEMP_PAGE_HEADER_FORMAT, page[:self.TEMP_PAGE_HEADER_SIZE])[0]
                    offset = self.TEMP_PAGE_HEADER_SIZE

                    for _ in range(num_records):
                        chunk = page[offset:offset + entry_size]
                        if len(chunk) < entry_size:
                            break
                        key, ptr = struct.unpack(entry_format,chunk)
                        yield key, ptr
                        offset += entry_size

    def _external_sort_index(self, input_path, output_path):
        pointer_fmt = BPlusNode.PTR_FORMAT
        entry_format = self.key_fmt + pointer_fmt

        sorter = ExternalSort(record_format=entry_format,page_size=self.PAGE_SIZE, buffer_size=self.sort_buffer_size)

        sorter.external_sort(heap_path=input_path,output_path=output_path,sort_key_index=0)
    
    def _allocate_node(self):
        root_ptr, total_nodes = self._read_header()
        ptr = self.HEADER_SIZE + total_nodes * self.PAGE_SIZE
        self._write_header(root_ptr,total_nodes + 1)
        return ptr

    def _build_leaf_level(self, sorted_path, total_entries):

        leaf_entries = []
        min_keys = self._min_keys_leaf()
        remaining = total_entries

        current_leaf = BPlusNode(self.key_fmt,self.key_size,self.ORDER, self.PAGE_SIZE,node_type=1)

        current_offset = self._allocate_node()

        prev_leaf = None
        prev_offset = None

        for key, ptr in self._iter_index_entries(sorted_path):
            remaining_after = remaining - 1

            if (current_leaf.num_keys >= self.ORDER or (remaining_after < min_keys and remaining > min_keys)):
                if prev_leaf:
                    prev_leaf.next_leaf = current_offset
                    self._write_node(prev_leaf, prev_offset)

                self._write_node(current_leaf, current_offset)

                leaf_entries.append((current_leaf.keys[0], current_offset))

                prev_leaf = current_leaf
                prev_offset = current_offset

                current_leaf = BPlusNode(self.key_fmt, self.key_size,self.ORDER, self.PAGE_SIZE, node_type=1)

                current_offset = self._allocate_node()

            current_leaf.keys.append(key)
            current_leaf.pointers.append(ptr)

            current_leaf.num_keys += 1

            remaining -= 1

        if current_leaf.num_keys > 0:
            if prev_leaf:
                prev_leaf.next_leaf = current_offset
                self._write_node(prev_leaf, prev_offset)

            self._write_node(current_leaf, current_offset)
            leaf_entries.append((current_leaf.keys[0], current_offset))

        return leaf_entries
    
    def _build_internal_level(self, level_entries):
        parent_entries = []
        min_children = self._min_keys_internal() + 1
        remaining = len(level_entries)
        current_node = BPlusNode(self.key_fmt, self.key_size, self.ORDER, self.PAGE_SIZE, node_type=0)
        current_offset = self._allocate_node()
        first = True
        current_subtree_min = None

        for key, ptr in level_entries:
            remaining_after = remaining - 1
            if (
                current_node.num_keys >= self.ORDER or
                (
                    remaining_after < min_children and
                    remaining > min_children
                )
            ):
                self._write_node(current_node, current_offset)
                parent_entries.append((current_subtree_min, current_offset))
                current_node = BPlusNode(self.key_fmt, self.key_size, self.ORDER, self.PAGE_SIZE, node_type=0)
                current_offset = self._allocate_node()
                first = True
                current_subtree_min = None

            child = self._read_node(ptr)
            child.parent_ptr = current_offset

            self._write_node(child, ptr)
            if first:
                current_node.pointers.append(ptr)
                current_subtree_min = key
                first = False
            else:
                current_node.keys.append(key)
                current_node.pointers.append(ptr)
                current_node.num_keys += 1
            remaining -= 1

        if current_node.pointers:
            self._write_node(current_node, current_offset)
            parent_entries.append((current_subtree_min, current_offset))
        return parent_entries
    
    def build_bulk_tree(self, sorted_path, total_entries):
        level = self._build_leaf_level(sorted_path, total_entries)

        while len(level) > 1:
            level = self._build_internal_level(level)

        root_key, root_ptr = level[0]
        root = self._read_node(root_ptr)
        root.is_root = 1
        self._write_node(root, root_ptr)
        _, total_nodes = self._read_header()
        self._write_header(root_ptr, total_nodes)
        self.root = root_ptr
    

    def _parsed_row_generator(self, rows):
        for row in rows:
            parsed = []
            csv_idx = 0

            for col in self.table_meta.columns:
                col_type = col["type"].upper()
                value = row[csv_idx].strip()

                if col_type == "INT":
                    parsed.append(int(value))
                    csv_idx += 1
                elif col_type == "FLOAT":
                    parsed.append(float(value))
                    csv_idx += 1
                elif col_type == "VARCHAR":
                    parsed.append(value.encode('utf-8'))
                    csv_idx += 1
                elif col_type == "BOOLEAN":
                    parsed.append(value.lower() in ("true", "1"))
                    csv_idx += 1
                elif col_type == "DATE":
                    parsed.append(value.encode('utf-8'))
                    csv_idx += 1
                elif col_type == "POINT":
                    try:
                        # Caso CSV real:
                        # longitude,latitude
                        x_val = float(row[csv_idx].strip())
                        y_val = float(row[csv_idx + 1].strip())

                        parsed.extend([x_val, y_val])
                        csv_idx += 2
                    except:
                        # POINT(x,y)
                        if value.upper().startswith("POINT"):
                            coords = value[value.find("(")+1:value.find(")")]
                            x, y = coords.split(",")
                        # (x y) o (x,y)
                        elif value.startswith("(") and value.endswith(")"):
                            coords = value.strip("()")
                            if "," in coords:
                                x, y = coords.split(",")
                            else:
                                x, y = coords.split()
                        # x,y
                        elif "," in value:
                            x, y = value.split(",")
                        else:
                            raise ValueError( f"Formato POINT inválido: {value}")

                        parsed.extend([ float(x.strip()),float(y.strip()) ])
                        csv_idx += 1
                else:
                    parsed.append(value)
                    csv_idx += 1
            # is_deleted
            parsed.append(False)
            yield parsed

    def bulk_load(self, csv_path, delimiter=','):
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter=delimiter)
            first_row = next(reader, None)

            if first_row is None:
                return

            has_header = not self._matches_schema(first_row)

            if has_header:
                rows = reader
            else:
                rows = itertools.chain([first_row], reader)

            parsed_rows = self._parsed_row_generator(rows)

            temp_unsorted = os.path.join(self.data_dir,"tmp_unsorted.idx")

            temp_sorted = os.path.join(self.data_dir,"tmp_sorted.idx")

            if os.path.exists(self.filename):
                os.remove(self.filename)

            if os.path.exists(self.heap_path):
                os.remove(self.heap_path)

            with open(self.filename, 'wb') as f:
                f.write(struct.pack(self.HEADER_FORMAT,self.HEADER_SIZE, 0))

            self.heap = HeapFile(
                table_meta=self.table_meta,
                filepath=self.heap_path,
                page_size=self.PAGE_SIZE
            )

            try:
                total_entries = self._generate_index_entries( parsed_rows, temp_unsorted)
                self._external_sort_index(temp_unsorted, temp_sorted )
                self.build_bulk_tree( temp_sorted, total_entries)
            finally:
                if os.path.exists(temp_unsorted):
                    os.remove(temp_unsorted)
                if os.path.exists(temp_sorted):
                    os.remove(temp_sorted)

    def bulk_load_2(self, csv_path, delimiter=','):
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:

            reader = csv.reader(f, delimiter=delimiter)

            first_row = next(reader, None)

            if first_row is None:
                return

            has_header = not self._matches_schema(first_row)

            if has_header:
                rows = reader
            else:
                rows = itertools.chain([first_row], reader)

            for row in rows:

                parsed = []

                csv_idx = 0

                for col in self.table_meta.columns:

                    col_type = col["type"].upper()

                    value = row[csv_idx].strip()

                    if col_type == "INT":

                        parsed.append(int(value))
                        csv_idx += 1

                    elif col_type == "FLOAT":

                        parsed.append(float(value))
                        csv_idx += 1

                    elif col_type == "VARCHAR":

                        parsed.append(value.encode('utf-8'))
                        csv_idx += 1

                    elif col_type == "BOOLEAN":

                        parsed.append(
                            value.lower() in ("true", "1")
                        )

                        csv_idx += 1

                    elif col_type == "DATE":

                        parsed.append(
                            value.encode('utf-8')
                        )

                        csv_idx += 1

                    elif col_type == "POINT":

                        try:

                            # Caso CSV real:
                            # longitude,latitude

                            x_val = float(row[csv_idx].strip())
                            y_val = float(row[csv_idx + 1].strip())

                            parsed.extend([
                                x_val,
                                y_val
                            ])

                            csv_idx += 2

                        except:

                            # Caso POINT(x,y)
                            if value.upper().startswith("POINT"):

                                coords = value[
                                    value.find("(")+1:value.find(")")
                                ]

                                x, y = coords.split(",")

                            # Caso (x y) o (x,y)
                            elif value.startswith("(") and value.endswith(")"):

                                coords = value.strip("()")

                                if "," in coords:
                                    x, y = coords.split(",")
                                else:
                                    x, y = coords.split()

                            # Caso x,y
                            elif "," in value:

                                x, y = value.split(",")

                            else:

                                raise ValueError(
                                    f"Formato POINT inválido: {value}"
                                )

                            parsed.extend([
                                float(x.strip()),
                                float(y.strip())
                            ])

                            csv_idx += 1

                    else:

                        parsed.append(value)
                        csv_idx += 1

                # columna oculta is_deleted
                parsed.append(False)

                self.add(tuple(parsed), is_bulk=True)
                
    def _matches_schema(self, row):
        try:
            csv_idx = 0
            for col in self.table_meta.columns:
                col_type = col["type"].upper()
                if col_type == "POINT":
                    # POINT como 2 columnas CSV consecutivas
                    float(row[csv_idx].strip())
                    float(row[csv_idx + 1].strip())
                    csv_idx += 2
                else:
                    value = row[csv_idx].strip()
                    if col_type == "INT":
                        int(value)
                    elif col_type == "FLOAT":
                        float(value)
                    elif col_type == "BOOLEAN":
                        if value.lower() not in (
                            "true", "false", "0", "1"
                        ):
                            return False
                    elif col_type == "DATE":
                        pass
                    elif col_type == "VARCHAR":
                        pass
                    csv_idx += 1
            return True
        except:
            return False
        
    def knn_search(self, key, k):
        raise NotImplementedError("knn_search no soportado")