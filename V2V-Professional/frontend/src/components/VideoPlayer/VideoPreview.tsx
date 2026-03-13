import { useRef, useState } from 'react';
import { useProjectStore } from '@/store/useProjectStore';
import ReactPlayer from 'react-player';
import { Play, Pause, Volume2, VolumeX, Maximize, Minimize } from 'lucide-react';

export function VideoPreview() {
  const { currentProject } = useProjectStore();
  const playerRef = useRef<any>(null);
  const [playing, setPlaying] = useState(false);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const [played, setPlayed] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const videoUrl = currentProject?.video_path;

  if (!videoUrl) {
    return (
      <div className="flex items-center justify-center h-full bg-black rounded-lg">
        <p className="text-white/50">No hay video disponible</p>
      </div>
    );
  }

  const handleProgress = (state: { played: number; playedSeconds: number }) => {
    setPlayed(state.played);
  };

  const handleDuration = (dur: number) => {
    setDuration(dur);
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = parseFloat(e.target.value);
    playerRef.current?.seekTo(value);
    setPlayed(value);
  };

  const toggleFullscreen = () => {
    setIsFullscreen(!isFullscreen);
  };

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className={`relative bg-black rounded-lg overflow-hidden ${isFullscreen ? 'fixed inset-0 z-50' : ''}`}>
      <ReactPlayer
        ref={playerRef}
        url={videoUrl}
        playing={playing}
        volume={volume}
        muted={muted}
        onProgress={handleProgress}
        onDuration={handleDuration}
        width="100%"
        height={isFullscreen ? '100%' : 'auto'}
        style={{ aspectRatio: '16/9' }}
      />
      
      {/* Controls overlay */}
      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-4">
        {/* Progress bar */}
        <input
          type="range"
          min={0}
          max={duration || 1}
          step={0.1}
          value={played}
          onChange={handleSeek}
          className="w-full h-1 bg-white/30 rounded-lg appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:rounded-full"
        />
        
        <div className="flex items-center justify-between mt-2">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPlaying(!playing)}
              className="p-2 hover:bg-white/20 rounded-full transition-colors"
            >
              {playing ? (
                <Pause className="w-5 h-5 text-white" />
              ) : (
                <Play className="w-5 h-5 text-white" />
              )}
            </button>
            
            <div className="flex items-center gap-2">
              <button
                onClick={() => setMuted(!muted)}
                className="p-2 hover:bg-white/20 rounded-full transition-colors"
              >
                {muted ? (
                  <VolumeX className="w-5 h-5 text-white" />
                ) : (
                  <Volume2 className="w-5 h-5 text-white" />
                )}
              </button>
              <input
                type="range"
                min={0}
                max={1}
                step={0.1}
                value={muted ? 0 : volume}
                onChange={(e) => setVolume(parseFloat(e.target.value))}
                className="w-20 h-1 bg-white/30 rounded-lg appearance-none cursor-pointer"
              />
            </div>
            
            <span className="text-white text-sm">
              {formatTime(played)} / {formatTime(duration)}
            </span>
          </div>
          
          <button
            onClick={toggleFullscreen}
            className="p-2 hover:bg-white/20 rounded-full transition-colors"
          >
            {isFullscreen ? (
              <Minimize className="w-5 h-5 text-white" />
            ) : (
              <Maximize className="w-5 h-5 text-white" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
