import threading
from backend.parser.sql_lexer import DBMSSqlLexer
from backend.parser.sql_parser import DBMSSqlParser
from backend.executor import Executor
from backend.transaction_manager import TransactionManager

def parsear_consulta(sql):
    lexer = DBMSSqlLexer()
    parser = DBMSSqlParser(lexer.tokenize(sql)) 
    return parser.parse()

if __name__ == '__main__':
    print("=== INICIANDO MOTOR ===")
    motor = Executor()
    tx_manager = TransactionManager(motor)
    
    # Conflicto sobre Employee_ID (9999) al mismo tiempo
    sql_tx1_op1 = "INSERT INTO Empleados VALUES (99999, 'Juan', 30, 'Peru', 'IT', 'Dev', 5000.50, '2026-05-04');"
    
    sql_tx2_op1 = "INSERT INTO Empleados VALUES (99999, 'Pedro', 28, 'Chile', 'QA', 'Tester', 4000.50, '2026-05-04');"
    sql_tx2_op2 = "INSERT INTO Empleados VALUES (88888, 'Ana', 35, 'Mexico', 'HR', 'Manager', 6000.50, '2026-05-04');"

    # Parsea el texto a ASTs (fuera de los hilos para simular que ya llegaron listos del cliente)
    ast_tx1 = [parsear_consulta(sql_tx1_op1)]
    
    # La TX2 tiene dos operaciones
    ast_tx2 = [
        parsear_consulta(sql_tx2_op1), 
        parsear_consulta(sql_tx2_op2)
    ]

    print("\n=== INICIANDO SIMULADOR DE ACCESO CONCURRENTE ===")

    hilo1 = threading.Thread(target=tx_manager.execute_transaction, args=(1, ast_tx1))
    hilo2 = threading.Thread(target=tx_manager.execute_transaction, args=(2, ast_tx2))

    hilo1.start()
    hilo2.start()

    hilo1.join()
    hilo2.join()
    
    print("\n=== SIMULACIÓN FINALIZADA ===")