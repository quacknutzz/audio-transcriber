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

const INSTRUMENT_ORDER = ['vocals', 'piano', 'guitar', 'bass', 'drums', 'other'];

/* ── Pipeline stages for progress display ────────────────── */
const STAGES = [
  { key: 'upload', label: 'Upload', threshold: 5 },
  { key: 'separate', label: 'Stem Separation', threshold: 10 },
  { key: 'transcribe', label: 'Transcribing', threshold: 50 },
  { key: 'render', label: 'Notation Export', threshold: 90 },
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

  // Active Studio state
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
      setMessage('Processing started on local GPU...');
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
    <main className="relative min-h-screen flex flex-col items-center bg-[#0d0c0b] text-[#f2f0eb] font-sans antialiased selection:bg-[#3d3831] selection:text-[#faf9f6]">

      {/* ── Minimal tactile grid texture ────────────────── */}
      <div
        className="pointer-events-none fixed inset-0 opacity-[0.02]"
        style={{
          backgroundImage: 'linear-gradient(rgba(240,235,225,0.15) 1px, transparent 1px), linear-gradient(90deg, rgba(240,235,225,0.15) 1px, transparent 1px)',
          backgroundSize: '32px 32px',
        }}
      />

      {/* ── Content container ────────────────────────────── */}
      <div className="relative z-10 flex flex-col items-center w-full max-w-5xl px-6 py-8 sm:py-12">

        {/* ── History button (top-right) ─────────────────── */}
        <button
          onClick={() => setHistoryOpen(true)}
          className="fixed top-5 right-5 z-30 px-3 py-1.5 rounded-lg bg-[#191816] border border-[#2e2b27] hover:bg-[#252320] hover:border-[#423e38] flex items-center gap-2 transition-colors group shadow-md"
          title="Transcription History"
        >
          <svg className="w-3.5 h-3.5 text-[#a8a196] group-hover:text-[#edeae4] transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span className="text-xs font-medium text-[#c4beb3] group-hover:text-white">History</span>
          {historyList.length > 0 && (
            <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-[#252320] text-[#a8a196] border border-[#36332e]">
              {historyList.length}
            </span>
          )}
        </button>

        {/* ── Minimalist Header ──────────────────────────── */}
        <div className="text-center mb-8 space-y-2">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-[#2b2926] bg-[#161514] text-[11px] font-mono text-[#8a847b]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#bbb4a8]" />
            Local Audio-to-Score Transcription
          </div>
          <h1 className="text-3xl sm:text-5xl tracking-tight font-black text-[#f4f2ed]">
            Ghost<span className="text-[#969085] font-light">Note</span>
          </h1>
        </div>

        {/* ── Recent Songs Switcher Bar ──────────────────── */}
        {historyList.length > 0 && (
          <div className="w-full mb-8 flex flex-col items-center">
            <div className="flex items-center gap-1.5 flex-wrap justify-center p-1.5 rounded-xl bg-[#151413] border border-[#262421] shadow-inner">
              <span className="text-[10px] font-mono uppercase tracking-wider text-[#69645d] px-2.5">
                Projects:
              </span>

              {historyList.map((item) => {
                const isSelected = currentSong === item.filename;
                const dName = item.filename.replace(/\.[^/.]+$/, '');
                return (
                  <button
                    key={item.filename}
                    onClick={() => handleLoadSong(item)}
                    className={`
                      px-3 py-1.5 rounded-lg text-xs font-medium transition-colors flex items-center gap-2 active:scale-98
                      ${isSelected
                        ? 'bg-[#282623] text-[#ffffff] border border-[#d6cfc2] shadow-sm'
                        : 'bg-[#1b1a18] text-[#9c958b] hover:text-[#edeae4] hover:bg-[#22201d] border border-[#2a2825]'
                      }
                    `}
                    title={`Open ${dName}`}
                  >
                    <span className="text-xs">🎵</span>
                    <span className="truncate max-w-[150px] sm:max-w-[200px]">{dName}</span>
                    {isSelected && <span className="w-1.5 h-1.5 rounded-full bg-[#ded8ce]" />}
                  </button>
                );
              })}

              {/* Toggle upload button */}
              <button
                onClick={() => setShowUpload(!showUpload)}
                className={`
                  px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5 border active:scale-98
                  ${showUpload
                    ? 'bg-[#292623] text-[#edeae4] border-[#4a453e]'
                    : 'bg-[#161514] text-[#736d64] hover:text-[#c7c0b4] border-dashed border-[#302d29] hover:bg-[#1e1d1b]'
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
                {showUpload ? 'Close' : '+ New Audio'}
              </button>
            </div>
          </div>
        )}

        {/* ── Minimalist Upload Dropzone ─────────────────── */}
        {(showUpload || !currentSong) && (
          <div className="w-full max-w-xl mb-8 animate-fadeIn">
            <div
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`
                relative cursor-pointer rounded-xl border border-dashed transition-all duration-200
                ${isDragging
                  ? 'border-[#d4cdbf] bg-[#1e1c1a]'
                  : file
                    ? 'border-[#948d81] bg-[#1a1917]'
                    : 'border-[#2d2b27] bg-[#141312] hover:border-[#45413a] hover:bg-[#181716]'
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

              <div className="flex flex-col items-center justify-center py-7 px-5 gap-2.5 text-center">
                {file ? (
                  <>
                    <div className="w-9 h-9 rounded-lg bg-[#252320] border border-[#3b3832] flex items-center justify-center text-[#ded9ce]">
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                      </svg>
                    </div>
                    <p className="text-xs font-semibold text-[#f0ede6]">{file.name}</p>
                    <p className="text-[11px] font-mono text-[#787268]">{(file.size / (1024 * 1024)).toFixed(1)} MB • Click to change</p>
                  </>
                ) : (
                  <>
                    <div className="w-9 h-9 rounded-lg bg-[#1d1b19] border border-[#2b2824] flex items-center justify-center text-[#8a8377]">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                      </svg>
                    </div>
                    <p className="text-xs font-medium text-[#c9c3b8]">
                      Drop audio file here or <span className="text-[#f5f3ef] underline underline-offset-2">browse</span>
                    </p>
                    <p className="text-[10px] font-mono text-[#635e57]">MP3, WAV, M4A, FLAC • Processed locally on RTX GPU</p>
                  </>
                )}
              </div>
            </div>

            {/* Action button */}
            {file && !uploading && (
              <button
                onClick={handleUpload}
                disabled={!file || uploading}
                className="mt-3 w-full rounded-lg bg-[#ded9cf] hover:bg-[#edeae4] text-[#141312] py-2.5 px-4 font-bold text-xs tracking-wide transition-colors active:scale-98 shadow-sm"
              >
                Start Transcription
              </button>
            )}
          </div>
        )}

        {/* ── Minimalist Progress Bar ─────────────────────── */}
        {uploading && (
          <div className="w-full max-w-xl mb-8 animate-fadeIn">
            <div className="bg-[#161513] rounded-xl border border-[#2d2a27] p-5">
              {/* Stages */}
              <div className="flex items-center justify-between mb-4">
                {STAGES.map((stage, i) => {
                  const isPast = currentStageIndex > i;
                  const isCurrent = currentStageIndex === i;
                  return (
                    <div key={stage.key} className="flex items-center gap-1.5 flex-1">
                      <div className={`
                        w-5 h-5 rounded-md flex items-center justify-center text-[10px] font-mono font-bold transition-colors shrink-0
                        ${isPast ? 'bg-[#292724] text-[#d6cfc2] border border-[#3e3a35]' :
                          isCurrent ? 'bg-[#ded9cf] text-[#141312] font-black' :
                            'bg-[#1a1917] text-[#545049] border border-[#24221f]'}
                      `}>
                        {isPast ? '✓' : i + 1}
                      </div>
                      <span className={`text-[11px] hidden sm:block ${isPast ? 'text-[#a39c91]' : isCurrent ? 'text-[#f0ede6] font-semibold' : 'text-[#4d4943]'}`}>
                        {stage.label}
                      </span>
                      {i < STAGES.length - 1 && (
                        <div className={`flex-1 h-px mx-1.5 ${isPast ? 'bg-[#3b3731]' : 'bg-[#22201d]'}`} />
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Progress bar track */}
              <div className="w-full bg-[#201f1c] h-1.5 rounded-full overflow-hidden">
                <div
                  className="bg-[#dcd6ca] h-full transition-all duration-500 ease-out rounded-full"
                  style={{ width: `${progress}%` }}
                />
              </div>

              {/* Status message */}
              <div className="flex items-center justify-between mt-2.5">
                <p className="text-[11px] text-[#8a8479] font-mono">{message}</p>
                <span className="text-[11px] text-[#ded9ce] font-mono font-semibold tabular-nums">{progress}%</span>
              </div>
            </div>
          </div>
        )}

        {/* ── Active Studio View ──────────────────────────── */}
        {currentSong && allInstrumentKeys.length > 0 && (
          <div className="w-full animate-fadeIn">

            {/* Song Header Strip */}
            <div className="w-full flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 p-4 rounded-xl bg-[#171614] border border-[#292724] mb-5">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] font-mono uppercase tracking-widest text-[#736d64]">
                    Active Project
                  </span>
                  <span className="text-[10px] font-mono px-2 py-0.2 rounded bg-[#22201d] text-[#a39d91] border border-[#2e2b27]">
                    100% Offline AI
                  </span>
                  <span className="text-[10px] font-mono px-2 py-0.2 rounded bg-[#22201d] text-[#8a8479] border border-[#2e2b27]">
                    {Object.keys(availableStems).length} Scores
                  </span>
                </div>
                <h2 className="text-xl sm:text-2xl font-bold text-[#f5f3ef] tracking-tight">
                  {cleanSongTitle}
                </h2>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => setShowUpload(true)}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium text-[#b5afa4] bg-[#201f1c] hover:bg-[#2b2925] hover:text-[#f4f1eb] border border-[#2f2c28] transition-colors flex items-center gap-1.5"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" />
                  </svg>
                  New Track
                </button>
              </div>
            </div>

            {/* Track Cards Grid */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3 w-full mb-6">
              {allInstrumentKeys.map((instrument) => {
                const xmlUrl = availableStems[instrument];
                const audioUrl = availableStemsAudio[instrument];
                const hasScore = !!xmlUrl;
                const isActive = activeStem === instrument;
                const icon = INSTRUMENT_ICONS[instrument] || '🎵';

                return (
                  <div
                    key={instrument}
                    onClick={() => hasScore && handleScoreView(instrument, xmlUrl)}
                    className={`
                      rounded-xl border transition-all p-3.5 flex flex-col justify-between
                      ${hasScore ? 'cursor-pointer' : ''}
                      ${isActive
                        ? 'border-[#e0d9cc] bg-[#22201d] shadow-sm'
                        : 'border-[#262421] bg-[#161513] hover:border-[#383530] hover:bg-[#1b1a18]'
                      }
                    `}
                  >
                    <div>
                      {/* Card Header */}
                      <div className="flex items-center justify-between mb-2.5">
                        <div className="flex items-center gap-2">
                          <span className="text-lg">{icon}</span>
                          <div>
                            <h3 className="text-xs font-bold capitalize text-[#eeebe4]">
                              {instrument}
                            </h3>
                            <span className="text-[10px] text-[#6e6860] font-mono">
                              {hasScore ? 'Score Ready' : 'Percussion Audio'}
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
                              px-2.5 py-1 text-[11px] font-semibold rounded-md transition-colors
                              ${isActive
                                ? 'bg-[#ded9cf] text-[#141312]'
                                : 'bg-[#22201d] text-[#999286] hover:text-[#f2efe8] hover:bg-[#2c2a26] border border-[#302d29]'
                              }
                            `}
                          >
                            {isActive ? 'Viewing' : 'Score'}
                          </button>
                        ) : (
                          <span className="text-[10px] font-mono text-[#66615a] px-2 py-0.5 rounded bg-[#1c1b19] border border-[#262422]">
                            Audio
                          </span>
                        )}
                      </div>

                      {/* Mini Audio Player */}
                      {audioUrl && (
                        <div className="mt-2" onClick={(e) => e.stopPropagation()}>
                          <audio
                            controls
                            onPlay={() => handleAudioPlay(instrument)}
                            src={getAbsoluteUrl(audioUrl)}
                            className="w-full h-7 opacity-75 hover:opacity-100 transition-opacity"
                          />
                        </div>
                      )}
                    </div>

                    {/* Card Footer */}
                    {hasScore && (
                      <div className="mt-3 flex justify-between items-center pt-2 border-t border-[#252320]" onClick={(e) => e.stopPropagation()}>
                        <span className="text-[10px] font-mono text-[#787268]">
                          {isActive ? '● Currently Loaded' : 'Click to View'}
                        </span>
                        <button
                          onClick={() => downloadFile(getAbsoluteUrl(xmlUrl), `${cleanSongTitle}_${instrument}.musicxml`)}
                          className="text-[11px] font-mono text-[#8a8377] hover:text-[#e8e4dc] transition-colors flex items-center gap-1 bg-transparent border-none cursor-pointer"
                          title="Download MusicXML file"
                        >
                          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                          </svg>
                          XML
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* ── Sheet Music Display Section ───────────────── */}
            {musicXml && activeStem && (
              <div ref={scoreRef} className="w-full mt-3 mb-16 animate-fadeIn">
                <div className="rounded-xl overflow-hidden border border-[#2e2b27] bg-[#161513] shadow-lg">
                  {/* Score toolbar header */}
                  <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between px-5 py-3 bg-[#191816] border-b border-[#292724] gap-2">
                    <div className="flex items-center gap-2.5">
                      <span className="text-xl">{INSTRUMENT_ICONS[activeStem] || '🎵'}</span>
                      <div>
                        <h2 className="text-xs font-bold text-[#f2efe9] capitalize flex items-center gap-2">
                          <span>{activeStem}</span>
                          <span className="text-[11px] font-normal text-[#8a8479]">— Sheet Music</span>
                        </h2>
                        <p className="text-[10px] font-mono text-[#6b665e]">
                          {cleanSongTitle} • Quantized 16th-note notation
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => downloadFile(getAbsoluteUrl(availableStems[activeStem]), `${cleanSongTitle}_${activeStem}.musicxml`)}
                        className="px-3 py-1 rounded-md bg-[#23211e] hover:bg-[#2e2b27] text-[#ded9ce] border border-[#38342f] text-xs font-medium transition-colors flex items-center gap-1.5 shadow-xs"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                        Export MusicXML
                      </button>
                    </div>
                  </div>

                  {/* Score SVG container (OSMD requires clean white background) */}
                  <div className="bg-white overflow-x-auto p-3">
                    <ScoreDisplay xmlData={musicXml} />
                  </div>
                </div>
              </div>
            )}

          </div>
        )}

      </div>

      {/* ── History Drawer ──────────────────────────────── */}
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
