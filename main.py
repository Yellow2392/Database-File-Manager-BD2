from backend.parser.sql_lexer import DBMSSqlLexer
from backend.parser.sql_parser import DBMSSqlParser

from backend.executor import Executor

if __name__ == '__main__':
    consulta = """
        CREATE TABLE Viajes (
        ID INT,
        VendorID INT,
        Pickup_Time VARCHAR,
        Dropoff_Time VARCHAR,
        Passenger_Count INT,
        Trip_Distance FLOAT,
        Pickup_Location POINT INDEX RTree,
        RatecodeID INT,
        Store_Flag VARCHAR,
        Dropoff_Location POINT, 
        Payment_Type VARCHAR,
        Fare_Amount FLOAT,
        Extra FLOAT,
        MTA_Tax FLOAT,
        Tip_Amount FLOAT,
        Tolls_Amount FLOAT,
        Improvement_Surcharge FLOAT,
        Total_Amount FLOAT
    ) FROM FILE "yellow_tripdata_2016-01_10k.csv";
    """
    consulta = "SELECT * FROM Viajes WHERE Pickup_Location IN (POINT(-73.9903, 40.7346), RADIUS 0.001);"
    #consulta = 'CREATE TABLE Empleados (Employee_ID INT INDEX Sequential, Employee_Name VARCHAR, Age INT, Country VARCHAR, Department VARCHAR, Position VARCHAR, Salary FLOAT, Joining_Date VARCHAR) FROM FILE "employee.csv" DELIMITER ";";'
    #consulta = 'SELECT * FROM Empleados WHERE Employee_ID = 17648;'
    #consulta = 'SELECT * FROM Empleados WHERE Employee_ID BETWEEN 1000 AND 1200;'

    # Parseo
    lexer = DBMSSqlLexer()
    parser = DBMSSqlParser(lexer.tokenize(consulta))
    ast = parser.parse()

    # Ejecución
    motor = Executor()
    motor.execute(ast)