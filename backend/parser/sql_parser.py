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
        # elif token.type == 'CREATE': return self.parse_create()
        # elif token.type == 'INSERT': return self.parse_insert()
        else:
            raise SyntaxError(f"Sentencia SQL no soportada: {token.value}")

    def parse_select(self):
        # Regla: SELECT * FROM <id> WHERE <id> <condicion> ;
        self.match('SELECT')
        self.match('SYMBOL', '*')  # Por ahora que el símbolo sea estrictamente *
        self.match('FROM')
        
        table_name = self.match('ID').value
        
        self.match('WHERE')
        column_name = self.match('ID').value
        
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