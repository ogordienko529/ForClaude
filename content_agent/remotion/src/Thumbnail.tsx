import '@fontsource/montserrat/900.css';
import React, {useEffect, useState} from 'react';
import {AbsoluteFill, continueRender, delayRender, Img, staticFile} from 'remotion';

export type ThumbnailProps = {image: string; title: string; tag?: string; accent?: string};

/** YouTube thumbnail (1280x720): a frame from the video, dark gradient, 2-5 huge words, a tag. */
export const Thumbnail: React.FC<ThumbnailProps> = ({image, title, tag, accent = '#ffd21f'}) => {
  const [handle] = useState(() => delayRender('font'));
  useEffect(() => {
    document.fonts.load('900 80px Montserrat').catch(() => undefined).then(() => continueRender(handle));
  }, [handle]);
  const words = title.split(/(\*[^*]+\*)/).filter(Boolean);
  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      {image ? <Img src={staticFile(image)} style={{width: '100%', height: '100%', objectFit: 'cover'}} /> : null}
      <AbsoluteFill style={{background: 'linear-gradient(90deg, rgba(0,0,0,0.78) 0%, rgba(0,0,0,0.35) 55%, rgba(0,0,0,0) 80%)'}} />
      <div style={{position: 'absolute', left: 56, top: 70, width: 760}}>
        {tag ? (
          <div style={{display: 'inline-block', padding: '8px 20px', borderRadius: 10, background: accent, color: '#111',
            fontFamily: '"Montserrat", sans-serif', fontWeight: 900, fontSize: 34, marginBottom: 22, textTransform: 'uppercase'}}>
            {tag}
          </div>
        ) : null}
        <div style={{fontFamily: '"Montserrat", sans-serif', fontWeight: 900, fontSize: 104, lineHeight: 1.02, color: '#fff',
          textTransform: 'uppercase', WebkitTextStroke: '14px #000', paintOrder: 'stroke fill', textShadow: '0 10px 0 rgba(0,0,0,0.5)'}}>
          {words.map((w, i) => (w.startsWith('*') ? <span key={i} style={{color: accent}}>{w.slice(1, -1)}</span> : <span key={i}>{w}</span>))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
