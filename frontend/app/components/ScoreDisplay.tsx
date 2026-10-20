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
                    drawingParameters: 'default',
                    autoBeam: true,
                    drawTitle: false,
                    drawSubtitle: false,
                    drawComposer: false,
                    drawCredits: false,
                    drawPartNames: false,
                    drawPartAbbreviations: false,
                    drawMeasureNumbers: true,
                    drawTimeSignatures: true,
                });

                const rules = osmdRef.current.EngravingRules;
                rules.RenderXMeasuresPerLineAkaSystem = 4;
                rules.AutoGenerateMultipleRestMeasuresFromRestMeasures = true;
                rules.RenderMultipleRestMeasures = true;
                rules.MinimumDistanceBetweenSystems = 5.0;
                rules.MinSkyBottomDistBetweenSystems = 4.5;
                rules.MeasureNumberLabelOffset = 2.2;
                rules.PercussionOneLineCutoff = 0;
                rules.StretchLastSystemLine = false;

                await osmdRef.current.load(xmlData);
                osmdRef.current.zoom = 0.95;
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
                    <div className="relative w-10 h-10">
                        <div className="absolute inset-0 rounded-full border-2 border-[#3d3934]" />
                        <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-[#d4cdbf] animate-spin" />
                    </div>
                    <p className="text-xs text-[#8a8479] font-medium">Rendering sheet music notation...</p>
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
                    padding: '28px 24px',
                }}
            />
        </div>
    );
}
