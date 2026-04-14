import { useState, useEffect, useRef, useCallback } from 'react'

const WIDTH = 900
const HEIGHT = 620

// Pure-JS force-directed simulation. No external deps.
function useForceLayout(nodes, edges, centerKey) {
  const [positions, setPositions] = useState({})
  const rafRef = useRef(null)

  useEffect(() => {
    if (!nodes.length) {
      setPositions({})
      return
    }

    // Initialize positions: center the focal node, others on a ring then random
    const init = {}
    const cx = WIDTH / 2
    const cy = HEIGHT / 2
    nodes.forEach((n, i) => {
      if (n.key === centerKey) {
        init[n.key] = { x: cx, y: cy, vx: 0, vy: 0, fixed: true }
      } else {
        const angle = (i / nodes.length) * Math.PI * 2
        const r = 200 + Math.random() * 60
        init[n.key] = {
          x: cx + Math.cos(angle) * r,
          y: cy + Math.sin(angle) * r,
          vx: 0,
          vy: 0,
          fixed: false,
        }
      }
    })

    let pos = init
    let iter = 0
    const MAX_ITER = 240
    const REPULSION = 4500
    const SPRING_K = 0.018
    const SPRING_LEN = 95
    const CENTER_K = 0.012
    const DAMPING = 0.82

    const tick = () => {
      const forces = {}
      nodes.forEach(n => { forces[n.key] = { fx: 0, fy: 0 } })

      // Repulsion (O(n^2) — fine for ≤200 nodes)
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = pos[nodes[i].key]
          const b = pos[nodes[j].key]
          let dx = a.x - b.x
          let dy = a.y - b.y
          let d2 = dx * dx + dy * dy
          if (d2 < 1) { d2 = 1; dx = Math.random() - 0.5; dy = Math.random() - 0.5 }
          const f = REPULSION / d2
          const d = Math.sqrt(d2)
          const fx = (dx / d) * f
          const fy = (dy / d) * f
          forces[nodes[i].key].fx += fx
          forces[nodes[i].key].fy += fy
          forces[nodes[j].key].fx -= fx
          forces[nodes[j].key].fy -= fy
        }
      }

      // Spring attraction along edges
      edges.forEach(e => {
        const a = pos[e.source]
        const b = pos[e.target]
        if (!a || !b) return
        const dx = b.x - a.x
        const dy = b.y - a.y
        const d = Math.sqrt(dx * dx + dy * dy) || 1
        const stretch = d - SPRING_LEN
        const f = SPRING_K * stretch * (1 + Math.log(1 + (e.weight || 1)))
        const fx = (dx / d) * f
        const fy = (dy / d) * f
        forces[e.source].fx += fx
        forces[e.source].fy += fy
        forces[e.target].fx -= fx
        forces[e.target].fy -= fy
      })

      // Centering pull
      nodes.forEach(n => {
        const p = pos[n.key]
        forces[n.key].fx += (WIDTH / 2 - p.x) * CENTER_K
        forces[n.key].fy += (HEIGHT / 2 - p.y) * CENTER_K
      })

      // Integrate
      const next = {}
      nodes.forEach(n => {
        const p = pos[n.key]
        if (p.fixed) {
          next[n.key] = p
          return
        }
        const f = forces[n.key]
        const vx = (p.vx + f.fx * 0.05) * DAMPING
        const vy = (p.vy + f.fy * 0.05) * DAMPING
        let x = p.x + vx
        let y = p.y + vy
        // Soft clamp to viewport
        x = Math.max(30, Math.min(WIDTH - 30, x))
        y = Math.max(30, Math.min(HEIGHT - 30, y))
        next[n.key] = { x, y, vx, vy, fixed: false }
      })

      pos = next
      iter++
      if (iter % 4 === 0 || iter === MAX_ITER) {
        setPositions({ ...pos })
      }
      if (iter < MAX_ITER) {
        rafRef.current = requestAnimationFrame(tick)
      }
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [nodes, edges, centerKey])

  return positions
}


export default function NetworkPage({ apiUrl }) {
  const [stats, setStats] = useState(null)
  const [graph, setGraph] = useState({ nodes: [], edges: [], center: null })
  const [loading, setLoading] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [activeResearcher, setActiveResearcher] = useState('')
  const [hoverKey, setHoverKey] = useState(null)
  const [selected, setSelected] = useState(null)

  const loadGraph = useCallback(async (researcher) => {
    setLoading(true)
    try {
      const url = researcher
        ? `${apiUrl}/api/collaboration/graph?researcher=${encodeURIComponent(researcher)}&max_nodes=80`
        : `${apiUrl}/api/collaboration/graph?max_nodes=60`
      const res = await fetch(url)
      const data = await res.json()
      setGraph({
        nodes: data.nodes || [],
        edges: data.edges || [],
        center: data.center || null,
      })
      setSelected(data.center || null)
    } catch (e) {
      console.error('Graph load failed:', e)
    } finally {
      setLoading(false)
    }
  }, [apiUrl])

  useEffect(() => {
    fetch(`${apiUrl}/api/collaboration/stats`).then(r => r.json()).then(setStats).catch(() => {})
    loadGraph(null)
  }, [apiUrl, loadGraph])

  const handleSearch = (e) => {
    e.preventDefault()
    if (!searchInput.trim()) return
    setActiveResearcher(searchInput.trim())
    loadGraph(searchInput.trim())
  }

  const handleClear = () => {
    setActiveResearcher('')
    setSearchInput('')
    loadGraph(null)
  }

  const handleNodeClick = (node) => {
    setSelected(node)
    setActiveResearcher(node.name)
    setSearchInput(node.name)
    loadGraph(node.name)
  }

  const positions = useForceLayout(graph.nodes, graph.edges, graph.center?.key)

  // Build edge color/width
  const renderEdges = () => graph.edges.map((e, i) => {
    const a = positions[e.source]
    const b = positions[e.target]
    if (!a || !b) return null
    const isAdvisor = e.kind === 'advisor'
    const stroke = isAdvisor ? '#F1BE48' : '#9aa3b2'
    const width = Math.min(1 + (e.weight || 1) * 0.7, 4)
    const dim = hoverKey && hoverKey !== e.source && hoverKey !== e.target
    return (
      <line
        key={`e${i}`}
        x1={a.x} y1={a.y} x2={b.x} y2={b.y}
        stroke={stroke}
        strokeWidth={width}
        strokeOpacity={dim ? 0.15 : 0.55}
        strokeDasharray={isAdvisor ? '4 3' : null}
      />
    )
  })

  const renderNodes = () => graph.nodes.map((n) => {
    const p = positions[n.key]
    if (!p) return null
    const isCenter = graph.center && n.key === graph.center.key
    const isFaculty = !!n.faculty_id
    const isHover = hoverKey === n.key
    const isSelected = selected && selected.key === n.key
    const r = isCenter ? 14 : isFaculty ? 9 : 6
    const fill = isCenter
      ? '#C8102E'
      : isFaculty
        ? '#C8102E'
        : '#7d8594'
    const stroke = isSelected ? '#F1BE48' : isHover ? '#fff' : 'rgba(255,255,255,0.5)'
    return (
      <g
        key={n.key}
        transform={`translate(${p.x},${p.y})`}
        style={{ cursor: 'pointer' }}
        onMouseEnter={() => setHoverKey(n.key)}
        onMouseLeave={() => setHoverKey(null)}
        onClick={() => handleNodeClick(n)}
      >
        <circle
          r={r}
          fill={fill}
          stroke={stroke}
          strokeWidth={isSelected ? 3 : isHover ? 2 : 1}
          opacity={hoverKey && !isHover && !isCenter ? 0.45 : 1}
        />
        {(isCenter || isHover || isSelected || isFaculty) && (
          <text
            x={r + 4}
            y={4}
            fontSize={isCenter ? 13 : 11}
            fontWeight={isCenter ? 700 : 500}
            fill="#1a1a1a"
            stroke="#fff"
            strokeWidth={3}
            paintOrder="stroke"
          >
            {n.name}
          </text>
        )}
      </g>
    )
  })

  return (
    <div className="network-page">
      <div className="network-header">
        <h2>🕸️ Research Collaboration Network</h2>
        <p className="network-subtitle">
          Co-authorship and advisor-student relationships extracted from indexed documents.
        </p>
        {stats && (
          <div className="network-stats">
            <span>📄 {stats.documents} docs</span>
            <span>👤 {stats.people} people</span>
            <span>🔗 {stats.coauthor_edges} co-author edges</span>
            <span>🎓 {stats.advisor_edges} advisor edges</span>
            <span>🏷️ {stats.faculty_matched} matched to faculty</span>
          </div>
        )}
      </div>

      <form onSubmit={handleSearch} className="network-search">
        <input
          type="text"
          value={searchInput}
          onChange={e => setSearchInput(e.target.value)}
          placeholder="Center on a researcher (e.g. Tavanapong, Wallapak)"
          className="network-input"
        />
        <button type="submit" disabled={loading} className="network-btn">
          {loading ? '⏳' : '🎯'} Center
        </button>
        {activeResearcher && (
          <button type="button" onClick={handleClear} className="network-btn-secondary">
            ✕ Clear
          </button>
        )}
      </form>

      <div className="network-body">
        <div className="network-canvas">
          <svg width={WIDTH} height={HEIGHT} style={{ background: '#fafbfd', borderRadius: 8 }}>
            {renderEdges()}
            {renderNodes()}
          </svg>
          <div className="network-legend">
            <span><span className="dot dot-center"></span> Focal researcher</span>
            <span><span className="dot dot-faculty"></span> Faculty (matched)</span>
            <span><span className="dot dot-other"></span> Other author / student</span>
            <span><span className="line line-coauthor"></span> Co-author</span>
            <span><span className="line line-advisor"></span> Advisor</span>
          </div>
        </div>

        <aside className="network-side">
          {selected ? (
            <div className="network-detail">
              <h3>{selected.name}</h3>
              {selected.department && <p className="muted">{selected.department}</p>}
              <p>📄 {selected.paper_count || 0} indexed papers</p>
              {selected.faculty_id && (
                <p className="muted small">Faculty ID: {selected.faculty_id}</p>
              )}
              <NetworkDetailLists apiUrl={apiUrl} researcher={selected.name} />
            </div>
          ) : (
            <div className="network-detail">
              <p className="muted">Click a node or search for a researcher to see their network.</p>
              <p className="muted small">
                Showing the {graph.nodes.length} most-connected people in the corpus.
              </p>
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}


function NetworkDetailLists({ apiUrl, researcher }) {
  const [coauthors, setCoauthors] = useState([])
  const [students, setStudents] = useState([])
  const [advisors, setAdvisors] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!researcher) return
    let cancelled = false
    setLoading(true)
    Promise.all([
      fetch(`${apiUrl}/api/collaboration/coauthors?researcher=${encodeURIComponent(researcher)}&top_k=15`).then(r => r.json()),
      fetch(`${apiUrl}/api/collaboration/students?advisor=${encodeURIComponent(researcher)}`).then(r => r.json()),
      fetch(`${apiUrl}/api/collaboration/advisors?student=${encodeURIComponent(researcher)}`).then(r => r.json()),
    ]).then(([co, stu, adv]) => {
      if (cancelled) return
      setCoauthors(co.coauthors || [])
      setStudents(stu.students || [])
      setAdvisors(adv.advisors || [])
    }).catch(() => {}).finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [apiUrl, researcher])

  if (loading) return <p className="muted small">Loading…</p>

  const renderList = (label, items, key) => items.length > 0 && (
    <div className="network-detail-list">
      <h4>{label} ({items.length})</h4>
      <ul>
        {items.slice(0, 12).map((p, i) => (
          <li key={i}>
            <span>{p.name}</span>
            {p.department && <span className="muted small"> · {p.department.slice(0, 35)}</span>}
            <span className="badge">{p[key]}</span>
          </li>
        ))}
      </ul>
    </div>
  )

  return (
    <>
      {renderList('Co-authors', coauthors, 'shared_papers')}
      {renderList('Students supervised', students, 'shared_papers')}
      {renderList('Advisors', advisors, 'shared_papers')}
      {coauthors.length === 0 && students.length === 0 && advisors.length === 0 && (
        <p className="muted small">No relationships found in the indexed corpus.</p>
      )}
    </>
  )
}
