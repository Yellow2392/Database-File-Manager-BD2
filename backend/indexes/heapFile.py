import os
import struct
from collections import defaultdict


class HeapFile:
    FILE_HEADER_FORMAT = 'ii'# free_head, total_pages
    FILE_HEADER_SIZE = struct.calcsize(FILE_HEADER_FORMAT)

   
    # metadata del record
    # next_free:
    #
    # -1 -> activo
    # -2 -> eliminado y fin de free list
    # >=0 -> eliminado y apunta al siguiente free
    RECORD_META_FORMAT = 'i'
    RECORD_META_SIZE = struct.calcsize(RECORD_META_FORMAT)


    PAGE_HEADER_FORMAT = 'i'
    PAGE_HEADER_SIZE = struct.calcsize(PAGE_HEADER_FORMAT)

    def __init__(self, table_meta, filepath, page_size):

        self.table_meta = table_meta
        self.filepath = filepath
        self.PAGE_SIZE = page_size

        self.RECORD_SIZE = (self.RECORD_META_SIZE + self.table_meta.record_size )

        self.BLOCK_FACTOR = (self.PAGE_SIZE - self.PAGE_HEADER_SIZE) // self.RECORD_SIZE

        # crear archivo
        if not os.path.exists(self.filepath):

            with open(self.filepath, 'wb') as f:
                # free_head = -1
                # total_pages = 0
                f.write(struct.pack( self.FILE_HEADER_FORMAT, -1, 0))

    #header
    def _read_header(self):
        with open(self.filepath, 'rb') as f:
            f.seek(0)
            return struct.unpack(self.FILE_HEADER_FORMAT, f.read(self.FILE_HEADER_SIZE))

    def _write_header(self, free_head, total_pages):
        with open(self.filepath, 'r+b') as f:
            f.seek(0)
            f.write(struct.pack(self.FILE_HEADER_FORMAT,free_head,total_pages))

    ## page
    def _page_offset(self, page_id):
        return self.FILE_HEADER_SIZE + page_id * self.PAGE_SIZE

    def _record_offset_in_page(self, slot):
        return self.PAGE_HEADER_SIZE + slot * self.RECORD_SIZE

    #insert
    def insert(self, record_tuple):
        free_head, total_pages = self._read_header()

        #usar free list
        if free_head != -1:

            with open(self.filepath, 'r+b') as f:
                f.seek(free_head)

                meta_raw = f.read(self.RECORD_META_SIZE)
                next_free, = struct.unpack(self.RECORD_META_FORMAT, meta_raw)

                #payload usuario
                payload = struct.pack(self.table_meta.struct_format, *record_tuple)
                #metadata activa
                meta = struct.pack(self.RECORD_META_FORMAT, -1)

                #escribir record
                f.seek(free_head)
                f.write(meta + payload)

            # actualizar free list
            if next_free == -2:
                next_free = -1

            self._write_header(next_free, total_pages )
            return free_head

        #append simple
        with open(self.filepath, 'r+b') as f:

            # primera pagina
            if total_pages == 0:
                page_id = 0
                self._write_page(f, page_id, [record_tuple])
                self._write_header(-1, 1)

                return self._page_offset(0) +self.PAGE_HEADER_SIZE

            #ultima pagina
            last_page = total_pages - 1

            f.seek(self._page_offset(last_page))

            page_data = bytearray(f.read(self.PAGE_SIZE))
            num_records = struct.unpack(self.PAGE_HEADER_FORMAT, page_data[:self.PAGE_HEADER_SIZE])[0]

            #cabe en pagina
            if num_records < self.BLOCK_FACTOR:
                local_offset = self._record_offset_in_page(num_records)
                meta = struct.pack(self.RECORD_META_FORMAT, -1)

                payload = struct.pack(
                    self.table_meta.struct_format,
                    *record_tuple
                )

                full_record = meta + payload

                page_data[local_offset:local_offset + self.RECORD_SIZE] = full_record

                self._write_page_raw(f, last_page, page_data, num_records + 1)

                return self._page_offset(last_page) + local_offset

            #nueva pagina
            else:
                new_page = total_pages

                self._write_page(f, new_page, [record_tuple])
                self._write_header(-1, total_pages + 1)

                return self._page_offset(new_page) + self.PAGE_HEADER_SIZE
    def delete(self, offset):
        free_head, total_pages = self._read_header()

        with open(self.filepath, 'r+b') as f:
            f.seek(offset)

            raw = f.read(self.RECORD_SIZE)

            next_free, = struct.unpack(self.RECORD_META_FORMAT, raw[:self.RECORD_META_SIZE])

            # ya eliminado
            if next_free != -1:
                return None

            #recuperar record
            payload = raw[self.RECORD_META_SIZE:]
            deleted_record = struct.unpack(self.table_meta.struct_format, payload)

            #metadata nueva
            new_next = free_head if free_head != -1 else -2
            new_meta = struct.pack(self.RECORD_META_FORMAT, new_next)

            f.seek(offset)
            f.write(new_meta)

        # actualizar free list
        self._write_header(offset, total_pages)

        return deleted_record

    def read(self, offset):
        with open(self.filepath, 'rb') as f:
            f.seek(offset)
            raw = f.read(self.RECORD_SIZE)

        next_free, = struct.unpack(self.RECORD_META_FORMAT, raw[:self.RECORD_META_SIZE])

        #liminado
        if next_free != -1:
            return None

        payload = raw[self.RECORD_META_SIZE:]

        return struct.unpack(self.table_meta.struct_format,payload)

    #read varios
    def read_many(self, offsets):
        pages = defaultdict(list)

        # agrupar offsets por página
        for off in offsets:
            page_id = (off - self.FILE_HEADER_SIZE) // self.PAGE_SIZE
            pages[page_id].append(off)

        results = []

        with open(self.filepath, 'rb') as f:

            for page_id, offs in pages.items():

                f.seek(self._page_offset(page_id))
                page_data = f.read(self.PAGE_SIZE)

                for off in offs:
                    local = off - self._page_offset(page_id)

                    raw = page_data[local:local + self.RECORD_SIZE]
                    next_free, = struct.unpack(self.RECORD_META_FORMAT, raw[:self.RECORD_META_SIZE])

                    # eliminado
                    if next_free != -1:
                        continue

                    payload = raw[self.RECORD_META_SIZE:]
                    record = struct.unpack(self.table_meta.struct_format, payload)
                    results.append(record)
        return results
    

    def bulk_insert(self, records, reset=False):

        # reiniciar heap solo si se pide
        if reset:
            if os.path.exists(self.filepath):
                os.remove(self.filepath)
            with open(self.filepath, 'wb') as f:
                # free_head = -1
                # total_pages = 0
                f.write(struct.pack(self.FILE_HEADER_FORMAT,-1,0))

        # abrir existente
        with open(self.filepath, 'r+b') as f:
            # leer header actual
            f.seek(0)
            free_head, total_pages = struct.unpack(
                self.FILE_HEADER_FORMAT,
                f.read(self.FILE_HEADER_SIZE)
            )
            current_page = total_pages
            page_records = []
            offsets = []
            for record_tuple in records:
                page_records.append(record_tuple)
                # página llena
                if len(page_records) >= self.BLOCK_FACTOR:
                    self._write_page( f,current_page, page_records)

                    # offsets físicos
                    for slot in range(len(page_records)):
                        offsets.append(self._page_offset(current_page) + self.PAGE_HEADER_SIZE+ slot * self.RECORD_SIZE)
                    current_page += 1
                    page_records.clear()
            # última página parcial
            if page_records:
                self._write_page(f,current_page,page_records)

                for slot in range(len(page_records)):
                    offsets.append(self._page_offset(current_page) + self.PAGE_HEADER_SIZE+ slot * self.RECORD_SIZE)
                current_page += 1

            # actualizar header final
            f.seek(0)
            f.write( struct.pack(self.FILE_HEADER_FORMAT, -1, current_page ))
        return offsets
    
    def _write_page(self, f, page_id, records):

        f.seek(self._page_offset(page_id))

        # header página
        header = struct.pack(self.PAGE_HEADER_FORMAT, len(records))

        body = []

        for record_tuple in records:
            meta = struct.pack(self.RECORD_META_FORMAT, -1)
            payload = struct.pack(self.table_meta.struct_format, *record_tuple)
            body.append(meta + payload)

        body = b''.join(body)
        padding = b'\x00' * (self.PAGE_SIZE - self.PAGE_HEADER_SIZE - len(body))

        f.write(header +body +padding)

    def _write_page_raw(self, f, page_id,page_data, num_records):
        header = struct.pack(self.PAGE_HEADER_FORMAT, num_records)

        f.seek(self._page_offset(page_id))
        f.write(header + page_data[self.PAGE_HEADER_SIZE:])