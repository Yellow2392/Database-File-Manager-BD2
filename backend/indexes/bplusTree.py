import struct
import os
import re
import itertools
from backend.catalog import TYPE_MAP
from .base import BaseIndex
from .heapFile import HeapFile
import csv

class BPlusNode:
    HEADER_FORMAT = 'BBiii'  # node_type, is_root, num_keys, parent_ptr, next_leaf
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    INT_SIZE = struct.calcsize('i')  # para punteros

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