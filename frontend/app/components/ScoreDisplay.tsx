'use client';

import React, { useEffect, useRef } from 'react';
import { OpenSheetMusicDisplay } from 'opensheetmusicdisplay';

interface ScoreDisplayProps {
    xmlData: string;
}

export default function ScoreDisplay({ xmlData }: ScoreDisplayProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const osmdRef = useRef<OpenSheetMusicDisplay | null>(null);

    useEffect(() => {
        if (!containerRef.current || !xmlData) return;

        const setupOsmd = async () => {
            // Clear previous
            containerRef.current!.innerHTML = '';

            osmdRef.current = new OpenSheetMusicDisplay(containerRef.current!, {
                autoResize: true,
                backend: 'svg',
                drawingParameters: 'compacttight', // optimize for screen
            });

            try {
                await osmdRef.current.load(xmlData);
                osmdRef.current.render();
            } catch (e) {
                console.error('OSMD Render Error:', e);
            }
        };

        setupOsmd();
    }, [xmlData]);

    return <div ref={containerRef} className="w-full h-full min-h-[500px]" />;
}
