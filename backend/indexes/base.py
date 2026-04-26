from abc import ABC, abstractmethod
from backend.catalog import PAGE_SIZE
import os

class BaseIndex(ABC):
    def __init__(self, table_meta, key_column, data_dir="backend/data"):
        # Propiedades comunes para las técnicas
        self.table_meta = table_meta
        self.key_column = key_column
        self.data_dir = data_dir
        
        self.PAGE_SIZE = PAGE_SIZE
        
        self.disk_reads = 0
        self.disk_writes = 0
        
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

    @abstractmethod
    def add(self, record_tuple, is_bulk = False):
        """
        Inserta un registro en disco.
        :param record_tuple: Tupla con los valores parseados (incluyendo is_deleted al final).
        """
        pass

    @abstractmethod
    def search(self, key_value):
        """
        Busca un registro por su llave primaria.
        :param key_value: El valor de la llave a buscar.
        :return: La tupla del registro encontrado, o None si no existe/está eliminado.
        """
        pass

    @abstractmethod
    def remove(self, key_value):
        """
        Realiza la eliminación lógica de un registro.
        :param key_value: El valor de la llave a eliminar.
        :return: True si se eliminó con éxito, False si no se encontró.
        """
        pass

    @abstractmethod
    def rangeSearch(self, begin_key, end_key):
        """
        Busca registros en un rango de llaves.
        :param begin_key: Límite inferior.
        :param end_key: Límite superior.
        :return: Lista de tuplas encontradas.
        """
        pass

    @abstractmethod
    def bulk_load(self, csv_path, delimiter = ','):
        """
        Realiza la carga masiva de datos desde un archivo CSV.
        Cada técnica implementará esto de la forma más óptima posible.
        """
        pass