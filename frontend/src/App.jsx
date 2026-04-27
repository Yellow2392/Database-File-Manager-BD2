import { useState } from 'react'
import axios from 'axios'
import './App.css'

function App() {
  const [query, setQuery] = useState('SELECT * FROM Viajes WHERE Pickup_Location IN (POINT(-73.9903, 40.7346), RADIUS 0.001);')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const executeQuery = async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    
    try {
      // Configuraremos el endpoint del backend fastapi mas adelante (Paso 2)
      const res = await axios.post('http://localhost:8000/execute', { query })
      setResult(res.data)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Error en la consulta')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="container">
      <header>
        <h1>Database File Manager (BD2) 🗄️</h1>
        <p>Sistema indexado de Memoria Secundaria</p>
      </header>

      <main>
        <section className="input-section">
          <label>Query SQL:</label>
          <textarea 
            value={query} 
            onChange={(e) => setQuery(e.target.value)} 
            rows={5}
            placeholder="Escribe tu consulta CREATE, INSERT, SELECT..."
          />
          <button onClick={executeQuery} disabled={loading}>
            {loading ? 'Ejecutando...' : 'Ejecutar Query'}
          </button>
        </section>

        {error && <div className="error-box">Obtuvimos un error: {error}</div>}

        {result && (
          <section className="results-section">
            <div className="metrics">
              <div className="metric-box">⏱️ Tiempo:<br/><b>{result.time_ms} ms</b></div>
              <div className="metric-box">🔄 Accesos Disco (Reads):<br/><b>{result.disk_reads}</b></div>
              <div className="metric-box">💾 Accesos Disco (Writes):<br/><b>{result.disk_writes}</b></div>
            </div>

            {result.image_url && (
              <div className="image-result">
                <h3>Plot Geoespacial (R-Tree)</h3>
                {/* Aqui cargaremos el plot cuando busquemos por KNN o RADIO */}
                <img src={`http://localhost:8000${result.image_url}`} alt="Spatial Plot" />
              </div>
            )}

            {result.data && result.data.length > 0 ? (
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      {Object.keys(result.data[0]).map((key) => (
                        <th key={key}>{key}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.data.map((row, idx) => (
                      <tr key={idx}>
                        {Object.values(row).map((val, i) => (
                          <td key={i}>{val !== null ? val.toString() : 'NULL'}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p>No se encontraron registros o era una query de CREATE/INSERT.</p>
            )}
          </section>
        )}
      </main>
    </div>
  )
}

export default App