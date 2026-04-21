from backend.parser.sql_lexer import DBMSSqlLexer
from backend.parser.sql_parser import DBMSSqlParser

from backend.executor import Executor

if __name__ == '__main__':
    consulta = 'CREATE TABLE Clientes (Employee_ID INT, Employee_Name VARCHAR, Age INT, Country VARCHAR, Department VARCHAR, Position VARCHAR, Salary FLOAT, Joining_Date VARCHAR) FROM FILE "employee.csv";'
    
    # 1. Parseo
    lexer = DBMSSqlLexer()
    parser = DBMSSqlParser(lexer.tokenize(consulta))
    ast = parser.parse()

    # 2. Ejecución
    motor = Executor()
    motor.execute(ast)