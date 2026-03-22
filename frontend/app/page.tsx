'use client';

import { useState, useRef } from 'react';
import dynamic from 'next/dynamic';
import HistoryPanel from './components/HistoryPanel';

const ScoreDisplay = dynamic(() => import('./components/ScoreDisplay'), { ssr: false });

/* ── Instrument icon map ─────────────────────────────────── */
const INSTRUMENT_ICONS: Record<string, string> = {
  bass: '🎸',
  guitar: '🎸',
  piano: '🎹',
  drums: '🥁',
  vocals: '🎤',
  other: '🎵',
  keys: '🎹',
};

const INSTRUMENT_COLORS: Record<string, { from: string; to: string; ring: string }> = {
  bass: { from: 'from-amber-500', to: 'to-orange-600', ring: 'ring-amber-500/30' },
  guitar: { from: 'from-emerald-500', to: 'to-teal-600', ring: 'ring-emerald-500/30' },
  piano: { from: 'from-violet-500', to: 'to-purple-600', ring: 'ring-violet-500/30' },
  drums: { from: 'from-rose-500', to: 'to-red-600', ring: 'ring-rose-500/30' },
  vocals: { from: 'from-sky-500', to: 'to-blue-600', ring: 'ring-sky-500/30' },
  other: { from: 'from-fuchsia-500', to: 'to-pink-600', ring: 'ring-fuchsia-500/30' },
  keys: { from: 'from-violet-500', to: 'to-purple-600', ring: 'ring-violet-500/30' },
};

/* ── Pipeline stages for progress display ────────────────── */
const STAGES = [
  { key: 'upload', label: 'Upload', threshold: 5 },
  { key: 'separate', label: 'Separating', threshold: 10 },
  { key: 'transcribe', label: 'Transcribing', threshold: 50 },
  { key: 'render', label: 'Finalizing', threshold: 90 },
  { key: 'complete', label: 'Done', threshold: 100 },
];

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
  const [availableStems, setAvailableStems] = useState<{ [key: string]: string }>({});
  const [availableStemsAudio, setAvailableStemsAudio] = useState<{ [key: string]: string }>({});
  const [activeStem, setActiveStem] = useState<string | null>(null);
  const [musicXml, setMusicXml] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const scoreRef = useRef<HTMLDivElement>(null);

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
    setMessage('Uploading...');
    setProgress(5);
    setAvailableStems({});
    setAvailableStemsAudio({});
    setActiveStem(null);
    setMusicXml(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('http://127.0.0.1:8000/upload', {
        method: 'POST',
        body: formData,
      });
      if (!response.ok) throw new Error('Upload failed');
      const data = await response.json();
      setMessage('Processing started...');
      pollStatus(data.filename);
    } catch (err: any) {
      console.error('Upload catch block triggered:', err);
      setMessage(`Upload failed: ${err.message || String(err)}. Please try again.`);
      setUploading(false);
    }
  };

  const pollStatus = async (filename: string) => {
    try {
      const res = await fetch(
        `http://127.0.0.1:8000/status/${encodeURIComponent(filename)}?t=${Date.now()}`,
        { cache: 'no-store', headers: { 'Cache-Control': 'no-cache' } }
      );
      if (res.ok) {
        const data = await res.json();
        setMessage(data.message);
        setProgress(data.progress || 0);

        if (data.status === 'completed') {
          setUploading(false);
          setAvailableStems(data.results || {});
          setAvailableStemsAudio(data.stems || {});
          setMessage(data.message || 'Transcription Complete!');
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

  /* ── Reset to home ─────────────────────────────────────── */
  const resetApp = () => {
    setFile(null);
    setUploading(false);
    setMessage('');
    setProgress(0);
    setAvailableStems({});
    setAvailableStemsAudio({});
    setActiveStem(null);
    setMusicXml(null);
  };

  /* ── Load sheet music ──────────────────────────────────── */
  const loadXmlData = async (instrumentName: string, urlPath: string) => {
    try {
      setActiveStem(instrumentName);
      setMessage(`Loading ${instrumentName} sheet music...`);
      const res = await fetch(`http://127.0.0.1:8000${urlPath}`);
      if (!res.ok) throw new Error('Failed to fetch XML file');
      const text = await res.text();
      setMusicXml(text);
      setMessage(`Viewing ${instrumentName} score`);
      // Scroll to score
      setTimeout(() => scoreRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 200);
    } catch {
      setMessage(`Error loading ${instrumentName} score`);
    }
  };

  /* ── Determine current pipeline stage ──────────────────── */
  const currentStageIndex = STAGES.findIndex((s) => progress < s.threshold);
  const isComplete = Object.keys(availableStems).length > 0 && !uploading;

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
      <div className="relative z-10 flex flex-col items-center w-full max-w-6xl px-6 py-12 lg:py-20">

        {/* ── History toggle (top-right) ────────────────── */}
        <button
          onClick={() => setHistoryOpen(true)}
          className="fixed top-5 right-5 z-30 w-10 h-10 rounded-xl bg-slate-800/60 border border-slate-700/50 hover:bg-slate-700/60 backdrop-blur-sm flex items-center justify-center transition-all hover:scale-105 active:scale-95 group shadow-lg"
          title="Transcription History"
        >
          <svg className="w-[18px] h-[18px] text-slate-400 group-hover:text-indigo-300 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </button>

        {/* ── Header ─────────────────────────────────────── */}
        <div className="text-center mb-14 space-y-4">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-slate-700/50 bg-slate-800/40 backdrop-blur-sm text-xs font-medium text-slate-400 mb-4">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            Multi-Instrument Transcription
          </div>
          <h1 className="text-5xl lg:text-7xl tracking-tight font-black text-transparent bg-clip-text bg-gradient-to-br from-white via-slate-200 to-slate-400">
            Ghost<span className="bg-gradient-to-r from-indigo-400 via-fuchsia-400 to-rose-400 bg-clip-text">Note</span>
          </h1>

          {/* Back / New Upload button - visible when results are loaded */}
          {isComplete && (
            <button
              onClick={resetApp}
              className="mt-4 inline-flex items-center gap-2 px-5 py-2 rounded-full border border-slate-700/50 bg-slate-800/40 hover:bg-slate-700/40 backdrop-blur-sm text-xs font-semibold text-slate-300 hover:text-white transition-all active:scale-95"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" />
              </svg>
              New Upload
            </button>
          )}
        </div>

        {/* ── Upload Zone ────────────────────────────────── */}
        <div className="w-full max-w-2xl mb-8">
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
                  : 'border-slate-700/60 bg-slate-900/30 hover:border-slate-500/60 hover:bg-slate-800/20'
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

            <div className="flex flex-col items-center justify-center py-10 px-6 gap-3">
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
                    Drop audio file here or <span className="text-indigo-400">browse</span>
                  </p>
                  <p className="text-xs text-slate-600">Supports MP3, WAV, M4A, FLAC</p>
                </>
              )}
            </div>
          </div>

          {/* ── Error Alert ────────────────────────────────── */}
          {file && !uploading && !isComplete && message.includes('failed') && (
            <div className="mt-6 w-full animate-fadeIn rounded-xl bg-rose-500/10 border border-rose-500/20 p-4 text-center">
              <div className="flex items-center justify-center gap-2 text-rose-400 mb-1">
                <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
                <span className="font-semibold text-sm">Error Occurred</span>
              </div>
              <p className="text-xs text-rose-300/80">{message.replace(/Transcription failed: |Upload failed: /g, '')}</p>
            </div>
          )}

          {/* ── Transcribe button ──────────────────────────── */}
          {file && !uploading && !isComplete && (
            <button
              onClick={handleUpload}
              disabled={!file || uploading}
              className="mt-4 w-full group relative overflow-hidden rounded-xl bg-gradient-to-r from-indigo-600 via-violet-600 to-fuchsia-600 px-6 py-3.5 font-bold text-white shadow-[0_0_30px_-5px_rgba(99,102,241,0.4)] transition-all hover:shadow-[0_0_40px_-5px_rgba(99,102,241,0.6)] active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <div className="absolute inset-0 bg-gradient-to-r from-indigo-500 via-violet-500 to-fuchsia-500 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
              <span className="relative flex items-center justify-center gap-2.5 text-sm tracking-wide">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                Start Transcription
              </span>
            </button>
          )}
        </div>

        {/* ── Pipeline Progress ───────────────────────────── */}
        {uploading && (
          <div className="w-full max-w-2xl mb-12 animate-fadeIn">
            <div className="backdrop-blur-xl bg-slate-900/50 rounded-2xl border border-slate-700/40 p-6">
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
              <div className="w-full bg-slate-800/60 h-1.5 rounded-full overflow-hidden">
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
                <span className="text-xs text-slate-600 font-mono tabular-nums">{progress}%</span>
              </div>
            </div>
          </div>
        )}

        {/* ── Instrument Cards Grid ──────────────────────── */}
        {isComplete && (
          <div className="w-full animate-fadeIn">
            <div className="flex flex-col items-center gap-4 mb-6">
              <div className="flex items-center gap-3 w-full">
                <div className="h-px flex-1 bg-gradient-to-r from-transparent via-slate-700/50 to-transparent" />
                <h2 className="text-sm font-bold uppercase tracking-[0.2em] text-slate-500">
                  Isolated Tracks
                </h2>
                <div className="h-px flex-1 bg-gradient-to-r from-transparent via-slate-700/50 to-transparent" />
              </div>

              {message && message.includes('completed in') && (
                <div className="text-xs font-mono font-medium text-emerald-400/90 bg-emerald-500/10 px-4 py-1.5 rounded-full border border-emerald-500/20 shadow-[0_0_15px_-3px_rgba(52,211,153,0.15)] flex items-center gap-2">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  {message}
                </div>
              )}
            </div>

            <div className="grid grid-cols-2 md:grid-cols-3 gap-3 w-full">
              {Object.entries(availableStems).map(([instrument, xmlUrl]) => {
                const audioUrl = availableStemsAudio[instrument];
                const isActive = activeStem === instrument;
                const colors = INSTRUMENT_COLORS[instrument] || INSTRUMENT_COLORS.other;
                const icon = INSTRUMENT_ICONS[instrument] || '🎵';

                return (
                  <div
                    key={instrument}
                    className={`
                      group relative overflow-hidden rounded-xl border transition-all duration-300
                      ${isActive
                        ? `border-transparent ring-2 ${colors.ring} bg-slate-800/60`
                        : 'border-slate-800/60 bg-slate-900/40 hover:bg-slate-800/40 hover:border-slate-700/60'
                      }
                    `}
                  >
                    {/* Active gradient glow */}
                    {isActive && (
                      <div className={`absolute inset-0 bg-gradient-to-br ${colors.from} ${colors.to} opacity-[0.06] pointer-events-none`} />
                    )}

                    <div className="relative p-4">
                      {/* Header row */}
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2.5">
                          <span className="text-xl">{icon}</span>
                          <h3 className="text-sm font-bold capitalize text-slate-200">
                            {instrument}
                          </h3>
                        </div>
                        <button
                          onClick={() => loadXmlData(instrument, xmlUrl)}
                          className={`
                            px-3 py-1.5 text-xs font-semibold rounded-lg transition-all duration-200 active:scale-95
                            ${isActive
                              ? `bg-gradient-to-r ${colors.from} ${colors.to} text-white shadow-lg`
                              : 'bg-slate-800/80 text-slate-400 hover:text-slate-200 hover:bg-slate-700/80 border border-slate-700/40'
                            }
                          `}
                        >
                          {isActive ? 'Viewing' : 'Score'}
                        </button>
                      </div>

                      {/* Audio player */}
                      {audioUrl && (
                        <audio
                          controls
                          src={`http://127.0.0.1:8000${audioUrl}`}
                          className="w-full h-8 opacity-70 hover:opacity-100 transition-opacity"
                        />
                      )}

                      {/* Download button (safe for Electron) */}
                      <div className="mt-2 flex justify-end">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            downloadFile(`http://127.0.0.1:8000${xmlUrl}`, `${instrument}_score.musicxml`);
                          }}
                          className="text-[10px] text-slate-600 hover:text-slate-400 transition-colors flex items-center gap-1 bg-transparent border-none cursor-pointer"
                        >
                          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                          </svg>
                          MusicXML
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ── Sheet Music Viewer ──────────────────────────── */}
        {musicXml && (
          <div ref={scoreRef} className="w-full mt-8 mb-20 animate-fadeIn">
            <div className="rounded-2xl overflow-hidden border border-slate-700/40 shadow-[0_20px_60px_-15px_rgba(0,0,0,0.6)]">
              {/* Score header bar */}
              <div className="flex items-center justify-between px-5 py-3 bg-slate-900/80 backdrop-blur-sm border-b border-slate-700/40">
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full bg-gradient-to-r ${(INSTRUMENT_COLORS[activeStem || ''] || INSTRUMENT_COLORS.other).from} ${(INSTRUMENT_COLORS[activeStem || ''] || INSTRUMENT_COLORS.other).to}`} />
                  <h2 className="text-sm font-bold text-slate-200 capitalize">
                    {activeStem} — Sheet Music
                  </h2>
                </div>
                <span className="px-2.5 py-1 bg-slate-800/60 text-slate-500 text-[10px] font-bold rounded-md uppercase tracking-widest border border-slate-700/40">
                  MusicXML
                </span>
              </div>

              {/* Score body — white background for OSMD SVGs */}
              <div className="bg-white overflow-x-auto">
                <ScoreDisplay xmlData={musicXml} />
              </div>
            </div>
          </div>
        )}

      </div>

      {/* ── History Side Panel ──────────────────────────── */}
      <HistoryPanel
        isOpen={historyOpen}
        onClose={() => setHistoryOpen(false)}
        onLoadSong={(results, stems, filename) => {
          setAvailableStems(results);
          setAvailableStemsAudio(stems);
          setActiveStem(null);
          setMusicXml(null);
          setUploading(false);
          setMessage(`Loaded: ${filename.replace(/\.[^/.]+$/, '')}`);
        }}
        onViewScore={(instrumentName, xmlUrl) => {
          loadXmlData(instrumentName, xmlUrl);
        }}
        downloadFile={downloadFile}
      />
    </main>
  );
}
