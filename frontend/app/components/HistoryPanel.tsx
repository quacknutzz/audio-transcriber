'use client';

import { useState, useEffect } from 'react';

const INSTRUMENT_ICONS: Record<string, string> = {
    vocals: '🎤',
    piano: '🎹',
    guitar: '🎸',
    bass: '🎸',
    drums: '🥁',
    other: '🎵',
    keys: '🎹',
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

    const handleDelete = async (e: React.MouseEvent, filename: string) => {
        e.stopPropagation();
        if (!window.confirm(`Permanently delete ${filename} and its generated scores from disk?`)) return;

        try {
            const res = await fetch(`http://127.0.0.1:8000/history/${encodeURIComponent(filename)}`, { method: 'DELETE' });
            if (res.ok) {
                setHistory(prev => prev.filter(item => item.filename !== filename));
                if (expandedSong === filename) setExpandedSong(null);
            }
        } catch (err) {
            console.error("Failed to delete", err);
        }
    };

    const displayName = (filename: string) => filename.replace(/\.[^/.]+$/, '');

    return (
        <>
            {/* Backdrop */}
            <div
                className={`fixed inset-0 z-40 bg-black/60 backdrop-blur-xs transition-opacity duration-200 ${isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
                onClick={onClose}
            />

            {/* Drawer */}
            <div
                className={`
                    fixed top-0 right-0 z-50 h-full w-[400px] max-w-[92vw]
                    bg-[#131211] border-l border-[#282623]
                    shadow-2xl transition-transform duration-250 ease-out
                    ${isOpen ? 'translate-x-0' : 'translate-x-full'}
                    flex flex-col text-[#ece9e3]
                `}
            >
                {/* Header */}
                <div className="flex items-center justify-between px-5 py-4 border-b border-[#252320]">
                    <div className="flex items-center gap-2.5">
                        <div className="w-7 h-7 rounded-md bg-[#22201d] border border-[#33302b] flex items-center justify-center">
                            <svg className="w-3.5 h-3.5 text-[#cfc8bd]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                        </div>
                        <h2 className="text-xs font-bold uppercase tracking-wider text-[#dedad2]">History</h2>
                    </div>
                    <button
                        onClick={onClose}
                        className="w-7 h-7 rounded-md bg-[#1e1c1a] hover:bg-[#2a2825] border border-[#2d2a27] flex items-center justify-center text-[#9c968d] hover:text-[#f0ede6] transition-colors"
                    >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>

                {/* Song list */}
                <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2.5 scrollbar-thin">
                    {loading && (
                        <div className="flex items-center justify-center py-12">
                            <div className="w-5 h-5 border-2 border-[#3d3934] border-t-[#d4cdbf] rounded-full animate-spin" />
                        </div>
                    )}

                    {!loading && history.length === 0 && (
                        <div className="text-center py-12">
                            <div className="w-10 h-10 rounded-full bg-[#1b1a18] border border-[#2d2b28] flex items-center justify-center mx-auto mb-3">
                                <svg className="w-5 h-5 text-[#6c6760]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                                </svg>
                            </div>
                            <p className="text-xs text-[#8c867e] font-medium">No transcriptions found</p>
                            <p className="text-[11px] text-[#5e5a54] mt-0.5">Upload a track to begin</p>
                        </div>
                    )}

                    {!loading && history.map((item) => {
                        const isExpanded = expandedSong === item.filename;
                        const instrumentCount = Object.keys(item.results).length;

                        return (
                            <div key={item.filename} className="rounded-xl border border-[#2a2825] bg-[#1a1917] overflow-hidden transition-all">
                                {/* Song header row */}
                                <div className="w-full flex items-center gap-2.5 px-3.5 py-3 hover:bg-[#201f1c] transition-colors">
                                    <div
                                        role="button"
                                        tabIndex={0}
                                        onClick={() => { onLoadSong(item.results, item.stems, item.filename); onClose(); }}
                                        className="flex items-center gap-2.5 flex-1 min-w-0 cursor-pointer group/title"
                                        title="Click to open this song in Studio"
                                    >
                                        <div className="w-8 h-8 rounded-lg bg-[#242220] border border-[#33302b] flex items-center justify-center shrink-0 group-hover/title:bg-[#2d2b27] transition-colors">
                                            <span className="text-sm">🎵</span>
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <p className="text-xs font-bold text-[#eae6df] group-hover/title:text-white transition-colors truncate">
                                                {displayName(item.filename)}
                                            </p>
                                            <p className="text-[10px] text-[#858077] font-mono">
                                                {instrumentCount} track{instrumentCount !== 1 ? 's' : ''} • Click to open
                                            </p>
                                        </div>
                                    </div>

                                    {/* Quick Open Button */}
                                    <button
                                        onClick={() => { onLoadSong(item.results, item.stems, item.filename); onClose(); }}
                                        className="px-2.5 py-1 text-[11px] font-semibold text-[#f0ede6] bg-[#272522] hover:bg-[#322f2b] border border-[#3d3934] rounded-lg transition-colors shrink-0"
                                        title="Open song in studio"
                                    >
                                        Open
                                    </button>

                                    {/* Expand Stems Toggle */}
                                    <button
                                        onClick={() => toggleSong(item.filename)}
                                        className="w-7 h-7 rounded-md text-[#78736b] hover:text-[#d4cdbf] hover:bg-[#252320] flex items-center justify-center transition-colors shrink-0"
                                        title="Toggle stems details"
                                    >
                                        <svg
                                            className={`w-3.5 h-3.5 transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
                                            fill="none" stroke="currentColor" viewBox="0 0 24 24"
                                        >
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
                                        </svg>
                                    </button>

                                    {/* Delete Button */}
                                    <button
                                        onClick={(e) => handleDelete(e, item.filename)}
                                        className="w-7 h-7 rounded-md text-[#66615b] hover:text-[#d17777] hover:bg-[#2c1d1d] flex items-center justify-center transition-colors shrink-0"
                                        title="Delete Transcription"
                                    >
                                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                        </svg>
                                    </button>
                                </div>

                                {/* Expanded instrument details */}
                                {isExpanded && (
                                    <div className="border-t border-[#262421] px-3 py-2 space-y-1.5 bg-[#161514]">
                                        <button
                                            onClick={() => { onLoadSong(item.results, item.stems, item.filename); onClose(); }}
                                            className="w-full flex items-center justify-center gap-2 px-3 py-1.5 rounded-lg bg-[#272522] border border-[#3b3833] text-[#ded9cf] text-xs font-semibold hover:bg-[#33302b] transition-colors mb-2"
                                        >
                                            Open in Main Studio
                                        </button>

                                        {Object.entries(item.results).map(([instrument, xmlUrl]) => {
                                            const icon = INSTRUMENT_ICONS[instrument] || '🎵';
                                            return (
                                                <div key={instrument} className="flex items-center gap-2 px-2 py-1 rounded-md hover:bg-[#1f1e1b] transition-colors">
                                                    <span className="text-sm">{icon}</span>
                                                    <span className="text-[11px] font-medium text-[#c4beb4] capitalize flex-1">{instrument}</span>

                                                    <button
                                                        onClick={() => { onViewScore(instrument, xmlUrl); onClose(); }}
                                                        className="px-2 py-0.5 text-[10px] font-semibold text-[#b8b2a7] hover:text-[#f4f1eb] bg-[#22201d] hover:bg-[#2d2b27] rounded border border-[#33302c] transition-colors"
                                                    >
                                                        Score
                                                    </button>

                                                    <button
                                                        onClick={() => downloadFile(xmlUrl.startsWith('http') ? xmlUrl : `http://127.0.0.1:8000${xmlUrl}`, `${displayName(item.filename)}_${instrument}.musicxml`)}
                                                        className="px-2 py-0.5 text-[10px] font-semibold text-[#807a72] hover:text-[#c4beb4] bg-[#1d1c1a] hover:bg-[#252421] rounded border border-[#2d2a27] transition-colors"
                                                        title="Download MusicXML"
                                                    >
                                                        XML
                                                    </button>
                                                </div>
                                            );
                                        })}

                                        {/* Audio Stems */}
                                        {Object.keys(item.stems).length > 0 && (
                                            <div className="mt-2 pt-2 border-t border-[#252320]">
                                                <p className="text-[10px] text-[#6b665f] font-mono uppercase tracking-wider mb-1 px-2">Stems Audio</p>
                                                {Object.entries(item.stems).map(([instrument, stemUrl]) => (
                                                    <div key={`stem-${instrument}`} className="px-2 py-1">
                                                        <div className="flex items-center gap-1.5 mb-1 text-[10px] text-[#858077] capitalize font-medium">
                                                            <span>{INSTRUMENT_ICONS[instrument] || '🎵'}</span>
                                                            <span>{instrument}</span>
                                                        </div>
                                                        <audio
                                                            controls
                                                            src={stemUrl.startsWith('http') ? stemUrl : `http://127.0.0.1:8000${stemUrl}`}
                                                            className="w-full opacity-70 hover:opacity-100 transition-opacity"
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
