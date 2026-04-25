from backend.parser.sql_lexer import DBMSSqlLexer
from backend.parser.sql_parser import DBMSSqlParser

from backend.executor import Executor

if __name__ == '__main__':
    #consulta = 'CREATE TABLE Empleados (Employee_ID INT INDEX Sequential, Employee_Name VARCHAR, Age INT, Country VARCHAR, Department VARCHAR, Position VARCHAR, Salary FLOAT, Joining_Date VARCHAR) FROM FILE "employee.csv";'
    consulta = 'SELECT * FROM Empleados WHERE Employee_ID = 17648;'
    #consulta = 'SELECT * FROM Empleados WHERE Employee_ID BETWEEN 1000 AND 12000;'

    # Parseo
    lexer = DBMSSqlLexer()
    parser = DBMSSqlParser(lexer.tokenize(consulta))
    ast = parser.parse()

    # Ejecución
    motor = Executor()
    motor.execute(ast)