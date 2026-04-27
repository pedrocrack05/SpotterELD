import React, { useMemo } from 'react';

// Status id → row index (0-based top to bottom)
const STATUS_ROW = { 1: 0, 2: 1, 3: 2, 4: 3 };
const STATUS_LABELS = [
  'Off Duty',
  'Sleeper Berth',
  'Driving',
  'On Duty (Not Driving)',
];
const STATUS_COLORS = {
  1: '#000000ff',
  2: '#000000ff',
  3: '#000000ff',
  4: '#000000ff',
};

// ── helpers ──────────────────────────────────────────────────────────────────

function timeFrac(isoStr, dateStr) {
  // Use UTC to avoid browser timezone offsets shifting the lines
  const dt = new Date(isoStr.endsWith('Z') ? isoStr : isoStr + 'Z');
  const dayStr = isoStr.split('T')[0];
  if (dayStr !== dateStr) return isoStr > dateStr ? 24 : 0;
  return dt.getUTCHours() + dt.getUTCMinutes() / 60 + dt.getUTCSeconds() / 3600;
}

function fracToX(frac) {
  // Maps 0–24 → 0–100 (percentage within grid)
  return (frac / 24) * 100;
}

function minsToHHMM(mins) {
  const h = Math.floor(mins / 60);
  const m = Math.round((mins % 60) / 15) * 15; // round to nearest 15 min
  return `${h}:${m.toString().padStart(2, '0')}`;
}

// ── Hour ruler ────────────────────────────────────────────────────────────────

const HourRuler = ({ dark = false, showSubticks = false }) => {
  const labels = [
    { h: 0, label: null },
    ...[1,2,3,4,5,6,7,8,9,10,11].map(h => ({ h, label: String(h) })),
    { h: 12, label: 'Noon' },
    ...[1,2,3,4,5,6,7,8,9,10,11].map((l, i) => ({ h: 13 + i, label: String(l) })),
    { h: 24, label: null },
  ];

  // Generate 15-min ticks
  const subTicks = [];
  if (showSubticks) {
    for (let h = 0; h < 24; h++) {
      subTicks.push({ h: h + 0.25, type: 'quarter' });
      subTicks.push({ h: h + 0.50, type: 'half' });
      subTicks.push({ h: h + 0.75, type: 'quarter' });
    }
  }

  return (
    <div className={`relative h-7 ${dark ? 'bg-gray-900' : 'bg-gray-800'} border-b border-gray-600 select-none`}>
      {/* Midnight */}
      <div className="absolute left-0 top-0 h-full flex flex-col items-start justify-center pl-[2px]">
        <span className="text-[7px] font-black text-white leading-[7px]">Mid-</span>
        <span className="text-[7px] font-black text-white leading-[7px]">night</span>
      </div>

      {/* Sub-ticks (15 min) */}
      {subTicks.map(({ h, type }) => (
        <div
          key={`sub-${h}`}
          className="absolute bottom-0 w-px bg-gray-500"
          style={{ 
            left: `${fracToX(h)}%`, 
            height: type === 'half' ? '6px' : '3px' 
          }}
        />
      ))}

      {labels.map(({ h, label }) => (
        <div
          key={h}
          className="absolute top-0 h-full flex items-center justify-center"
          style={{ left: `${fracToX(h)}%`, transform: 'translateX(-50%)' }}
        >
          {label && (
            <span className="text-[8px] font-black text-white">{label}</span>
          )}
          <div className="absolute bottom-0 w-px h-2.5 bg-gray-400" />
        </div>
      ))}
    </div>
  );
};

// ── Main component ────────────────────────────────────────────────────────────

const LogGrid = ({ events = [], date }) => {
  const sorted = useMemo(
    () => [...events].sort((a, b) => new Date(a.start) - new Date(b.start)),
    [events]
  );

  // Totals per status
  const totals = useMemo(() => {
    const t = { 1: 0, 2: 0, 3: 0, 4: 0 };
    events.forEach(e => { t[e.status] = (t[e.status] || 0) + e.duration_mins; });
    return t;
  }, [events]);

  // Build SVG path for the status line
  const { pathD, dots } = useMemo(() => {
    if (!sorted.length) return { pathD: '', dots: [] };
    let d = '';
    const dotList = [];
    let prevStatus = null;
    sorted.forEach((ev, i) => {
      const row   = STATUS_ROW[ev.status] ?? 0;
      const yMid  = (row + 0.5) * (100 / 4);
      const xS    = fracToX(timeFrac(ev.start, date));
      const xE    = fracToX(Math.min(24, timeFrac(ev.end, date)));

      if (i === 0) {
        d += `M ${xS} ${yMid}`;
      } else {
        d += ` L ${xS} ${yMid}`;
      }
      d += ` L ${xE} ${yMid}`;

      // Red dot ONLY when status changes
      if (ev.status !== prevStatus) {
        dotList.push({ x: xS, y: yMid, key: `dot-${i}` });
        prevStatus = ev.status;
      }
    });
    return { pathD: d, dots: dotList };
  }, [sorted, date]);

  // Remark events (non-driving key events)
  const remarkEvents = useMemo(
    () =>
      sorted.filter(e => e.action && !e.action.startsWith('Driving') && e.action !== 'Off Duty'),
    [sorted]
  );

  return (
    <div className="font-mono select-none w-full border border-gray-800 rounded-sm overflow-hidden bg-white">

      {/* ── Hour ruler header ── */}
      <div className="bg-gray-900 border-b border-gray-700 flex">
        <div className="w-28 shrink-0 flex flex-col items-start justify-center px-2 py-1 border-r border-gray-700">
          <span className="text-[10px] font-black text-gray-400 uppercase">Status</span>
        </div>
        <div className="flex-1 relative">
          <HourRuler dark />
        </div>
        <div className="w-14 shrink-0 flex flex-col items-center justify-center border-l border-gray-700 py-1">
          <span className="text-[8px] font-black text-gray-300 uppercase">Total Hrs</span>
        </div>
      </div>

      {/* ── Status rows ── */}
      <div className="relative">
        {[1, 2, 3, 4].map(statusId => {
          const row   = STATUS_ROW[statusId];
          const label = STATUS_LABELS[row];
          const color = STATUS_COLORS[statusId];
          return (
            <div key={statusId} className="flex border-b border-gray-300 last:border-0" style={{ height: '38px' }}>
              {/* Label */}
              <div
                className="w-28 shrink-0 flex items-center px-2 border-r border-gray-300 text-[10px] font-black uppercase leading-tight"
                style={{ color }}
              >
                {label.split('\n').map((l, i) => (
                  <span key={i} className="block">{l}</span>
                ))}
              </div>

              {/* Grid cell */}
              <div className="flex-1 relative overflow-hidden">
                {/* Hour lines */}
                {Array.from({ length: 25 }, (_, h) => (
                  <React.Fragment key={h}>
                    <div
                      className="absolute top-0 h-full border-l border-gray-200"
                      style={{ left: `${fracToX(h)}%` }}
                    />
                    {h < 24 && [15, 30, 45].map(m => (
                      <div
                        key={m}
                        className={`absolute border-l border-gray-200 ${row < 2 ? 'top-0' : 'bottom-0'}`}
                        style={{
                          left:   `${fracToX(h + m / 60)}%`,
                          height: m === 30 ? '50%' : '33%',
                        }}
                      />
                    ))}
                  </React.Fragment>
                ))}
              </div>

              {/* Total hours */}
              <div className="w-14 shrink-0 flex items-center justify-center border-l border-gray-300 text-[12px] font-black" style={{ color }}>
                {minsToHHMM(totals[statusId] || 0)}
              </div>
            </div>
          );
        })}

        {/* ── Status path SVG overlay (covers grid area only) ── */}
        <svg
          className="absolute inset-0 pointer-events-none"
          style={{ left: '7rem', right: '3.5rem', width: 'calc(100% - 7rem - 3.5rem)', height: '100%' }}
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
        >
          <path
            d={pathD}
            fill="none"
            stroke="#111827"
            strokeWidth="1.8"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </div>

      {/* ── Remarks section ── */}
      <div className="border-t-2 border-gray-800 bg-gray-50">
        {/* Mini ruler for remarks */}
        <div className="flex border-b border-gray-300">
          <div className="w-28 shrink-0 flex items-center px-2 border-r border-gray-300">
            <span className="text-[12px] font-black text-indigo-700 uppercase tracking-widest">Remarks</span>
          </div>
          <div className="flex-1 relative">
            <HourRuler showSubticks />
          </div>
          <div className="w-14 shrink-0 border-l border-gray-300" />
        </div>

        {/* Remark markers zone */}
        <div className="flex" style={{ minHeight: '160px' }}>
          <div className="w-28 shrink-0 border-r border-gray-300" />
          <div className="flex-1 relative overflow-hidden">
            {remarkEvents.map((ev, idx) => {
              const frac = timeFrac(ev.start, date);
              const xPct = fracToX(Math.min(24, Math.max(0, frac)));
              const city   = ev.location || '';
              const action = ev.action   || '';
              const label  = city ? `${city}` : action;
              const sub    = city ? action : '';
              return (
                <div
                  key={idx}
                  className="absolute top-0"
                  style={{ left: `${xPct}%` }}
                >
                  {/* Vertical bracket line */}
                  <div className="w-px bg-gray-600 absolute top-0" style={{ height: '130px', left: 46, top: -19, transform: 'rotate(-45deg)' }} />
                  {/* Angled text */}
                  <div
                    className="absolute whitespace-nowrap"
                    style={{
                      top: '20px',
                      left: '32px',
                      transform: 'rotate(45deg)',
                      transformOrigin: 'top left',
                    }}
                  >
                    <span className="text-[8px] font-bold text-gray-800 block leading-tight">{label}</span>
                    {sub && <span className="text-[6.5px] text-gray-500 block leading-tight">{sub}</span>}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="w-14 shrink-0 border-l border-gray-300" />
        </div>
      </div>
    </div>
  );
};

export default LogGrid;