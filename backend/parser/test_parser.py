from sql_lexer import DBMSSqlLexer
from sql_parser import DBMSSqlParser


if __name__ == '__main__':
    consulta = "SELECT * FROM Ubicaciones WHERE coord IN (POINT(12.5, -77.0), RADIUS 50);"
    #consulta = 'CREATE TABLE Customer (DNI INT INDEX ExtendibleHash, Nombre VARCHAR, Sueldo FLOAT) FROM FILE "data.csv";'
    #consulta = 'INSERT INTO Customer VALUES (71234567, "Juan Perez", 2500.50);'
    #consulta = "DELETE FROM Customer WHERE DNI = 71234567;"
    
    # tokenizacion
    lexer = DBMSSqlLexer()
    tokens = lexer.tokenize(consulta)

    # Parser -> Plan de ejecución
    parser = DBMSSqlParser(tokens)
    ast = parser.parse()

    print(ast)