import os
import plotly.graph_objects as go
import plotly.io as pio
from datetime import datetime
import json
import numpy as np

def save_spatial_plot(target_point, clean_results, spatial_col_idx, search_type="KNN", param=None, data_dir="backend/data"):
    """Genera un gráfico interactivo de dispersión espacial usando Plotly"""
    images_dir = os.path.join(data_dir, "images")
    os.makedirs(images_dir, exist_ok=True)
    
    # Coordenadas de los resultados limpios
    x_coords = []
    y_coords = []
    hover_texts = []
    
    for idx, row in enumerate(clean_results):
        point_tuple = row[spatial_col_idx]
        x = point_tuple[0]
        y = point_tuple[1]
        x_coords.append(x)
        y_coords.append(y)
        hover_texts.append(f"<b>Resultado #{idx + 1}</b><br>X: {x:.6f}<br>Y: {y:.6f}")
    
    # Crear figura con Plotly
    fig = go.Figure()
    
    # Agregar puntos de resultados
    fig.add_trace(go.Scatter(
        x=x_coords, y=y_coords,
        mode='markers',
        name='Resultados',
        marker=dict(
            size=8,
            color='blue',
            opacity=0.7,
            line=dict(color='darkblue', width=1)
        ),
        text=hover_texts,
        hovertemplate='%{text}<extra></extra>',
        hoverinfo='text'
    ))
    
    # Agregar punto objetivo (X roja)
    fig.add_trace(go.Scatter(
        x=[target_point[0]],
        y=[target_point[1]],
        mode='markers',
        name='Punto Objetivo',
        marker=dict(
            size=15,
            symbol='x',
            color='red',
            line=dict(color='darkred', width=2)
        ),
        hovertemplate=f"<b>Punto Objetivo</b><br>X: {target_point[0]:.6f}<br>Y: {target_point[1]:.6f}<extra></extra>"
    ))
    
    # Agregar círculo de radio si es búsqueda por rango
    if search_type == "RANGE" and param is not None:
        # Crear puntos para dibujar el círculo
        theta = np.linspace(0, 2*np.pi, 100)
        circle_x = target_point[0] + param * np.cos(theta)
        circle_y = target_point[1] + param * np.sin(theta)
        
        fig.add_trace(go.Scatter(
            x=circle_x.tolist(), 
            y=circle_y.tolist(),
            mode='lines',
            name=f'Radio ({param})',
            line=dict(color='red', dash='dash', width=2),
            hoverinfo='skip'
        ))
    
    # Configurar layout
    titulo = f"KNN (K={param})" if search_type == "KNN" else f"Búsqueda por Radio ({param})"
    
    fig.update_layout(
        title=f"Resultados Espaciales: {titulo}",
        xaxis_title="Eje X (Longitud)",
        yaxis_title="Eje Y (Latitud)",
        hovermode='closest',
        plot_bgcolor='rgba(240, 240, 240, 0.5)',
        paper_bgcolor='white',
        width=800,
        height=800,
        font=dict(size=11),
        legend=dict(
            x=0.02,
            y=0.98,
            bgcolor='rgba(255, 255, 255, 0.8)',
            bordercolor='gray',
            borderwidth=1
        )
    )
    
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='lightgray')
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='lightgray')
    
    # Guardar como HTML interactivo
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{search_type.lower()}_{timestamp}.html"
    filepath = os.path.join(images_dir, filename)
    
    fig.write_html(filepath)
    
    # Retornar el JSON de Plotly en lugar de HTML para mejor integración
    plot_json = pio.to_json(fig)
    
    return filepath, plot_json