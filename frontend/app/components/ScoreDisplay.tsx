'use client';

import React, { useEffect, useRef, useState } from 'react';
import { OpenSheetMusicDisplay } from 'opensheetmusicdisplay';

interface ScoreDisplayProps {
    xmlData: string;
}

export default function ScoreDisplay({ xmlData }: ScoreDisplayProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const osmdRef = useRef<OpenSheetMusicDisplay | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!containerRef.current || !xmlData) return;

        setLoading(true);
        setError(null);

        const setupOsmd = async () => {
            try {
                // Clear previous render
                containerRef.current!.innerHTML = '';

                osmdRef.current = new OpenSheetMusicDisplay(containerRef.current!, {
                    autoResize: true,
                    backend: 'svg',
                    drawingParameters: 'compacttight',
                    drawTitle: true,
                    drawComposer: false,
                    drawCredits: false,
                    drawPartNames: true,
                    drawPartAbbreviations: false,
                    drawMeasureNumbers: true,
                    drawTimeSignatures: true,
                });

                await osmdRef.current.load(xmlData);
                osmdRef.current.render();
                setLoading(false);
            } catch (e) {
                console.error('OSMD Render Error:', e);
                setError('Failed to render sheet music. The MusicXML file may be invalid.');
                setLoading(false);
            }
        };

        setupOsmd();
    }, [xmlData]);

    return (
        <div className="relative">
            {/* Loading overlay */}
            {loading && (
                <div className="flex flex-col items-center justify-center py-20 gap-4">
                    <div className="relative w-12 h-12">
                        <div className="absolute inset-0 rounded-full border-2 border-indigo-200/30" />
                        <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-indigo-500 animate-spin" />
                    </div>
                    <p className="text-sm text-slate-500 font-medium">Rendering sheet music...</p>
                </div>
            )}

            {/* Error display */}
            {error && (
                <div className="flex flex-col items-center justify-center py-16 gap-3">
                    <svg className="w-10 h-10 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                    </svg>
                    <p className="text-sm text-rose-500 font-medium">{error}</p>
                </div>
            )}

            {/* OSMD Container — white background critical for SVG readability */}
            <div
                ref={containerRef}
                className="w-full min-h-[300px] bg-white rounded-xl"
                style={{
                    display: loading || error ? 'none' : 'block',
                    background: '#ffffff',
                    padding: '24px 16px',
                }}
            />
        </div>
    );
}
