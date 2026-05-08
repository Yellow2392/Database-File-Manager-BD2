import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import './App.css'

// Utilidad para resaltar sintaxis SQL sin librerias extra
const highlightSQL = (text) => {
  if (!text) return '';
  
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  const keywords = [
    'SELECT', 'FROM', 'WHERE', 'INSERT', 'INTO', 'VALUES', 
    'CREATE', 'TABLE', 'DROP', 'INDEX', 'DELETE', 'RADIUS', 'POINT', 
    'IN', 'AND', 'OR', 'NOT', 'NULL', 'PRIMARY', 'KEY', 
    'FILE', 'DELIMITER', 'BETWEEN'
  ];
  
  const types = ['INT', 'VARCHAR', 'FLOAT', 'BOOLEAN', 'DATE'];

  const allKeywords = [...keywords, ...types];
  const regex = new RegExp(
    `('.*?'|".*?")|\\b(${allKeywords.join('|')})\\b|\\b(\\d+(\\.\\d+)?)\\b`,
    'gi'
  );

  return html.replace(regex, (match, pString, pKw) => {
    if (pString) {
      return `<span class="sql-string">${match}</span>`;
    } else if (pKw) {
      const isType = types.some(t => t.toLowerCase() === match.toLowerCase());
      if (isType) {
        return `<span class="sql-type">${match}</span>`;
      }
      return `<span class="sql-keyword">${match}</span>`;
    } else {
      return `<span class="sql-number">${match}</span>`;
    }
  });
};

function App() {
  const [query, setQuery] = useState('SELECT * FROM Viajes WHERE Pickup_Location IN (POINT(-73.9903, 40.7346), RADIUS 0.001);')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [schema, setSchema] = useState([])
  const [hoveredCoords, setHoveredCoords] = useState(null)
  const [toast, setToast] = useState(null)
  const plotContainerRef = useRef(null)

  const showToast = (type, message) => {
    setToast({ type, message })
    setTimeout(() => setToast(null), 1800)
  }

  const [leftWidth, setLeftWidth] = useState(() => {
    return parseInt(localStorage.getItem('leftWidth')) || 250
  })
  const [rightWidth, setRightWidth] = useState(() => {
    return parseInt(localStorage.getItem('rightWidth')) || 700
  })

  const handleMouseDownLeft = (e) => {
    e.preventDefault()
    const startX = e.clientX
    const startWidth = leftWidth

    const handleMouseMove = (moveEvent) => {
      const diff = moveEvent.clientX - startX
      const newWidth = Math.max(150, Math.min(startWidth + diff, 600))
      setLeftWidth(newWidth)
      localStorage.setItem('leftWidth', newWidth.toString())
    }

    const handleMouseUp = () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      document.body.style.userSelect = 'auto'
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    document.body.style.userSelect = 'none'
  }

  const handleMouseDownRight = (e) => {
    e.preventDefault()
    const startX = e.clientX
    const startWidth = rightWidth

    const handleMouseMove = (moveEvent) => {
      const diff = startX - moveEvent.clientX
      const newWidth = Math.max(300, Math.min(startWidth + diff, 1200))
      setRightWidth(newWidth)
      localStorage.setItem('rightWidth', newWidth.toString())
    }

    const handleMouseUp = () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      document.body.style.userSelect = 'auto'
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    document.body.style.userSelect = 'none'
  }

  const fetchSchema = async () => {
    try {
      const res = await axios.get('http://localhost:8000/schema')
      setSchema(res.data)
    } catch (err) {
      console.error('Error loading schema:', err)
    }
  }

  useEffect(() => {
    fetchSchema()
  }, [])

  useEffect(() => {
    if (result && result.plot && plotContainerRef.current) {
      try {
        const plotData = JSON.parse(result.plot);
        const container = plotContainerRef.current;
        const width = container.offsetWidth - 20;
        const height = container.offsetHeight - 20;

        plotData.layout.width = width;
        plotData.layout.height = height;
        plotData.layout.autosize = true;
        plotData.layout.margin = { l: 50, r: 50, t: 50, b: 50 };

        const config = {
          responsive: true,
          displayModeBar: true,
          displaylogo: false,
          modeBarButtonsToAdd: ['pan2d', 'select2d', 'lasso2d', 'resetScale2d'],
          toImageButtonOptions: {
            format: 'png',
            filename: 'rtree_plot',
            height: 800,
            width: 1000,
            scale: 1
          }
        };

        window.Plotly.newPlot(container, plotData.data, plotData.layout, config);

        const handleResize = () => {
          const newWidth = container.offsetWidth - 20;
          const newHeight = container.offsetHeight - 20;
          window.Plotly.relayout(container, { 
            width: newWidth, 
            height: newHeight 
          });
        };

        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
      } catch (err) {
        console.error('Error renderizando gráfico:', err);
      }
    }
  }, [result?.plot])

  const executeQuery = async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    setHoveredCoords(null)

    try {
      const res = await axios.post('http://localhost:8000/execute', { query })
      setResult(res.data)
      fetchSchema()
      showToast('success', 'Consulta ejecutada correctamente')
    } catch (err) {
      const message = err.response?.data?.detail || err.message || 'Error en la consulta'
      setError(message)
      showToast('error', message)
    } finally {
      setLoading(false)
    }
  }

  const handleRowHover = (row) => {
    const coordCols = [];
    result.columns.forEach((colName, idx) => {
      if (colName.toLowerCase().includes('location')) {
        coordCols.push({ name: colName, idx: idx, value: row[idx] });
      }
    });
    setHoveredCoords(coordCols);
  }

  const handleRowLeave = () => {
    setHoveredCoords(null);
  }

  return (
    <>
      {toast && (
        <div className={`toast toast-${toast.type}`}>
          <span className="toast-icon">{toast.type === 'success' ? '✓' : '✕'}</span>
          <span>{toast.message}</span>
        </div>
      )}

      <div className="ide-layout">
        {/* Left Sidebar: Database Schema */}
        <aside className="sidebar left-sidebar" style={{ width: `${leftWidth}px`, minWidth: `${leftWidth}px` }}>
          <div className="sidebar-header">
            <h2>🗄️ Database</h2>
          </div>
          <div className="schema-container">
            {schema.map((table, i) => (
              <div key={i} className="table-block">
                <div className="table-title">
                  <span className="icon">📄</span> {table.name} 
                  <span className="index-badge">{table.index}</span>
                </div>
                <ul className="column-list">
                  {table.columns.map((col, j) => (
                    <li key={j}>
                      <span className="col-name">{col.name}</span>
                      <span className="col-type">{col.type}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </aside>

        <div
          className="resizer resizer-left"
          onMouseDown={handleMouseDownLeft}
        />

        <main className="main-content">
          <div className="editor-pane">
            <div className="editor-toolbar">
              <button onClick={executeQuery} disabled={loading} className="run-button">
                ▶ {loading ? 'Running...' : 'Run Query'}
              </button>
            </div>
            <div className="editor-container">
              <div className="line-numbers">
                {query.split('\n').map((_, i) => (
                  <div key={i}>{i + 1}</div>
                ))}
              </div>
              <div className="editor-wrapper">
                <div 
                  className="highlight-layer" 
                  dangerouslySetInnerHTML={{ __html: highlightSQL(query) }}
                />
                <textarea 
                  className="sql-input"
                  value={query} 
                  onChange={(e) => setQuery(e.target.value)} 
                  placeholder="Escribe tu consulta SQL aquí..."
                  spellCheck="false"
                />
              </div>
            </div>
          </div>

          <div className="results-pane">
            {error && <div className="error-box">{error}</div>}
            
            {(!result && !error) && (
              <div className="empty-results">Waiting for execution...</div>
            )}

            {result && result.rows && result.rows.length > 0 && (
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      {result.columns.map((colName, idx) => (
                        <th key={idx}>{colName}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, idx) => (
                      <tr key={idx} 
                          onMouseEnter={() => handleRowHover(row)}
                          onMouseLeave={handleRowLeave}>
                        {row.map((val, i) => (
                          <td key={i}>{val !== null && val !== undefined ? String(val) : 'NULL'}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            
            {result && (!result.rows || result.rows.length === 0) && (
              <div className="empty-results">Ejecución completada. Sin resultados tubulares.</div>
            )}
          </div>
        </main>

        <div
          className="resizer resizer-right"
          onMouseDown={handleMouseDownRight}
        />

        <aside className="sidebar right-sidebar" style={{ width: `${rightWidth}px`, minWidth: `${rightWidth}px` }}>
          <div className="sidebar-header">
            <h2>📊 Analytics & Plot</h2>
          </div>
          
          <div className="metrics-container">
            <div className="metric-card">
              <span className="metric-title">⏱️ Execution Time</span>
              <span className="metric-value">{result?.metrics?.executionTime || '-'}</span>
            </div>
            <div className="metric-card">
              <span className="metric-title">🔄 Disk Reads</span>
              <span className="metric-value">{result?.metrics?.diskReads ?? '-'}</span>
            </div>
            <div className="metric-card">
              <span className="metric-title">💾 Disk Writes</span>
              <span className="metric-value">{result?.metrics?.diskWrites ?? '-'}</span>
            </div>
          </div>

          <div className="plot-container">
            <h3>R-Tree Plot Viewer</h3>
            <div className="plot-box" ref={plotContainerRef}>
              {!result || !result.plot ? (
                <div className="no-plot-text">No data to plot. Use a Spatial Query to visualize.</div>
              ) : null}
            </div>
            {hoveredCoords && hoveredCoords.length > 0 && (
              <div className="coordinates-info">
                <strong>📍 Coordenadas:</strong>
                {hoveredCoords.map((coord, idx) => (
                  <div key={idx} className="coords-row">
                    <strong>{coord.name}:</strong> {coord.value}
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>
      </div>
    </>
  )
}

export default App