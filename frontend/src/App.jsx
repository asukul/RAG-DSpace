import { useState, useEffect, useMemo } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Faculty data will be fetched from API
const FACULTY_DATA_INITIAL = []

// Document type icons
const DOC_TYPE_ICONS = {
  'thesis': '📜',
  'dissertation': '🎓',
  'creative component': '💡',
  'presentation': '📊',
  'article': '📄',
  'report': '📋',
  'conference paper': '🎤',
  'default': '📁'
}

function App() {
  const [activeTab, setActiveTab] = useState('search')
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState(null)

  // Data
  const [facultyData, setFacultyData] = useState([])

  // Display Options
  const [showPhotos, setShowPhotos] = useState(true) // For sidebar
  const [resultsGroupBy, setResultsGroupBy] = useState('none')
  const [facultyGroupBy, setFacultyGroupBy] = useState('none') // none, department, college
  const [collapsedGroups, setCollapsedGroups] = useState({}) // Track collapsed state per group
  const [showResultFaculty, setShowResultFaculty] = useState(true)
  const [showResultPhotos, setShowResultPhotos] = useState(false)
  const [showResultDetails, setShowResultDetails] = useState(false)

  useEffect(() => {
    fetchStats()
    fetchFaculty()
  }, [])

  const fetchFaculty = async () => {
    try {
      const res = await fetch(`${API_URL}/api/faculty`)
      if (res.ok) setFacultyData(await res.json())
    } catch (e) {
      console.error('Faculty fetch error:', e)
    }
  }

  const fetchStats = async () => {
    try {
      const res = await fetch(`${API_URL}/api/stats`)
      if (res.ok) setStats(await res.json())
    } catch (e) {
      console.error('Stats error:', e)
    }
  }

  // Admin Data
  const [adminSubTab, setAdminSubTab] = useState('config') // config, faculty, docs

  // URL Config Data
  const [scraperUrls, setScraperUrls] = useState([])
  const [dspaceUrls, setDSpaceUrls] = useState([])
  const [newScraperUrl, setNewScraperUrl] = useState({ department: '', url: '' })
  const [newDSpaceUrl, setNewDSpaceUrl] = useState({ name: '', url: '', type: 'collection' })

  // Faculty CRUD Data
  const [adminFaculty, setAdminFaculty] = useState([])
  const [facultySearch, setFacultySearch] = useState('')
  const [editingFaculty, setEditingFaculty] = useState(null) // null = none, {} = new, populated = edit
  const [editMode, setEditMode] = useState('simple') // simple, advanced
  const [jsonContent, setJsonContent] = useState('')

  // Manual Docs Data
  const [manualDocs, setManualDocs] = useState([])
  const [editingDoc, setEditingDoc] = useState(null)

  // Groups Data
  const [groups, setGroups] = useState([])
  const [renameModal, setRenameModal] = useState(null) // { oldName: string }
  const [mergeModal, setMergeModal] = useState(null) // { sourceGroup: string }

  // Faculty Manager - Drag & Drop State
  const [facultyViewMode, setFacultyViewMode] = useState('grouped') // 'table' or 'grouped'
  const [draggingFaculty, setDraggingFaculty] = useState(null)
  const [dragOverGroup, setDragOverGroup] = useState(null)
  const [selectedForMerge, setSelectedForMerge] = useState([]) // IDs for faculty merge
  const [duplicateSuggestions, setDuplicateSuggestions] = useState([])
  const [ignoredDuplicates, setIgnoredDuplicates] = useState(new Set()) // Ignored pair IDs

  // People Search State
  const [peopleNameSearch, setPeopleNameSearch] = useState('')
  const [peopleFilterMode, setPeopleFilterMode] = useState('all') // all, department, college, area, topic
  const [selectedFilterValue, setSelectedFilterValue] = useState('')
  const [facultyDocCounts, setFacultyDocCounts] = useState({})
  const [facultyDocCountsLoading, setFacultyDocCountsLoading] = useState(false)

  // Document Manager State
  const [allDocuments, setAllDocuments] = useState([])
  const [docStats, setDocStats] = useState(null)
  const [docViewMode, setDocViewMode] = useState('cards') // 'cards', 'table', 'reports'
  const [expandedDocs, setExpandedDocs] = useState(new Set())
  const [docFilter, setDocFilter] = useState({ type: '', year: '', search: '' })

  // Faculty Mismatch Flagging State
  const [flaggedMismatches, setFlaggedMismatches] = useState([])

  // Toast Notification State
  const [toast, setToast] = useState(null) // { message: string, type: 'success' | 'error' | 'info' }

  // Mismatch Faculty Search State
  const [mismatchFacultySearch, setMismatchFacultySearch] = useState({}) // { [mismatchId]: searchTerm }
  const [mismatchDropdownOpen, setMismatchDropdownOpen] = useState({}) // { [mismatchId]: boolean }

  // Expanded Metadata State (for "See More" in search results)
  const [expandedMetadata, setExpandedMetadata] = useState(new Set())

  // Topic Discovery State
  const [discoveredTopics, setDiscoveredTopics] = useState(null)
  const [discoveryLoading, setDiscoveryLoading] = useState(false)
  const [expandedCategories, setExpandedCategories] = useState(new Set())

  const toggleMetadataExpanded = (uuid) => {
    setExpandedMetadata(prev => {
      const newSet = new Set(prev)
      if (newSet.has(uuid)) {
        newSet.delete(uuid)
      } else {
        newSet.add(uuid)
      }
      return newSet
    })
  }

  const showToast = (message, type = 'info') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  // Topic Discovery Functions
  const fetchDiscoveredTopics = async () => {
    try {
      const res = await fetch(`${API_URL}/api/admin/topics/discovered`)
      if (res.ok) {
        const data = await res.json()
        setDiscoveredTopics(data)
      }
    } catch (e) {
      console.error('Error fetching topics:', e)
    }
  }

  const handleDiscoverTopics = async () => {
    setDiscoveryLoading(true)
    try {
      const res = await fetch(`${API_URL}/api/admin/topics/discover`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        setDiscoveredTopics(data)
        showToast(`✅ Discovered ${data.total_topics_found} topics from ${data.total_documents_analyzed} documents!`, 'success')
      } else {
        showToast('❌ Failed to discover topics', 'error')
      }
    } catch (e) {
      console.error('Error discovering topics:', e)
      showToast('❌ Error analyzing documents', 'error')
    } finally {
      setDiscoveryLoading(false)
    }
  }

  const toggleCategory = (categoryName) => {
    setExpandedCategories(prev => {
      const newSet = new Set(prev)
      if (newSet.has(categoryName)) {
        newSet.delete(categoryName)
      } else {
        newSet.add(categoryName)
      }
      return newSet
    })
  }

  // Fetch topics when Topics tab is active
  useEffect(() => {
    if (activeTab === 'topics') {
      fetchDiscoveredTopics()
    }
  }, [activeTab])

  // Fetch faculty document counts when Faculty tab is active
  const fetchFacultyDocCounts = async () => {
    setFacultyDocCountsLoading(true)
    try {
      const res = await fetch(`${API_URL}/api/admin/faculty/document-counts`)
      if (res.ok) {
        const data = await res.json()
        setFacultyDocCounts(data.counts || {})
      }
    } catch (e) {
      console.error('Error fetching faculty doc counts:', e)
    } finally {
      setFacultyDocCountsLoading(false)
    }
  }

  useEffect(() => {
    if (activeTab === 'faculty' && Object.keys(facultyDocCounts).length === 0) {
      fetchFacultyDocCounts()
    }
  }, [activeTab])

  const fetchAdminData = async () => {
    try {
      const [sRes, dRes, fRes, mRes, gRes] = await Promise.all([
        fetch(`${API_URL}/api/admin/scraper-urls`),
        fetch(`${API_URL}/api/admin/dspace-urls`),
        fetch(`${API_URL}/api/admin/faculty`),
        fetch(`${API_URL}/api/admin/documents`),
        fetch(`${API_URL}/api/admin/groups`)
      ])
      if (sRes.ok) setScraperUrls(await sRes.json())
      if (dRes.ok) setDSpaceUrls(await dRes.json())
      if (fRes.ok) setAdminFaculty(await fRes.json())
      if (mRes.ok) setManualDocs(await mRes.json())
      if (gRes.ok) setGroups(await gRes.json())

      // Fetch duplicates separately (can be slow for large datasets)
      fetch(`${API_URL}/api/admin/faculty/duplicates`)
        .then(r => r.ok ? r.json() : [])
        .then(setDuplicateSuggestions)
        .catch(() => setDuplicateSuggestions([]))

      // Fetch flagged mismatches
      fetch(`${API_URL}/api/admin/mismatches`)
        .then(r => r.ok ? r.json() : [])
        .then(setFlaggedMismatches)
        .catch(() => setFlaggedMismatches([]))
    } catch (e) {
      console.error('Admin fetch error:', e)
    }
  }

  const fetchDocuments = async () => {
    try {
      const [docsRes, statsRes] = await Promise.all([
        fetch(`${API_URL}/api/admin/documents/all`),
        fetch(`${API_URL}/api/admin/documents/stats`)
      ])
      if (docsRes.ok) setAllDocuments(await docsRes.json())
      if (statsRes.ok) setDocStats(await statsRes.json())
    } catch (e) { console.error('Doc fetch error:', e) }
  }

  const handleExportDocs = (format) => {
    window.open(`${API_URL}/api/admin/documents/export?format=${format}`, '_blank')
  }

  const [indexingStatus, setIndexingStatus] = useState(null)

  const handleIndexNow = async () => {
    setIndexingStatus('Indexing from DSpace...')
    try {
      const res = await fetch(`${API_URL}/api/admin/documents/index-now`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        setIndexingStatus(`✅ ${data.message} (Total: ${data.total_cached})`)
        fetchDocuments()
      } else {
        setIndexingStatus('❌ Indexing failed')
      }
    } catch (e) {
      setIndexingStatus('❌ Error: ' + e.message)
    }
    setTimeout(() => setIndexingStatus(null), 5000)
  }

  const handleFlagMismatch = async (source, faculty, authorName) => {
    try {
      const res = await fetch(`${API_URL}/api/admin/mismatches`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          document_id: source.uuid || source.id || source.title,
          document_title: source.title,
          matched_faculty_id: faculty.id,
          matched_faculty_name: faculty.name,
          author_name_in_doc: authorName || (source.authors || [])[0] || 'Unknown',
          document_authors: source.authors || [],
          document_advisors: source.advisors || []
        })
      })
      if (res.ok) {
        showToast('✅ Mismatch flagged for admin review!', 'success')
      } else {
        showToast('⚠️ Already flagged or error occurred', 'error')
      }
    } catch (e) {
      console.error('Flag error:', e)
      showToast('❌ Error flagging mismatch', 'error')
    }
  }


  useEffect(() => {
    if (activeTab === 'admin') {
      fetchAdminData()
      fetchStats()
      fetchDocuments()
    }
  }, [activeTab])

  // --- Handlers ---

  // Stats/System Handlers
  const handleReseed = async () => {
    if (!confirm("⚠️ WARNING: This will overwrite 'faculty.json' with the default verified data. Any manual changes to faculty will be lost (if they have same names). Proceed?")) return;

    try {
      const res = await fetch(`${API_URL}/api/admin/reseed-faculty`, { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        alert(data.message);
        fetchAdminData();
        fetchFaculty();
        fetchStats();
      } else {
        alert("Failed to reseed: " + JSON.stringify(data));
      }
    } catch (e) {
      console.error(e);
      alert("Error reseeding data");
    }
  }

  // URL Handlers
  const handleAddScraperUrl = async (e) => {
    e.preventDefault()
    if (!newScraperUrl.department || !newScraperUrl.url) return
    try {
      const res = await fetch(`${API_URL}/api/admin/scraper-urls`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newScraperUrl)
      })
      if (res.ok) {
        setNewScraperUrl({ department: '', url: '' })
        fetchAdminData()
      }
    } catch (e) { console.error(e) }
  }

  const handleDeleteScraperUrl = async (id) => {
    if (!confirm('Delete this source?')) return
    try {
      await fetch(`${API_URL}/api/admin/scraper-urls/${id}`, { method: 'DELETE' })
      fetchAdminData()
    } catch (e) { console.error(e) }
  }

  const handleAddDSpaceUrl = async (e) => {
    e.preventDefault()
    if (!newDSpaceUrl.name || !newDSpaceUrl.url) return
    try {
      const res = await fetch(`${API_URL}/api/admin/dspace-urls`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newDSpaceUrl)
      })
      if (res.ok) {
        setNewDSpaceUrl({ name: '', url: '', type: 'collection' })
        fetchAdminData()
      }
    } catch (e) { console.error(e) }
  }

  const handleDeleteDSpaceUrl = async (id) => {
    if (!confirm('Delete this collection?')) return
    try {
      await fetch(`${API_URL}/api/admin/dspace-urls/${id}`, { method: 'DELETE' })
      fetchAdminData()
    } catch (e) { console.error(e) }
  }

  // Faculty Handlers
  const handleEditFaculty = (faculty) => {
    setEditingFaculty(faculty || {
      id: crypto.randomUUID(),
      name: '',
      department: 'Department of Computer Science',
      college: 'College of Liberal Arts and Sciences',
      research_interests: [],
      courses_taught: []
    })
    setJsonContent(JSON.stringify(faculty || {
      id: crypto.randomUUID(),
      name: '',
      is_teaching_faculty: false,
      department: 'Department of Computer Science',
      college: 'College of Liberal Arts and Sciences'
    }, null, 2))
    setEditMode('simple')
  }

  const handleSaveFaculty = async (e) => {
    if (e) e.preventDefault()

    let payload = editingFaculty
    if (editMode === 'advanced') {
      try {
        payload = JSON.parse(jsonContent)
      } catch (err) {
        alert('Invalid JSON')
        return
      }
    } else {
      // Ensure array fields are arrays in simple mode
      if (typeof payload.research_interests === 'string') {
        payload.research_interests = payload.research_interests.split(',').map(s => s.trim()).filter(Boolean)
      }
      if (typeof payload.courses_taught === 'string') {
        payload.courses_taught = payload.courses_taught.split(',').map(s => s.trim()).filter(Boolean)
      }
    }

    try {
      const res = await fetch(`${API_URL}/api/admin/faculty`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (res.ok) {
        setEditingFaculty(null)
        fetchAdminData()
        fetchFaculty() // Refresh main faculty list too
      } else {
        alert('Failed to save faculty')
      }
    } catch (e) { console.error(e) }
  }

  const handleDeleteFaculty = async (id) => {
    if (!confirm('Are you sure you want to delete this faculty member?')) return
    try {
      await fetch(`${API_URL}/api/admin/faculty/${id}`, { method: 'DELETE' })
      fetchAdminData()
      fetchFaculty()
    } catch (e) { console.error(e) }
  }

  // Document Handlers
  const handleEditDoc = (doc) => {
    setEditingDoc(doc || { title: '', abstract: '', authors: [], date: new Date().getFullYear().toString(), url: '', type: 'publication' })
  }

  const handleSaveDoc = async (e) => {
    if (e) e.preventDefault()
    let payload = { ...editingDoc }
    if (typeof payload.authors === 'string') {
      payload.authors = payload.authors.split(',').map(s => s.trim())
    }

    try {
      const res = await fetch(`${API_URL}/api/admin/documents`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (res.ok) {
        setEditingDoc(null)
        fetchAdminData()
      }
    } catch (e) { console.error(e) }
  }

  const handleDeleteDoc = async (id) => {
    if (!confirm('Delete this document?')) return
    try {
      await fetch(`${API_URL}/api/admin/documents/${id}`, { method: 'DELETE' })
      fetchAdminData()
    } catch (e) { console.error(e) }
  }

  // Group Handlers
  const handleRenameGroup = async (oldName, newName) => {
    if (!newName || newName === oldName) return
    try {
      const res = await fetch(`${API_URL}/api/admin/groups/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_name: oldName, new_name: newName })
      })
      if (res.ok) {
        setRenameModal(null)
        fetchAdminData()
        fetchFaculty()
      } else {
        const err = await res.json()
        alert(err.detail || 'Failed to rename group')
      }
    } catch (e) { console.error(e) }
  }

  const handleMergeGroups = async (sourceGroup, targetGroup) => {
    if (!targetGroup || sourceGroup === targetGroup) return
    try {
      const res = await fetch(`${API_URL}/api/admin/groups/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_group: sourceGroup, target_group: targetGroup })
      })
      if (res.ok) {
        setMergeModal(null)
        fetchAdminData()
        fetchFaculty()
      } else {
        const err = await res.json()
        alert(err.detail || 'Failed to merge groups')
      }
    } catch (e) { console.error(e) }
  }

  // Drag-Drop Handlers for Faculty Manager
  const handleDropFacultyOnGroup = async (facultyId, newDepartment) => {
    try {
      // Find the faculty member
      const faculty = adminFaculty.find(f => f.id === facultyId)
      if (!faculty || faculty.department === newDepartment) return

      // Update via API
      const res = await fetch(`${API_URL}/api/admin/faculty`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...faculty, department: newDepartment })
      })

      if (res.ok) {
        fetchAdminData()
        fetchFaculty()
      }
    } catch (e) { console.error(e) }

    setDraggingFaculty(null)
    setDragOverGroup(null)
  }

  const handleMergeFacultyRecords = async () => {
    if (selectedForMerge.length < 2) {
      alert('Select at least 2 faculty members to merge')
      return
    }

    const primaryId = selectedForMerge[0]
    const secondaryIds = selectedForMerge.slice(1)
    const primary = adminFaculty.find(f => f.id === primaryId)

    if (!confirm(`Merge ${selectedForMerge.length} records into "${primary?.name}"? This cannot be undone.`)) return

    try {
      const res = await fetch(`${API_URL}/api/admin/faculty/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ primary_id: primaryId, secondary_ids: secondaryIds })
      })

      if (res.ok) {
        setSelectedForMerge([])
        fetchAdminData()
        fetchFaculty()
      } else {
        const err = await res.json()
        alert(err.detail || 'Failed to merge faculty')
      }
    } catch (e) { console.error(e) }
  }

  // Duplicate Suggestion Handlers
  const handleAcceptDuplicate = async (dup) => {
    // Use faculty1 as primary (usually the one with more complete data)
    const primaryId = dup.faculty1.id
    const secondaryId = dup.faculty2.id

    try {
      const res = await fetch(`${API_URL}/api/admin/faculty/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ primary_id: primaryId, secondary_ids: [secondaryId] })
      })

      if (res.ok) {
        fetchAdminData()
        fetchFaculty()
      } else {
        const err = await res.json()
        alert(err.detail || 'Failed to merge')
      }
    } catch (e) { console.error(e) }
  }

  const handleIgnoreDuplicate = (dup) => {
    const pairKey = [dup.faculty1.id, dup.faculty2.id].sort().join('|')
    setIgnoredDuplicates(prev => new Set([...prev, pairKey]))
  }

  const handleSearch = async (e) => {
    e.preventDefault()
    if (!query.trim()) return

    setLoading(true)
    try {
      const res = await fetch(`${API_URL}/api/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, limit: 50 })
      })
      if (res.ok) {
        setResults(await res.json())
      }
    } catch (e) {
      console.error('Search error:', e)
    } finally {
      setLoading(false)
    }
  }

  // Helper to find faculty mentioned in a specific result
  const getMatchedFaculty = (source) => {
    if (!showResultFaculty || !facultyData.length) return []

    // Get all people from source in order
    const sourcePeople = [
      ...(source.authors || []),
      ...(source.advisors || []),
      ...(source.contributors || [])
    ]

    // Find matches preserving order
    const matches = []
    const seenIds = new Set()

    sourcePeople.forEach(personName => {
      const pName = personName.toLowerCase()
      // Find faculty that matches this person
      const match = facultyData.find(f => {
        const fName = f.name.toLowerCase()
        const fParts = fName.split(' ')
        const fLast = fParts[fParts.length - 1]

        // Use regex for strict word boundary matching to avoid partial matches
        // e.g. prevent "Wei Le" matching "Lei Qi"
        const escapeRegExp = (string) => string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

        // Match full name "Adisak Sukul" or last name "Sukul" as distinct words
        const fNamePattern = new RegExp(`\\b${escapeRegExp(fName)}\\b`, 'i');
        const fLastPattern = new RegExp(`\\b${escapeRegExp(fLast)}\\b`, 'i');

        return fNamePattern.test(pName) || fLastPattern.test(pName)
      })

      if (match && !seenIds.has(match.id)) {
        matches.push(match)
        seenIds.add(match.id)
      }
    })

    return matches
  }

  // Use related faculty from API results
  const relatedFaculty = useMemo(() => {
    if (results?.related_faculty && results.related_faculty.length > 0) {
      return results.related_faculty
    }
    return []
  }, [results])

  // Group results by document type


  const groupedResults = useMemo(() => {
    if (!results?.sources || resultsGroupBy === 'none') return null

    const groups = {}
    results.sources.forEach(source => {
      const type = (source.type || 'publication').toLowerCase()
      if (!groups[type]) groups[type] = []
      groups[type].push(source)
    })
    return groups
  }, [results, resultsGroupBy])

  const getTypeIcon = (type) => {
    const key = Object.keys(DOC_TYPE_ICONS).find(k => type?.toLowerCase().includes(k))
    return DOC_TYPE_ICONS[key] || DOC_TYPE_ICONS.default
  }

  const renderResultItem = (source, index) => {
    const matchedFaculty = getMatchedFaculty(source)
    const isExpanded = false // TODO: per-item state if needed, simpler to rely on global for now or just standard details

    const handleFacultyClick = (faculty) => {
      // Placeholder for future functionality, e.g., navigate to faculty page or filter
      console.log('Clicked faculty:', faculty.name);
      // Example: set query to faculty name and switch to search tab
      setQuery(faculty.name);
      setActiveTab('search');
    };

    return (
      <li key={index} className="result-item">
        <div className="result-icon">{getTypeIcon(source.type)}</div>
        <div className="result-content">
          <h3>
            <a href={source.url} target="_blank" rel="noopener noreferrer">
              {source.title}
            </a>
          </h3>
          <div className="meta">
            {(source.authors || []).join(', ')} • {source.date} • {source.type}
          </div>

          {/* Faculty Matches */}
          {matchedFaculty.length > 0 && showResultFaculty && (
            <div className="matched-faculty">
              {matchedFaculty.map(f => (
                <div key={f.id} className="faculty-chip">
                  <div className="chip-main" onClick={() => handleFacultyClick(f)}>
                    {showResultPhotos && (
                      <img
                        src={f.photo_url || `https://ui-avatars.com/api/?name=${f.name}&background=random`}
                        alt={f.name}
                        className="chip-photo"
                        onError={(e) => {
                          e.target.onerror = null
                          e.target.src = `https://ui-avatars.com/api/?name=${f.name}&background=random`
                        }}
                      />
                    )}
                    <span>{f.name}</span>
                  </div>
                  <button
                    className="flag-btn"
                    title="Flag incorrect match"
                    onClick={(e) => { e.stopPropagation(); handleFlagMismatch(source, f, (source.authors || [])[0]) }}
                  >🚩</button>
                </div>
              ))}
            </div>
          )}

          {/* Extended Details */}
          {(showResultDetails && source.abstract) && (
            <div className="source-details">
              <p className="source-abstract">{source.abstract}</p>
            </div>
          )}
          {(!showResultDetails && source.abstract) && (
            <p className="source-abstract truncated">{source.abstract.substring(0, 150)}...</p>
          )}

          {/* See More Metadata Button */}
          <div className="result-actions">
            <button
              className="see-more-btn"
              onClick={() => toggleMetadataExpanded(source.uuid)}
            >
              {expandedMetadata.has(source.uuid) ? '📜 Hide Metadata' : '📝 See More'}
            </button>
          </div>

          {/* Expandable Full Metadata Panel */}
          {expandedMetadata.has(source.uuid) && (
            <div className="metadata-panel">
              <h4>📄 Full DSpace Metadata</h4>
              <table className="metadata-table">
                <tbody>
                  {source.uuid && <tr><td><strong>UUID</strong></td><td>{source.uuid}</td></tr>}
                  {source.handle && <tr><td><strong>Handle</strong></td><td>{source.handle}</td></tr>}
                  {source.date && <tr><td><strong>Date</strong></td><td>{source.date}</td></tr>}
                  {source.type && <tr><td><strong>Type</strong></td><td>{source.type}</td></tr>}
                  {/* Always show Authors */}
                  <tr className="highlight-row">
                    <td><strong>👤 Authors</strong></td>
                    <td>{source.authors?.length > 0 ? source.authors.join(', ') : <em className="no-data">No authors listed</em>}</td>
                  </tr>
                  {/* Always show Advisors */}
                  <tr className="highlight-row">
                    <td><strong>🎓 Advisors</strong></td>
                    <td>{source.advisors?.length > 0 ? source.advisors.join(', ') : <em className="no-data">No advisors listed</em>}</td>
                  </tr>
                  {source.publisher && <tr><td><strong>Publisher</strong></td><td>{source.publisher}</td></tr>}
                  {source.language && <tr><td><strong>Language</strong></td><td>{source.language}</td></tr>}
                  {source.rights && <tr><td><strong>Rights</strong></td><td>{source.rights}</td></tr>}
                  {source.identifier_doi && <tr><td><strong>DOI</strong></td><td>{source.identifier_doi}</td></tr>}
                  {source.identifier_uri && <tr><td><strong>URI</strong></td><td>{source.identifier_uri}</td></tr>}
                  {source.format && <tr><td><strong>Format</strong></td><td>{source.format}</td></tr>}
                  {source.degree_name && <tr><td><strong>Degree</strong></td><td>{source.degree_name}</td></tr>}
                  {source.degree_level && <tr><td><strong>Degree Level</strong></td><td>{source.degree_level}</td></tr>}
                  {source.degree_discipline && <tr><td><strong>Discipline</strong></td><td>{source.degree_discipline}</td></tr>}
                  {(source.subjects?.length > 0) && <tr><td><strong>Subjects</strong></td><td>{source.subjects.join(', ')}</td></tr>}
                  {(source.contributors?.length > 0) && <tr><td><strong>Contributors</strong></td><td>{source.contributors.join(', ')}</td></tr>}
                </tbody>
              </table>
              {source.raw_metadata && Object.keys(source.raw_metadata).length > 0 && (
                <details className="raw-metadata-details">
                  <summary>🗄 Raw DC Elements ({Object.keys(source.raw_metadata).length} fields)</summary>
                  <table className="metadata-table raw">
                    <tbody>
                      {Object.entries(source.raw_metadata).sort().map(([key, values]) => (
                        <tr key={key}>
                          <td><code>{key}</code></td>
                          <td>{Array.isArray(values) ? values.join(' | ') : values}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              )}
              <a
                href={source.url || source.dspace_url}
                target="_blank"
                rel="noopener noreferrer"
                className="dspace-link-btn"
              >
                🚀 View Full Item on DSpace
              </a>
            </div>
          )}
        </div>
      </li>
    )
  }

  return (
    <div className="app">
      {/* Toast Notification */}
      {toast && (
        <div className={`toast-notification toast-${toast.type}`}>
          {toast.message}
        </div>
      )}
      <header className="header">
        <div className="header-content">
          <h1>🌪️ ISU Research Search</h1>
          <p>AI-Powered Search for Iowa State Computer Science Research</p>
          <nav className="nav">
            <button className={activeTab === 'search' ? 'active' : ''} onClick={() => setActiveTab('search')}>
              🔍 Search
            </button>
            <button className={activeTab === 'faculty' ? 'active' : ''} onClick={() => setActiveTab('faculty')}>
              👥 Faculty
            </button>
            <button className={activeTab === 'topics' ? 'active' : ''} onClick={() => setActiveTab('topics')}>
              🗺️ Topics
            </button>
            <button className={activeTab === 'admin' ? 'active' : ''} onClick={() => setActiveTab('admin')}>
              ⚙️ Admin
            </button>
          </nav>
        </div>
      </header>

      <div className="main-container">
        <main className="main-content">
          {activeTab === 'search' && (
            <div className="search-page">
              <form onSubmit={handleSearch} className="search-form">
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search research papers, theses, dissertations..."
                  className="search-input"
                />
                <button type="submit" disabled={loading} className="search-btn">
                  {loading ? '⏳' : '🔍'} Search
                </button>
              </form>

              {stats && (
                <div className="stats-bar">
                  <span>📚 {stats.indexed_documents || 0} indexed documents</span>
                  <span>👥 {stats.faculty_count || 0} faculty</span>
                  <span>🤖 Gemini RAG: {stats.gemini_enabled ? '✅' : '❌'}</span>
                </div>
              )}

              {/* Search Suggestions - show when no results yet */}
              {!results && !loading && (
                <>
                  {/* Regular Search Suggestions */}
                  <div className="search-suggestions">
                    <p className="suggestions-label">🔍 Try searching for:</p>
                    <div className="suggestions-chips">
                      {[
                        'Machine Learning',
                        'Artificial Intelligence',
                        'Data Science',
                        'Climate Change',
                        'Bioinformatics',
                        'Cybersecurity',
                        'Renewable Energy',
                        'Robotics'
                      ].map((suggestion, idx) => (
                        <button
                          key={idx}
                          type="button"
                          className="suggestion-chip regular"
                          onClick={() => { setQuery(suggestion); }}
                        >
                          {suggestion}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Cross-Discipline Search Suggestions */}
                  <div className="search-suggestions cross-discipline">
                    <p className="suggestions-label">🔀 Or, try cross-discipline search:</p>
                    <div className="suggestions-chips">
                      {[
                        'Political Science and Deep Learning',
                        'Biology and Machine Learning',
                        'Agriculture and Climate AI',
                        'Psychology and Natural Language Processing',
                        'Economics and Neural Networks',
                        'Chemistry and Computer Vision',
                        'Sociology and Data Mining',
                        'Physics and Quantum Computing'
                      ].map((suggestion, idx) => (
                        <button
                          key={idx}
                          type="button"
                          className="suggestion-chip cross"
                          onClick={() => { setQuery(suggestion); }}
                        >
                          {suggestion}
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}

              {results && (
                <>
                  {results.answer && (
                    <div className="ai-answer">
                      <h3>🤖 AI Answer</h3>
                      <div className="answer-content">{results.answer}</div>
                      <div className="search-meta">
                        Mode: {results.search_mode} | Files searched: {results.files_searched} | Results: {results.total_results}
                      </div>
                    </div>
                  )}

                  {results.sources && results.sources.length > 0 && (
                    <div className="sources">
                      <div className="results-header">
                        <h3>📄 Sources ({results.sources.length})</h3>
                        <div className="results-controls">
                          <div className="control-group">
                            <label>Group by: </label>
                            <select value={resultsGroupBy} onChange={(e) => setResultsGroupBy(e.target.value)}>
                              <option value="none">None</option>
                              <option value="type">Document Type</option>
                            </select>
                          </div>

                          <div className="control-group toggles">
                            <label title="Show faculty authors">
                              <input type="checkbox" checked={showResultFaculty} onChange={(e) => setShowResultFaculty(e.target.checked)} />
                              👥 Faculty
                            </label>
                            <label title="Show faculty photos">
                              <input type="checkbox" checked={showResultPhotos} onChange={(e) => setShowResultPhotos(e.target.checked)} />
                              🖼️ Photos
                            </label>
                            <label title="Show full details">
                              <input type="checkbox" checked={showResultDetails} onChange={(e) => setShowResultDetails(e.target.checked)} />
                              📝 Details
                            </label>
                          </div>
                        </div>
                      </div>

                      {resultsGroupBy === 'type' && groupedResults ? (
                        <div className="results-tree">
                          {Object.entries(groupedResults).map(([type, items]) => (
                            <details key={type} open>
                              <summary>
                                {getTypeIcon(type)} {type.charAt(0).toUpperCase() + type.slice(1)} ({items.length})
                              </summary>
                              <ul className="type-items">
                                {items.map((source, idx) => renderResultItem(source, idx))}
                              </ul>
                            </details>
                          ))}
                        </div>
                      ) : (
                        <ul className="sources-list">
                          {results.sources.map((source, idx) => renderResultItem(source, idx))}
                        </ul>
                      )}
                    </div>
                  )}

                  {results.suggested_queries && (
                    <div className="suggestions">
                      <h4>💡 Related searches:</h4>
                      {results.suggested_queries.map((sq, idx) => (
                        <button key={idx} className="suggestion-btn" onClick={() => { setQuery(sq); }}>
                          {sq}
                        </button>
                      ))}
                    </div>
                  )}
                </>
              )}

              {!results && !loading && (
                <div className="welcome-message">
                  <h2>Welcome to ISU Research Search</h2>
                  <p>Search for research papers, theses, and dissertations from Iowa State's Computer Science department.</p>
                  <div className="example-queries">
                    <h4>Try searching for:</h4>
                    <button className="suggestion-btn" onClick={() => setQuery('machine learning healthcare')}>
                      machine learning healthcare
                    </button>
                    <button className="suggestion-btn" onClick={() => setQuery('deep learning computer vision')}>
                      deep learning computer vision
                    </button>
                    <button className="suggestion-btn" onClick={() => setQuery('software testing automation')}>
                      software testing automation
                    </button>
                    <button className="suggestion-btn" onClick={() => setQuery('robotics motion planning')}>
                      robotics motion planning
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === 'faculty' && (
            <div className="faculty-page people-search">
              <h2>👥 People Search</h2>
              <p style={{ color: '#64748b', marginBottom: '1rem' }}>
                Find researchers by name, department, college, research area, or topic.
              </p>

              {/* Search Bar */}
              <div className="people-search-bar" style={{ marginBottom: '1.5rem' }}>
                <input
                  type="text"
                  placeholder="🔍 Search by name..."
                  value={peopleNameSearch}
                  onChange={(e) => setPeopleNameSearch(e.target.value)}
                  style={{
                    width: '100%',
                    maxWidth: '500px',
                    padding: '0.75rem 1rem',
                    fontSize: '1rem',
                    border: '2px solid #e2e8f0',
                    borderRadius: '8px',
                    outline: 'none',
                    transition: 'border-color 0.2s'
                  }}
                />
              </div>

              {/* Filter Tabs */}
              <div className="people-filter-tabs" style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
                {['all', 'department', 'college', 'area', 'topic'].map(mode => (
                  <button
                    key={mode}
                    className={`filter-tab ${peopleFilterMode === mode ? 'active' : ''}`}
                    onClick={() => { setPeopleFilterMode(mode); setSelectedFilterValue(''); }}
                    style={{
                      padding: '0.5rem 1rem',
                      border: 'none',
                      borderRadius: '20px',
                      cursor: 'pointer',
                      background: peopleFilterMode === mode ? 'linear-gradient(135deg, #c8102e, #991b1b)' : '#f1f5f9',
                      color: peopleFilterMode === mode ? 'white' : '#475569',
                      fontWeight: peopleFilterMode === mode ? '600' : '500',
                      transition: 'all 0.2s'
                    }}
                  >
                    {mode === 'all' ? '👥 All' :
                      mode === 'department' ? '🏢 Departments' :
                        mode === 'college' ? '🎓 Colleges' :
                          mode === 'area' ? '🔬 Research Areas' : '🏷️ Topics'}
                  </button>
                ))}
              </div>

              {/* Filter Values (when not "all") */}
              {peopleFilterMode !== 'all' && (
                <div className="filter-values" style={{ marginBottom: '1.5rem', display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                  {(() => {
                    let values = [];
                    if (peopleFilterMode === 'department') {
                      values = [...new Set(facultyData.map(f => f.department).filter(Boolean))].sort();
                    } else if (peopleFilterMode === 'college') {
                      values = [...new Set(facultyData.map(f => f.college).filter(Boolean))].sort();
                    } else if (peopleFilterMode === 'area') {
                      values = [...new Set(facultyData.flatMap(f => f.research_areas || []))].sort();
                    } else if (peopleFilterMode === 'topic') {
                      values = [...new Set(facultyData.flatMap(f => f.research_interests || []))].sort();
                    }
                    return values.map((val, idx) => (
                      <button
                        key={idx}
                        className={`filter-value-chip ${selectedFilterValue === val ? 'active' : ''}`}
                        onClick={() => setSelectedFilterValue(selectedFilterValue === val ? '' : val)}
                        style={{
                          padding: '0.4rem 0.8rem',
                          border: '1px solid',
                          borderColor: selectedFilterValue === val ? '#c8102e' : '#e2e8f0',
                          borderRadius: '16px',
                          background: selectedFilterValue === val ? '#fef2f2' : 'white',
                          color: selectedFilterValue === val ? '#c8102e' : '#475569',
                          cursor: 'pointer',
                          fontSize: '0.85rem',
                          transition: 'all 0.2s'
                        }}
                      >
                        {val}
                      </button>
                    ));
                  })()}
                </div>
              )}

              {/* Stats Bar */}
              <div style={{ marginBottom: '1rem', color: '#64748b', fontSize: '0.9rem' }}>
                Showing {(() => {
                  let filtered = facultyData;
                  if (peopleNameSearch) {
                    filtered = filtered.filter(f => f.name.toLowerCase().includes(peopleNameSearch.toLowerCase()));
                  }
                  if (selectedFilterValue) {
                    if (peopleFilterMode === 'department') {
                      filtered = filtered.filter(f => f.department === selectedFilterValue);
                    } else if (peopleFilterMode === 'college') {
                      filtered = filtered.filter(f => f.college === selectedFilterValue);
                    } else if (peopleFilterMode === 'area') {
                      filtered = filtered.filter(f => (f.research_areas || []).includes(selectedFilterValue));
                    } else if (peopleFilterMode === 'topic') {
                      filtered = filtered.filter(f => (f.research_interests || []).includes(selectedFilterValue));
                    }
                  }
                  return filtered.length;
                })()} of {facultyData.length} faculty members
              </div>

              {/* Faculty Grid */}
              <div className="faculty-grid">
                {(() => {
                  let filtered = facultyData;
                  if (peopleNameSearch) {
                    filtered = filtered.filter(f => f.name.toLowerCase().includes(peopleNameSearch.toLowerCase()));
                  }
                  if (selectedFilterValue) {
                    if (peopleFilterMode === 'department') {
                      filtered = filtered.filter(f => f.department === selectedFilterValue);
                    } else if (peopleFilterMode === 'college') {
                      filtered = filtered.filter(f => f.college === selectedFilterValue);
                    } else if (peopleFilterMode === 'area') {
                      filtered = filtered.filter(f => (f.research_areas || []).includes(selectedFilterValue));
                    } else if (peopleFilterMode === 'topic') {
                      filtered = filtered.filter(f => (f.research_interests || []).includes(selectedFilterValue));
                    }
                  }
                  return filtered.map(f => (
                    <div key={f.id} className="faculty-card" style={{ position: 'relative' }}>
                      <img src={f.photo_url} alt={f.name} className="card-photo"
                        onError={(e) => { e.target.onerror = null; e.target.src = 'https://via.placeholder.com/100?text=Photo' }} />
                      <h3>{f.name}</h3>

                      {/* Document Count Badge */}
                      {facultyDocCounts[f.id] > 0 && (
                        <button
                          className="doc-count-badge"
                          onClick={() => { setQuery(f.name); setActiveTab('search'); }}
                          title={`Search for documents by ${f.name}`}
                          style={{
                            position: 'absolute',
                            top: '0.5rem',
                            right: '0.5rem',
                            background: 'linear-gradient(135deg, #059669, #047857)',
                            color: 'white',
                            border: 'none',
                            borderRadius: '12px',
                            padding: '0.25rem 0.6rem',
                            fontSize: '0.75rem',
                            fontWeight: '600',
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.25rem',
                            boxShadow: '0 2px 4px rgba(0,0,0,0.15)'
                          }}
                        >
                          📄 {facultyDocCounts[f.id]}
                        </button>
                      )}

                      <div className="rank">{f.rank}</div>
                      {f.department && <div style={{ fontSize: '0.8rem', color: '#64748b', marginBottom: '0.5rem' }}>{f.department}</div>}
                      <div className="interests">
                        {(f.research_interests || []).slice(0, 3).map((int, i) => (
                          <span
                            key={i}
                            className="interest-tag"
                            onClick={() => { setPeopleFilterMode('topic'); setSelectedFilterValue(int); }}
                            style={{ cursor: 'pointer' }}
                          >
                            {int}
                          </span>
                        ))}
                      </div>
                      <a href={f.profile_url} target="_blank" rel="noopener noreferrer" className="profile-link">
                        View Profile →
                      </a>
                    </div>
                  ));
                })()}
              </div>
            </div>
          )}

          {/* Topics Page */}
          {activeTab === 'topics' && (
            <div className="topics-page">
              <h2>🗺️ Research Topic Discovery</h2>
              <p style={{ color: '#64748b', marginBottom: '1.5rem' }}>
                Discover research topics by analyzing all indexed documents from DSpace.
              </p>

              {/* Discovery Controls */}
              <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', marginBottom: '2rem', flexWrap: 'wrap' }}>
                <button
                  className="btn-primary"
                  onClick={handleDiscoverTopics}
                  disabled={discoveryLoading}
                  style={{ padding: '0.75rem 1.5rem', fontSize: '1rem' }}
                >
                  {discoveryLoading ? '⏳ Analyzing Documents...' : '🔍 Run Topic Discovery'}
                </button>

                {discoveredTopics && (
                  <div style={{ display: 'flex', gap: '1.5rem', color: '#475569', fontSize: '0.9rem' }}>
                    <span>📚 <strong>{discoveredTopics.total_documents_analyzed}</strong> documents analyzed</span>
                    <span>🏷️ <strong>{discoveredTopics.total_topics_found}</strong> topics found</span>
                    {discoveredTopics.last_discovered && (
                      <span>⏰ Last run: {new Date(discoveredTopics.last_discovered).toLocaleString()}</span>
                    )}
                  </div>
                )}
              </div>

              {/* No Topics Yet */}
              {!discoveredTopics && !discoveryLoading && (
                <div style={{ textAlign: 'center', padding: '3rem', background: '#f8fafc', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
                  <p style={{ fontSize: '1.2rem', marginBottom: '1rem' }}>🔮 No topics discovered yet</p>
                  <p style={{ color: '#64748b' }}>Click "Run Topic Discovery" to analyze all indexed documents and extract research topics.</p>
                </div>
              )}

              {/* Top Topics */}
              {discoveredTopics?.top_topics?.length > 0 && (
                <div style={{ marginBottom: '2rem' }}>
                  <h3 style={{ color: 'var(--isu-red)', marginBottom: '1rem' }}>🔥 Top Research Topics</h3>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                    {discoveredTopics.top_topics.slice(0, 20).map((topic, idx) => (
                      <button
                        key={idx}
                        className="suggestion-chip cross"
                        onClick={() => { setQuery(topic.name); setActiveTab('search'); }}
                        style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                      >
                        {topic.name}
                        <span style={{ background: 'rgba(0,0,0,0.15)', padding: '0.1rem 0.4rem', borderRadius: '10px', fontSize: '0.75rem' }}>
                          {topic.count}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Topic Categories */}
              {discoveredTopics?.categories?.length > 0 && (
                <div>
                  <h3 style={{ color: 'var(--isu-red)', marginBottom: '1rem' }}>📂 Topics by Category</h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    {discoveredTopics.categories.map((category, idx) => (
                      <div key={idx} style={{ background: 'white', border: '1px solid #e2e8f0', borderRadius: '8px', overflow: 'hidden' }}>
                        <div
                          onClick={() => toggleCategory(category.name)}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            padding: '1rem',
                            background: '#f8fafc',
                            cursor: 'pointer',
                            borderBottom: expandedCategories.has(category.name) ? '1px solid #e2e8f0' : 'none'
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            <span style={{ fontSize: '1.1rem' }}>{expandedCategories.has(category.name) ? '▼' : '▶'}</span>
                            <strong>{category.name}</strong>
                            <span style={{ color: '#64748b', fontSize: '0.9rem' }}>({category.topics.length} topics)</span>
                          </div>
                          <span style={{ background: 'var(--isu-red)', color: 'white', padding: '0.25rem 0.75rem', borderRadius: '12px', fontSize: '0.85rem' }}>
                            {category.total_docs} docs
                          </span>
                        </div>

                        {expandedCategories.has(category.name) && (
                          <div style={{ padding: '1rem', display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                            {category.topics.slice(0, 30).map((topic, tidx) => (
                              <button
                                key={tidx}
                                className="suggestion-chip regular"
                                onClick={() => { setQuery(topic.name); setActiveTab('search'); }}
                              >
                                {topic.name} ({topic.count})
                              </button>
                            ))}
                            {category.topics.length > 30 && (
                              <span style={{ color: '#64748b', padding: '0.5rem', fontStyle: 'italic' }}>
                                +{category.topics.length - 30} more topics
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === 'admin' && (
            <div className="admin-page">
              <h1>⚙️ System Administration</h1>

              <div className="admin-tabs">
                <button className={`admin-tab-btn ${adminSubTab === 'config' ? 'active' : ''}`} onClick={() => setAdminSubTab('config')}>Configuration</button>
                <button className={`admin-tab-btn ${adminSubTab === 'groups' ? 'active' : ''}`} onClick={() => setAdminSubTab('groups')}>Group Manager</button>
                <button className={`admin-tab-btn ${adminSubTab === 'faculty' ? 'active' : ''}`} onClick={() => setAdminSubTab('faculty')}>Faculty Manager</button>
                <button className={`admin-tab-btn ${adminSubTab === 'docs' ? 'active' : ''}`} onClick={() => setAdminSubTab('docs')}>Document Manager</button>
                <button className={`admin-tab-btn ${adminSubTab === 'mismatches' ? 'active' : ''}`} onClick={() => setAdminSubTab('mismatches')}>
                  🚩 Mismatches {flaggedMismatches.filter(m => m.status === 'pending').length > 0 && <span className="badge">{flaggedMismatches.filter(m => m.status === 'pending').length}</span>}
                </button>
              </div>

              {/* === Configuration Tab === */}
              {adminSubTab === 'config' && (
                <>
                  <div className="admin-section">
                    <h2>📊 Database Statistics</h2>
                    <p>Current system data counts.</p>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
                      <div className="stat-card" style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                        <strong>Faculty Members</strong>
                        <div style={{ fontSize: '1.5rem', color: '#c8102e' }}>{stats?.faculty_count || 0}</div>
                      </div>
                      <div className="stat-card" style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                        <strong>Manual Documents</strong>
                        <div style={{ fontSize: '1.5rem', color: '#c8102e' }}>{stats?.manual_documents_count || 0}</div>
                      </div>
                      <div className="stat-card" style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                        <strong>Scraper Sources</strong>
                        <div style={{ fontSize: '1.5rem', color: '#c8102e' }}>{stats?.scraper_sources_count || 0}</div>
                      </div>
                      <div className="stat-card" style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                        <strong>DSpace Collections</strong>
                        <div style={{ fontSize: '1.5rem', color: '#c8102e' }}>{stats?.dspace_collections_count || 0}</div>
                      </div>
                    </div>

                    <h3>🔧 Maintenance</h3>
                    <div style={{ marginTop: '1rem' }}>
                      <button className="btn-secondary" onClick={handleReseed} style={{ borderColor: '#c8102e', color: '#c8102e' }}>
                        ⚠️ Reset / Reseed Faculty Data
                      </button>
                      <p style={{ fontSize: '0.85rem', color: '#64748b', marginTop: '0.5rem' }}>
                        If the Faculty list is empty, click this button to re-populate it from the verified source file.
                      </p>
                    </div>
                  </div>

                  <div className="admin-section">
                    <h2>🕸️ Faculty Scraper Sources</h2>
                    <p>Manage URLs for the faculty web scraper. The scraper extracts faculty profiles, photos, and research interests.</p>
                    <form onSubmit={handleAddScraperUrl} className="admin-form">
                      <input type="text" placeholder="Department Name" value={newScraperUrl.department} onChange={e => setNewScraperUrl({ ...newScraperUrl, department: e.target.value })} required />
                      <input type="url" placeholder="URL" value={newScraperUrl.url} onChange={e => setNewScraperUrl({ ...newScraperUrl, url: e.target.value })} required />
                      <button type="submit">Add Source</button>
                    </form>
                    <div className="admin-list">
                      {scraperUrls.map(item => (
                        <div key={item.id} className="admin-list-item">
                          <div className="admin-item-info"><strong>{item.department}</strong><a href={item.url} target="_blank">{item.url}</a></div>
                          <button onClick={() => handleDeleteScraperUrl(item.id)} className="delete-btn">Delete</button>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="admin-section">
                    <h2>📚 DSpace Collections</h2>
                    <p>Manage DSpace collections/communities to index for search results.</p>
                    <form onSubmit={handleAddDSpaceUrl} className="admin-form">
                      <input type="text" placeholder="Collection Name" value={newDSpaceUrl.name} onChange={e => setNewDSpaceUrl({ ...newDSpaceUrl, name: e.target.value })} required />
                      <input type="url" placeholder="URL" value={newDSpaceUrl.url} onChange={e => setNewDSpaceUrl({ ...newDSpaceUrl, url: e.target.value })} required />
                      <button type="submit">Add Collection</button>
                    </form>
                    <div className="admin-list">
                      {dspaceUrls.map(item => (
                        <div key={item.id} className="admin-list-item">
                          <div className="admin-item-info"><strong>{item.name}</strong><a href={item.url} target="_blank">{item.url}</a></div>
                          <button onClick={() => handleDeleteDSpaceUrl(item.id)} className="delete-btn">Delete</button>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              )}

              {/* === Group Manager Tab === */}
              {adminSubTab === 'groups' && (
                <div className="admin-section full-width">
                  <div className="modal-header">
                    <h2>🏷️ Faculty Group Management</h2>
                    <span style={{ color: '#64748b' }}>Manage department groups. Rename or merge groups to organize faculty.</span>
                  </div>

                  <div className="data-table-container">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Department / Group</th>
                          <th>Faculty Count</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {groups.sort((a, b) => a.name.localeCompare(b.name)).map(g => (
                          <tr key={g.name}>
                            <td>{g.name}</td>
                            <td>{g.count}</td>
                            <td className="actions-cell">
                              <button className="edit-btn" onClick={() => setRenameModal({ oldName: g.name, newName: g.name })}>Rename</button>
                              <button className="btn-secondary" onClick={() => setMergeModal({ sourceGroup: g.name, targetGroup: '' })}>Merge Into...</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Rename Modal */}
                  {renameModal && (
                    <div className="modal-overlay" onClick={() => setRenameModal(null)}>
                      <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <div className="modal-header"><h3>Rename Group</h3></div>
                        <div className="form-group">
                          <label>Current Name: <strong>{renameModal.oldName}</strong></label>
                        </div>
                        <div className="form-group">
                          <label>New Name</label>
                          <input
                            type="text"
                            value={renameModal.newName}
                            onChange={e => setRenameModal({ ...renameModal, newName: e.target.value })}
                            autoFocus
                          />
                        </div>
                        <div className="form-actions">
                          <button className="btn-secondary" onClick={() => setRenameModal(null)}>Cancel</button>
                          <button className="btn-primary" onClick={() => handleRenameGroup(renameModal.oldName, renameModal.newName)}>Rename</button>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Merge Modal */}
                  {mergeModal && (
                    <div className="modal-overlay" onClick={() => setMergeModal(null)}>
                      <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <div className="modal-header"><h3>Merge Group</h3></div>
                        <div className="form-group">
                          <label>Source Group (will be removed): <strong>{mergeModal.sourceGroup}</strong></label>
                        </div>
                        <div className="form-group">
                          <label>Target Group (faculty will move here)</label>
                          <select
                            value={mergeModal.targetGroup}
                            onChange={e => setMergeModal({ ...mergeModal, targetGroup: e.target.value })}
                          >
                            <option value="">-- Select Target Group --</option>
                            {groups.filter(g => g.name !== mergeModal.sourceGroup).map(g => (
                              <option key={g.name} value={g.name}>{g.name} ({g.count} faculty)</option>
                            ))}
                          </select>
                        </div>
                        <div className="form-actions">
                          <button className="btn-secondary" onClick={() => setMergeModal(null)}>Cancel</button>
                          <button className="btn-primary" onClick={() => handleMergeGroups(mergeModal.sourceGroup, mergeModal.targetGroup)}>Merge</button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* === Faculty Manager Tab === */}
              {adminSubTab === 'faculty' && (
                <div className="admin-section full-width">
                  <div className="modal-header">
                    <h2>👥 Faculty Management</h2>
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                      <select value={facultyViewMode} onChange={e => setFacultyViewMode(e.target.value)} style={{ padding: '0.5rem' }}>
                        <option value="table">📋 Table View</option>
                        <option value="grouped">🗂️ Grouped View (Drag & Drop)</option>
                      </select>
                      <button className="btn-primary" onClick={() => handleEditFaculty(null)}>+ Add Faculty</button>
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', marginBottom: '1rem' }}>
                    <input type="text" placeholder="Filter faculty..." className="search-input" style={{ flex: 1 }} value={facultySearch} onChange={e => setFacultySearch(e.target.value)} />
                    {selectedForMerge.length > 1 && (
                      <button className="btn-primary" onClick={handleMergeFacultyRecords} style={{ background: '#f59e0b' }}>
                        🔗 Merge Selected ({selectedForMerge.length})
                      </button>
                    )}
                  </div>

                  {/* Duplicate Suggestions Panel */}
                  {(() => {
                    const filteredDuplicates = duplicateSuggestions.filter(dup => {
                      const pairKey = [dup.faculty1.id, dup.faculty2.id].sort().join('|')
                      return !ignoredDuplicates.has(pairKey)
                    })

                    if (filteredDuplicates.length === 0) return null

                    return (
                      <div className="duplicate-suggestions-panel">
                        <div className="suggestions-header">
                          <h3>⚠️ Potential Duplicates Detected ({filteredDuplicates.length})</h3>
                          <span style={{ color: '#64748b', fontSize: '0.9rem' }}>Review and merge or ignore these suggestions</span>
                        </div>
                        <div className="suggestions-list">
                          {filteredDuplicates.slice(0, 10).map((dup, idx) => (
                            <div key={idx} className="suggestion-card">
                              <div className="suggestion-pair">
                                <div className="suggestion-faculty">
                                  <strong>{dup.faculty1.name}</strong>
                                  <span className="suggestion-meta">{dup.faculty1.department}</span>
                                  <span className="suggestion-rank">{dup.faculty1.rank}</span>
                                </div>
                                <div className="suggestion-arrow">↔️</div>
                                <div className="suggestion-faculty">
                                  <strong>{dup.faculty2.name}</strong>
                                  <span className="suggestion-meta">{dup.faculty2.department}</span>
                                  <span className="suggestion-rank">{dup.faculty2.rank}</span>
                                </div>
                              </div>
                              <div className="suggestion-reason">{dup.reason}</div>
                              <div className="suggestion-actions">
                                <button className="btn-primary" onClick={() => handleAcceptDuplicate(dup)} style={{ background: '#22c55e' }}>
                                  ✓ Merge
                                </button>
                                <button className="btn-secondary" onClick={() => handleIgnoreDuplicate(dup)}>
                                  ✕ Ignore
                                </button>
                              </div>
                            </div>
                          ))}
                          {filteredDuplicates.length > 10 && (
                            <div style={{ textAlign: 'center', padding: '0.5rem', color: '#64748b' }}>
                              + {filteredDuplicates.length - 10} more suggestions...
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  })()}

                  {facultyViewMode === 'table' ? (
                    <div className="data-table-container">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th style={{ width: '40px' }}><input type="checkbox" disabled title="Select all (per department in grouped view)" /></th>
                            <th>Name</th>
                            <th>Rank</th>
                            <th>Department</th>
                            <th>Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {adminFaculty.filter(f => f.name.toLowerCase().includes(facultySearch.toLowerCase())).map(f => (
                            <tr key={f.id}>
                              <td>
                                <input
                                  type="checkbox"
                                  checked={selectedForMerge.includes(f.id)}
                                  onChange={e => {
                                    if (e.target.checked) setSelectedForMerge([...selectedForMerge, f.id])
                                    else setSelectedForMerge(selectedForMerge.filter(id => id !== f.id))
                                  }}
                                />
                              </td>
                              <td>{f.name}</td>
                              <td>{f.rank || f.title}</td>
                              <td>{f.department}</td>
                              <td className="actions-cell">
                                <button className="edit-btn" onClick={() => handleEditFaculty(f)}>Edit</button>
                                <button className="delete-btn" onClick={() => handleDeleteFaculty(f.id)}>Delete</button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="faculty-dnd-container">
                      {(() => {
                        // Group faculty by department
                        const filteredFaculty = adminFaculty.filter(f => f.name.toLowerCase().includes(facultySearch.toLowerCase()))
                        const grouped = {}
                        filteredFaculty.forEach(f => {
                          const dept = f.department || 'Other'
                          if (!grouped[dept]) grouped[dept] = []
                          grouped[dept].push(f)
                        })

                        return Object.entries(grouped).sort().map(([dept, members]) => (
                          <div
                            key={dept}
                            className={`dnd-group ${dragOverGroup === dept ? 'drag-over' : ''}`}
                            onDragOver={e => { e.preventDefault(); setDragOverGroup(dept) }}
                            onDragLeave={() => setDragOverGroup(null)}
                            onDrop={() => { if (draggingFaculty) handleDropFacultyOnGroup(draggingFaculty, dept) }}
                          >
                            <h4 className="dnd-group-header">{dept} ({members.length})</h4>
                            <div className="dnd-cards">
                              {members.map(f => (
                                <div
                                  key={f.id}
                                  className={`dnd-card ${draggingFaculty === f.id ? 'dragging' : ''}`}
                                  draggable
                                  onDragStart={() => setDraggingFaculty(f.id)}
                                  onDragEnd={() => { setDraggingFaculty(null); setDragOverGroup(null) }}
                                >
                                  <input
                                    type="checkbox"
                                    checked={selectedForMerge.includes(f.id)}
                                    onChange={e => {
                                      e.stopPropagation()
                                      if (e.target.checked) setSelectedForMerge([...selectedForMerge, f.id])
                                      else setSelectedForMerge(selectedForMerge.filter(id => id !== f.id))
                                    }}
                                    className="dnd-checkbox"
                                  />
                                  <div className="dnd-info">
                                    <div className="dnd-name">{f.name}</div>
                                    <div className="dnd-dept">{f.department}</div>
                                    <div className="dnd-rank">{f.rank || f.title}</div>
                                  </div>
                                  <div className="dnd-actions">
                                    <button onClick={() => handleEditFaculty(f)}>✏️</button>
                                    <button onClick={() => handleDeleteFaculty(f.id)}>🗑️</button>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        ))
                      })()}
                    </div>
                  )}


                  {/* Edit Faculty Modal */}
                  {editingFaculty && (
                    <div className="modal-overlay">
                      <div className="modal-content">
                        <div className="modal-header">
                          <h3>{editingFaculty.name ? 'Edit Faculty' : 'New Faculty'}</h3>
                          <button className="modal-close" onClick={() => setEditingFaculty(null)}>×</button>
                        </div>

                        <div className="mode-toggle">
                          <label><input type="radio" name="mode" checked={editMode === 'simple'} onChange={() => setEditMode('simple')} /> Simple Mode</label>
                          <label><input type="radio" name="mode" checked={editMode === 'advanced'} onChange={() => setEditMode('advanced')} /> Advanced (JSON)</label>
                        </div>

                        <form onSubmit={handleSaveFaculty}>
                          {editMode === 'simple' ? (
                            <>
                              <div className="form-group">
                                <label>Name</label>
                                <input type="text" value={editingFaculty.name} onChange={e => setEditingFaculty({ ...editingFaculty, name: e.target.value })} required />
                              </div>
                              <div className="form-group">
                                <label>Rank</label>
                                <input type="text" value={editingFaculty.rank || ''} onChange={e => setEditingFaculty({ ...editingFaculty, rank: e.target.value })} />
                              </div>
                              <div className="form-group">
                                <label>Department</label>
                                <input type="text" value={editingFaculty.department || ''} onChange={e => setEditingFaculty({ ...editingFaculty, department: e.target.value })} />
                              </div>
                              <div className="form-group">
                                <label>Research Interests (comma separated)</label>
                                <textarea value={Array.isArray(editingFaculty.research_interests) ? editingFaculty.research_interests.join(', ') : editingFaculty.research_interests} onChange={e => setEditingFaculty({ ...editingFaculty, research_interests: e.target.value })} />
                              </div>
                            </>
                          ) : (
                            <div className="form-group">
                              <label>JSON Data</label>
                              <textarea className="json-editor" value={jsonContent} onChange={e => setJsonContent(e.target.value)} />
                            </div>
                          )}
                          <div className="form-actions">
                            <button type="button" className="btn-secondary" onClick={() => setEditingFaculty(null)}>Cancel</button>
                            <button type="submit" className="btn-primary">Save Changes</button>
                          </div>
                        </form>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* === Document Manager Tab === */}
              {adminSubTab === 'docs' && (
                <div className="admin-section full-width">
                  {/* Header with View Modes and Actions */}
                  <div className="modal-header">
                    <h2>📄 Document Manager</h2>
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                      <select value={docViewMode} onChange={e => setDocViewMode(e.target.value)} style={{ padding: '0.5rem' }}>
                        <option value="cards">📋 Card View</option>
                        <option value="table">📊 Table View</option>
                        <option value="reports">📈 Reports & Analytics</option>
                      </select>
                      <button className="btn-secondary" onClick={() => handleExportDocs('csv')}>📥 CSV</button>
                      <button className="btn-secondary" onClick={() => handleExportDocs('json')}>📥 JSON</button>
                      <button className="btn-secondary" onClick={handleIndexNow} disabled={indexingStatus}>🔄 Index Now</button>
                      <button className="btn-primary" onClick={() => handleEditDoc(null)}>+ Add Document</button>
                    </div>
                  </div>

                  {/* Indexing Status */}
                  {indexingStatus && (
                    <div style={{ padding: '0.75rem', background: '#fef3c7', borderRadius: '8px', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      {indexingStatus.startsWith('Indexing') && <span className="loading-spinner">⏳</span>}
                      {indexingStatus}
                    </div>
                  )}

                  {/* Filter Bar */}
                  {docViewMode !== 'reports' && (
                    <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
                      <input
                        type="text"
                        placeholder="Search documents..."
                        className="search-input"
                        style={{ flex: 1, minWidth: '200px' }}
                        value={docFilter.search}
                        onChange={e => setDocFilter({ ...docFilter, search: e.target.value })}
                      />
                      <select
                        value={docFilter.type}
                        onChange={e => setDocFilter({ ...docFilter, type: e.target.value })}
                        style={{ padding: '0.5rem' }}
                      >
                        <option value="">All Types</option>
                        {docStats && Object.keys(docStats.by_type).map(t => (
                          <option key={t} value={t}>{t} ({docStats.by_type[t]})</option>
                        ))}
                      </select>
                      <select
                        value={docFilter.year}
                        onChange={e => setDocFilter({ ...docFilter, year: e.target.value })}
                        style={{ padding: '0.5rem' }}
                      >
                        <option value="">All Years</option>
                        {docStats && Object.keys(docStats.by_year).reverse().map(y => (
                          <option key={y} value={y}>{y} ({docStats.by_year[y]})</option>
                        ))}
                      </select>
                    </div>
                  )}

                  {/* Summary Stats */}
                  <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
                    <div className="stat-badge">📚 {allDocuments.length} Total Documents</div>
                    <div className="stat-badge">✋ {docStats?.by_source?.manual || 0} Manual</div>
                    <div className="stat-badge">🗃️ {docStats?.by_source?.dspace || 0} DSpace</div>
                  </div>

                  {/* Card View */}
                  {docViewMode === 'cards' && (
                    <div className="doc-cards-container">
                      {allDocuments
                        .filter(d => {
                          const search = docFilter.search.toLowerCase()
                          const matchesSearch = !search || d.title?.toLowerCase().includes(search) ||
                            (d.authors || []).join(' ').toLowerCase().includes(search)
                          const matchesType = !docFilter.type || d.type === docFilter.type
                          const matchesYear = !docFilter.year || (d.date || '').startsWith(docFilter.year)
                          return matchesSearch && matchesType && matchesYear
                        })
                        .slice(0, 50)
                        .map(d => (
                          <div key={d.id || d.uuid} className="doc-card">
                            <div className="doc-card-header" onClick={() => {
                              const id = d.id || d.uuid
                              setExpandedDocs(prev => {
                                const next = new Set(prev)
                                next.has(id) ? next.delete(id) : next.add(id)
                                return next
                              })
                            }}>
                              <span className="doc-expand">{expandedDocs.has(d.id || d.uuid) ? '▼' : '▶'}</span>
                              <div className="doc-card-title">
                                <strong>{d.title}</strong>
                                <div className="doc-meta">
                                  <span className={`source-badge ${d.source}`}>{d.source_name || d.source}</span>
                                  <span>{d.date}</span>
                                  <span>{d.type}</span>
                                </div>
                              </div>
                            </div>
                            {expandedDocs.has(d.id || d.uuid) && (
                              <div className="doc-card-body">
                                <p><strong>Authors:</strong> {(d.authors || []).join(', ') || 'Unknown'}</p>
                                {d.abstract && <p><strong>Abstract:</strong> {d.abstract.substring(0, 300)}...</p>}
                                {d.subjects?.length > 0 && <p><strong>Subjects:</strong> {d.subjects.join(', ')}</p>}
                                {d.url && <a href={d.url} target="_blank" rel="noopener noreferrer" className="profile-link">🔗 View Document</a>}
                              </div>
                            )}
                          </div>
                        ))}
                      {allDocuments.length === 0 && <p style={{ color: '#888' }}>No documents found. Add manual documents or check DSpace connection.</p>}
                    </div>
                  )}

                  {/* Table View */}
                  {docViewMode === 'table' && (
                    <div className="data-table-container">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Title</th>
                            <th>Authors</th>
                            <th>Date</th>
                            <th>Type</th>
                            <th>Source</th>
                            <th>Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {allDocuments
                            .filter(d => {
                              const search = docFilter.search.toLowerCase()
                              const matchesSearch = !search || d.title?.toLowerCase().includes(search)
                              const matchesType = !docFilter.type || d.type === docFilter.type
                              const matchesYear = !docFilter.year || (d.date || '').startsWith(docFilter.year)
                              return matchesSearch && matchesType && matchesYear
                            })
                            .slice(0, 100)
                            .map(d => (
                              <tr key={d.id || d.uuid}>
                                <td style={{ maxWidth: '300px' }}>{d.title}</td>
                                <td>{(d.authors || []).slice(0, 2).join(', ')}{d.authors?.length > 2 ? '...' : ''}</td>
                                <td>{d.date}</td>
                                <td>{d.type}</td>
                                <td><span className={`source-badge ${d.source}`}>{d.source}</span></td>
                                <td>
                                  {d.url && <a href={d.url} target="_blank" rel="noopener noreferrer">View</a>}
                                  {d.source === 'manual' && (
                                    <>
                                      <button className="edit-btn" onClick={() => handleEditDoc(d)}>Edit</button>
                                      <button className="delete-btn" onClick={() => handleDeleteDoc(d.id)}>Delete</button>
                                    </>
                                  )}
                                </td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Reports View */}
                  {docViewMode === 'reports' && docStats && (
                    <div className="reports-dashboard">
                      <div className="charts-grid">
                        {/* By Type Chart */}
                        <div className="chart-card">
                          <h3>📊 Documents by Type</h3>
                          <div className="bar-chart">
                            {Object.entries(docStats.by_type).slice(0, 8).map(([type, count]) => (
                              <div key={type} className="bar-row">
                                <span className="bar-label">{type}</span>
                                <div className="bar-container">
                                  <div className="bar" style={{ width: `${Math.min(100, (count / Math.max(...Object.values(docStats.by_type))) * 100)}%` }}></div>
                                  <span className="bar-value">{count}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>

                        {/* By Year Chart */}
                        <div className="chart-card">
                          <h3>📅 Documents by Year</h3>
                          <div className="bar-chart">
                            {Object.entries(docStats.by_year).slice(-10).map(([year, count]) => (
                              <div key={year} className="bar-row">
                                <span className="bar-label">{year}</span>
                                <div className="bar-container">
                                  <div className="bar year-bar" style={{ width: `${Math.min(100, (count / Math.max(...Object.values(docStats.by_year))) * 100)}%` }}></div>
                                  <span className="bar-value">{count}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>

                        {/* Top Authors */}
                        <div className="chart-card">
                          <h3>👤 Top Authors</h3>
                          <div className="bar-chart">
                            {Object.entries(docStats.top_authors).slice(0, 10).map(([author, count]) => (
                              <div key={author} className="bar-row">
                                <span className="bar-label" title={author}>{author.length > 25 ? author.substring(0, 22) + '...' : author}</span>
                                <div className="bar-container">
                                  <div className="bar author-bar" style={{ width: `${Math.min(100, (count / Math.max(...Object.values(docStats.top_authors))) * 100)}%` }}></div>
                                  <span className="bar-value">{count}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>

                        {/* Top Subjects */}
                        <div className="chart-card">
                          <h3>🏷️ Top Subjects</h3>
                          <div className="keyword-cloud">
                            {Object.entries(docStats.top_subjects).slice(0, 20).map(([subject, count]) => (
                              <span key={subject} className="keyword-tag" style={{
                                fontSize: `${Math.max(0.75, Math.min(1.5, 0.75 + (count / Math.max(...Object.values(docStats.top_subjects))) * 0.75))}rem`,
                                opacity: 0.5 + (count / Math.max(...Object.values(docStats.top_subjects))) * 0.5
                              }}>
                                {subject} ({count})
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Edit Doc Modal */}
                  {editingDoc && (
                    <div className="modal-overlay">
                      <div className="modal-content">
                        <div className="modal-header">
                          <h3>{editingDoc.id ? 'Edit Document' : 'New Document'}</h3>
                          <button className="modal-close" onClick={() => setEditingDoc(null)}>×</button>
                        </div>
                        <form onSubmit={handleSaveDoc}>
                          <div className="form-group">
                            <label>Title</label>
                            <input type="text" value={editingDoc.title} onChange={e => setEditingDoc({ ...editingDoc, title: e.target.value })} required />
                          </div>
                          <div className="form-group">
                            <label>Authors (comma separated)</label>
                            <input type="text" value={Array.isArray(editingDoc.authors) ? editingDoc.authors.join(', ') : editingDoc.authors} onChange={e => setEditingDoc({ ...editingDoc, authors: e.target.value })} required />
                          </div>
                          <div className="form-group">
                            <label>Type</label>
                            <input type="text" value={editingDoc.type || ''} onChange={e => setEditingDoc({ ...editingDoc, type: e.target.value })} placeholder="e.g., Thesis, Article, Report" />
                          </div>
                          <div className="form-group">
                            <label>Publication Date</label>
                            <input type="text" value={editingDoc.date} onChange={e => setEditingDoc({ ...editingDoc, date: e.target.value })} />
                          </div>
                          <div className="form-group">
                            <label>Abstract</label>
                            <textarea value={editingDoc.abstract} onChange={e => setEditingDoc({ ...editingDoc, abstract: e.target.value })} />
                          </div>
                          <div className="form-group">
                            <label>Subjects (comma separated)</label>
                            <input type="text" value={Array.isArray(editingDoc.subjects) ? editingDoc.subjects.join(', ') : (editingDoc.subjects || '')} onChange={e => setEditingDoc({ ...editingDoc, subjects: e.target.value.split(',').map(s => s.trim()) })} />
                          </div>
                          <div className="form-group">
                            <label>URL</label>
                            <input type="url" value={editingDoc.url} onChange={e => setEditingDoc({ ...editingDoc, url: e.target.value })} />
                          </div>
                          <div className="form-actions">
                            <button type="button" className="btn-secondary" onClick={() => setEditingDoc(null)}>Cancel</button>
                            <button type="submit" className="btn-primary">Save Document</button>
                          </div>
                        </form>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* === Mismatches Review Tab === */}
              {adminSubTab === 'mismatches' && (
                <div className="admin-section full-width">
                  <div className="modal-header">
                    <h2>🚩 Faculty Mismatch Review</h2>
                    <span style={{ color: '#666' }}>{flaggedMismatches.filter(m => m.status === 'pending').length} pending</span>
                  </div>

                  {flaggedMismatches.length === 0 ? (
                    <p style={{ color: '#888', textAlign: 'center', padding: '2rem' }}>No mismatches flagged. Users can flag incorrect faculty matches on search results using the 🚩 button.</p>
                  ) : (
                    <div className="mismatch-list">
                      {flaggedMismatches.map(m => (
                        <div key={m.id} className={`mismatch-card ${m.status}`}>
                          <div className="mismatch-header">
                            <h4>
                              <a
                                href={`https://dr.lib.iastate.edu/items/${m.document_id}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="mismatch-title-link"
                              >
                                {m.document_title?.substring(0, 80)}...
                              </a>
                            </h4>
                            <span className={`status-badge ${m.status}`}>{m.status}</span>
                          </div>
                          <div className="mismatch-details">
                            <p><strong>Author in doc:</strong> {m.author_name_in_doc}</p>
                            <p><strong>Matched as:</strong> <span style={{ color: '#ef4444' }}>{m.matched_faculty_name}</span></p>
                            <p><strong>Flagged:</strong> {new Date(m.created_at).toLocaleDateString()}</p>
                            {/* Authors/Advisors Metadata */}
                            <div className="mismatch-metadata" style={{ marginTop: '0.75rem', background: 'linear-gradient(90deg, #fef3c7 0%, #fff7ed 100%)', borderRadius: '6px', padding: '0.5rem 0.75rem' }}>
                              <p style={{ margin: '0.25rem 0', fontSize: '0.85rem' }}>
                                <strong>👤 Authors:</strong> {m.document_authors?.length > 0 ? m.document_authors.join(', ') : <em style={{ color: '#9ca3af' }}>Not available</em>}
                              </p>
                              <p style={{ margin: '0.25rem 0', fontSize: '0.85rem' }}>
                                <strong>🎓 Advisors:</strong> {m.document_advisors?.length > 0 ? m.document_advisors.join(', ') : <em style={{ color: '#9ca3af' }}>Not available</em>}
                              </p>
                            </div>
                          </div>
                          {m.status === 'pending' && (
                            <div className="mismatch-actions">
                              <div className="faculty-search-picker">
                                <input
                                  type="text"
                                  placeholder="🔍 Search faculty by name..."
                                  className="faculty-search-input"
                                  value={mismatchFacultySearch[m.id] || ''}
                                  onChange={(e) => {
                                    setMismatchFacultySearch({ ...mismatchFacultySearch, [m.id]: e.target.value })
                                    setMismatchDropdownOpen({ ...mismatchDropdownOpen, [m.id]: true })
                                  }}
                                  onFocus={() => setMismatchDropdownOpen({ ...mismatchDropdownOpen, [m.id]: true })}
                                />
                                {mismatchDropdownOpen[m.id] && (
                                  <div className="faculty-search-results">
                                    {adminFaculty
                                      .filter(f => {
                                        const search = (mismatchFacultySearch[m.id] || '').toLowerCase()
                                        return !search || f.name.toLowerCase().includes(search)
                                      })
                                      .slice(0, 10)
                                      .map(f => (
                                        <div
                                          key={f.id}
                                          className="faculty-search-item"
                                          onClick={async () => {
                                            await fetch(`${API_URL}/api/admin/mismatches/resolve`, {
                                              method: 'POST',
                                              headers: { 'Content-Type': 'application/json' },
                                              body: JSON.stringify({
                                                mismatch_id: m.id,
                                                action: 'correct',
                                                correct_faculty_id: f.id
                                              })
                                            })
                                            setMismatchDropdownOpen({ ...mismatchDropdownOpen, [m.id]: false })
                                            setMismatchFacultySearch({ ...mismatchFacultySearch, [m.id]: '' })
                                            showToast(`✅ Assigned to ${f.name}`, 'success')
                                            fetchAdminData()
                                          }}
                                        >
                                          <img
                                            src={f.photo_url || `https://ui-avatars.com/api/?name=${f.name}&background=random`}
                                            alt={f.name}
                                            className="faculty-search-photo"
                                          />
                                          <div>
                                            <strong>{f.name}</strong>
                                            <span>{f.department || 'Faculty'}</span>
                                          </div>
                                        </div>
                                      ))}
                                    {adminFaculty.filter(f => {
                                      const search = (mismatchFacultySearch[m.id] || '').toLowerCase()
                                      return !search || f.name.toLowerCase().includes(search)
                                    }).length === 0 && (
                                        <div className="faculty-search-empty">No matching faculty found</div>
                                      )}
                                  </div>
                                )}
                              </div>
                              <button
                                className="btn-secondary"
                                onClick={async () => {
                                  await fetch(`${API_URL}/api/admin/mismatches/resolve`, {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ mismatch_id: m.id, action: 'ignore' })
                                  })
                                  fetchAdminData()
                                }}
                              >Ignore</button>
                              <button
                                className="delete-btn"
                                onClick={async () => {
                                  await fetch(`${API_URL}/api/admin/mismatches/${m.id}`, { method: 'DELETE' })
                                  fetchAdminData()
                                }}
                              >Delete</button>
                            </div>
                          )}
                          {m.status === 'resolved' && (
                            <p style={{ color: '#16a34a', fontSize: '0.85rem' }}>✅ Resolved: {m.resolution_action}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

            </div>
          )}

          {activeTab === 'topics' && (
            <div className="topics-page">
              <h2>🗺️ Research Topics</h2>
              <div className="topics-grid">
                {['AI and Machine Learning', 'Software Engineering', 'Systems and Networking', 'Theory', 'Robotics', 'Security', 'Human-Computer Interaction', 'Bioinformatics'].map(topic => (
                  <div key={topic} className="topic-card" onClick={() => { setQuery(topic); setActiveTab('search'); }}>
                    <h3>{topic}</h3>
                    <p>{facultyData.filter(f => f.group === topic).length} faculty</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </main>

        {/* Dynamic People Sidebar - Only shows on Search tab */}
        {/* Dynamic People Sidebar - Only shows on Search tab */}
        {activeTab === 'search' && (
          <aside className="people-sidebar">
            <div className="sidebar-controls">
              <label>
                <input type="checkbox" checked={showPhotos} onChange={(e) => setShowPhotos(e.target.checked)} />
                Show photos
              </label>
            </div>

            {/* Section 1: Experts Found (from results) */}
            {results?.found_faculty?.length > 0 && (
              <div className="sidebar-section">
                <h3>🔍 Experts Found</h3>
                <div className="faculty-list">
                  {results.found_faculty.map(f => (
                    <div key={f.id} className="faculty-item" onClick={() => { setQuery(f.name) }}>
                      {showPhotos && (
                        <img src={f.photo_url} alt={f.name} className="faculty-photo"
                          onError={(e) => e.target.src = 'https://ui-avatars.com/api/?name=${f.name}&background=random'} />
                      )}
                      <div className="faculty-info">
                        <a href={f.profile_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>{f.name}</a>
                        <span className="faculty-rank">{f.rank}</span>
                        <span className="faculty-interests">
                          {f.research_interests.slice(0, 2).join(', ')}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Section 2: Related Experts (from semantic search) */}
            {results?.related_faculty?.length > 0 && (
              <div className="sidebar-section" style={{ marginTop: '1.5rem', borderTop: '1px solid #eee', paddingTop: '1rem' }}>
                <h3>💡 Related Experts</h3>
                <div className="faculty-list">
                  {results.related_faculty.map(f => (
                    <div key={f.id} className="faculty-item" onClick={() => { setQuery(f.name) }}>
                      {showPhotos && (
                        <img src={f.photo_url} alt={f.name} className="faculty-photo"
                          onError={(e) => e.target.src = 'https://ui-avatars.com/api/?name=${f.name}&background=random'} />
                      )}
                      <div className="faculty-info">
                        <a href={f.profile_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>{f.name}</a>
                        <span className="faculty-rank">{f.rank}</span>
                        <span className="faculty-interests">
                          {f.research_interests.slice(0, 2).join(', ')}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Empty State */}
            {(!results?.found_faculty?.length && !results?.related_faculty?.length) && (
              <div className="sidebar-empty">
                <p>🔍 Search for a topic to see related faculty experts</p>
                <p className="hint">Try: "machine learning", "robotics", "software testing"</p>
              </div>
            )}
          </aside>
        )}
      </div>

      <footer className="footer">
        <p>ISU Research Search • by Adisak Sukul</p>
        <p>Department of Computer Science, Iowa State University</p>
        <p style={{ fontSize: '0.8rem', marginTop: '0.5rem', opacity: 0.7, fontFamily: 'monospace' }}>
          Local Instance: D:\Dropbox\RAG-DSpace\AntiGravity Gemini 3 Pro\isu-research-search
        </p>
      </footer>
    </div>
  )
}

export default App
