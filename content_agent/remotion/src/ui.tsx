import React from 'react';
import {FONTS, usePalette} from './theme';

/** Small uppercase label used across templates. */
export const Kicker: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => {
  const p = usePalette();
  return (
    <div
      style={{
        fontFamily: FONTS.sans,
        fontWeight: 800,
        fontSize: 30,
        letterSpacing: '0.22em',
        textTransform: 'uppercase',
        color: p.accent,
        ...style,
      }}
    >
      {children}
    </div>
  );
};
