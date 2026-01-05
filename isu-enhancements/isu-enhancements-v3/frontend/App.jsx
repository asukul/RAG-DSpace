import { useState, useEffect, useMemo } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Faculty data with verified courses
const FACULTY_DATA = [
  // Professors
  { id: "pavan-aduri", name: "Pavan Aduri", rank: "Professor", group: "Theory", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/aduri_pavan.jpg", profile_url: "https://www.cs.iastate.edu/people/pavan-aduri", research_interests: ["Computational Complexity", "Algorithm Design", "Randomness"], courses_taught: [], is_teaching_faculty: false },
  { id: "myra-cohen", name: "Myra Cohen", rank: "Professor", group: "Software Engineering", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/myra_cohen_0.jpg", profile_url: "https://www.cs.iastate.edu/people/myra-cohen", research_interests: ["Software Testing", "Combinatorial Testing", "Search-Based SE"], courses_taught: ["COMS 4170"], is_teaching_faculty: false },
  { id: "yan-bin-jia", name: "Yan-Bin Jia", rank: "Professor", group: "Robotics", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-12/jia2025.jpg", profile_url: "https://www.cs.iastate.edu/people/yan-bin-jia", research_interests: ["Robotics", "Motion Planning", "Manipulation", "Haptics"], courses_taught: ["COMS 4770"], is_teaching_faculty: false },
  { id: "wallapak-tavanapong", name: "Wallapak Tavanapong", rank: "Professor", group: "AI and Machine Learning", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/tavanapong_wallapak.jpg", profile_url: "https://www.cs.iastate.edu/people/wallapak-tavanapong", research_interests: ["Medical AI", "Deep Learning", "Computer Vision", "Colonoscopy"], courses_taught: [], is_teaching_faculty: false },
  { id: "sam-xin", name: "Chunsheng (Sam) Xin", rank: "Professor", group: "Systems and Networking", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-08/thumbnail_Xin_photo_HR.jpg", profile_url: "https://www.cs.iastate.edu/people/sam-xin", research_interests: ["Cybersecurity", "Machine Learning", "Network Security"], courses_taught: [], is_teaching_faculty: false },
  
  // Associate Professors
  { id: "ying-cai", name: "Ying Cai", rank: "Associate Professor", group: "Systems and Networking", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/cai.jpg", profile_url: "https://www.cs.iastate.edu/people/ying-cai", research_interests: ["Wireless Networks", "Mobile Computing", "Database"], courses_taught: ["COMS 3630"], is_teaching_faculty: false },
  { id: "soma-chaudhuri", name: "Soma Chaudhuri", rank: "Associate Professor", group: "Theory", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/chaudhuri_4.png", profile_url: "https://www.cs.iastate.edu/people/soma-chaudhuri", research_interests: ["Distributed Computing", "Fault Tolerance", "Algorithms"], courses_taught: ["COMS 2300"], is_teaching_faculty: false },
  { id: "ali-jannesari", name: "Ali Jannesari", rank: "Associate Professor", group: "Systems and Networking", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/ali_janessari1.jpg", profile_url: "https://www.cs.iastate.edu/people/ali-jannesari", research_interests: ["High Performance Computing", "ML Systems", "Parallel Computing"], courses_taught: ["COMS 3190"], is_teaching_faculty: false },
  { id: "wei-le", name: "Wei Le", rank: "Associate Professor", group: "Software Engineering", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-07/Capture%20One%20Catalog1631%202.jpg", profile_url: "https://www.cs.iastate.edu/people/wei-le", research_interests: ["Program Analysis", "Software Testing", "ML for Code"], courses_taught: [], is_teaching_faculty: false },
  { id: "qi-li", name: "Qi Li", rank: "Associate Professor", group: "Security", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-06/Qi%20Li%202023.jpg", profile_url: "https://www.cs.iastate.edu/people/qi-li", research_interests: ["Cybersecurity", "ML Security", "NLP Security"], courses_taught: [], is_teaching_faculty: false },
  { id: "nok-wongpiromsarn", name: "Tichakorn (Nok) Wongpiromsarn", rank: "Associate Professor", group: "Robotics", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/nok.jpeg", profile_url: "https://www.cs.iastate.edu/people/tichakorn-nok-wongpiromsarn", research_interests: ["Formal Methods", "Autonomous Systems", "Motion Planning"], courses_taught: ["COMS 3110"], is_teaching_faculty: false },
  { id: "wensheng-zhang", name: "Wensheng Zhang", rank: "Associate Professor", group: "Systems and Networking", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/zhang_wensheng.jpg", profile_url: "https://www.cs.iastate.edu/people/wensheng-zhang", research_interests: ["Network Security", "Video Analysis", "Operating Systems"], courses_taught: ["COMS 3520"], is_teaching_faculty: false },
  
  // Assistant Professors
  { id: "hongyang-gao", name: "Hongyang Gao", rank: "Assistant Professor", group: "AI and Machine Learning", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/img_1814_0.jpg", profile_url: "https://www.cs.iastate.edu/people/hongyang-gao", research_interests: ["Deep Learning", "Graph Neural Networks", "Neural ODEs"], courses_taught: ["COMS 4740"], is_teaching_faculty: false },
  { id: "mengdi-huai", name: "Mengdi Huai", rank: "Assistant Professor", group: "AI and Machine Learning", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/mengdi_img.jpg", profile_url: "https://www.cs.iastate.edu/people/mengdi-huai", research_interests: ["Trustworthy AI", "Fairness in ML", "Privacy-Preserving ML"], courses_taught: ["COMS 5730"], is_teaching_faculty: false },
  { id: "regis-kopper", name: "Regis Kopper", rank: "Assistant Professor", group: "Human-Computer Interaction", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-09/cs_faculty_23.jpg", profile_url: "https://www.cs.iastate.edu/people/regis-kopper", research_interests: ["Virtual Reality", "Augmented Reality", "3D Interaction"], courses_taught: ["COMS 4740"], is_teaching_faculty: false },
  { id: "liyi-li", name: "Liyi Li", rank: "Assistant Professor", group: "Software Engineering", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/liyi.jpg", profile_url: "https://www.cs.iastate.edu/people/liyi-li", research_interests: ["Programming Languages", "Type Systems", "Formal Methods"], courses_taught: ["COMS 3420"], is_teaching_faculty: false },
  { id: "bowen-weng", name: "Bowen Weng", rank: "Assistant Professor", group: "Robotics", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/bowenw_0.jpeg", profile_url: "https://www.cs.iastate.edu/people/bowen-weng", research_interests: ["Reinforcement Learning", "Autonomous Vehicles", "Legged Robots"], courses_taught: ["COMS 4720"], is_teaching_faculty: false },
  { id: "lin-yan", name: "Lin Yan", rank: "Assistant Professor", group: "AI and Machine Learning", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/lin.jpg", profile_url: "https://www.cs.iastate.edu/people/lin-yan", research_interests: ["Data Visualization", "Visual Analytics", "Topological Data Analysis"], courses_taught: [], is_teaching_faculty: false },
  
  // Teaching Faculty
  { id: "georgi-batinov", name: "Georgi Batinov", rank: "Assistant Teaching Professor", group: "Teaching", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/uncropped.jpg", profile_url: "https://www.cs.iastate.edu/people/georgi-batinov", research_interests: ["CS Education", "HCI", "User Experience"], courses_taught: ["COMS 2280", "COMS 3260", "COMS 3620", "COMS 3630"], is_teaching_faculty: true },
  { id: "matthew-holman", name: "Matthew Holman", rank: "Assistant Teaching Professor", group: "Teaching", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/profilepicture2.jpg", profile_url: "https://www.cs.iastate.edu/people/matthew-holman", research_interests: ["CS Education", "Introductory Programming"], courses_taught: ["COMS 1270", "COMS 2270"], is_teaching_faculty: true },
  { id: "ashwin-joshy", name: "Ashwin Kallingal Joshy", rank: "Assistant Teaching Professor", group: "Teaching", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/2025-09/cs_faculty_18.jpg", profile_url: "https://www.cs.iastate.edu/people/ashwin-kallingal-joshy", research_interests: ["CS Education", "Data Structures"], courses_taught: ["COMS 2280", "COMS 2300"], is_teaching_faculty: true },
  { id: "ambrose-laing", name: "Ambrose Kofi Laing", rank: "Associate Teaching Professor", group: "Teaching", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/laingportrait2a.jpg", profile_url: "https://www.cs.iastate.edu/people/ambrose-kofi-laing", research_interests: ["CS Education", "Programming Pedagogy"], courses_taught: ["COMS 1130", "COMS 2270"], is_teaching_faculty: true },
  { id: "simanta-mitra", name: "Simanta Mitra", rank: "Teaching Professor", group: "Teaching", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/dsc_0069.jpg", profile_url: "https://www.cs.iastate.edu/people/simanta-mitra", research_interests: ["CS Education", "Software Engineering", "Agile"], courses_taught: ["COMS 3090", "COMS 4020"], is_teaching_faculty: true },
  { id: "trent-muhr", name: "Trent Muhr", rank: "Lecturer", group: "Teaching", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/screenshot_2024-08-15_at_4.10.02_pm.jpg", profile_url: "https://www.cs.iastate.edu/people/trent-muhr", research_interests: ["CS Education", "Algorithms"], courses_taught: ["COMS 2280", "COMS 3110", "COMS 3270"], is_teaching_faculty: true },
  { id: "jeremy-sheaffer", name: "Jeremy Sheaffer", rank: "Assistant Teaching Professor", group: "Teaching", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/sheaffer_jeremy.jpg", profile_url: "https://www.cs.iastate.edu/people/jeremy-sheaffer", research_interests: ["CS Education", "Systems Programming", "Graphics"], courses_taught: ["COMS 3210", "COMS 3270", "COMS 3360"], is_teaching_faculty: true },
  { id: "adisak-sukul", name: "Adisak Sukul", rank: "Teaching Professor", group: "Teaching", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/sukul_adisak.jpg", profile_url: "https://www.cs.iastate.edu/people/adisak-sukul", research_interests: ["Data Science", "Machine Learning", "Cloud Computing", "Deep Learning"], courses_taught: ["COMS 1130", "AI 2010X"], is_teaching_faculty: true },
  { id: "matthew-tancreti", name: "Matthew Tancreti", rank: "Associate Teaching Professor", group: "Teaching", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/my_project_1.png", profile_url: "https://www.cs.iastate.edu/people/matthew-tancreti", research_interests: ["Embedded Systems", "Operating Systems"], courses_taught: ["COMS 2270"], is_teaching_faculty: true },
  { id: "wenting-xu", name: "Wenting Xu", rank: "Assistant Teaching Professor", group: "Teaching", photo_url: "https://www.cs.iastate.edu/files/styles/profile_picture/public/people/profilepictures/thumbnail_img_1943.jpg", profile_url: "https://www.cs.iastate.edu/people/wenting-xu", research_interests: ["CS Education"], courses_taught: ["COMS 1130"], is_teaching_faculty: true },
]

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
  const [showPhotos, setShowPhotos] = useState(true)
  const [resultsGroupBy, setResultsGroupBy] = useState('none')

  useEffect(() => {
    fetchStats()
  }, [])

  const fetchStats = async () => {
    try {
      const res = await fetch(`${API_URL}/api/stats`)
      if (res.ok) setStats(await res.json())
    } catch (e) {
      console.error('Stats error:', e)
    }
  }

  const handleSearch = async (e) => {
    e.preventDefault()
    if (!query.trim()) return
    
    setLoading(true)
    try {
      const res = await fetch(`${API_URL}/api/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, limit: 20 })
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

  // Find related faculty based on search results and query
  const relatedFaculty = useMemo(() => {
    if (!results && !query.trim()) return []
    
    const searchTerms = query.toLowerCase().split(/\s+/).filter(t => t.length > 2)
    const matched = new Set()
    const facultyScores = new Map()
    
    // Score faculty based on research interests matching query
    FACULTY_DATA.forEach(f => {
      let score = 0
      const allText = [
        ...f.research_interests,
        f.group,
        ...f.courses_taught
      ].join(' ').toLowerCase()
      
      searchTerms.forEach(term => {
        if (allText.includes(term)) {
          score += 2
        }
        // Partial matches
        f.research_interests.forEach(interest => {
          if (interest.toLowerCase().includes(term) || term.includes(interest.toLowerCase().substring(0, 4))) {
            score += 1
          }
        })
      })
      
      if (score > 0) {
        facultyScores.set(f.id, score)
        matched.add(f.id)
      }
    })
    
    // Also check if results mention any faculty or related topics
    if (results?.sources) {
      results.sources.forEach(source => {
        const sourceText = `${source.title} ${source.abstract || ''} ${(source.authors || []).join(' ')}`.toLowerCase()
        
        FACULTY_DATA.forEach(f => {
          // Check if faculty name appears in results
          if (sourceText.includes(f.name.toLowerCase().split(' ')[1])) {
            const currentScore = facultyScores.get(f.id) || 0
            facultyScores.set(f.id, currentScore + 3)
            matched.add(f.id)
          }
          
          // Check research interest overlap
          f.research_interests.forEach(interest => {
            if (sourceText.includes(interest.toLowerCase())) {
              const currentScore = facultyScores.get(f.id) || 0
              facultyScores.set(f.id, currentScore + 1)
              matched.add(f.id)
            }
          })
        })
      })
    }
    
    // Include faculty from API response if available
    if (results?.related_faculty) {
      results.related_faculty.forEach(f => {
        matched.add(f.id)
        const currentScore = facultyScores.get(f.id) || 0
        facultyScores.set(f.id, currentScore + 5)
      })
    }
    
    // Sort by score and return top matches
    return FACULTY_DATA
      .filter(f => matched.has(f.id))
      .sort((a, b) => (facultyScores.get(b.id) || 0) - (facultyScores.get(a.id) || 0))
      .slice(0, 8)
  }, [query, results])

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

  return (
    <div className="app">
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
                          <label>Group by: </label>
                          <select value={resultsGroupBy} onChange={(e) => setResultsGroupBy(e.target.value)}>
                            <option value="none">None</option>
                            <option value="type">Document Type</option>
                          </select>
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
                                {items.map((source, idx) => (
                                  <li key={idx} className="source-item">
                                    <a href={source.url} target="_blank" rel="noopener noreferrer">
                                      {source.title}
                                    </a>
                                    <div className="source-meta">
                                      {source.authors?.slice(0, 3).join(', ')} {source.date && `• ${source.date}`}
                                    </div>
                                    {source.abstract && <p className="source-abstract">{source.abstract}</p>}
                                  </li>
                                ))}
                              </ul>
                            </details>
                          ))}
                        </div>
                      ) : (
                        <ul className="sources-list">
                          {results.sources.map((source, idx) => (
                            <li key={idx} className="source-item">
                              <span className="source-type-icon">{getTypeIcon(source.type)}</span>
                              <a href={source.url} target="_blank" rel="noopener noreferrer">
                                {source.title}
                              </a>
                              <div className="source-meta">
                                {source.authors?.slice(0, 3).join(', ')} {source.date && `• ${source.date}`}
                                {source.type && ` • ${source.type}`}
                              </div>
                              {source.abstract && <p className="source-abstract">{source.abstract}</p>}
                            </li>
                          ))}
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
            <div className="faculty-page">
              <h2>👥 Computer Science Faculty</h2>
              <div className="faculty-grid">
                {FACULTY_DATA.map(f => (
                  <div key={f.id} className="faculty-card">
                    <img src={f.photo_url} alt={f.name} className="card-photo" 
                         onError={(e) => e.target.src = 'https://via.placeholder.com/100?text=Photo'} />
                    <h3>{f.name}</h3>
                    <div className="rank">{f.rank}</div>
                    <div className="interests">
                      {f.research_interests.slice(0, 3).map((int, i) => (
                        <span key={i} className="interest-tag">{int}</span>
                      ))}
                    </div>
                    {f.courses_taught.length > 0 && (
                      <div className="courses">
                        📚 {f.courses_taught.join(', ')}
                      </div>
                    )}
                    <a href={f.profile_url} target="_blank" rel="noopener noreferrer" className="profile-link">
                      View Profile →
                    </a>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'topics' && (
            <div className="topics-page">
              <h2>🗺️ Research Topics</h2>
              <div className="topics-grid">
                {['AI and Machine Learning', 'Software Engineering', 'Systems and Networking', 'Theory', 'Robotics', 'Security', 'Human-Computer Interaction', 'Bioinformatics'].map(topic => (
                  <div key={topic} className="topic-card" onClick={() => { setQuery(topic); setActiveTab('search'); }}>
                    <h3>{topic}</h3>
                    <p>{FACULTY_DATA.filter(f => f.group === topic).length} faculty</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </main>

        {/* Dynamic People Sidebar - Only shows on Search tab */}
        {activeTab === 'search' && (
          <aside className="people-sidebar">
            <h3>👥 Related Experts</h3>
            
            <div className="sidebar-controls">
              <label>
                <input type="checkbox" checked={showPhotos} onChange={(e) => setShowPhotos(e.target.checked)} />
                Show photos
              </label>
            </div>

            {relatedFaculty.length > 0 ? (
              <div className="faculty-list">
                {relatedFaculty.map(f => (
                  <div key={f.id} className="faculty-item">
                    {showPhotos && (
                      <img src={f.photo_url} alt={f.name} className="faculty-photo"
                           onError={(e) => e.target.src = 'https://via.placeholder.com/40?text=?'} />
                    )}
                    <div className="faculty-info">
                      <a href={f.profile_url} target="_blank" rel="noopener noreferrer">{f.name}</a>
                      <span className="faculty-rank">{f.rank}</span>
                      <span className="faculty-interests">
                        {f.research_interests.slice(0, 2).join(', ')}
                      </span>
                      {f.courses_taught.length > 0 && (
                        <span className="faculty-courses">📚 {f.courses_taught.slice(0, 2).join(', ')}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="sidebar-empty">
                <p>🔍 Search for a topic to see related faculty experts</p>
                <p className="hint">Try: "machine learning", "robotics", "software testing"</p>
              </div>
            )}

            {query && relatedFaculty.length === 0 && results && (
              <div className="sidebar-empty">
                <p>No faculty experts found for this specific query.</p>
                <p className="hint">Try broader terms like research areas.</p>
              </div>
            )}
          </aside>
        )}
      </div>

      <footer className="footer">
        <p>ISU Research Search • Powered by Google Gemini RAG</p>
        <p>Department of Computer Science, Iowa State University</p>
      </footer>
    </div>
  )
}

export default App
