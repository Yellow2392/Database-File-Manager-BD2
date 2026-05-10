import os
import struct
import time
import shutil

class ExternalHashing:
    def __init__(self, recordformat: str, pagesize: int, buffersize: int):
        self.recordformat = recordformat
        self.pagesize = pagesize
        self.buffersize = buffersize

        self.B = buffersize // pagesize
        if self.B < 2:
            raise ValueError("BUFFERSIZE debe permitir al menos 2 páginas en RAM.")

        self.k = self.B - 1  # 1 buffer de entrada, k buffers de salida
        self.recordsize = struct.calcsize(recordformat)
        self.header_format = 'i 12x'
        self.header_size = 16
        self.recordsperpage = (pagesize - self.header_size) // self.recordsize
        self.recordsperpage = pagesize // self.recordsize

        self.pagesread = 0
        self.pageswritten = 0

    def externalhashgroupby(self, heappath: str, groupkeyindex: int) -> dict:
        starttotal = time.time()

        try:
            startp1 = time.time()
            partitionpaths = self.partitiondata(heappath, groupkeyindex)
            timephase1 = time.time() - startp1

            startp2 = time.time()
            result = self.aggregatepartitions(partitionpaths, groupkeyindex)
            timephase2 = time.time() - startp2
            
        finally:
            if os.path.exists("temp_partitions"):
                shutil.rmtree("temp_partitions", ignore_errors=True)

        timetotal = time.time() - starttotal

        return {
            "result": result,
            "partitionscreated": len(partitionpaths),
            "pagesread": self.pagesread,
            "pageswritten": self.pageswritten,
            "timephase1sec": round(timephase1, 4),
            "timephase2sec": round(timephase2, 4),
            "timetotalsec": round(timetotal, 4)
        }

    def partitiondata(self, heappath: str, groupkeyindex: int) -> list[str]:
        if not os.path.exists(heappath):
            return []

        os.makedirs("temp_partitions", exist_ok=True)

        partitionpaths = [f"temp_partitions/partition_{i}.bin" for i in range(self.k)]

        for path in partitionpaths:
            open(path, "wb").close()

        outputbuffers = [[] for _ in range(self.k)]

        totalpages = os.path.getsize(heappath) // self.pagesize

        with open(heappath, "rb") as heapfile:
            for _ in range(totalpages):
                pagedata = heapfile.read(self.pagesize)
                if not pagedata:
                    break

                self.pagesread += 1
                records = self.extractrecords(pagedata)

                for record in records:
                    key = self.normalizekey(record[groupkeyindex])
                    partitionid = self.hashpartition(key)

                    outputbuffers[partitionid].append(record)

                    if len(outputbuffers[partitionid]) == self.recordsperpage:
                        with open(partitionpaths[partitionid], "ab") as pf:
                            self.writebinarypage(pf, outputbuffers[partitionid])
                        self.pageswritten += 1
                        outputbuffers[partitionid] = []

        for partitionid in range(self.k):
            if outputbuffers[partitionid]:
                with open(partitionpaths[partitionid], "ab") as pf:
                    self.writebinarypage(pf, outputbuffers[partitionid])
                self.pageswritten += 1
                outputbuffers[partitionid] = []

        nonemptypartitions = [
            path for path in partitionpaths if os.path.getsize(path) > 0
        ]
        return nonemptypartitions

    def aggregatepartitions(self, partitionpaths: list[str], groupkeyindex: int) -> dict:
        finalresult = {}

        for path in partitionpaths:
            partitionpages = os.path.getsize(path) // self.pagesize

            #if partitionpages > self.B:
            #    raise MemoryError(
            #        f"La partición {path} no cabe en RAM durante la Fase 2 "
            #        f"({partitionpages} páginas > B={self.B})."
            #    )

            partialcount = {}

            with open(path, "rb") as pf:
                while True:
                    pagedata = pf.read(self.pagesize)
                    if not pagedata:
                        break

                    self.pagesread += 1
                    records = self.extractrecords(pagedata)

                    for record in records:
                        key = self.normalizekey(record[groupkeyindex])
                        partialcount[key] = partialcount.get(key, 0) + 1

            for key, count in partialcount.items():
                finalresult[key] = finalresult.get(key, 0) + count

        #for path in partitionpaths:
        #    if os.path.exists(path):
        #        os.remove(path)

        #if os.path.exists("temp_partitions") and not os.listdir("temp_partitions"):
        #    os.rmdir("temp_partitions")

        return dict(sorted(finalresult.items()))

    def hashpartition(self, key) -> int:
        return hash(key) % self.k

    def normalizekey(self, value):
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore").rstrip("\x00").strip()
        return value

    def extractrecords(self, pagedata: bytes) -> list[tuple]:
        num_records = struct.unpack(self.header_format, pagedata[:16])[0]
        records = []

        for i in range(num_records):
            offset = self.header_size + (i * self.recordsize)
            recordbytes = pagedata[offset: offset + self.recordsize]
            
            record_tuple = struct.unpack(self.recordformat, recordbytes)
            
            is_deleted = record_tuple[-1]
            if is_deleted is True:
                continue
                
            records.append(record_tuple)

        return records

    def writebinarypage(self, filehandle, records: list[tuple]):
        pagebuffer = bytearray()
        
        pagebuffer.extend(struct.pack(self.header_format, len(records)))

        for rec in records:
            pagebuffer.extend(struct.pack(self.recordformat, *rec))

        padding = self.pagesize - len(pagebuffer)
        if padding > 0:
            pagebuffer.extend(b"\x00" * padding)

        filehandle.write(pagebuffer)