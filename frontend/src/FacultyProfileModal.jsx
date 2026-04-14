import { useState, useEffect, useCallback, useMemo } from 'react'
import './PaperDetailModal.css'  // reuse the same modal styles

/**
 * Faculty profile modal — shows merged DSpace + OpenAlex publication list
 * for a single faculty member. Clicking a publication opens the
 * PaperDetailModal via the onOpenPaper callback.
 *
 * Props:
 *  - facultyId: string  (id from FACULTY_DATA, e.g. "adisak-sukul")
 *  - onClose: () => void
 *  - apiUrl: string
 *  - currentUser: object | null
 *  - showToast: (msg, type) => void
 *  - onOpenPaper: (canonicalId) => void
 */
const SOURCE_LABELS = {
  dspace:   { label: 'DSpace',   color: '#C8102E' },
  openalex: { label: 'OpenAlex', color: '#1f6feb' },
  both:     { label: 'Both',     color: '#5b8a72' },
}

function authHeaders() {
  const token = localStorage.getItem('isu_rag_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// Some scraped profiles have their entire bio paragraph stored as a single
// research_interests entry. Strip anything that reads like prose before
// rendering as pill tags.
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

export default function FacultyProfileModal({
  facultyId, onClose, apiUrl, onOpenPaper,
}) {
  const [profile,      setProfile]      = useState(null)
  const [publications, setPublications] = useState(null)
  const [counts,       setCounts]       = useState(null)
  const [openalexId,   setOpenalexId]   = useState(null)
  const [loading,      setLoading]      = useState(true)
  const [error,        setError]        = useState(null)

  // UI state
  const [sourceFilter, setSourceFilter] = useState('all')   // 'all'|'dspace'|'openalex'|'both'
  const [yearFilter,   setYearFilter]   = useState('')      // string year
  const [titleFilter,  setTitleFilter]  = useState('')

  const fetchAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [pf, pubs] = await Promise.all([
        fetch(`${apiUrl}/api/faculty/${encodeURIComponent(facultyId)}`, {
          headers: { ...authHeaders() },
        }),
        fetch(`${apiUrl}/api/faculty/${encodeURIComponent(facultyId)}/publications?limit=500`, {
          headers: { ...authHeaders() },
        }),
      ])
      if (!pf.ok) {
        setError(pf.status === 404 ? 'Faculty not found' : `Profile error ${pf.status}`)
      } else {
        setProfile(await pf.json())
      }
      if (pubs.ok) {
        const data = await pubs.json()
        setPublications(data.publications || [])
        setCounts(data.counts || null)
        setOpenalexId(data.openalex_id || null)
      } else {
        setPublications([])
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [apiUrl, facultyId])

  useEffect(() => { fetchAll() }, [fetchAll])

  // ESC closes
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const overlayClick = (e) => { if (e.target === e.currentTarget) onClose() }

  // Build year list for filter dropdown
  const availableYears = useMemo(() => {
    if (!publications) return []
    const ys = new Set()
    publications.forEach(p => { if (p.year) ys.add(String(p.year).slice(0, 4)) })
    return Array.from(ys).filter(Boolean).sort((a, b) => b.localeCompare(a))
  }, [publications])

  const filtered = useMemo(() => {
    if (!publications) return []
    return publications.filter(p => {
      if (sourceFilter !== 'all' && p.source !== sourceFilter) return false
      if (yearFilter && String(p.year || '').slice(0, 4) !== yearFilter) return false
      if (titleFilter && !(p.title || '').toLowerCase().includes(titleFilter.toLowerCase())) return false
      return true
    })
  }, [publications, sourceFilter, yearFilter, titleFilter])

  // Group by year for display
  const byYear = useMemo(() => {
    const groups = new Map()
    filtered.forEach(p => {
      const y = String(p.year || '').slice(0, 4) || 'Unknown'
      if (!groups.has(y)) groups.set(y, [])
      groups.get(y).push(p)
    })
    // Sort years desc
    return Array.from(groups.entries()).sort((a, b) => {
      if (a[0] === 'Unknown') return 1
      if (b[0] === 'Unknown') return -1
      return b[0].localeCompare(a[0])
    })
  }, [filtered])

  return (
    <div className="paper-modal-overlay" onClick={overlayClick}>
      <div className="paper-modal-content" style={{ maxWidth: '1100px' }}>
        <div className="paper-modal-header">
          <h2 className="paper-modal-title">
            {loading ? 'Loading…' : (profile?.name || 'Faculty')}
          </h2>
          <button className="paper-modal-close" onClick={onClose} title="Close (Esc)">×</button>
        </div>

        {loading && <div className="paper-modal-body"><p>Loading faculty profile and publications…</p></div>}

        {error && (
          <div className="paper-modal-body">
            <p className="paper-modal-error">⚠ {error}</p>
          </div>
        )}

        {profile && !loading && (
          <div className="paper-modal-body">

            {/* Profile fact strip */}
            <div className="paper-fact-strip">
              {profile.rank && <span className="paper-fact"><strong>Rank:</strong> {profile.rank}</span>}
              {profile.department && <span className="paper-fact"><strong>Dept:</strong> {profile.department}</span>}
              {profile.college && <span className="paper-fact"><strong>College:</strong> {profile.college}</span>}
              {Array.isArray(profile.affiliations) && profile.affiliations.length > 0 && (
                <span className="paper-fact"><strong>Centers:</strong> {profile.affiliations.join(', ')}</span>
              )}
              {profile.email && (
                <span className="paper-fact">
                  <strong>Email:</strong>{' '}
                  <a href={`mailto:${profile.email}`}>{profile.email}</a>
                </span>
              )}
              {profile.profile_url && (
                <span className="paper-fact">
                  <a href={profile.profile_url} target="_blank" rel="noopener noreferrer">
                    Open ISU profile →
                  </a>
                </span>
              )}
              {openalexId && (
                <span className="paper-fact">
                  <a href={`https://openalex.org/${openalexId}`} target="_blank" rel="noopener noreferrer">
                    OpenAlex {openalexId} →
                  </a>
                </span>
              )}
            </div>

            {/* Two-column layout: photo + interests on left, pub list on right */}
            <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'flex-start' }}>

              {/* Left column: photo, interests */}
              <div style={{ flex: '0 0 260px' }}>
                {profile.photo_url && (
                  <img
                    src={profile.photo_url}
                    alt={profile.name}
                    style={{ width: '100%', borderRadius: '8px', marginBottom: '1rem' }}
                    onError={(e) => { e.target.style.display = 'none' }}
                  />
                )}

                {cleanDisplayInterests(profile.research_interests).length > 0 && (
                  <section className="paper-section">
                    <h3>Research interests</h3>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem' }}>
                      {cleanDisplayInterests(profile.research_interests).map((it, i) => (
                        <span
                          key={i}
                          style={{
                            background: '#fef2f2',
                            color: '#c8102e',
                            padding: '0.25rem 0.6rem',
                            borderRadius: '12px',
                            fontSize: '0.8rem',
                            border: '1px solid #fecaca',
                          }}
                        >
                          {it}
                        </span>
                      ))}
                    </div>
                  </section>
                )}

                {Array.isArray(profile.courses_taught) && profile.courses_taught.length > 0 && (
                  <section className="paper-section">
                    <h3>Courses taught</h3>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem' }}>
                      {profile.courses_taught.map((c, i) => (
                        <span
                          key={i}
                          style={{
                            background: '#f1f5f9',
                            color: '#475569',
                            padding: '0.25rem 0.6rem',
                            borderRadius: '12px',
                            fontSize: '0.8rem',
                          }}
                        >
                          {c}
                        </span>
                      ))}
                    </div>
                  </section>
                )}

                {Array.isArray(profile.affiliations) && profile.affiliations.length > 0 && (
                  <section className="paper-section">
                    <h3>Center affiliations</h3>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem' }}>
                      {profile.affiliations.map((aff, i) => (
                        <span
                          key={i}
                          style={{
                            background: '#fffbeb',
                            color: '#92400e',
                            padding: '0.25rem 0.6rem',
                            borderRadius: '12px',
                            fontSize: '0.8rem',
                            border: '1px solid #fde68a',
                          }}
                        >
                          {aff}
                        </span>
                      ))}
                    </div>
                  </section>
                )}
              </div>

              {/* Right column: publications */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <section className="paper-section">
                  <h3>
                    Publications
                    <span className="paper-section-count">
                      {' '}({filtered.length} of {publications?.length || 0})
                    </span>
                  </h3>

                  {counts && (
                    <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '0.78rem', color: '#64748b' }}>
                        DSpace: <strong>{counts.dspace}</strong> ·
                        OpenAlex: <strong>{counts.openalex}</strong> ·
                        Both: <strong>{counts.merged}</strong> ·
                        Total unique: <strong>{counts.total}</strong>
                      </span>
                    </div>
                  )}

                  {/* Filter row */}
                  <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
                    <select
                      value={sourceFilter}
                      onChange={(e) => setSourceFilter(e.target.value)}
                      style={{ padding: '0.4rem 0.6rem', border: '1px solid #e2e8f0', borderRadius: '6px' }}
                    >
                      <option value="all">All sources</option>
                      <option value="dspace">DSpace only</option>
                      <option value="openalex">OpenAlex only</option>
                      <option value="both">In both</option>
                    </select>
                    <select
                      value={yearFilter}
                      onChange={(e) => setYearFilter(e.target.value)}
                      style={{ padding: '0.4rem 0.6rem', border: '1px solid #e2e8f0', borderRadius: '6px' }}
                    >
                      <option value="">All years</option>
                      {availableYears.map(y => <option key={y} value={y}>{y}</option>)}
                    </select>
                    <input
                      type="text"
                      placeholder="Filter titles…"
                      value={titleFilter}
                      onChange={(e) => setTitleFilter(e.target.value)}
                      style={{
                        flex: 1,
                        minWidth: '160px',
                        padding: '0.4rem 0.6rem',
                        border: '1px solid #e2e8f0',
                        borderRadius: '6px',
                      }}
                    />
                  </div>

                  {filtered.length === 0 && (
                    <p className="paper-empty">No publications match the current filters.</p>
                  )}

                  {byYear.map(([year, pubs]) => (
                    <div key={year} style={{ marginBottom: '1rem' }}>
                      <h4 style={{
                        fontSize: '0.85rem',
                        color: '#64748b',
                        margin: '0.5rem 0 0.4rem',
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                        borderBottom: '1px solid #e2e8f0',
                        paddingBottom: '0.2rem',
                      }}>
                        {year} <span style={{ fontWeight: 400 }}>({pubs.length})</span>
                      </h4>
                      <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                        {pubs.map((p, i) => {
                          const meta = SOURCE_LABELS[p.source] || { label: p.source, color: '#888' }
                          const clickable = !!p.canonical_id && !!onOpenPaper
                          return (
                            <li key={`${p.canonical_id || p.title}-${i}`} style={{
                              padding: '0.6rem 0',
                              borderBottom: '1px solid #f1f5f9',
                              fontSize: '0.88rem',
                            }}>
                              <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                                <span style={{
                                  background: meta.color,
                                  color: 'white',
                                  fontSize: '0.65rem',
                                  padding: '0.15rem 0.4rem',
                                  borderRadius: '4px',
                                  flexShrink: 0,
                                  marginTop: '0.15rem',
                                }}>
                                  {meta.label}
                                </span>
                                {clickable ? (
                                  <button
                                    type="button"
                                    onClick={() => onOpenPaper(p.canonical_id)}
                                    style={{
                                      background: 'none',
                                      border: 'none',
                                      padding: 0,
                                      color: '#1f6feb',
                                      cursor: 'pointer',
                                      textAlign: 'left',
                                      fontWeight: 500,
                                      flex: 1,
                                      minWidth: 0,
                                    }}
                                  >
                                    {p.title}
                                  </button>
                                ) : (
                                  <span style={{ flex: 1, minWidth: 0, fontWeight: 500 }}>{p.title}</span>
                                )}
                                {p.cited_by_count != null && p.cited_by_count > 0 && (
                                  <span style={{
                                    color: '#c8102e',
                                    fontSize: '0.75rem',
                                    flexShrink: 0,
                                    marginTop: '0.15rem',
                                  }}>
                                    {p.cited_by_count} cited
                                  </span>
                                )}
                              </div>
                              {(p.authors?.length > 0 || p.type || p.doi) && (
                                <div style={{ marginLeft: '2.6rem', marginTop: '0.2rem', fontSize: '0.78rem', color: '#64748b' }}>
                                  {p.authors?.length > 0 && (
                                    <span>{p.authors.slice(0, 6).join(', ')}{p.authors.length > 6 ? ` +${p.authors.length - 6}` : ''}</span>
                                  )}
                                  {p.type && <span> · {p.type}</span>}
                                  {p.doi && (
                                    <> · <a href={`https://doi.org/${p.doi}`} target="_blank" rel="noopener noreferrer">DOI</a></>
                                  )}
                                  {p.url && (
                                    <> · <a href={p.url} target="_blank" rel="noopener noreferrer">DSpace</a></>
                                  )}
                                </div>
                              )}
                            </li>
                          )
                        })}
                      </ul>
                    </div>
                  ))}
                </section>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
