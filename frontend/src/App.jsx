import { useState } from 'react'
import axios from 'axios'
import './App.css'

// Utilidad para resaltar sintaxis SQL sin librerias extra
const highlightSQL = (text) => {
  if (!text) return '';
  
  // Escapar HTML básico
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  const keywords = [
    'SELECT', 'FROM', 'WHERE', 'INSERT', 'INTO', 'VALUES', 
    'CREATE', 'TABLE', 'DROP', 'INDEX', 'RADIUS', 'POINT', 
    'IN', 'AND', 'OR', 'NOT', 'NULL', 'PRIMARY', 'KEY', 
    'FILE', 'DELIMITER', 'BETWEEN'
  ];
  
  const types = ['INT', 'VARCHAR', 'FLOAT'];

  // Construye una sola expresión regular para evaluar los tokens sin alterar el HTML ya inyectado
  const allKeywords = [...keywords, ...types];
  const regex = new RegExp(
    `('.*?'|".*?")|\\b(${allKeywords.join('|')})\\b|\\b(\\d+(\\.\\d+)?)\\b`,
    'gi'
  );

  return html.replace(regex, (match, pString, pKw) => {
    if (pString) {
      return `<span class="sql-string">${match}</span>`;
    } else if (pKw) {
      // Diferenciar si es un tipo de dato o keyword normal
      const isType = types.some(t => t.toLowerCase() === match.toLowerCase());
      if (isType) {
        return `<span class="sql-type">${match}</span>`;
      }
      return `<span class="sql-keyword">${match}</span>`;
    } else {
      // Caso de números
      return `<span class="sql-number">${match}</span>`;
    }
  });
};

function App() {
  const [query, setQuery] = useState('SELECT * FROM Viajes WHERE Pickup_Location IN (POINT(-73.9903, 40.7346), RADIUS 0.001);')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Mapeo mock de las tablas para el sidebar izquierdo
  const schemaMock = [
    {
      name: "Viajes", index: "R-Tree",
      columns: [
        { name: "ID", type: "INT" },
        { name: "Pickup_Location", type: "POINT" },
        { name: "Dropoff_Location", type: "POINT" },
        { name: "Total_Amount", type: "FLOAT" }
      ]
    },
    {
      name: "Empleados", index: "Sequential",
      columns: [
        { name: "Employee_ID", type: "INT" },
        { name: "Employee_Name", type: "VARCHAR" },
        { name: "Age", type: "INT" }
      ]
    }
  ]

  const executeQuery = async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    
    try {
      const res = await axios.post('http://localhost:8000/execute', { query })
      setResult(res.data)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Error en la consulta')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="ide-layout">
      {/* Left Sidebar: Database Schema */}
      <aside className="sidebar left-sidebar">
        <div className="sidebar-header">
          <h2>🗄️ Database</h2>
        </div>
        <div className="schema-container">
          {schemaMock.map((table, i) => (
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

      {/* Main Content: Editor & Results */}
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
                    <tr key={idx}>
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

      {/* Right Sidebar: Statistics & Plot */}
      <aside className="sidebar right-sidebar">
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
          <div className="plot-box">
             {result && result.image_url ? (
               <img src={`http://localhost:8000${result.image_url}`} alt="R-Tree Spatial Visualization" />
             ) : (
               <div className="no-plot-text">No data to plot. Use a Spatial Query to visualize.</div>
             )}
          </div>
        </div>
      </aside>
    </div>
  )
}

export default App