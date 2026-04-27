import os
import matplotlib.pyplot as plt
from datetime import datetime

def save_spatial_plot(target_point, clean_results, spatial_col_idx, search_type="KNN", param=None, data_dir="backend/data"):
    # Genera un gráfico de dispersión de la búsqueda espacial y lo guarda como PNG.
    images_dir = os.path.join(data_dir, "images")
    os.makedirs(images_dir, exist_ok=True)
    
    fig, ax = plt.subplots(figsize=(8, 8))
    
    # Coordenadas de los resultados limpios
    x_coords = []
    y_coords = []
    for row in clean_results:
        point_tuple = row[spatial_col_idx]
        x_coords.append(point_tuple[0])
        y_coords.append(point_tuple[1])
        
    # Puntos encontrados
    ax.scatter(x_coords, y_coords, c='blue', alpha=0.6, edgecolors='k', s=30, label='Resultados')
    
    # Punto objetivo
    ax.scatter([target_point[0]], [target_point[1]], c='red', marker='X', s=150, label='Punto Objetivo')
    
    if search_type == "RANGE" and param is not None:
        circle = plt.Circle(target_point, param, color='red', fill=False, linestyle='--', linewidth=2, label=f'Radio ({param})')
        ax.add_patch(circle)
        
    ax.set_aspect('equal', adjustable='datalim')
    
    titulo = f"KNN (K={param})" if search_type == "KNN" else f"Búsqueda por Radio ({param})"
    plt.title(f"Resultados Espaciales: {titulo}")
    plt.xlabel("Eje X")
    plt.ylabel("Eje Y")
    plt.grid(True, linestyle=':', alpha=0.7)
    plt.legend()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{search_type.lower()}_{timestamp}.png"
    filepath = os.path.join(images_dir, filename)
    
    plt.savefig(filepath, dpi=300, bbox_inches='tight')
    plt.close()
    
    return filepath