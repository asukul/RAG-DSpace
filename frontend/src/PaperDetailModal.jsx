import { useState, useEffect, useCallback } from 'react'
import './PaperDetailModal.css'

/**
 * Paper detail modal — fetches the merged view from /api/papers/{canonical_id}
 * and lets logged-in users propose field overrides.
 *
 * Props:
 *  - canonicalId: string  (e.g. "paper:dspace:00005f81-..." or "paper:openalex:W12345")
 *  - onClose: () => void
 *  - apiUrl: string
 *  - currentUser: { id, name, email, role } | null
 *  - showToast: (msg, type) => void
 */
const EDITABLE_FIELDS = [
  { key: 'title',        label: 'Title',        type: 'text' },
  { key: 'year',         label: 'Year',         type: 'number' },
  { key: 'doi',          label: 'DOI',          type: 'text' },
  { key: 'type',         label: 'Type',         type: 'text' },
  { key: 'first_author', label: 'First author', type: 'text' },
]

const SOURCE_LABELS = {
  dspace:   { label: 'DSpace',   color: '#C8102E' },
  openalex: { label: 'OpenAlex', color: '#1f6feb' },
  crossref: { label: 'Crossref', color: '#5b8a72' },
  scholar:  { label: 'Scholar',  color: '#5e35b1' },
  user:     { label: 'User edit',color: '#F1BE48' },
}

function authHeaders() {
  const token = localStorage.getItem('isu_rag_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export default function PaperDetailModal({
  canonicalId, onClose, apiUrl, currentUser, showToast,
}) {
  const [paper,   setPaper]   = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  // Edit form state — only one field at a time
  const [editingField, setEditingField] = useState(null)  // 'title', 'year', etc.
  const [editValue,    setEditValue]    = useState('')
  const [editRationale,setEditRationale]= useState('')
  const [submitting,   setSubmitting]   = useState(false)

  const fetchPaper = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(
        `${apiUrl}/api/papers/${encodeURIComponent(canonicalId)}`,
        { headers: { ...authHeaders() } },
      )
      if (!res.ok) {
        const msg = res.status === 404 ? 'Paper not found' : `Error ${res.status}`
        setError(msg)
        setPaper(null)
      } else {
        setPaper(await res.json())
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [apiUrl, canonicalId])

  useEffect(() => { fetchPaper() }, [fetchPaper])

  // ESC closes
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const startEdit = (field) => {
    if (!currentUser) {
      showToast?.('Sign in to edit', 'info')
      return
    }
    setEditingField(field)
    setEditValue(paper?.[field] != null ? String(paper[field]) : '')
    setEditRationale('')
  }

  const cancelEdit = () => {
    setEditingField(null)
    setEditValue('')
    setEditRationale('')
  }

  const submitEdit = async (e) => {
    e.preventDefault()
    if (!editingField || submitting) return
    setSubmitting(true)
    try {
      const old_value = paper?.[editingField]
      let new_value = editValue
      if (editingField === 'year') {
        const n = parseInt(editValue, 10)
        if (Number.isNaN(n)) { showToast?.('Year must be a number', 'error'); setSubmitting(false); return }
        new_value = n
      }
      const res = await fetch(
        `${apiUrl}/api/papers/${encodeURIComponent(canonicalId)}/edit`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify({
            action: 'edit_field',
            field: editingField,
            payload: { old: old_value, new: new_value },
            rationale: editRationale || null,
          }),
        },
      )
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        showToast?.(err.detail || `Edit failed (${res.status})`, 'error')
      } else {
        showToast?.('Edit saved', 'success')
        cancelEdit()
        fetchPaper()
      }
    } catch (err) {
      showToast?.(String(err), 'error')
    } finally {
      setSubmitting(false)
    }
  }

  const deleteOverride = async (overrideId) => {
    if (!confirm('Delete this override? (admin only)')) return
    try {
      const res = await fetch(
        `${apiUrl}/api/papers/override/${overrideId}`,
        { method: 'DELETE', headers: { ...authHeaders() } },
      )
      if (!res.ok) {
        showToast?.(`Delete failed (${res.status})`, 'error')
      } else {
        showToast?.('Override deleted', 'success')
        fetchPaper()
      }
    } catch (err) {
      showToast?.(String(err), 'error')
    }
  }

  const overlayClick = (e) => { if (e.target === e.currentTarget) onClose() }

  return (
    <div className="paper-modal-overlay" onClick={overlayClick}>
      <div className="paper-modal-content">
        <div className="paper-modal-header">
          <h2 className="paper-modal-title">
            {loading ? 'Loading…' : (paper?.title || 'Paper')}
          </h2>
          <button className="paper-modal-close" onClick={onClose} title="Close (Esc)">×</button>
        </div>

        {loading && <div className="paper-modal-body"><p>Fetching merged paper view…</p></div>}

        {error && (
          <div className="paper-modal-body">
            <p className="paper-modal-error">⚠ {error}</p>
            <p className="paper-modal-hint">
              Canonical id: <code>{canonicalId}</code>
            </p>
          </div>
        )}

        {paper && !loading && (
          <div className="paper-modal-body">
            {/* Top fact strip */}
            <div className="paper-fact-strip">
              {paper.year && <span className="paper-fact"><strong>Year:</strong> {paper.year}</span>}
              {paper.type && <span className="paper-fact"><strong>Type:</strong> {paper.type}</span>}
              {paper.first_author && <span className="paper-fact"><strong>First author:</strong> {paper.first_author}</span>}
              {paper.doi && (
                <span className="paper-fact">
                  <strong>DOI:</strong>{' '}
                  <a href={`https://doi.org/${paper.doi}`} target="_blank" rel="noopener noreferrer">{paper.doi}</a>
                </span>
              )}
              <span className="paper-fact paper-fact-id"><strong>ID:</strong> <code>{paper.canonical_id}</code></span>
            </div>

            {/* Editable canonical fields */}
            <section className="paper-section">
              <h3>Canonical record {currentUser ? '' : <span className="paper-section-hint">(sign in to edit)</span>}</h3>
              <table className="paper-edit-table">
                <tbody>
                  {EDITABLE_FIELDS.map(f => {
                    const isEditing = editingField === f.key
                    const value = paper[f.key]
                    return (
                      <tr key={f.key}>
                        <td className="paper-edit-label">{f.label}</td>
                        <td className="paper-edit-value">
                          {isEditing ? (
                            <form onSubmit={submitEdit} className="paper-edit-form">
                              <input
                                type={f.type}
                                value={editValue}
                                onChange={(e) => setEditValue(e.target.value)}
                                autoFocus
                              />
                              <input
                                type="text"
                                placeholder="Optional rationale"
                                value={editRationale}
                                onChange={(e) => setEditRationale(e.target.value)}
                              />
                              <div className="paper-edit-actions">
                                <button type="submit" className="paper-btn-primary" disabled={submitting}>
                                  {submitting ? 'Saving…' : 'Save'}
                                </button>
                                <button type="button" className="paper-btn-secondary" onClick={cancelEdit}>Cancel</button>
                              </div>
                            </form>
                          ) : (
                            <div className="paper-value-row">
                              <span className="paper-value">
                                {value != null && value !== '' ? String(value) : <em className="paper-empty">empty</em>}
                              </span>
                              {currentUser && (
                                <button className="paper-btn-link" onClick={() => startEdit(f.key)}>Edit</button>
                              )}
                            </div>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </section>

            {/* Sources */}
            <section className="paper-section">
              <h3>Sources <span className="paper-section-count">({paper.sources?.length || 0})</span></h3>
              {(paper.sources || []).length === 0 && <p className="paper-empty">No source rows recorded.</p>}
              <div className="paper-source-list">
                {(paper.sources || []).map((s, i) => {
                  const meta = SOURCE_LABELS[s.source] || { label: s.source, color: '#888' }
                  return (
                    <div key={`${s.source}-${s.source_id}-${i}`} className="paper-source-card">
                      <div className="paper-source-header">
                        <span className="paper-source-badge" style={{ background: meta.color }}>{meta.label}</span>
                        <span className="paper-source-id"><code>{s.source_id}</code></span>
                        {s.cited_by_count != null && (
                          <span className="paper-source-cited">{s.cited_by_count.toLocaleString()} citations</span>
                        )}
                      </div>
                      {s.title && s.title !== paper.title && (
                        <div className="paper-source-row"><strong>Title (variant):</strong> {s.title}</div>
                      )}
                      {s.authors?.length > 0 && (
                        <div className="paper-source-row"><strong>Authors:</strong> {s.authors.slice(0, 12).join(', ')}{s.authors.length > 12 ? ` +${s.authors.length - 12} more` : ''}</div>
                      )}
                      {(s.year || s.venue) && (
                        <div className="paper-source-row">
                          {s.year && <span><strong>Year:</strong> {s.year}</span>}
                          {s.venue && <span style={{ marginLeft: '1rem' }}><strong>Venue:</strong> {s.venue}</span>}
                        </div>
                      )}
                      {s.doi && (
                        <div className="paper-source-row">
                          <strong>DOI:</strong>{' '}
                          <a href={`https://doi.org/${s.doi}`} target="_blank" rel="noopener noreferrer">{s.doi}</a>
                        </div>
                      )}
                      {s.abstract && (
                        <details className="paper-source-abstract">
                          <summary>Abstract</summary>
                          <p>{s.abstract}</p>
                        </details>
                      )}
                      {s.fetched_at && (
                        <div className="paper-source-fetched">fetched {new Date(s.fetched_at).toLocaleString()}</div>
                      )}
                    </div>
                  )
                })}
              </div>
            </section>

            {/* Override history */}
            {(paper.overrides?.length > 0) && (
              <section className="paper-section">
                <h3>Override history <span className="paper-section-count">({paper.overrides.length})</span></h3>
                <ul className="paper-override-list">
                  {paper.overrides.map(o => (
                    <li key={o.id} className="paper-override-item">
                      <div className="paper-override-main">
                        <span className="paper-override-action">{o.action}</span>
                        {o.field && <span className="paper-override-field">{o.field}</span>}
                        {o.payload && o.payload.new !== undefined && (
                          <span className="paper-override-arrow">
                            <em>{String(o.payload.old ?? '')}</em>
                            {' → '}
                            <strong>{String(o.payload.new ?? '')}</strong>
                          </span>
                        )}
                      </div>
                      <div className="paper-override-meta">
                        user #{o.user_id} · {new Date(o.created_at).toLocaleString()}
                        {o.rationale && <> · "{o.rationale}"</>}
                        {currentUser?.role === 'admin' && (
                          <button
                            className="paper-btn-link paper-btn-danger"
                            onClick={() => deleteOverride(o.id)}
                            style={{ marginLeft: '0.75rem' }}
                          >Delete</button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
