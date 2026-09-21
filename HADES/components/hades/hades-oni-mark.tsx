export function HadesOniMark() {
  return (
    <svg
      viewBox="0 0 64 64"
      aria-hidden="true"
      className="h-[3.15rem] w-[3.15rem] shrink-0 drop-shadow-[0_0_10px_rgba(177,138,79,0.22)]"
    >
      <defs>
        <linearGradient id="hades-oni-gold" x1="8" y1="8" x2="56" y2="58" gradientUnits="userSpaceOnUse">
          <stop stopColor="#d5b679" />
          <stop offset="0.48" stopColor="#a87d3d" />
          <stop offset="1" stopColor="#6f4f27" />
        </linearGradient>
        <linearGradient id="hades-oni-steel" x1="18" y1="13" x2="45" y2="52" gradientUnits="userSpaceOnUse">
          <stop stopColor="#575651" />
          <stop offset="0.55" stopColor="#292a28" />
          <stop offset="1" stopColor="#111210" />
        </linearGradient>
      </defs>
      <path d="M10 23C5 14 8 6 13 3c.5 8 4 13 10 17l-6 8-7-5Z" fill="url(#hades-oni-gold)" stroke="#e0c48c" strokeWidth=".8" />
      <path d="M54 23c5-9 2-17-3-20-.5 8-4 13-10 17l6 8 7-5Z" fill="url(#hades-oni-gold)" stroke="#e0c48c" strokeWidth=".8" />
      <path d="M32 10c-9 0-17 7-19 17-2 11 3 24 19 32 16-8 21-21 19-32-2-10-10-17-19-17Z" fill="url(#hades-oni-steel)" stroke="#9f783f" strokeWidth="1.15" />
      <path d="M32 12v43" stroke="#bd9555" strokeWidth="1" opacity=".72" />
      <circle cx="32" cy="19" r="6.5" fill="#171816" stroke="#c99f5c" strokeWidth="1.2" />
      <circle cx="32" cy="19" r="2.1" fill="#d9b46e" />
      <path d="M17 26c4-5 9-7 15-5-4 2-7 6-8 10l-7-5Zm30 0c-4-5-9-7-15-5 4 2 7 6 8 10l7-5Z" fill="#383936" stroke="#877047" strokeWidth=".8" />
      <path d="m18 31 10 2-5 6-7-3 2-5Zm28 0-10 2 5 6 7-3-2-5Z" fill="#121311" stroke="#a17b42" strokeWidth=".8" />
      <path d="m20 33 6 1-3 2-4-1 1-2Zm24 0-6 1 3 2 4-1-1-2Z" fill="#d6aa61" />
      <path d="M32 28 27 42l5 3 5-3-5-14Z" fill="#1a1b19" stroke="#6c6555" strokeWidth=".7" />
      <path d="M19 40c3 1 6 3 8 6l-5 5-5-6 2-5Zm26 0c-3 1-6 3-8 6l5 5 5-6-2-5Z" fill="#242522" stroke="#7d6339" strokeWidth=".75" />
      <path d="M25 47c2 1 4 2 7 2s5-1 7-2l-2 7-5 3-5-3-2-7Z" fill="#10110f" stroke="#a17a40" strokeWidth=".8" />
      <path d="m26 47 2 5 2-4m8-1-2 5-2-4" stroke="#d5b679" strokeWidth="1.15" strokeLinecap="round" />
      <path d="M12 29c-2 7 0 16 5 22M52 29c2 7 0 16-5 22" fill="none" stroke="#71552f" strokeWidth="1" opacity=".7" />
    </svg>
  );
}
