import re
from typing import NamedTuple, List, Any

class Token(NamedTuple):
    type: str
    value: Any
    line: int
    column: int

class DBMSSqlLexer:
    def __init__(self):
        # Keywords
        self.keywords = {
            'CREATE', 'TABLE', 'FROM', 'FILE', 'INDEX',
            'SELECT', 'WHERE', 'BETWEEN', 'AND', 'IN',
            'POINT', 'RADIUS', 'K', 'INSERT', 'INTO',
            'VALUES', 'DELETE', 'INT', 'FLOAT', 'VARCHAR'
        }
        
        # Automata finito
        self.token_specification = [
            ('NUMBER',    r'-?\d+(\.\d+)?'),           # Enteros o punto flotante
            ('STRING',    r'\'[^\']*\'|"[^"]*"'),      # Literales de cadena
            ('ID',        r'[A-Za-z_][A-Za-z0-9_]*'),  # Nombres de tablas, columnas
            ('SYMBOL',    r'[(),;*]'),                 # Paréntesis, comas, punto y coma, asterisco
            ('OP',        r'>=|<=|!=|[=><]'),          # Operadores relacionales
            ('WS',        r'\s+'),                     # Espacios, tabs, saltos de línea
            ('MISMATCH',  r'.'),                       # Cualquier otro caracter (dispara error)
        ]
        
        # Expresion regular
        tok_regex = '|'.join('(?P<%s>%s)' % pair for pair in self.token_specification)
        self.get_token = re.compile(tok_regex).match

    def tokenize(self, code: str) -> List[Token]:
        tokens = []
        line_num = 1
        line_start = 0
        pos = 0
        match = self.get_token(code)
        
        while match is not None:
            type_ = match.lastgroup
            value = match.group(type_)
            column = match.start() - line_start
            
            if type_ == 'NUMBER':
                value = float(value) if '.' in value else int(value)
            
            elif type_ == 'ID': # Si es palabra reservada cambia el tipo
                value_upper = value.upper()
                if value_upper in self.keywords:
                    type_ = value_upper
            
            elif type_ == 'STRING':
                value = value.strip('\'"')
            
            elif type_ == 'WS':
                # Para reporte de errores
                if '\n' in value:
                    line_num += value.count('\n')
                    line_start = match.end()
                pos = match.end()
                match = self.get_token(code, pos)
                continue
            
            elif type_ == 'MISMATCH':
                raise SyntaxError(f'Error léxico en línea {line_num}, columna {column}: Caracter inesperado {value!r}')
            
            tokens.append(Token(type_, value, line_num, column))
            pos = match.end()
            match = self.get_token(code, pos)
            
        return tokens