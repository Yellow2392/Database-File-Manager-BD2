from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.parser.sql_lexer import DBMSSqlLexer
from backend.parser.sql_parser import DBMSSqlParser
from backend.executor import Executor
from backend.transaction_manager import TransactionManager
import time
import threading
from typing import List

app = FastAPI()

# Configurar CORS para que React pueda comunicarse con FastAPI sin bloqueos
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Estructura del cuerpo de la petición esperada desde Axios
class QueryRequest(BaseModel):
    query: str

# Estructuras para simulación de concurrencia
class TransactionPayload(BaseModel):
    tx_id: int
    queries: List[str]

class ConcurrencyRequest(BaseModel):
    transactions: List[TransactionPayload]

# Helper de parsing
def parse_query(sql_text: str):
    lexer = DBMSSqlLexer()
    parser = DBMSSqlParser(lexer.tokenize(sql_text))
    return parser.parse()

@app.get("/schema")
def get_schema():
    try:
        motor = Executor()
        schema = []
        for table_name, meta in motor.catalog.items():
            index_name = meta.primary_index.__class__.__name__ if meta.primary_index else "Sequential"
            if index_name == "SequentialFile":
                index_name = "Sequential"
            elif index_name == "RTreeIndex":
                index_name = "R-Tree"
            
            schema.append({
                "name": table_name,
                "index": index_name,
                "columns": meta.columns
            })
        return schema
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/execute")
def execute_query(request: QueryRequest):
    try:
        start_time = time.time()
        
        # 1. Parseo
        ast = parse_query(request.query)
        
        # 2. Motor de Ejecución
        motor = Executor()
        resultados = motor.execute(ast) 
        
        execution_time = (time.time() - start_time) * 1000 # a milisegundos

        if not resultados:
            resultados = {"columns": [], "rows": [], "diskReads": 0, "diskWrites": 0, "plot": None}

        # 3. Retornar los resultados en formato JSON manejable por React
        return {
            "columns": resultados.get("columns", []),
            "rows": resultados.get("rows", []),
            "metrics": {
                "executionTime": f"{execution_time:.2f} ms",
                "diskReads": resultados.get("diskReads", 0),
                "diskWrites": resultados.get("diskWrites", 0)
            },
            "plot":  resultados.get("plot", None)
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
@app.post("/simulate-concurrency")
def simulate_concurrency(request: ConcurrencyRequest):
    try:
        start_time = time.time()
        motor = Executor()
        tx_manager = TransactionManager(motor)
        
        hilos = []
        
        for tx in request.transactions: # Por cada transacción
            ast_list = []
            
            for sql in tx.queries:
                ast = parse_query(sql)
                if ast:
                    ast_list.append(ast)
            
            # Un hilo para esta transacción
            t = threading.Thread(
                target=tx_manager.execute_transaction, 
                args=(tx.tx_id, ast_list)
            )
            hilos.append(t)
            
        # Concurrencia
        for t in hilos:
            t.start()
            
        # Todas las transacciones deben finalizar
        for t in hilos:
            t.join()
            
        execution_time = (time.time() - start_time) * 1000
            
        return {
            "status": "success",
            "metrics": {
                "simulationTime": f"{execution_time:.2f} ms",
                "totalTransactions": len(request.transactions)
            },
            "log": tx_manager.log
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)