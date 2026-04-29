import os
import struct
import heapq
import time

class ExternalSort:
    def __init__(self, record_format: str, page_size: int, buffer_size: int):
        self.record_format = record_format
        self.page_size = page_size
        self.buffer_size = buffer_size
        self.B = buffer_size // page_size
        
        self.record_size = struct.calcsize(record_format)
        
        self.header_format = 'i 12x' # 4 bytes para int, 12 de relleno
        self.header_size = 16
        # Espacio restante para registros
        self.records_per_page = (self.page_size - self.header_size) // self.record_size

        self.pages_read = 0
        self.pages_written = 0

    #! Método completo
    def external_sort(self, heap_path: str, output_path: str, sort_key_index: int) -> dict:
        start_total = time.time()
        
        # Fase 1
        start_p1 = time.time()
        runs = self.generate_runs(heap_path, sort_key_index)
        time_phase1 = time.time() - start_p1
        
        # Fase 2
        start_p2 = time.time()
        k = self.B - 1  # Capacidad real de mezcla
        
        intermediate_count = 0
        
        while len(runs) > k:
            batch = runs[:k]
            runs = runs[k:]
            
            intermediate_path = f"temp_runs/inter_{intermediate_count}.bin"
            self.multiway_merge(batch, intermediate_path, sort_key_index)
            
            runs.append(intermediate_path)
            intermediate_count += 1
            
        self.multiway_merge(runs, output_path, sort_key_index)
        time_phase2 = time.time() - start_p2
        
        end_total = time.time()

        return {
            'runs_generated': len(runs),
            'pages_read': self.pages_read,
            'pages_written': self.pages_written,
            'time_phase1_sec': round(time_phase1, 4),
            'time_phase2_sec': round(time_phase2, 4),
            'time_total_sec': round(end_total - start_total, 4)
        }

    #! FASE 1
    """
    Lee B páginas a la vez, las ordena en memoria por el sort_key,
    las escribe como archivos temporales de run ordenado.
    Retorna la lista de rutas de los runs generados.
    """
    def generate_runs(self, heap_path: str, sort_key_index: int) -> list[str]:
        if not os.path.exists(heap_path):
            return []

        run_paths = []
        total_pages = os.path.getsize(heap_path) // self.page_size
        current_page = 0
        run_count = 0

        os.makedirs("temp_runs", exist_ok=True)

        with open(heap_path, 'rb') as f:
            while current_page < total_pages:
                # Hastaa B páginas en memoria
                pages_to_read = min(self.B, total_pages - current_page)
                memory_records = []
                
                for _ in range(pages_to_read):
                    page_data = f.read(self.page_size)
                    self.pages_read += 1 #? Incremento
                    memory_records.extend(self._extract_records(page_data))
                    current_page += 1

                # Ordenar internamente
                memory_records.sort(key=lambda x: x[sort_key_index])

                # Escribir como run ordenado al disco
                run_filename = f"temp_runs/run_{run_count}.bin"
                self._write_run(run_filename, memory_records)
                run_paths.append(run_filename)
                run_count += 1

        return run_paths
    
    #! FASE 2
    """
    Realiza un k-way merge de los runs usando un min-heap.
    Escribe el resultado ordenado en output_path.
    Usa B-1 buffers de entrada y 1 buffer de salida.
    """
    def multiway_merge(self, run_paths: list[str], output_path: str, sort_key_index: int):
        min_heap = []
        run_files = [open(path, 'rb') for path in run_paths] # Todos los archivos de runs
        run_iters = []
        output_buffer = []
        
        for i, f in enumerate(run_files):
            first_page = f.read(self.page_size)
            if first_page:
                self.pages_read += 1
                records = self._extract_records(first_page)
                if records:
                    first_rec = records.pop(0)
                    heapq.heappush(min_heap, (first_rec[sort_key_index], i, first_rec))
                    run_iters.append(self._run_record_generator(f, records))
                else:
                    run_iters.append(iter([]))
            else:
                run_iters.append(iter([]))

        with open(output_path, 'wb') as out_f:
            while min_heap:
                val, run_idx, record = heapq.heappop(min_heap)
                output_buffer.append(record)
                
                if len(output_buffer) == self.records_per_page:
                    self._write_binary_page(out_f, output_buffer)
                    self.pages_written += 1
                    output_buffer = []
                
                try:
                    # Cargar el siguiente registro del run de donde vino
                    next_rec = next(run_iters[run_idx])
                    heapq.heappush(min_heap, (next_rec[sort_key_index], run_idx, next_rec))
                except StopIteration:
                    pass

            # Registros restantes -> buffer de salida
            if output_buffer:
                self._write_binary_page(out_f, output_buffer)

        for f in run_files:
            f.close()
        for path in run_paths:
            os.remove(path)

    # Private:

    def _extract_records(self, page_data: bytes) -> list[tuple]:
        num_records = struct.unpack(self.header_format, page_data[:16])[0]
        records = []
        
        for i in range(num_records):
            offset = self.header_size + (i * self.record_size)
            record_bytes = page_data[offset : offset + self.record_size]
            records.append(struct.unpack(self.record_format, record_bytes))
            
        return records

    def _write_run(self, path: str, records: list[tuple]):
        # Escribe una lista de registros ordenados en un archivo de run
        with open(path, 'wb') as f:
            current_page_records = []
            for rec in records:
                current_page_records.append(rec)
                if len(current_page_records) == self.records_per_page:
                    self._write_binary_page(f, current_page_records)
                    self.pages_written += 1 # Escritura de página
                    current_page_records = []
            
            if current_page_records:
                self._write_binary_page(f, current_page_records)

    def _write_binary_page(self, file_handle, records: list[tuple]): 
        page_buffer = bytearray()
        
        # Número de registros en la página
        page_buffer.extend(struct.pack(self.header_format, len(records)))
        
        for rec in records:
            page_buffer.extend(struct.pack(self.record_format, *rec))
        
        padding = self.page_size - len(page_buffer)
        if padding > 0:
            page_buffer.extend(b'\x00' * padding)
            
        file_handle.write(page_buffer)
    
    def _run_record_generator(self, file_handle, initial_records): # Generador que entrega registros uno a uno, leyendo páginas de disco cuando es necesario
        # Entrega los que ya sacamos de la primera página
        for r in initial_records:
            yield r
            
        # Lee del archivo página por página
        while True:
            page_data = file_handle.read(self.page_size)
            if not page_data:
                break
            self.pages_read += 1 # Lectura de página
            records = self._extract_records(page_data)
            for r in records:
                yield r
