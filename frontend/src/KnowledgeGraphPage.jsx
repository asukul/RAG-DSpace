import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import CytoscapeComponent from 'react-cytoscapejs'
import './KnowledgeGraphPage.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8005'
const LS_TOKEN = 'isu_rag_token'

// Local apiFetch helper (App.jsx defines one but doesn't export it).
async function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  const token = localStorage.getItem(LS_TOKEN)
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (options.body) headers['Content-Type'] = 'application/json'
  const res = await fetch(`${API_URL}${path}`, { ...options, headers })
  return res
}

// Strip bio-prose entries that scrapers dumped into research_interests.
function cleanDisplayInterests(interests) {
  return (interests || []).filter(i => {
    if (!i || typeof i !== 'string') return false
    const s = i.trim()
    if (!s) return false
    if (s.length > 80) return false
    if (/^I /.test(s)) return false
    if (s.includes('. ')) return false
    return true
  })
}

// ISU palette by entity type
const TYPE_STYLE = {
  paper:      { color: '#C8102E', shape: 'round-rectangle', size: 20 },
  author:     { color: '#555555', shape: 'ellipse',         size: 16 },
  faculty:    { color: '#F1BE48', shape: 'ellipse',         size: 26 },
  department: { color: '#003D7A', shape: 'round-rectangle', size: 22 },
  college:    { color: '#4B0082', shape: 'round-rectangle', size: 26 },
  topic:      { color: '#2F855A', shape: 'hexagon',         size: 20 },
}

function buildElements(graph, rootId) {
  if (!graph) return []
  const nodes = (graph.nodes || []).map(n => ({
    data: {
      id: n.id,
      label: (n.name || n.id).slice(0, 28),
      type: n.type,
      payload: n.payload || {},
      color: (TYPE_STYLE[n.type] || {}).color || '#777',
      shape: (TYPE_STYLE[n.type] || {}).shape || 'ellipse',
      size:  (TYPE_STYLE[n.type] || {}).size || 14,
    },
    classes: n.id === rootId ? 'root' : '',
  }))
  const edges = (graph.edges || []).map((e, i) => ({
    data: {
      id: `e${i}-${e.subject}-${e.predicate}-${e.object}`,
      source: e.subject,
      target: e.object,
      label: e.predicate,
    },
  }))
  return [...nodes, ...edges]
}

const STYLESHEET = [
  // ── Nodes: labels hidden by default, shown on hover & root ──
  {
    selector: 'node',
    style: {
      'background-color': 'data(color)',
      'label': '',
      'shape': 'data(shape)',
      'width': 'data(size)',
      'height': 'data(size)',
      'border-width': 1,
      'border-color': '#ffffff',
      'border-opacity': 0.85,
      'transition-property': 'background-color, border-color, border-width, width, height, opacity',
      'transition-duration': '150ms',
    },
  },
  // Root node — always show label, slightly larger
  {
    selector: 'node.root',
    style: {
      'label': 'data(label)',
      'font-size': 8,
      'font-weight': 700,
      'color': '#222',
      'text-valign': 'bottom',
      'text-halign': 'center',
      'text-margin-y': 3,
      'text-wrap': 'ellipsis',
      'text-max-width': 80,
      'text-outline-width': 2,
      'text-outline-color': '#ffffff',
      'text-outline-opacity': 0.9,
      'border-color': '#9B0C23',
      'border-width': 3,
      'width': 34,
      'height': 34,
    },
  },
  // Hovered node — reveal label, enlarge slightly
  {
    selector: 'node.hover',
    style: {
      'label': 'data(label)',
      'font-size': 8,
      'color': '#222',
      'text-valign': 'bottom',
      'text-halign': 'center',
      'text-margin-y': 3,
      'text-wrap': 'ellipsis',
      'text-max-width': 90,
      'text-outline-width': 2,
      'text-outline-color': '#ffffff',
      'text-outline-opacity': 0.9,
      'border-color': '#F1BE48',
      'border-width': 2,
      'z-index': 999,
    },
  },
  {
    selector: 'node[type = "faculty"]',
    style: {
      'border-color': '#9B0C23',
      'border-width': 1.5,
    },
  },
  {
    selector: 'node:selected',
    style: {
      'label': 'data(label)',
      'font-size': 9,
      'color': '#222',
      'text-valign': 'bottom',
      'text-halign': 'center',
      'text-margin-y': 4,
      'text-outline-width': 2,
      'text-outline-color': '#ffffff',
      'border-color': '#F1BE48',
      'border-width': 4,
      'border-opacity': 1,
    },
  },
  // ── Edges: no labels, thin, semi-transparent ──
  {
    selector: 'edge',
    style: {
      'curve-style': 'bezier',
      'width': 0.8,
      'line-color': '#cccccc',
      'target-arrow-color': '#cccccc',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 0.5,
      'opacity': 0.4,
    },
  },
  // Highlight edges connected to hovered node
  {
    selector: 'edge.hover-connected',
    style: {
      'width': 1.5,
      'opacity': 0.85,
      'label': 'data(label)',
      'font-size': 7,
      'color': '#666',
      'text-background-color': '#ffffff',
      'text-background-opacity': 0.9,
      'text-background-padding': 1,
    },
  },
  {
    selector: 'edge[label = "authored"]',
    style: { 'line-color': '#9B0C23', 'target-arrow-color': '#9B0C23', 'opacity': 0.5 },
  },
  {
    selector: 'edge[label = "coauthored"]',
    style: { 'line-color': '#aaaaaa', 'target-arrow-shape': 'none', 'opacity': 0.25 },
  },
  {
    selector: 'edge[label = "same_as"]',
    style: { 'line-color': '#F1BE48', 'line-style': 'dashed', 'opacity': 0.6 },
  },
  {
    selector: 'edge[label = "interested_in"]',
    style: { 'line-color': '#2F855A', 'opacity': 0.45 },
  },
  {
    selector: 'edge[label = "affiliated_with"]',
    style: { 'line-color': '#003D7A', 'opacity': 0.45 },
  },
  // Dim non-connected nodes when hovering
  {
    selector: 'node.dimmed',
    style: { 'opacity': 0.2 },
  },
]


export default function KnowledgeGraphPage({ onOpenPaper } = {}) {
  const [stats, setStats] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searchOpen, setSearchOpen] = useState(false)
  const [selectedEntity, setSelectedEntity] = useState(null)
  const [graph, setGraph] = useState(null)
  const [depth, setDepth] = useState(1)
  const [maxNodes, setMaxNodes] = useState(40)
  const [layoutName, setLayoutName] = useState('cose')
  const [loadingGraph, setLoadingGraph] = useState(false)
  const [randomFaculty, setRandomFaculty] = useState([])
  const [openalexCitedBy, setOpenalexCitedBy] = useState(null)
  const [openalexAuthorWorks, setOpenalexAuthorWorks] = useState(null)
  const [loadingOpenalex, setLoadingOpenalex] = useState(false)

  const cyRef = useRef(null)

  // Fetch stats once
  useEffect(() => {
    apiFetch('/api/kg/stats')
      .then(r => r.ok ? r.json() : null)
      .then(setStats)
      .catch(() => {})
    apiFetch('/api/faculty')
      .then(r => r.ok ? r.json() : [])
      .then(all => {
        // Pick 12 with photos
        const withPhotos = all.filter(f => f.photo_url && f.id)
        const shuffled = withPhotos.sort(() => Math.random() - 0.5).slice(0, 12)
        setRandomFaculty(shuffled)
      })
      .catch(() => {})
  }, [])

  // Debounced search
  useEffect(() => {
    const q = searchQuery.trim()
    if (q.length < 2) {
      setSearchResults([])
      setSearchOpen(false)
      return
    }
    const handle = setTimeout(async () => {
      try {
        const res = await apiFetch(
          `/api/kg/search?q=${encodeURIComponent(q)}&types=faculty,paper,author,department,topic&limit=15`
        )
        if (res.ok) {
          const data = await res.json()
          setSearchResults(data.results || [])
          setSearchOpen((data.results || []).length > 0)
        }
      } catch {}
    }, 200)
    return () => clearTimeout(handle)
  }, [searchQuery])

  // Fetch graph when selectedEntity changes
  useEffect(() => {
    if (!selectedEntity) {
      setGraph(null)
      return
    }
    let cancelled = false
    setLoadingGraph(true)
    apiFetch(
      `/api/kg/graph?root_id=${encodeURIComponent(selectedEntity.id)}&depth=${depth}&max_nodes=${maxNodes}`
    )
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (cancelled) return
        setGraph(data)
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoadingGraph(false)
      })
    return () => { cancelled = true }
  }, [selectedEntity, depth, maxNodes])

  const elements = useMemo(() => buildElements(graph, selectedEntity?.id), [graph, selectedEntity])

  const rootId = selectedEntity?.id
  const layout = useMemo(() => {
    const base = {
      animate: true,
      animationDuration: 500,
      padding: 50,
      fit: true,
      avoidOverlap: true,
      nodeDimensionsIncludeLabels: true,
    }
    if (layoutName === 'concentric') return {
      ...base, name: 'concentric',
      concentric: n => n.data('id') === rootId ? 1000 : n.degree(),
      levelWidth: () => 1,
      minNodeSpacing: 30,
      equidistant: true,
      spacingFactor: 1.0,
    }
    if (layoutName === 'cose') return {
      ...base, name: 'cose',
      randomize: true,
      idealEdgeLength: 80,
      nodeRepulsion: 30000,
      gravity: 0.25,
      numIter: 1500,
      nodeOverlap: 20,
      nestingFactor: 1.2,
      edgeElasticity: 80,
      initialTemp: 200,
    }
    if (layoutName === 'breadthfirst') return {
      ...base, name: 'breadthfirst',
      directed: true,
      spacingFactor: 1.4,
      roots: rootId ? `[id = "${rootId}"]` : undefined,
    }
    if (layoutName === 'circle') return { ...base, name: 'circle', spacingFactor: 1.8 }
    if (layoutName === 'grid') return { ...base, name: 'grid', spacingFactor: 1.5 }
    return { ...base, name: layoutName }
  }, [layoutName, rootId])

  const handleSelectSuggestion = (entity) => {
    setSelectedEntity(entity)
    setSearchQuery('')
    setSearchResults([])
    setSearchOpen(false)
    setOpenalexCitedBy(null)
    setOpenalexAuthorWorks(null)
  }

  const fetchOpenAlexCitedBy = async (workId) => {
    setLoadingOpenalex(true)
    try {
      const res = await apiFetch(`/api/kg/openalex/work/${workId}/cited_by?limit=10`)
      if (res.ok) {
        const data = await res.json()
        setOpenalexCitedBy(data.works || [])
      }
    } catch {} finally { setLoadingOpenalex(false) }
  }

  const fetchOpenAlexAuthorWorks = async (authorId) => {
    setLoadingOpenalex(true)
    try {
      const res = await apiFetch(`/api/kg/openalex/author/${authorId}/works?limit=15`)
      if (res.ok) {
        const data = await res.json()
        setOpenalexAuthorWorks(data.works || [])
      }
    } catch {} finally { setLoadingOpenalex(false) }
  }

  // Cytoscape click → re-root, hover → reveal labels
  const onCyInit = useCallback((cy) => {
    cyRef.current = cy
    cy.on('tap', 'node', (evt) => {
      const node = evt.target.data()
      const newEntity = {
        id: node.id,
        type: node.type,
        name: node.label,
        payload: node.payload,
      }
      setSelectedEntity(newEntity)
    })
    // Hover: show label on hovered node + connected neighbors, dim the rest
    cy.on('mouseover', 'node', (evt) => {
      const node = evt.target
      node.addClass('hover')
      const neighborhood = node.neighborhood()
      neighborhood.nodes().addClass('hover')
      neighborhood.edges().addClass('hover-connected')
      cy.nodes().not(node).not(neighborhood.nodes()).addClass('dimmed')
    })
    cy.on('mouseout', 'node', () => {
      cy.nodes().removeClass('hover dimmed')
      cy.edges().removeClass('hover-connected')
    })
  }, [])

  // Re-run layout every time graph data or layout choice changes
  useEffect(() => {
    const cy = cyRef.current
    if (!cy || !graph) return
    cy.resize()
    // Manually run layout — react-cytoscapejs only applies it on mount
    try {
      const run = cy.layout(layout)
      run.run()
      run.one('layoutstop', () => {
        try { cy.fit(undefined, 50) } catch {}
      })
    } catch {
      try { cy.fit(undefined, 50) } catch {}
    }
  }, [graph, layout])

  return (
    <div className="kg-page">
      <div className="kg-header">
        <h2>Knowledge Graph</h2>
        <p className="kg-tag">
          Browse the ISU research corpus as a graph of papers, authors, faculty,
          departments, colleges and topics. Click any node to re-center the view.
        </p>
      </div>

      <div className="kg-search-shell">
        <input
          type="text"
          className="kg-search-input"
          placeholder="Search for a faculty member, paper, topic, department..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onFocus={() => searchResults.length > 0 && setSearchOpen(true)}
          onBlur={() => setTimeout(() => setSearchOpen(false), 150)}
        />
        {searchOpen && searchResults.length > 0 && (
          <div className="kg-suggest-dropdown">
            {searchResults.map(r => (
              <div
                key={r.id}
                className="kg-suggest-item"
                onMouseDown={(e) => { e.preventDefault(); handleSelectSuggestion(r) }}
              >
                <span className={`kg-type-badge type-${r.type}`}>{r.type.slice(0, 3).toUpperCase()}</span>
                <span className="kg-suggest-name">{r.name}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="kg-controls">
        <label>Depth
          <select value={depth} onChange={e => setDepth(parseInt(e.target.value, 10))}>
            <option value={1}>1</option>
            <option value={2}>2</option>
            <option value={3}>3</option>
          </select>
        </label>
        <label>Max nodes
          <select value={maxNodes} onChange={e => setMaxNodes(parseInt(e.target.value, 10))}>
            <option value={20}>20</option>
            <option value={40}>40</option>
            <option value={60}>60</option>
            <option value={120}>120</option>
            <option value={200}>200</option>
          </select>
        </label>
        <label>Layout
          <select value={layoutName} onChange={e => setLayoutName(e.target.value)}>
            <option value="cose">cose (force-directed)</option>
            <option value="concentric">concentric (radial)</option>
            <option value="breadthfirst">breadthfirst (tree)</option>
            <option value="circle">circle</option>
            <option value="grid">grid</option>
          </select>
        </label>
        <div className="kg-legend">
          {Object.entries(TYPE_STYLE).map(([k, v]) => (
            <span key={k} className="kg-legend-item">
              <span className="kg-legend-dot" style={{ background: v.color }} />
              {k}
            </span>
          ))}
        </div>
      </div>

      <div className="kg-main">
        <div className="kg-canvas-wrap">
          {!selectedEntity && (
            <div className="kg-empty">
              <h3>Pick a starting point</h3>
              <p>Search above, or click one of these faculty members to drop into the graph.</p>
              <div className="kg-empty-faculty-grid">
                {randomFaculty.map(f => (
                  <button
                    key={f.id}
                    className="kg-faculty-tile"
                    onClick={() => handleSelectSuggestion({
                      id: `faculty:isu:${f.id}`,
                      type: 'faculty',
                      name: f.name,
                      payload: f,
                    })}
                  >
                    {f.photo_url && (
                      <img src={f.photo_url} alt="" onError={(e) => { e.target.style.display = 'none' }} />
                    )}
                    <div className="kg-faculty-name">{f.name}</div>
                    {f.department && <div className="kg-faculty-dept">{f.department}</div>}
                  </button>
                ))}
              </div>
              {stats && (
                <div className="kg-stats-strip">
                  <strong>{(stats.entities?.paper || 0).toLocaleString()}</strong> papers ·{' '}
                  <strong>{(stats.entities?.author || 0).toLocaleString()}</strong> authors ·{' '}
                  <strong>{(stats.entities?.faculty || 0).toLocaleString()}</strong> faculty ·{' '}
                  <strong>{(stats.entities?.department || 0).toLocaleString()}</strong> departments ·{' '}
                  <strong>{(stats.entities?.topic || 0).toLocaleString()}</strong> topics ·{' '}
                  <strong>{(stats.total_edges || 0).toLocaleString()}</strong> edges
                </div>
              )}
            </div>
          )}

          {selectedEntity && (
            <>
              {loadingGraph && <div className="kg-loading">Loading neighborhood…</div>}
              <CytoscapeComponent
                key={selectedEntity?.id || 'kg'}
                elements={elements}
                layout={layout}
                stylesheet={STYLESHEET}
                style={{ width: '100%', height: '100%' }}
                minZoom={0.3}
                maxZoom={3}
                cy={onCyInit}
              />
            </>
          )}
        </div>

        <aside className="kg-sidebar">
          {!selectedEntity && (
            <div className="kg-sidebar-empty">
              <p>Select an entity to see its details.</p>
            </div>
          )}
          {selectedEntity && (
            <>
              <div className="kg-detail-header">
                <span className={`kg-type-badge type-${selectedEntity.type}`}>
                  {selectedEntity.type.toUpperCase()}
                </span>
                <h3>{selectedEntity.name}</h3>
              </div>

              {selectedEntity.payload?.photo_url && (
                <img
                  src={selectedEntity.payload.photo_url}
                  alt=""
                  className="kg-detail-photo"
                  onError={(e) => { e.target.style.display = 'none' }}
                />
              )}

              {selectedEntity.payload?.rank && (
                <div className="kg-detail-row"><strong>Rank</strong> {selectedEntity.payload.rank}</div>
              )}
              {selectedEntity.payload?.title && selectedEntity.payload.title !== selectedEntity.payload.rank && (
                <div className="kg-detail-row"><strong>Title</strong> {selectedEntity.payload.title}</div>
              )}
              {selectedEntity.payload?.email && (
                <div className="kg-detail-row"><strong>Email</strong> {selectedEntity.payload.email}</div>
              )}
              {selectedEntity.payload?.department && (
                <div className="kg-detail-row"><strong>Department</strong> {selectedEntity.payload.department}</div>
              )}
              {selectedEntity.payload?.college && (
                <div className="kg-detail-row"><strong>College</strong> {selectedEntity.payload.college}</div>
              )}
              {selectedEntity.payload?.year && (
                <div className="kg-detail-row"><strong>Year</strong> {selectedEntity.payload.year}</div>
              )}
              {selectedEntity.payload?.type && selectedEntity.type === 'paper' && (
                <div className="kg-detail-row"><strong>Type</strong> {selectedEntity.payload.type}</div>
              )}
              {selectedEntity.type === 'paper' && onOpenPaper && (
                <div className="kg-detail-row" style={{ marginTop: '0.4rem' }}>
                  <button
                    type="button"
                    className="kg-link-btn"
                    onClick={() => onOpenPaper(selectedEntity.id)}
                    style={{ background: 'var(--isu-red)' }}
                    title="Open merged sources view (DSpace + OpenAlex) and edit"
                  >
                    🔗 Details & sources
                  </button>
                </div>
              )}
              {selectedEntity.payload?.collection && (
                <div className="kg-detail-row"><strong>Collection</strong> {selectedEntity.payload.collection}</div>
              )}

              {selectedEntity.payload?.openalex && (
                <div className="kg-detail-section">
                  <strong>OpenAlex</strong>
                  <div className="kg-openalex-stats">
                    <div className="kg-stat">
                      <div className="kg-stat-num">{(selectedEntity.payload.openalex.works_count || 0).toLocaleString()}</div>
                      <div className="kg-stat-label">works</div>
                    </div>
                    <div className="kg-stat">
                      <div className="kg-stat-num">{(selectedEntity.payload.openalex.cited_by_count || 0).toLocaleString()}</div>
                      <div className="kg-stat-label">citations</div>
                    </div>
                    <div className="kg-stat">
                      <div className="kg-stat-num">{selectedEntity.payload.openalex.h_index ?? '–'}</div>
                      <div className="kg-stat-label">h-index</div>
                    </div>
                    <div className="kg-stat">
                      <div className="kg-stat-num">{selectedEntity.payload.openalex.i10_index ?? '–'}</div>
                      <div className="kg-stat-label">i10</div>
                    </div>
                  </div>
                  {selectedEntity.payload.openalex.orcid && (
                    <div className="kg-detail-row" style={{ paddingLeft: 0, marginTop: '0.4rem' }}>
                      <strong>ORCID</strong>
                      <a href={selectedEntity.payload.openalex.orcid} target="_blank" rel="noopener noreferrer">
                        {selectedEntity.payload.openalex.orcid.replace('https://orcid.org/', '')}
                      </a>
                    </div>
                  )}
                  <a
                    href={`https://openalex.org/${selectedEntity.payload.openalex.id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="kg-link-btn"
                    style={{ marginTop: '0.4rem' }}
                  >
                    Open in OpenAlex →
                  </a>
                  {!openalexAuthorWorks && (
                    <button
                      type="button"
                      className="kg-link-btn"
                      onClick={() => fetchOpenAlexAuthorWorks(selectedEntity.payload.openalex.id)}
                      style={{ marginTop: '0.4rem', background: '#003D7A' }}
                    >
                      {loadingOpenalex ? 'Loading…' : 'Show OpenAlex publications'}
                    </button>
                  )}
                  {openalexAuthorWorks && openalexAuthorWorks.length > 0 && (
                    <div style={{ marginTop: '0.6rem' }}>
                      <strong style={{ display: 'block', fontSize: '0.7rem', textTransform: 'uppercase', color: 'var(--text-muted)', letterSpacing: '0.04em', marginBottom: '0.4rem' }}>
                        Top publications from OpenAlex
                      </strong>
                      {openalexAuthorWorks.map((w, i) => (
                        <div key={w.id || i} className="kg-detail-row" style={{ paddingLeft: 0, fontSize: '0.78rem' }}>
                          <span style={{ color: 'var(--text-muted)' }}>{w.publication_year}</span>
                          {' · '}
                          <a href={`https://openalex.org/${w.id}`} target="_blank" rel="noopener noreferrer">
                            {w.title?.slice(0, 70)}
                          </a>
                          {w.cited_by_count > 0 && (
                            <span style={{ color: 'var(--isu-red)', marginLeft: 4 }}>({w.cited_by_count} cited)</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {selectedEntity.type === 'paper' && (
                <div className="kg-detail-section">
                  <strong>Citation network</strong>
                  {!openalexCitedBy && (
                    <div>
                      <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', margin: '0.3rem 0' }}>
                        Lazy-fetched from OpenAlex on demand. Requires the paper to have a DOI in the OpenAlex index.
                      </p>
                      <button
                        type="button"
                        className="kg-link-btn"
                        onClick={() => {
                          // For DSpace papers, we need to look up the OpenAlex ID by DOI.
                          // Until reconciliation lands, this falls back to a search.
                          const doi = selectedEntity.payload?.doi
                          if (doi) {
                            fetchOpenAlexCitedBy(doi)
                          } else {
                            setOpenalexCitedBy([])
                          }
                        }}
                        style={{ background: '#003D7A' }}
                      >
                        {loadingOpenalex ? 'Loading…' : 'Find papers that cite this'}
                      </button>
                    </div>
                  )}
                  {openalexCitedBy && openalexCitedBy.length > 0 && (
                    <div style={{ marginTop: '0.4rem' }}>
                      {openalexCitedBy.map((w, i) => (
                        <div key={w.id || i} className="kg-detail-row" style={{ paddingLeft: 0, fontSize: '0.78rem' }}>
                          <span style={{ color: 'var(--text-muted)' }}>{w.publication_year}</span>
                          {' · '}
                          <a href={`https://openalex.org/${w.id}`} target="_blank" rel="noopener noreferrer">
                            {w.title?.slice(0, 70)}
                          </a>
                        </div>
                      ))}
                    </div>
                  )}
                  {openalexCitedBy && openalexCitedBy.length === 0 && (
                    <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', margin: '0.3rem 0' }}>
                      No citations found in OpenAlex (requires DOI mapping).
                    </p>
                  )}
                </div>
              )}

              {cleanDisplayInterests(selectedEntity.payload?.research_interests).length > 0 && (
                <div className="kg-detail-section">
                  <strong>Research interests</strong>
                  <div className="kg-tags">
                    {cleanDisplayInterests(selectedEntity.payload?.research_interests).map(t => (
                      <span key={t} className="kg-tag-pill">{t}</span>
                    ))}
                  </div>
                </div>
              )}

              {selectedEntity.payload?.dspace_url && (
                <a
                  href={selectedEntity.payload.dspace_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="kg-link-btn"
                >
                  Open in DSpace →
                </a>
              )}
              {selectedEntity.payload?.profile_url && (
                <a
                  href={selectedEntity.payload.profile_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="kg-link-btn"
                >
                  Open profile →
                </a>
              )}

              {graph && (
                <div className="kg-detail-section">
                  <strong>Neighborhood</strong>
                  <div className="kg-detail-row" style={{ paddingLeft: 0 }}>
                    {graph.node_count} nodes · {graph.edge_count} edges
                    {graph.truncated && ' · truncated (raise max nodes)'}
                  </div>
                </div>
              )}
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
