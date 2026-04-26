class DBMSSqlParser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def current_token(self):
        # Token actual sin avanzar
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def match(self, expected_type, expected_value=None):
        # Verifica que el token actual sea del tipo esperado y avanza
        token = self.current_token()
        
        if token and token.type == expected_type:
            if expected_value and token.value != expected_value:
                raise SyntaxError(f"Error en linea {token.line}: Se esperaba '{expected_value}', se encontro '{token.value}'")
            
            self.pos += 1
            return token
            
        if token:
            raise SyntaxError(f"Error en linea {token.line}, columna {token.column}: Se esperaba tipo {expected_type}, se encontró {token.type} ('{token.value}')")
        else:
            raise SyntaxError(f"Fin de consulta inesperado. Se esperaba {expected_type}")

    def parse(self):
        # Punto de entrada. Retorna el AST en forma de diccionario
        return self.parse_statement()

    def parse_statement(self):
        token = self.current_token()
        if not token:
            return None
            
        if token.type == 'SELECT':
            return self.parse_select()
        elif token.type == 'CREATE': 
            return self.parse_create()
        elif token.type == 'INSERT': 
            return self.parse_insert()
        elif token.type == 'DELETE':
            return self.parse_delete()
        else:
            raise SyntaxError(f"Sentencia SQL no soportada: {token.value}")
        
    """
    =========================================== CREATE ===========================================
    """
    
    def parse_create(self):
        # Regla: CREATE TABLE <id> ( <col_def_list> ) [FROM FILE <string>] ;
        
        self.match('CREATE')
        self.match('TABLE')
        
        table_name = self.match('ID').value
        
        self.match('SYMBOL', '(')
        
        # Lista de columnas
        columns = self.parse_column_list()
        
        self.match('SYMBOL', ')')
        
        # Bloque FROM FILE opcional
        file_path = None
        delimiter_char = ','

        if self.current_token() and self.current_token().type == 'FROM':
            self.match('FROM')
            self.match('FILE')
            # El lexer ya le quitó las comillas al string
            file_path = self.match('STRING').value 

            if self.current_token() and self.current_token().type == 'DELIMITER':
                self.match('DELIMITER')
                delimiter_char = self.match('STRING').value
            
        self.match('SYMBOL', ';')
        
        return {
            "statement": "CREATE",
            "table": table_name,
            "columns": columns,
            "file": file_path,
            "delimiter": delimiter_char
        }

    def parse_column_list(self):
        # Regla: <col_def> | <col_def> , <col_def_list>
        
        columns = []
        while True:
            col_name = self.match('ID').value
            
            # Reconocer el tipo de dato
            type_token = self.current_token()
            if type_token.type not in ('INT', 'FLOAT', 'VARCHAR', 'POINT'):
                raise SyntaxError(f"Tipo de dato no válido: {type_token.value}")
            col_type = self.match(type_token.type).value
            
            # Índice (opcional)
            index_tech = None
            if self.current_token() and self.current_token().type == 'INDEX':
                self.match('INDEX')
                index_tech = self.match('ID').value # Sequential, BTree, Hash
                
            columns.append({
                "name": col_name,
                "type": col_type,
                "index": index_tech
            })
            
            # Si hay una coma, hay más columnas. Si no, terminamos el bucle.
            if self.current_token() and self.current_token().value == ',':
                self.match('SYMBOL', ',')
            else:
                break
                
        return columns
    

    """
    =========================================== SEARCH ===========================================
    """

    def parse_select(self):
        # Regla: SELECT * FROM <id> WHERE <id> <condicion> ;
        self.match('SELECT')
        self.match('SYMBOL', '*')  # Por ahora que el símbolo sea estrictamente *
        self.match('FROM')
        
        table_name = self.match('ID').value
        
        self.match('WHERE')
        column_name = self.match('ID').value

        op_token = self.current_token()
        
        # Manejo para la consulta espacial
        if op_token and op_token.type == 'IN':
            self.match('IN')
            self.match('SYMBOL', '(')
            self.match('POINT')
            self.match('SYMBOL', '(')
            
            # Coordenada X
            x_val = self.match('NUMBER').value
            self.match('SYMBOL', ',')
            # Coordenada Y
            y_val = self.match('NUMBER').value
            
            self.match('SYMBOL', ')')
            self.match('SYMBOL', ',')
            
            tipo_busqueda = self.current_token().type
            
            if tipo_busqueda == 'K': # Búsqueda KNN
                self.match('K')
                param_val = int(self.match('NUMBER').value)
                action = 'knn'
            elif tipo_busqueda == 'RADIUS': # Búsqueda rangeSearch
                self.match('RADIUS')
                param_val = float(self.match('NUMBER').value)
                action = 'range_spatial'
            else:
                raise SyntaxError("Se esperaba K o RADIUS en la consulta espacial.")
                
            self.match('SYMBOL', ')')
            self.match('SYMBOL', ';')
            
            return {
                "statement": "SELECT",
                "table": table_name,
                "condition": {
                    "action": action,
                    "column": column_name,
                    "point": (x_val, y_val),
                    "param": param_val 
                }
            }
        
        # Análisis de condición a otra regla
        condition_ast = self.parse_condition(column_name)
        
        self.match('SYMBOL', ';') # Condición de final de sentencia
        
        # nodo raiz
        ast = {
            "statement": "SELECT",
            "table": table_name,
            "condition": condition_ast
        }
        return ast

    def parse_condition(self, column_name):
        # Traduce directamente a las llamadas requeridas: search, rangeSearch, kNN

        token = self.current_token()
        
        # Búsqueda Exacta: <col> = <valor>
        if token.type == 'OP' and token.value == '=':
            self.match('OP')
            val_token = self.current_token()
            if val_token.type not in ('NUMBER', 'STRING'):
                raise SyntaxError("Se esperaba un número o cadena después de '='")
            value = self.match(val_token.type).value
            
            return {
                "action": "search",
                "column": column_name,
                "key": value
            }
            
        # Busqueda por Rango: BETWEEN <v1> AND <v2>
        elif token.type == 'BETWEEN':
            self.match('BETWEEN')
            v1 = self.match('NUMBER').value
            self.match('AND')
            v2 = self.match('NUMBER').value
            
            return {
                "action": "rangeSearch",
                "column": column_name,
                "begin_key": v1,
                "end_key": v2
            }
            
        # Consultas Espaciales: IN (POINT(x, y), RADIUS r) | IN (POINT(x, y), K k)
        elif token.type == 'IN':
            self.match('IN')
            self.match('SYMBOL', '(')
            self.match('POINT')
            self.match('SYMBOL', '(')
            
            x = self.match('NUMBER').value
            self.match('SYMBOL', ',')
            y = self.match('NUMBER').value
            
            self.match('SYMBOL', ')')
            self.match('SYMBOL', ',')
            
            spatial_type = self.current_token()
            if spatial_type.type == 'RADIUS':
                self.match('RADIUS')
                radio = self.match('NUMBER').value
                self.match('SYMBOL', ')')
                return {
                    "action": "rangeSearch_spatial",
                    "column": column_name,
                    "point": (x, y),
                    "radius": radio
                }
            elif spatial_type.type == 'K':
                self.match('K')
                k_val = int(self.match('NUMBER').value) 
                self.match('SYMBOL', ')')
                return {
                    "action": "kNN",
                    "column": column_name,
                    "point": (x, y),
                    "k": k_val
                }
            else:
                raise SyntaxError("Se esperaba RADIUS o K dentro de la cláusula IN")
                
        else:
            raise SyntaxError(f"Condición no reconocida. Token actual: {token.value}")
        
    """
    =========================================== INSERT ===========================================
    """
    
    def parse_insert(self): 
        # Regla: INSERT INTO <id> VALUES ( <value_list> ) ;
         
        self.match('INSERT')
        self.match('INTO')
        
        table_name = self.match('ID').value
        
        self.match('VALUES')
        self.match('SYMBOL', '(')
        
        values = []
        # Procesar lista de valores separados por coma
        while True:
            token = self.current_token()
            
            if token and token.type in ('NUMBER', 'STRING'):
                val = self.match(token.type).value
                values.append(val)
            else:
                raise SyntaxError(f"Se esperaba un número o cadena en VALUES. Encontrado: {token.value if token else 'EOF'}")
            
            if self.current_token() and self.current_token().value == ',':
                self.match('SYMBOL', ',')
            else:
                break  # Termina si no hay coma
                
        self.match('SYMBOL', ')')
        self.match('SYMBOL', ';')
        
        return {
            "statement": "INSERT",
            "table": table_name,
            "values": values,
            "action": "add" 
        }
    
    """
    =========================================== DELETE ===========================================
    """

    def parse_delete(self):   
        # Regla: DELETE FROM <id> WHERE <id> = <value> ;
         
        self.match('DELETE')
        self.match('FROM')
        
        table_name = self.match('ID').value
        
        self.match('WHERE')
        column_name = self.match('ID').value
        
        self.match('OP', '=')
        
        # Extrae el valor a eliminar
        token = self.current_token()
        if token and token.type in ('NUMBER', 'STRING'):
            val = self.match(token.type).value
        else:
             raise SyntaxError(f"Se esperaba un número o cadena después de '='. Encontrado: {token.value if token else 'EOF'}")
             
        self.match('SYMBOL', ';')
        
        return {
            "statement": "DELETE",
            "table": table_name,
            "condition": {
                "action": "remove", 
                "column": column_name,
                "key": val
            }
        }