'use client';

import { useState, useRef, useEffect } from 'react';
import dynamic from 'next/dynamic';
import HistoryPanel from './components/HistoryPanel';

const ScoreDisplay = dynamic(() => import('./components/ScoreDisplay'), { ssr: false });

/* ── Instrument icon map ─────────────────────────────────── */
const INSTRUMENT_ICONS: Record<string, string> = {
  vocals: '🎤',
  piano: '🎹',
  guitar: '🎸',
  bass: '🎸',
  drums: '🥁',
  other: '🎵',
  keys: '🎹',
};

const INSTRUMENT_COLORS: Record<string, { from: string; to: string; ring: string; badge: string }> = {
  vocals: { from: 'from-sky-500', to: 'to-blue-600', ring: 'ring-sky-500/40', badge: 'bg-sky-500/10 text-sky-400 border-sky-500/20' },
  piano: { from: 'from-violet-500', to: 'to-purple-600', ring: 'ring-violet-500/40', badge: 'bg-violet-500/10 text-violet-400 border-violet-500/20' },
  guitar: { from: 'from-emerald-500', to: 'to-teal-600', ring: 'ring-emerald-500/40', badge: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' },
  bass: { from: 'from-amber-500', to: 'to-orange-600', ring: 'ring-amber-500/40', badge: 'bg-amber-500/10 text-amber-400 border-amber-500/20' },
  drums: { from: 'from-rose-500', to: 'to-red-600', ring: 'ring-rose-500/40', badge: 'bg-rose-500/10 text-rose-400 border-rose-500/20' },
  other: { from: 'from-fuchsia-500', to: 'to-pink-600', ring: 'ring-fuchsia-500/40', badge: 'bg-fuchsia-500/10 text-fuchsia-400 border-fuchsia-500/20' },
  keys: { from: 'from-violet-500', to: 'to-purple-600', ring: 'ring-violet-500/40', badge: 'bg-violet-500/10 text-violet-400 border-violet-500/20' },
};

const INSTRUMENT_ORDER = ['vocals', 'piano', 'guitar', 'bass', 'drums', 'other'];

/* ── Pipeline stages for progress display ────────────────── */
const STAGES = [
  { key: 'upload', label: 'Upload', threshold: 5 },
  { key: 'separate', label: 'Separating Stems', threshold: 10 },
  { key: 'transcribe', label: 'Transcribing', threshold: 50 },
  { key: 'render', label: 'MusicXML', threshold: 90 },
  { key: 'complete', label: 'Ready', threshold: 100 },
];

const API_BASE_URL = 'http://127.0.0.1:8000';

interface HistoryItem {
  filename: string;
  results: Record<string, string>;
  stems: Record<string, string>;
  message?: string;
  updated_at?: number;
}

export default function Home() {
  /* ── Safe download (prevents Electron navigation) ─── */
  const downloadFile = async (url: string, filename: string) => {
    try {
      const res = await fetch(url);
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      console.error('Download failed:', err);
    }
  };

  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState('');
  const [progress, setProgress] = useState(0);

  // Active Song Studio state
  const [currentSong, setCurrentSong] = useState<string | null>(null);
  const [historyList, setHistoryList] = useState<HistoryItem[]>([]);
  const [showUpload, setShowUpload] = useState(false);

  const [availableStems, setAvailableStems] = useState<{ [key: string]: string }>({});
  const [availableStemsAudio, setAvailableStemsAudio] = useState<{ [key: string]: string }>({});
  const [activeStem, setActiveStem] = useState<string | null>(null);
  const [activeAudio, setActiveAudio] = useState<string | null>(null);
  const [musicXml, setMusicXml] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const scoreRef = useRef<HTMLDivElement>(null);

  // Helper to get correct URL for audio/XML
  const getAbsoluteUrl = (urlPath: string) => urlPath.startsWith('http') ? urlPath : `${API_BASE_URL}${urlPath}`;

  // Handle audio play to ensure only one plays at a time
  const handleAudioPlay = (instrument: string) => {
    setActiveAudio(instrument);
    document.querySelectorAll('audio').forEach(audio => {
      const currentSrc = availableStemsAudio[instrument] ? getAbsoluteUrl(availableStemsAudio[instrument]) : '';
      if (!audio.paused && audio.src !== currentSrc) {
        audio.pause();
      }
    });
  };

  // Load sheet music XML
  const handleScoreView = (instrumentName: string, xmlUrl: string) => {
    const fetchUrl = getAbsoluteUrl(xmlUrl);
    setMessage(`Loading ${instrumentName} sheet music...`);

    fetch(fetchUrl)
      .then(res => {
        if (!res.ok) throw new Error('Failed to fetch XML file');
        return res.text();
      })
      .then(text => {
        setMusicXml(text);
        setActiveStem(instrumentName);
        setMessage(`Viewing ${instrumentName} score`);
        setTimeout(() => scoreRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 150);
      })
      .catch((err) => {
        console.error("Score fetch failed", err);
        setMessage(`Error loading ${instrumentName} score`);
      });
  };

  // Load an entire song into the Studio
  const handleLoadSong = (songItem: HistoryItem, preferredInst?: string) => {
    setCurrentSong(songItem.filename);
    setAvailableStems(songItem.results || {});
    setAvailableStemsAudio(songItem.stems || {});
    setUploading(false);
    setShowUpload(false);
    setMessage(`Loaded: ${songItem.filename.replace(/\.[^/.]+$/, '')}`);

    // Auto-select preferred track with sheet music (e.g. vocals or piano)
    const availableScores = songItem.results || {};
    let targetInst = preferredInst;
    if (!targetInst || !availableScores[targetInst]) {
      if (availableScores['vocals']) targetInst = 'vocals';
      else if (availableScores['piano']) targetInst = 'piano';
      else targetInst = Object.keys(availableScores)[0];
    }

    if (targetInst && availableScores[targetInst]) {
      handleScoreView(targetInst, availableScores[targetInst]);
    } else {
      setActiveStem(null);
      setMusicXml(null);
    }
  };

  // Fetch history list from backend
  const refreshHistory = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/history?t=${Date.now()}`);
      if (res.ok) {
        const data = await res.json();
        setHistoryList(data);
        return data;
      }
    } catch (err) {
      console.error('Failed to fetch history:', err);
    }
    return [];
  };

  // On mount: reconnect to active job or auto-load the latest song from history
  useEffect(() => {
    fetch(`${API_BASE_URL}/active`)
      .then(res => res.json())
      .then(data => {
        if (data && data.filename && data.status === 'processing') {
          setUploading(true);
          setShowUpload(true);
          setMessage(data.message || 'Reconnecting to active transcription...');
          setProgress(data.progress || 10);
          pollStatus(data.filename);
        } else {
          // If no background job is processing, load recent history and auto-load the newest song
          refreshHistory().then(history => {
            if (history && history.length > 0) {
              handleLoadSong(history[0]);
            } else {
              setShowUpload(true);
            }
          });
        }
      })
      .catch(() => {
        refreshHistory().then(history => {
          if (history && history.length > 0) {
            handleLoadSong(history[0]);
          } else {
            setShowUpload(true);
          }
        });
      });
  }, []);

  /* ── File handling ─────────────────────────────────────── */
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) setFile(e.target.files[0]);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const droppedFile = e.dataTransfer.files[0];
      if (droppedFile.type.startsWith('audio/')) {
        setFile(droppedFile);
      }
    }
  };

  /* ── Upload & poll ─────────────────────────────────────── */
  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setShowUpload(true);
    setMessage('Uploading...');
    setProgress(5);
    setActiveStem(null);
    setActiveAudio(null);
    setMusicXml(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch(`${API_BASE_URL}/upload`, {
        method: 'POST',
        body: formData,
      });
      if (!response.ok) throw new Error('Upload failed');
      const data = await response.json();
      setMessage('Processing started on RTX GPU...');
      pollStatus(data.filename);
    } catch (err: any) {
      console.error('Upload error:', err);
      setMessage(`Upload failed: ${err.message || String(err)}. Please try again.`);
      setUploading(false);
    }
  };

  const pollStatus = async (filename: string) => {
    try {
      const res = await fetch(
        `${API_BASE_URL}/status/${encodeURIComponent(filename)}?t=${Date.now()}`,
        { cache: 'no-store', headers: { 'Cache-Control': 'no-cache' } }
      );
      if (res.ok) {
        const data = await res.json();
        setMessage(data.message);
        setProgress(data.progress || 0);

        if (data.status === 'completed') {
          setUploading(false);
          setShowUpload(false);
          const completedItem: HistoryItem = {
            filename,
            results: data.results || {},
            stems: data.stems || {},
            message: data.message
          };
          refreshHistory();
          handleLoadSong(completedItem);
          return;
        } else if (data.status === 'error') {
          setUploading(false);
          setMessage(`Transcription failed: ${data.message || 'Unknown error'}`);
          return;
        }
      }
    } catch (err) {
      console.error('Polling error', err);
    }
    setTimeout(() => pollStatus(filename), 2500);
  };

  /* ── Reset to empty home ───────────────────────────────── */
  const resetApp = () => {
    setFile(null);
    setUploading(false);
    setMessage('');
    setProgress(0);
    setCurrentSong(null);
    setAvailableStems({});
    setAvailableStemsAudio({});
    setActiveStem(null);
    setActiveAudio(null);
    setMusicXml(null);
    setShowUpload(true);
  };

  /* ── Combined list of active instruments ────────────────── */
  const allInstrumentKeys = Array.from(
    new Set([
      ...INSTRUMENT_ORDER.filter(inst => availableStems[inst] || availableStemsAudio[inst]),
      ...Object.keys(availableStems),
      ...Object.keys(availableStemsAudio),
    ])
  );

  const currentStageIndex = STAGES.findIndex((s) => progress < s.threshold);
  const cleanSongTitle = currentSong ? currentSong.replace(/\.[^/.]+$/, '') : null;

  /* ─────────────────────────────── RENDER ────────────────── */
  return (
    <main className="relative min-h-screen flex flex-col items-center overflow-x-hidden bg-[#06080f] text-slate-100 font-sans selection:bg-fuchsia-500/30">

      {/* ── Ambient background ───────────────────────────── */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute top-[-20%] left-[-15%] w-[60vw] h-[60vw] bg-indigo-600/[0.07] rounded-full blur-[140px]" />
        <div className="absolute bottom-[-20%] right-[-15%] w-[70vw] h-[70vw] bg-fuchsia-600/[0.06] rounded-full blur-[160px]" />
        <div className="absolute top-[40%] left-[50%] w-[30vw] h-[30vw] bg-cyan-500/[0.04] rounded-full blur-[120px]" />
      </div>

      {/* ── Subtle grid overlay ──────────────────────────── */}
      <div
        className="pointer-events-none fixed inset-0 opacity-[0.03]"
        style={{
          backgroundImage: 'linear-gradient(rgba(255,255,255,0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.1) 1px, transparent 1px)',
          backgroundSize: '40px 40px',
        }}
      />

      {/* ── Content wrapper ──────────────────────────────── */}
      <div className="relative z-10 flex flex-col items-center w-full max-w-6xl px-6 py-8 lg:py-14">

        {/* ── History toggle button (top-right) ──────────── */}
        <button
          onClick={() => setHistoryOpen(true)}
          className="fixed top-5 right-5 z-30 px-3.5 py-2 rounded-xl bg-slate-800/80 border border-slate-700/60 hover:bg-slate-700/80 backdrop-blur-md flex items-center gap-2 transition-all hover:scale-105 active:scale-95 group shadow-xl"
          title="Transcription History"
        >
          <svg className="w-4 h-4 text-indigo-400 group-hover:text-indigo-300 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span className="text-xs font-semibold text-slate-300 group-hover:text-white">History</span>
          {historyList.length > 0 && (
            <span className="text-[10px] font-bold px-1.5 py-0.2 rounded-full bg-indigo-500/30 text-indigo-300 border border-indigo-500/40">
              {historyList.length}
            </span>
          )}
        </button>

        {/* ── Header ─────────────────────────────────────── */}
        <div className="text-center mb-8 space-y-3">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-slate-700/50 bg-slate-800/40 backdrop-blur-sm text-xs font-medium text-slate-400">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            100% Local AI Multi-Instrument Transcription
          </div>
          <h1 className="text-4xl lg:text-6xl tracking-tight font-black text-transparent bg-clip-text bg-gradient-to-br from-white via-slate-200 to-slate-400">
            Ghost<span className="bg-gradient-to-r from-indigo-400 via-fuchsia-400 to-rose-400 bg-clip-text">Note</span>
          </h1>
        </div>

        {/* ── Recent Songs Switcher Bar ──────────────────── */}
        {historyList.length > 0 && (
          <div className="w-full max-w-4xl mb-8 flex flex-col items-center">
            <div className="flex items-center gap-2 flex-wrap justify-center p-2 rounded-2xl bg-slate-900/40 border border-slate-800/80 backdrop-blur-md shadow-lg">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500 px-2 flex items-center gap-1.5">
                <svg className="w-3.5 h-3.5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                </svg>
                Songs:
              </span>

              {historyList.map((item) => {
                const isSelected = currentSong === item.filename;
                const dName = item.filename.replace(/\.[^/.]+$/, '');
                return (
                  <button
                    key={item.filename}
                    onClick={() => handleLoadSong(item)}
                    className={`
                      px-3 py-1.5 rounded-xl text-xs font-semibold transition-all flex items-center gap-2 active:scale-95
                      ${isSelected
                        ? 'bg-gradient-to-r from-indigo-600/40 to-fuchsia-600/30 text-white border border-indigo-500/60 shadow-[0_0_15px_-3px_rgba(99,102,241,0.3)] ring-1 ring-indigo-400/40'
                        : 'bg-slate-800/40 text-slate-400 hover:text-slate-200 hover:bg-slate-700/40 border border-slate-700/40'
                      }
                    `}
                    title={`Load ${dName}`}
                  >
                    <span>🎵</span>
                    <span className="truncate max-w-[160px] sm:max-w-[220px]">{dName}</span>
                    {isSelected && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse shrink-0" />}
                  </button>
                );
              })}

              {/* Toggle upload button */}
              <button
                onClick={() => setShowUpload(!showUpload)}
                className={`
                  px-3 py-1.5 rounded-xl text-xs font-medium transition-all flex items-center gap-1.5 border active:scale-95
                  ${showUpload
                    ? 'bg-fuchsia-500/20 text-fuchsia-300 border-fuchsia-500/40'
                    : 'bg-slate-800/20 text-slate-400 hover:text-slate-200 border-dashed border-slate-700/60 hover:bg-slate-800/50'
                  }
                `}
                title="Transcribe a new audio file"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  {showUpload ? (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                  ) : (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" />
                  )}
                </svg>
                {showUpload ? 'Close' : '+ New Upload'}
              </button>
            </div>
          </div>
        )}

        {/* ── Upload Box (Conditional or toggled) ─────────── */}
        {(showUpload || !currentSong) && (
          <div className="w-full max-w-2xl mb-10 animate-fadeIn">
            <div
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`
                relative group cursor-pointer rounded-2xl border-2 border-dashed transition-all duration-300
                ${isDragging
                  ? 'border-indigo-400 bg-indigo-500/10 scale-[1.02]'
                  : file
                    ? 'border-emerald-500/40 bg-emerald-500/5'
                    : 'border-slate-700/60 bg-slate-900/40 hover:border-slate-500/60 hover:bg-slate-800/30'
                }
              `}
            >
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleFileChange}
                accept="audio/*"
                className="hidden"
              />

              <div className="flex flex-col items-center justify-center py-8 px-6 gap-3">
                {file ? (
                  <>
                    <div className="w-12 h-12 rounded-xl bg-emerald-500/20 flex items-center justify-center">
                      <svg className="w-6 h-6 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                      </svg>
                    </div>
                    <p className="text-sm font-semibold text-slate-200">{file.name}</p>
                    <p className="text-xs text-slate-500">{(file.size / (1024 * 1024)).toFixed(1)} MB — Click to change</p>
                  </>
                ) : (
                  <>
                    <div className="w-12 h-12 rounded-xl bg-slate-800/80 border border-slate-700/50 flex items-center justify-center group-hover:bg-slate-700/80 transition-colors">
                      <svg className="w-6 h-6 text-slate-400 group-hover:text-slate-300 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                      </svg>
                    </div>
                    <p className="text-sm font-medium text-slate-300">
                      Drop audio file here or <span className="text-indigo-400 font-semibold">browse</span>
                    </p>
                    <p className="text-xs text-slate-500">Supports MP3, WAV, M4A, FLAC • Processed locally on RTX 4050</p>
                  </>
                )}
              </div>
            </div>

            {/* Transcribe action button */}
            {file && !uploading && (
              <button
                onClick={handleUpload}
                disabled={!file || uploading}
                className="mt-4 w-full group relative overflow-hidden rounded-xl bg-gradient-to-r from-indigo-600 via-violet-600 to-fuchsia-600 px-6 py-3.5 font-bold text-white shadow-[0_0_30px_-5px_rgba(99,102,241,0.4)] transition-all hover:shadow-[0_0_40px_-5px_rgba(99,102,241,0.6)] active:scale-[0.98] disabled:opacity-50"
              >
                <div className="absolute inset-0 bg-gradient-to-r from-indigo-500 via-violet-500 to-fuchsia-500 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
                <span className="relative flex items-center justify-center gap-2.5 text-sm tracking-wide">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  Start Polyphonic AI Transcription
                </span>
              </button>
            )}
          </div>
        )}

        {/* ── Pipeline Progress Indicator ─────────────────── */}
        {uploading && (
          <div className="w-full max-w-2xl mb-10 animate-fadeIn">
            <div className="backdrop-blur-xl bg-slate-900/60 rounded-2xl border border-slate-700/50 p-6 shadow-2xl">
              {/* Stage indicators */}
              <div className="flex items-center justify-between mb-5">
                {STAGES.map((stage, i) => {
                  const isPast = currentStageIndex > i;
                  const isCurrent = currentStageIndex === i;
                  return (
                    <div key={stage.key} className="flex items-center gap-2 flex-1">
                      <div className={`
                        w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-all duration-500 shrink-0
                        ${isPast ? 'bg-emerald-500/20 text-emerald-400 ring-1 ring-emerald-500/30' :
                          isCurrent ? 'bg-indigo-500/20 text-indigo-400 ring-1 ring-indigo-500/40 animate-pulse' :
                            'bg-slate-800/60 text-slate-600 ring-1 ring-slate-700/30'}
                      `}>
                        {isPast ? '✓' : i + 1}
                      </div>
                      <span className={`text-xs font-medium hidden sm:block ${isPast ? 'text-emerald-400/80' : isCurrent ? 'text-indigo-300' : 'text-slate-600'}`}>
                        {stage.label}
                      </span>
                      {i < STAGES.length - 1 && (
                        <div className={`flex-1 h-px mx-2 ${isPast ? 'bg-emerald-500/30' : 'bg-slate-700/40'}`} />
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Progress bar */}
              <div className="w-full bg-slate-800/80 h-2 rounded-full overflow-hidden">
                <div
                  className="bg-gradient-to-r from-indigo-500 via-violet-500 to-fuchsia-500 h-full transition-all duration-700 ease-out rounded-full relative"
                  style={{ width: `${progress}%` }}
                >
                  <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent animate-shimmer" />
                </div>
              </div>

              {/* Status message */}
              <div className="flex items-center justify-between mt-3">
                <p className="text-xs text-slate-400 font-medium">{message}</p>
                <span className="text-xs text-indigo-400 font-mono font-bold tabular-nums">{progress}%</span>
              </div>
            </div>
          </div>
        )}

        {/* ── Active Song Studio View ─────────────────────── */}
        {currentSong && allInstrumentKeys.length > 0 && (
          <div className="w-full animate-fadeIn">

            {/* Song Title & Project Banner */}
            <div className="w-full flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-5 rounded-2xl bg-gradient-to-r from-slate-900/90 to-slate-800/60 border border-slate-700/50 backdrop-blur-xl shadow-xl mb-6">
              <div>
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-indigo-400">
                    Active Studio Project
                  </span>
                  <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    100% Offline AI
                  </span>
                  <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
                    {Object.keys(availableStems).length} Scores Ready
                  </span>
                </div>
                <h2 className="text-2xl sm:text-3xl font-black text-white tracking-tight flex items-center gap-2.5">
                  <span>🎵</span>
                  <span>{cleanSongTitle}</span>
                </h2>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => setShowUpload(true)}
                  className="px-3.5 py-2 rounded-xl text-xs font-semibold text-slate-300 bg-slate-800/80 hover:bg-slate-700/80 hover:text-white border border-slate-700/50 transition-all flex items-center gap-1.5 active:scale-95"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" />
                  </svg>
                  New Song
                </button>
              </div>
            </div>

            {/* Track Cards Grid */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3.5 w-full mb-8">
              {allInstrumentKeys.map((instrument) => {
                const xmlUrl = availableStems[instrument];
                const audioUrl = availableStemsAudio[instrument];
                const hasScore = !!xmlUrl;
                const isActive = activeStem === instrument;
                const colors = INSTRUMENT_COLORS[instrument] || INSTRUMENT_COLORS.other;
                const icon = INSTRUMENT_ICONS[instrument] || '🎵';

                return (
                  <div
                    key={instrument}
                    onClick={() => hasScore && handleScoreView(instrument, xmlUrl)}
                    className={`
                      group relative overflow-hidden rounded-2xl border transition-all duration-300
                      ${hasScore ? 'cursor-pointer' : ''}
                      ${isActive
                        ? `border-transparent ring-2 ${colors.ring} bg-slate-800/80 shadow-lg shadow-indigo-500/10`
                        : 'border-slate-800/80 bg-slate-900/60 hover:bg-slate-800/50 hover:border-slate-700/80'
                      }
                    `}
                  >
                    {/* Active gradient glow */}
                    {isActive && (
                      <div className={`absolute inset-0 bg-gradient-to-br ${colors.from} ${colors.to} opacity-[0.08] pointer-events-none`} />
                    )}

                    <div className="relative p-4 flex flex-col justify-between h-full">
                      {/* Top row: Icon, Name & Score Action */}
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2.5">
                          <span className="text-2xl">{icon}</span>
                          <div>
                            <h3 className="text-sm font-bold capitalize text-slate-100 flex items-center gap-1.5">
                              {instrument}
                            </h3>
                            <span className="text-[10px] text-slate-500 font-medium">
                              {hasScore ? 'Notation + Stem' : 'Percussion Audio'}
                            </span>
                          </div>
                        </div>

                        {hasScore ? (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleScoreView(instrument, xmlUrl);
                            }}
                            className={`
                              px-3 py-1.5 text-xs font-bold rounded-lg transition-all duration-200 active:scale-95
                              ${isActive
                                ? `bg-gradient-to-r ${colors.from} ${colors.to} text-white shadow-md`
                                : 'bg-slate-800/80 text-slate-400 hover:text-slate-200 hover:bg-slate-700/80 border border-slate-700/50'
                              }
                            `}
                          >
                            {isActive ? 'Viewing' : 'Score'}
                          </button>
                        ) : (
                          <span className="text-[10px] font-semibold text-slate-500 px-2 py-0.5 rounded-md bg-slate-800/50 border border-slate-700/40">
                            Audio
                          </span>
                        )}
                      </div>

                      {/* Stem Audio Player */}
                      {audioUrl && (
                        <div className="mt-1" onClick={(e) => e.stopPropagation()}>
                          <audio
                            controls
                            onPlay={() => handleAudioPlay(instrument)}
                            src={getAbsoluteUrl(audioUrl)}
                            className="w-full h-8 opacity-75 hover:opacity-100 transition-opacity"
                          />
                        </div>
                      )}

                      {/* Footer: Download MusicXML */}
                      {hasScore && (
                        <div className="mt-3 flex justify-between items-center pt-2 border-t border-slate-800/60" onClick={(e) => e.stopPropagation()}>
                          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${colors.badge}`}>
                            {isActive ? 'Viewing Sheet Music' : 'Click to View Score'}
                          </span>
                          <button
                            onClick={() => downloadFile(getAbsoluteUrl(xmlUrl), `${cleanSongTitle}_${instrument}.musicxml`)}
                            className="text-[11px] text-slate-500 hover:text-indigo-300 transition-colors flex items-center gap-1 bg-transparent border-none cursor-pointer"
                            title="Download MusicXML file"
                          >
                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                            </svg>
                            Export XML
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* ── Sheet Music Display Section ───────────────── */}
            {musicXml && activeStem && (
              <div ref={scoreRef} className="w-full mt-2 mb-20 animate-fadeIn">
                <div className="rounded-2xl overflow-hidden border border-slate-700/60 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.7)] bg-slate-900/90">
                  {/* Score toolbar header */}
                  <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between px-6 py-4 bg-slate-900/95 backdrop-blur-md border-b border-slate-700/50 gap-3">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl">{INSTRUMENT_ICONS[activeStem] || '🎵'}</span>
                      <div>
                        <h2 className="text-base font-bold text-white capitalize flex items-center gap-2">
                          <span>{activeStem}</span>
                          <span className="text-xs font-normal text-slate-400">— Sheet Music</span>
                        </h2>
                        <p className="text-xs text-slate-500">
                          {cleanSongTitle} • Transcribed with 16th-note smart quantization
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2.5">
                      <button
                        onClick={() => downloadFile(getAbsoluteUrl(availableStems[activeStem]), `${cleanSongTitle}_${activeStem}.musicxml`)}
                        className="px-3.5 py-1.5 rounded-lg bg-indigo-500/15 hover:bg-indigo-500/25 text-indigo-300 border border-indigo-500/30 text-xs font-semibold transition-all flex items-center gap-1.5 active:scale-95 shadow-sm"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                        Download MusicXML
                      </button>
                    </div>
                  </div>

                  {/* Score SVG container (OSMD requires white background) */}
                  <div className="bg-white overflow-x-auto p-2">
                    <ScoreDisplay xmlData={musicXml} />
                  </div>
                </div>
              </div>
            )}

          </div>
        )}

      </div>

      {/* ── History Side Panel ──────────────────────────── */}
      <HistoryPanel
        isOpen={historyOpen}
        onClose={() => setHistoryOpen(false)}
        onLoadSong={(results, stems, filename) => {
          handleLoadSong({ filename, results, stems });
        }}
        onViewScore={(instrumentName, xmlUrl) => {
          handleScoreView(instrumentName, xmlUrl);
        }}
        downloadFile={downloadFile}
      />
    </main>
  );
}
