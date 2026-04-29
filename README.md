# Database File Manager (BD2)

**Curso:** Base de Datos 2  
**Institución:** Universidad de Ingeniería y Tecnología (UTEC)  
**Integrantes:**
- [Nombre Integrante 1]
- [Nombre Integrante 2]
- [Nombre Integrante 3]
- [Nombre Integrante 4]
- [Nombre Integrante 5]

---

## 1. Introducción y Objetivo
El objetivo principal de este proyecto es implementar un sistema gestor de almacenamiento en memoria secundaria simulado completamente desde cero utilizando Python. Este sistema permite interactuar con tablas a través de un dialecto SQL y evalúa empíricamente la eficiencia de distintas técnicas de indexación (Sequential File, Extendible Hashing, B+ Tree, R-Tree) mediante el conteo de accesos a páginas en disco y el registro del tiempo de ejecución. Además, se da soporte a consultas para bases de datos espaciales, definiendo las operaciones recurrentes de este tipo de manejo. No se utilizan motores de bases de datos externos, garantizando que toda E/S de datos esté controlada explícitamente y empaquetada en bloques fijos de bytes. 

---

## 2. Descripción de Técnicas y Algoritmos Implementados

### 2.1. Archivo Secuencial (Sequential File)
Esta técnica organiza los registros físicamente en el disco basándose en un atributo clave de ordenamiento.

- **Estructura Físico-Lógica:** Se implementa utilizando un Archivo Principal (Main File) con los registros ordenados y un Archivo Auxiliar (Aux File) para agilizar las inserciones antes de un proceso de reconstrucción (rebuild).
- **Algoritmo de Inserción:** Se realiza una inserción sobre el archivo auxiliar, leyendo la última página. Si el tamaño *k* del archivo auxiliar es mayor o igual a $\sqrt{n}$, donde *n* es el tamaño del archivo, se procede a realizar una reconstrucción fusionando el archivo principal y con el auxiliar. 
- **Algoritmo de Búsqueda:** Se hace una búsqueda binaria a nivel de páginas dentro del archivo principal y recorrido lineal en las páginas del archivo auxiliar.
- **Algoritmo de Búsqueda por Rango:** Se aprovecha el orden en el archivo principal para realizar una búsqueda binaria con la llave inicial. Una vez encontrado el inicio, empieza a recorrer ordenadamente el resto del archivo principal y secuencialmente el auxiliar para encontrar el último registro dentro del rango especificado.
- **Algoritmo de Eliminación:** Se busca al registro a eliminar mediante una búsqueda binaria sobre el archivo principal y sobre una búsqueda lineal sobre el archivo auxiliar. Una vez encontrado, marca al registro como eliminado y no se tiene encuenta para futuras consultas. Este se elimina una vez se llama a la reconstrucción del archivo.
- **Algoritmo de Inserción Masiva:** Se toma el CSV de entrada y se convierte en el archivo principal ordenado. Esto se logra a partir de cargar los registros en un bloques pequeños de RAM, ordenar el bloque y guardarlo como archivo binario para después hacer la mezcla de los archivos temporales y empaquetarlos en páginas del tamaño expecíficado. Todo esto se hace mediante el algoritmo externo **Two-Phase Multiway Merge Sort** (abreviado External Sort).
- **Algoritmo de Reconstrucción:** Se agarran los bytes del archivo principal y los bytes del auxiliar y los pega todos juntos en un solo archivo temporal, el cual se pasa al External Sort devolviendo un archivo principal completamente ordenado.

![Archivo Secuencial](./images/seq_file.png "Archivo Secuencial")

### 2.2. Extendible Hashing

### 2.3. B+ Tree

### 2.4. Índice Espacial (R-Tree)
Estructura de árbol diseñada para indexar información multidimensional. Utilizada para procesar los datos de ubicaciones geográficas (*Pickup_Location* / *Dropoff_Location*).

- **Estructura Físico-Lógica:** Nodos agrupados en páginas del disco como Minimum Bounding Boxes (MBBs).
- **Algoritmo de Inserción / Construcción:** 
  *[Describe cómo se realiza el particionamiento de nodos y la carga masiva]*
- **Algoritmo de Búsqueda (Point y Radius/KNN):** Funciona descartando los rectángulos delimitadores que no intersecan con el área de interés establecida.

![RTree](./images/r_tree.png "RTree")

---

## 3. Análisis Teórico Comparativo de Accesos a Disco
En base a la teoría y tamaño de página constante establecido (ej. 4 KB):

| Operación | Sequential File (Teórico) | R-Tree (Teórico) |
| :--- | :---: | :---: |
| **Búsqueda Puntual** | $O(\log_2 b)$ main + aux | $O(\log_m n)$ |
| **Búsqueda x Rango** | $O(\log_2 b + \frac{k}{r})$ | $O(\log_m n + C)$ |
| **Inserción** | $O(1)$ (en Aux log) | $O(\log_m n)$ o Split |

*Donde:* $n$ es la cantidad de registros poblados, $b$ es la cantidad de bloques en disco, $m$ constante de partición del árbol.  
*(Explicar brevemente el por qué de estas complejidades).*

---

## 4. Descripción del Parser SQL
Para poder interactuar con las estructuras desde sentencias abstractas, se desarrolló un Parser y Lexer propio:

- **Lexer (Análisis Léxico):** Construido usando expresiones regulares. Transforma la cadena SQL entrante (`SELECT`, `FROM`, `CREATE`, etc.) en una lista de *tokens*.
- **Parser (Análisis Sintáctico):** Basado en un procesador top-down. Verifica la secuencia lógica de los tokens asegurando la gramática requerida (soporte para `CREATE TABLE`, `INSERT`, `SELECT`, cláusulas `WHERE`, y keywords geoespaciales como `POINT`, `RADIUS`).
- **Autómatas / Gramática Principal:**  
  `S -> CREATE_STMT | INSERT_STMT | SELECT_STMT | DROP_STMT`  
  *(Adjuntar más detalle si se considera oportuno).*

---

## 5. Resultados Experimentales y Discusión
Para los experimentos se usó el dataset público de *Yellow Tripdata de Nueva York (2016)* con N = 1 000, 10 000 y 100 000.

### Métricas Obtenidas
*(Insertar una tabla con los resultados empíricos)*

### Gráficos
- **[Insertar gráfico comparativo de Tiempos (ms)]**
- **[Insertar gráfico comparativo de Accesos a Disco (reads/writes)]**

### Discusión
*(Analizar si los resultados escalaron de manera equivalente a la teoría O(N) colocada en el Punto 3, y dar conclusiones)*

---

## 6. Interfaz Gráfica (GUI)
*(Colocar capturas de pantalla de la aplicación ejecutándose)*
- **Captura 1:** Pantalla principal y carga (CREATE).
- **Captura 2:** Realizando una búsqueda SELECT y mostrando tabla de resultados y conteo de páginas de disco y tiempo.
- **Captura 3:** Visualización del plot Geoespacial.

---

## 7. Despliegue y Ejecución

Se ha empaquetado el sistema empleando contenedores para aislar sus dependencias.

**Vía Docker Compose (Recomendado):**
1. Asegurarse de tener instalado Docker Desktop.
2. Posicionarse en la carpeta raíz del repositorio.
3. Levantar la aplicación con:
   ```bash
   docker-compose up --build
