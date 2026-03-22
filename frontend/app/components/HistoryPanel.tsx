'use client';

import { useState, useEffect } from 'react';

const INSTRUMENT_ICONS: Record<string, string> = {
    bass: '🎸', guitar: '🎸', piano: '🎹', drums: '🥁',
    vocals: '🎤', other: '🎵', keys: '🎹',
};

interface HistoryItem {
    filename: string;
    results: Record<string, string>;
    stems: Record<string, string>;
    message: string;
}

interface HistoryPanelProps {
    isOpen: boolean;
    onClose: () => void;
    onLoadSong: (results: Record<string, string>, stems: Record<string, string>, filename: string) => void;
    onViewScore: (instrumentName: string, xmlUrl: string) => void;
    downloadFile: (url: string, filename: string) => void;
}

export default function HistoryPanel({ isOpen, onClose, onLoadSong, onViewScore, downloadFile }: HistoryPanelProps) {
    const [history, setHistory] = useState<HistoryItem[]>([]);
    const [expandedSong, setExpandedSong] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        if (isOpen) {
            setLoading(true);
            fetch('http://127.0.0.1:8000/history')
                .then(res => res.json())
                .then(data => { setHistory(data); setLoading(false); })
                .catch(() => setLoading(false));
        }
    }, [isOpen]);

    const toggleSong = (filename: string) => {
        setExpandedSong(expandedSong === filename ? null : filename);
    };

    // Strip file extension for display
    const displayName = (filename: string) => filename.replace(/\.[^/.]+$/, '');

    return (
        <>
            {/* Backdrop */}
            <div
                className={`fixed inset-0 z-40 bg-black/50 backdrop-blur-sm transition-opacity duration-300 ${isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
                onClick={onClose}
            />

            {/* Drawer */}
            <div
                className={`
          fixed top-0 right-0 z-50 h-full w-[380px] max-w-[90vw]
          bg-slate-900/95 backdrop-blur-2xl border-l border-slate-700/50
          shadow-[-20px_0_60px_-15px_rgba(0,0,0,0.5)]
          transition-transform duration-300 ease-out
          ${isOpen ? 'translate-x-0' : 'translate-x-full'}
          flex flex-col
        `}
            >
                {/* Header */}
                <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/40">
                    <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-lg bg-indigo-500/15 flex items-center justify-center">
                            <svg className="w-4 h-4 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                        </div>
                        <h2 className="text-sm font-bold text-slate-200 tracking-wide">Transcription History</h2>
                    </div>
                    <button
                        onClick={onClose}
                        className="w-7 h-7 rounded-lg bg-slate-800/60 hover:bg-slate-700/60 flex items-center justify-center transition-colors"
                    >
                        <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>

                {/* Song list */}
                <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2 scrollbar-thin">
                    {loading && (
                        <div className="flex items-center justify-center py-12">
                            <div className="w-5 h-5 border-2 border-indigo-400/30 border-t-indigo-400 rounded-full animate-spin" />
                        </div>
                    )}

                    {!loading && history.length === 0 && (
                        <div className="text-center py-12">
                            <div className="w-12 h-12 rounded-full bg-slate-800/60 flex items-center justify-center mx-auto mb-3">
                                <svg className="w-6 h-6 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                                </svg>
                            </div>
                            <p className="text-xs text-slate-500">No transcriptions yet</p>
                            <p className="text-[10px] text-slate-600 mt-1">Upload a song to get started</p>
                        </div>
                    )}

                    {!loading && history.map((item) => {
                        const isExpanded = expandedSong === item.filename;
                        const instrumentCount = Object.keys(item.results).length;

                        return (
                            <div key={item.filename} className="rounded-xl border border-slate-700/40 bg-slate-800/30 overflow-hidden transition-all">
                                {/* Song header row */}
                                <button
                                    onClick={() => toggleSong(item.filename)}
                                    className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-700/20 transition-colors text-left"
                                >
                                    <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-indigo-500/20 to-fuchsia-500/20 flex items-center justify-center shrink-0">
                                        <svg className="w-4 h-4 text-indigo-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                                        </svg>
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <p className="text-xs font-semibold text-slate-200 truncate">{displayName(item.filename)}</p>
                                        <p className="text-[10px] text-slate-500">{instrumentCount} track{instrumentCount !== 1 ? 's' : ''}</p>
                                    </div>
                                    <svg
                                        className={`w-4 h-4 text-slate-500 transition-transform duration-200 shrink-0 ${isExpanded ? 'rotate-180' : ''}`}
                                        fill="none" stroke="currentColor" viewBox="0 0 24 24"
                                    >
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
                                    </svg>
                                </button>

                                {/* Expanded instrument list */}
                                {isExpanded && (
                                    <div className="border-t border-slate-700/30 px-3 py-2 space-y-1.5 bg-slate-900/30">
                                        {/* Load all button */}
                                        <button
                                            onClick={() => { onLoadSong(item.results, item.stems, item.filename); onClose(); }}
                                            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-xs font-semibold hover:bg-indigo-500/20 transition-colors mb-2"
                                        >
                                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                                            </svg>
                                            Load All Tracks
                                        </button>

                                        {Object.entries(item.results).map(([instrument, xmlUrl]) => {
                                            const icon = INSTRUMENT_ICONS[instrument] || '🎵';
                                            const stemUrl = item.stems[instrument];

                                            return (
                                                <div key={instrument} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-slate-800/50 transition-colors group">
                                                    <span className="text-sm">{icon}</span>
                                                    <span className="text-[11px] font-medium text-slate-300 capitalize flex-1">{instrument}</span>

                                                    {/* View score */}
                                                    <button
                                                        onClick={() => { onViewScore(instrument, xmlUrl); onClose(); }}
                                                        className="px-2 py-1 text-[10px] font-semibold text-slate-400 hover:text-indigo-300 bg-slate-800/60 hover:bg-indigo-500/10 rounded-md transition-all border border-transparent hover:border-indigo-500/20"
                                                    >
                                                        Score
                                                    </button>

                                                    {/* Download */}
                                                    <button
                                                        onClick={() => downloadFile(`http://127.0.0.1:8000${xmlUrl}`, `${instrument}_score.musicxml`)}
                                                        className="px-2 py-1 text-[10px] font-semibold text-slate-500 hover:text-slate-300 bg-slate-800/40 hover:bg-slate-700/40 rounded-md transition-all"
                                                    >
                                                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                                                        </svg>
                                                    </button>
                                                </div>
                                            );
                                        })}

                                        {/* Stems audio section */}
                                        {Object.keys(item.stems).length > 0 && (
                                            <div className="mt-2 pt-2 border-t border-slate-700/20">
                                                <p className="text-[10px] text-slate-600 font-medium uppercase tracking-wider mb-1.5 px-2">Audio Stems</p>
                                                {Object.entries(item.stems).map(([instrument, stemUrl]) => (
                                                    <div key={`stem-${instrument}`} className="px-2 py-1">
                                                        <div className="flex items-center gap-2 mb-1">
                                                            <span className="text-[10px] text-slate-500 capitalize">{instrument}</span>
                                                        </div>
                                                        <audio
                                                            controls
                                                            src={`http://127.0.0.1:8000${stemUrl}`}
                                                            className="w-full h-7 opacity-60 hover:opacity-100 transition-opacity"
                                                        />
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        </>
    );
}
