'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';

const ScoreDisplay = dynamic(() => import('./components/ScoreDisplay'), { ssr: false });

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState('');
  const [progress, setProgress] = useState(0);
  const [availableStems, setAvailableStems] = useState<{ [key: string]: string }>({});
  const [availableStemsAudio, setAvailableStemsAudio] = useState<{ [key: string]: string }>({});
  const [activeStem, setActiveStem] = useState<string | null>(null);
  const [musicXml, setMusicXml] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFile(e.target.files[0]);
    }
  };

  const handleUpload = async () => {
    if (!file) return;

    setUploading(true);
    setMessage('Warming up AI engine...');

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('http://127.0.0.1:8000/upload', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error('Upload failed');
      }

      // Reset state for new upload
      setAvailableStems({});
      setAvailableStemsAudio({});
      setActiveStem(null);
      setMusicXml(null);
      setProgress(0);

      const data = await response.json();
      setMessage(`Success: ${data.message}`);

      // Start polling for status
      const filename = data.filename;
      pollStatus(filename);

    } catch (error) {
      console.error(error);
      setMessage('Error uploading file');
      setUploading(false);
    }
  };

  const pollStatus = async (filename: string) => {
    try {
      const res = await fetch(`http://127.0.0.1:8000/status/${encodeURIComponent(filename)}?t=${Date.now()}`, {
        cache: 'no-store',
        headers: {
          'Cache-Control': 'no-cache',
        }
      });
      if (res.ok) {
        const data = await res.json();
        setMessage(data.message);
        setProgress(data.progress || 0);

        if (data.status === 'completed') {
          setUploading(false);

          // Save the results dictionary so user can pick which instrument to view
          setAvailableStems(data.results || {});
          setAvailableStemsAudio(data.stems || {});
          setMessage("Transcription Complete! Select a track below to view and play.");
          return; // Stop polling
        } else if (data.status === 'error') {
          setUploading(false);
          return; // Stop polling
        }
      }
    } catch (err) {
      console.error("Polling error", err);
    }

    // Poll again in 2 seconds
    setTimeout(() => pollStatus(filename), 2000);
  };

  const loadXmlData = async (instrumentName: string, urlPath: string) => {
    try {
      setActiveStem(instrumentName);
      setMessage(`Loading sheet music for ${instrumentName}...`);

      const res = await fetch(`http://127.0.0.1:8000${urlPath}`);
      if (!res.ok) throw new Error("Failed to fetch XML file");

      const text = await res.text();
      setMusicXml(text);
      setMessage(`Showing ${instrumentName} sheet music.`);
    } catch (e) {
      console.error(e);
      setMessage(`Error loading ${instrumentName} XML`);
    }
  };

  return (
    <main className="relative min-h-screen flex flex-col items-center p-8 lg:p-24 overflow-x-hidden bg-slate-950 text-slate-100 font-sans selection:bg-fuchsia-500/30">

      {/* Dynamic Background Effects */}
      <div className="absolute top-[0%] left-[-10%] w-[50vw] h-[50vw] bg-fuchsia-600/20 rounded-full blur-[120px] mix-blend-screen pointer-events-none" />
      <div className="absolute bottom-[0%] right-[-10%] w-[60vw] h-[60vw] bg-indigo-600/20 rounded-full blur-[120px] mix-blend-screen pointer-events-none" />

      <div className="z-10 flex flex-col items-center w-full max-w-5xl">

        <h1 className="text-5xl lg:text-7xl tracking-tight font-extrabold mb-4 text-transparent bg-clip-text bg-gradient-to-br from-indigo-400 via-fuchsia-400 to-rose-400 drop-shadow-sm text-center">
          SonicScribe AI
        </h1>
        <p className="text-lg text-slate-400 mb-12 text-center max-w-2xl">
          Upload any audio file. Our neural engine isolates the instruments and transcribes flawless sheet music in minutes.
        </p>

        {/* Upload Card */}
        <div className="w-full max-w-2xl p-8 backdrop-blur-2xl bg-slate-900/50 rounded-3xl border border-slate-700/50 shadow-[0_8px_32px_rgba(0,0,0,0.4)] transition-all duration-500 hover:border-slate-600/50">
          <div className="flex flex-col md:flex-row gap-6 items-center">

            <div className="flex-1 w-full relative group cursor-pointer">
              <div className="absolute inset-0 bg-gradient-to-r from-indigo-500 to-fuchsia-500 rounded-xl blur opacity-25 group-hover:opacity-50 transition duration-500"></div>
              <div className="relative bg-slate-900 border border-slate-800 rounded-xl p-2 flex items-center justify-between">
                <input
                  type="file"
                  onChange={handleFileChange}
                  accept="audio/*"
                  className="block w-full text-sm text-slate-400 file:mr-4 file:py-3 file:px-6 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-slate-800 file:text-indigo-400 hover:file:bg-slate-700 hover:file:text-indigo-300 transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-fuchsia-500/50"
                />
              </div>
            </div>

            <button
              onClick={handleUpload}
              disabled={!file || uploading}
              className="group relative px-8 py-4 w-full md:w-auto overflow-hidden rounded-xl bg-slate-900 font-bold text-white shadow-[0_0_40px_-10px_rgba(0,0,0,0.5)] transition-all disabled:opacity-50 disabled:cursor-not-allowed border border-slate-700 focus:outline-none focus:ring-2 focus:ring-fuchsia-500/50"
            >
              <div className="absolute inset-0 bg-gradient-to-r from-indigo-600 to-fuchsia-600 opacity-0 group-hover:opacity-100 transition-opacity duration-300"></div>
              <span className="relative flex items-center justify-center gap-2">
                {uploading ? (
                  <>
                    <svg className="animate-spin -ml-1 mr-2 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Transcribing...
                  </>
                ) : 'Transcribe Audio'}
              </span>
            </button>

          </div>

          {/* Progress Bar / Message */}
          {message && (
            <div className="mt-8 overflow-hidden rounded-2xl bg-slate-950/50 border border-slate-800/50 p-4">
              <div className="flex items-center justify-between mb-3 px-2">
                <span className={`text-sm font-medium ${message.toLowerCase().includes('error') ? 'text-rose-400' : 'text-indigo-300'}`}>
                  {message}
                </span>
                <span className="text-xs text-slate-500 font-mono">{progress}%</span>
              </div>
              <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                <div
                  className="bg-gradient-to-r from-indigo-500 via-purple-500 to-fuchsia-500 h-full transition-all duration-700 ease-out"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}
        </div>

        {/* Stems & Output Section */}
        {Object.keys(availableStems).length > 0 && (
          <div className="w-full mt-16 animate-in fade-in slide-in-from-bottom-8 duration-700">
            <h2 className="text-2xl font-bold mb-6 text-slate-200 flex items-center gap-3">
              <span className="bg-fuchsia-500/20 text-fuchsia-400 p-2 rounded-lg">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"></path></svg>
              </span>
              Separated Instrument Tracks
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 w-full">
              {Object.entries(availableStems).map(([instrument, xmlUrl]) => {
                const audioUrl = availableStemsAudio[instrument];
                const isActive = activeStem === instrument;

                return (
                  <div
                    key={instrument}
                    className={`group relative overflow-hidden backdrop-blur-xl bg-slate-900/60 border rounded-2xl p-6 transition-all duration-300 hover:shadow-[0_8px_30px_rgba(0,0,0,0.3)] ${isActive ? 'border-fuchsia-500/50 shadow-[0_0_20px_rgba(217,70,239,0.15)]' : 'border-slate-700/50 leading-relaxed hover:border-slate-500/50'}`}
                  >
                    {isActive && <div className="absolute inset-0 bg-gradient-to-br from-fuchsia-500/10 to-indigo-500/5 pointer-events-none" />}

                    <div className="flex justify-between items-start mb-4">
                      <h3 className="text-xl font-bold capitalize text-slate-200 group-hover:text-white transition-colors">
                        {instrument}
                      </h3>

                      <div className="flex gap-2 relative z-10">
                        <a
                          href={`http://127.0.0.1:8000${xmlUrl}`}
                          download={`${instrument}_sheet_music.xml`}
                          className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition-colors tooltip-trigger flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-slate-500"
                          title="Download MusicXML"
                        >
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg>
                        </a>
                        <button
                          onClick={() => loadXmlData(instrument, xmlUrl)}
                          className={`px-4 py-2 font-semibold text-sm rounded-lg transition-colors active:scale-95 focus:outline-none focus:ring-2 focus:ring-fuchsia-500/50 ${isActive ? 'bg-fuchsia-600 text-white shadow-md' : 'bg-indigo-500/20 text-indigo-300 hover:bg-indigo-500/30'}`}
                        >
                          {isActive ? 'Viewing Header' : 'View Sheet'}
                        </button>
                      </div>
                    </div>

                    {audioUrl ? (
                      <div className="mt-4 pt-4 border-t border-slate-700/50 relative z-10 w-full">
                        <span className="text-xs text-slate-400 font-medium uppercase tracking-wider mb-3 block flex items-center gap-2">
                          <svg className="w-3 h-3 text-indigo-400" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M9.383 3.076A1 1 0 0110 4v12a1 1 0 01-1.707.707L4.586 13H2a1 1 0 01-1-1V8a1 1 0 011-1h2.586l3.707-3.707a1 1 0 011.09-.217zM14.657 2.929a1 1 0 011.414 0A9.972 9.972 0 0119 10a9.972 9.972 0 01-2.929 7.071 1 1 0 01-1.414-1.414A7.971 7.971 0 0017 10c0-2.21-.894-4.208-2.343-5.657a1 1 0 010-1.414zm-2.829 2.828a1 1 0 011.415 0A5.983 5.983 0 0115 10a5.984 5.984 0 01-1.757 4.243 1 1 0 01-1.415-1.415A3.984 3.984 0 0013 10a3.983 3.983 0 00-1.172-2.828 1 1 0 010-1.415z" clipRule="evenodd"></path></svg>
                          Audio Stem
                        </span>
                        <audio
                          controls
                          src={`http://127.0.0.1:8000${audioUrl}`}
                          className="w-full h-10 outline-none rounded-full"
                        />
                      </div>
                    ) : (
                      <div className="mt-4 pt-4 border-t border-slate-700/50">
                        <span className="text-xs text-slate-500 italic">Audio stem missing</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* MusicXML Viewer */}
        {musicXml && (
          <div className="w-full mt-12 mb-20 animate-in fade-in zoom-in-95 duration-500">
            <div className="bg-slate-50 text-black p-8 rounded-3xl overflow-x-auto shadow-[0_20px_50px_rgba(0,0,0,0.5)] border border-slate-200">
              <div className="flex justify-between items-center mb-6 pb-4 border-b border-slate-200/50">
                <h2 className="text-2xl font-bold text-slate-800 capitalize flex items-center gap-3">
                  <svg className="w-6 h-6 text-fuchsia-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"></path></svg>
                  {activeStem} Score
                </h2>
                <span className="px-3 py-1 bg-fuchsia-100 text-fuchsia-700 text-xs font-bold rounded-full uppercase tracking-widest border border-fuchsia-200 shadow-sm">Interactive Sheet</span>
              </div>

              {/* OSMD handles its own dimensions, we just provide a relative container */}
              <div className="min-h-[400px]">
                <ScoreDisplay xmlData={musicXml} />
              </div>
            </div>
          </div>
        )}

      </div>
    </main>
  );
}
