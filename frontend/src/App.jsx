import React, { useState } from 'react';
import LogGrid from './components/LogGrid';
import MapView from './components/MapView';

// ── Field components ──────────────────────────────────────────────────────────

const Field = ({ label, id, ...props }) => (
  <div>
    <label htmlFor={id} className="block text-[9px] font-black text-slate-500 uppercase tracking-widest mb-1">
      {label}
    </label>
    <input
      id={id}
      className="w-full bg-slate-50 border-2 border-slate-100 p-2 text-sm rounded-lg focus:border-indigo-500 outline-none transition-colors"
      {...props}
    />
  </div>
);

const SectionTitle = ({ children, isOpen, onToggle, collapsible = false }) => (
  <div 
    className={`flex justify-between items-center border-b border-slate-100 pb-1 mt-4 mb-3 ${collapsible ? 'cursor-pointer hover:bg-slate-50 transition-colors px-1' : ''}`}
    onClick={collapsible ? onToggle : undefined}
  >
    <h2 className="text-[9px] font-black text-slate-400 uppercase tracking-[0.2em]">
      {children}
    </h2>
    {collapsible && (
      <svg className={`w-3 h-3 text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M19 9l-7 7-7-7" />
      </svg>
    )}
  </div>
);

// ── Location Autocomplete ─────────────────────────────────────────────────────

const LocationInput = ({ label, value, onChange, placeholder }) => {
  const [suggestions, setSuggestions] = useState([]);
  const [show, setShow] = useState(false);

  const handleSearch = async (query) => {
    onChange(query);
    if (query.length < 3) {
      setSuggestions([]);
      return;
    }
    try {
      const res = await fetch(`https://photon.komoot.io/api/?q=${encodeURIComponent(query)}&limit=5`);
      const data = await res.json();
      const items = data.features.map(f => {
        const p = f.properties;
        return [p.name, p.state, p.country].filter(Boolean).join(', ');
      });
      setSuggestions([...new Set(items)]);
      setShow(true);
    } catch {
      setSuggestions([]);
    }
  };

  return (
    <div className="relative">
      <Field 
        label={label} 
        placeholder={placeholder} 
        value={value} 
        onChange={e => handleSearch(e.target.value)}
        onBlur={() => setTimeout(() => setShow(false), 200)}
        onFocus={() => value.length >= 3 && setShow(true)}
      />
      {show && suggestions.length > 0 && (
        <div className="absolute z-50 w-full bg-white border-2 border-slate-200 rounded-lg shadow-2xl mt-1 overflow-hidden">
          {suggestions.map((s, i) => (
            <div 
              key={i}
              className="p-2 text-xs hover:bg-indigo-50 cursor-pointer border-b border-slate-50 last:border-0 font-bold text-slate-700"
              onClick={() => {
                onChange(s);
                setSuggestions([]);
                setShow(false);
              }}
            >
              {s}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ── App ───────────────────────────────────────────────────────────────────────

function App() {

  const API_URL = import.meta.env.VITE_API_URL || '';
  // Trip params
  const [currentLoc,  setCurrentLoc]  = useState('');
  const [pickupLoc,   setPickupLoc]   = useState('');
  const [dropoffLoc,  setDropoffLoc]  = useState('');
  const [cycleUsed,   setCycleUsed]   = useState(0);
  const [startTime,   setStartTime]   = useState(
    new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  );
  const [startDate,   setStartDate]   = useState(
    new Date().toISOString().split('T')[0]
  );

  // Driver info (for PDF)
  const [driverName,       setDriverName]       = useState('');
  const [coDriver,         setCoDriver]         = useState('');
  const [carrier,          setCarrier]          = useState('');
  const [truckNo,          setTruckNo]          = useState('');
  const [trailerNo,        setTrailerNo]        = useState('');
  const [homeTerminal,     setHomeTerminal]     = useState('');
  const [shippingDoc,      setShippingDoc]      = useState('');
  const [shipperCommodity, setShipperCommodity] = useState('');

  // Results
  const [logsByDay,    setLogsByDay]    = useState({});
  const [route,        setRoute]        = useState(null);
  const [stopMarkers,  setStopMarkers]  = useState([]);
  const [loading,      setLoading]      = useState(false);
  const [pdfLoading,   setPdfLoading]   = useState(false);
  const [error,        setError]        = useState(null);

  // UI state
  const [showDriverInfo, setShowDriverInfo] = useState(false);
  const [showShipInfo,   setShowShipInfo]   = useState(false);

  const hasResults = Object.keys(logsByDay).length > 0;

  // ── Calculate ──────────────────────────────────────────────────────────────

  const handleCalculate = async () => {
    setLoading(true);
    setError(null);
    setLogsByDay({});
    setRoute(null);
    setStopMarkers([]);

    try {
      const res = await fetch(`${API_URL}/api/logs/calculate/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_loc:  currentLoc,
          pickup_loc:   pickupLoc,
          dropoff_loc:  dropoffLoc,
          cycle_used:   parseFloat(cycleUsed) || 0,
          start_time:   `${startDate}T${startTime}:00`,
        }),
      });

      const data = await res.json();
      if (!res.ok) { setError(data.error || 'Calculation error'); return; }

      setLogsByDay(data.logs);
      setRoute(data.route);
      setStopMarkers(data.stop_markers || []);
    } catch {
      setError('Connection error. Is the Django server running?');
    } finally {
      setLoading(false);
    }
  };

  // ── Download PDF ───────────────────────────────────────────────────────────

  const handleDownloadPdf = async () => {
    if (!hasResults) return;
    setPdfLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/logs/generate-pdf/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          logs:         logsByDay,
          route,
          current_loc:  currentLoc,
          dropoff_loc:  dropoffLoc,
          driver_info: {
            driver_name:       driverName,
            co_driver:         coDriver,
            carrier,
            truck_no:          truckNo,
            trailer_no:        trailerNo,
            home_terminal:     homeTerminal,
            shipping_doc:      shippingDoc,
            shipper_commodity: shipperCommodity,
          },
        }),
      });

      if (!res.ok) {
        const d = await res.json();
        setError(d.error || 'PDF generation failed');
        return;
      }

      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href     = url;
      a.download = 'drivers_daily_log.pdf';
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError('PDF download failed. Is the server running?');
    } finally {
      setPdfLoading(false);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="h-screen bg-slate-50 flex flex-col overflow-hidden font-sans">

      {/* ── Header ── */}
      <header className="bg-slate-900 text-white px-6 py-3 shadow-xl z-10 flex justify-between items-center shrink-0">
        <div className="flex items-center gap-3">
          <div className="bg-indigo-600 w-9 h-9 rounded-lg flex items-center justify-center font-black italic text-xl">S</div>
          <div>
            <h1 className="text-lg font-black tracking-tighter uppercase italic leading-none">
              SPOTTER <span className="text-indigo-400">TRUCKS</span>
            </h1>
            <p className="text-[9px] text-slate-400 font-bold uppercase tracking-widest">Advanced HOS &amp; ELD Engine</p>
          </div>
        </div>
        {hasResults && (
          <button
            onClick={handleDownloadPdf}
            disabled={pdfLoading}
            className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-[10px] font-black uppercase tracking-widest px-4 py-2 rounded-lg transition-colors shadow-lg"
          >
            {pdfLoading ? (
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 10v6m0 0l-3-3m3 3l3-3M3 17v3a1 1 0 001 1h16a1 1 0 001-1v-3" />
              </svg>
            )}
            {pdfLoading ? 'Generating...' : 'Download Daily Log PDF'}
          </button>
        )}
      </header>

      <main className="flex-1 flex overflow-hidden">

        {/* ── Sidebar ── */}
        <aside className="w-80 shrink-0 flex flex-col border-r border-slate-200 bg-white shadow-xl z-20 overflow-y-auto">
          {/* Map */}
          <div className="flex-1 min-h-[220px] border-t border-slate-200">
            <MapView routeData={route} stopMarkers={stopMarkers} />
          </div>
          <div className="p-5 space-y-1">

            {/* Trip Parameters */}
            <SectionTitle>Trip Parameters</SectionTitle>
            <div className="space-y-3">
              <LocationInput label="Current Location *" placeholder="Start city..."
                value={currentLoc} onChange={setCurrentLoc} />
              <LocationInput label="Pickup Location *" placeholder="Loading city..."
                value={pickupLoc} onChange={setPickupLoc} />
              <LocationInput label="Dropoff Location *" placeholder="Destination..."
                value={dropoffLoc} onChange={setDropoffLoc} />
              <div className="grid grid-cols-2 gap-3">
                <Field id="startDate" label="Departure Date *" type="date"
                  value={startDate} onChange={e => setStartDate(e.target.value)} />
                <Field id="startTime" label="Time *" type="time"
                  value={startTime} onChange={e => setStartTime(e.target.value)} />
              </div>
              <Field id="cycleUsed" label="Cycle Used (Hrs) *" type="number" min="0" max="70"
                value={cycleUsed} onChange={e => setCycleUsed(e.target.value)} />
            </div>

            {/* Driver Info */}
            <SectionTitle collapsible isOpen={showDriverInfo} onToggle={() => setShowDriverInfo(!showDriverInfo)}>
              Driver Information
            </SectionTitle>
            {showDriverInfo && (
              <div className="space-y-3 animate-in fade-in slide-in-from-top-2 duration-200">
                <Field id="driverName" label="Driver Name" placeholder="Full name"
                  value={driverName} onChange={e => setDriverName(e.target.value)} />
                <Field id="coDriver" label="Co-Driver" placeholder="Full name"
                  value={coDriver} onChange={e => setCoDriver(e.target.value)} />
                <Field id="carrier" label="Carrier Name" placeholder="Company name"
                  value={carrier} onChange={e => setCarrier(e.target.value)} />
                <div className="grid grid-cols-2 gap-3">
                  <Field id="truckNo" label="Truck / Vehicle No." placeholder="e.g. TRK-001"
                    value={truckNo} onChange={e => setTruckNo(e.target.value)} />
                  <Field id="trailerNo" label="Trailer No." placeholder="optional"
                    value={trailerNo} onChange={e => setTrailerNo(e.target.value)} />
                </div>
                <Field id="homeTerminal" label="Home Terminal" placeholder="City, State"
                  value={homeTerminal} onChange={e => setHomeTerminal(e.target.value)} />
              </div>
            )}

            {/* Shipping Info */}
            <SectionTitle collapsible isOpen={showShipInfo} onToggle={() => setShowShipInfo(!showShipInfo)}>
              Shipping Information
            </SectionTitle>
            {showShipInfo && (
              <div className="space-y-3 animate-in fade-in slide-in-from-top-2 duration-200">
                <Field id="shippingDoc" label="Shipping Doc / Bill of Lading" placeholder="Doc number"
                  value={shippingDoc} onChange={e => setShippingDoc(e.target.value)} />
                <Field id="shipperCommodity" label="Shipper & Commodity" placeholder="e.g. ACME Corp – Steel coils"
                  value={shipperCommodity} onChange={e => setShipperCommodity(e.target.value)} />
              </div>
            )}

            {/* Calculate button */}
            <button
              onClick={handleCalculate}
              disabled={loading || !currentLoc || !pickupLoc || !dropoffLoc || !startDate || !startTime}
              className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white py-3 rounded-xl font-black text-[10px] uppercase tracking-widest transition-all shadow-lg shadow-indigo-200 mt-4"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                  Calculating Route...
                </span>
              ) : 'Generate Trip Logs'}
            </button>

            {/* Route summary */}
            {route && (
              <div className="p-4 bg-indigo-50 rounded-xl border border-indigo-100 space-y-2">
                <h3 className="text-[9px] font-black text-indigo-500 uppercase tracking-widest">Route Summary</h3>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <p className="text-[8px] text-indigo-400 font-bold uppercase">Distance</p>
                    <p className="text-base font-black text-indigo-900">
                      {route.distance_miles?.toLocaleString()} <span className="text-[9px]">mi</span>
                    </p>
                    <p className="text-[8px] text-indigo-300">{route.distance_km?.toLocaleString()} km</p>
                  </div>
                  <div>
                    <p className="text-[8px] text-indigo-400 font-bold uppercase">Drive Time</p>
                    <p className="text-base font-black text-indigo-900">
                      {Math.floor((route.duration_mins || 0) / 60)}h {(route.duration_mins || 0) % 60}m
                    </p>
                  </div>
                </div>
                <p className="text-[8px] text-indigo-400 font-bold uppercase">Log Days</p>
                <p className="text-sm font-black text-indigo-900">{Object.keys(logsByDay).length} day(s)</p>
              </div>
            )}

            {/* Error */}
            {error && (
              <div className="p-3 bg-rose-50 border-2 border-rose-200 text-rose-600 text-[9px] font-black rounded-xl">
                ⚠️ {error}
              </div>
            )}
          </div>
        </aside>

        {/* ── Log sheets ── */}
        <section className="flex-1 p-8 overflow-y-auto bg-slate-50">
          <div className="max-w-5xl mx-auto space-y-10">
            {hasResults ? (
              Object.entries(logsByDay).map(([date, dayEvents]) => {
                const driveMins  = dayEvents.filter(e => e.status === 3).reduce((s, e) => s + e.duration_mins, 0);
                const onDutyMins = dayEvents.filter(e => e.status === 4).reduce((s, e) => s + e.duration_mins, 0);
                return (
                  <div key={date} className="bg-white rounded-2xl shadow-xl shadow-slate-200/60 overflow-hidden border border-slate-100">
                    {/* Day header */}
                    <div className="bg-slate-900 px-6 py-4 flex justify-between items-center">
                      <div>
                        <p className="text-[8px] font-black text-indigo-400 uppercase tracking-[0.3em]">HOS Log Sheet</p>
                        <h3 className="text-xl font-black text-white tracking-tight">{date}</h3>
                      </div>
                      <div className="text-right space-y-1">
                        <p className="text-[10px] text-slate-400 font-mono">Property-carrying 70 hr / 8 day</p>
                        <div className="flex gap-4 justify-end">
                          <span className="text-[13px] text-green-400 font-bold">
                            🚛 Drive: {Math.floor(driveMins/60)}h {driveMins%60}m
                          </span>
                          <span className="text-[13px] text-amber-400 font-bold">
                            ⚙️ On Duty: {Math.floor(onDutyMins/60)}h {onDutyMins%60}m
                          </span>
                      </div>
                        </div>
                    </div>
                    <div className="p-6">
                      <LogGrid events={dayEvents} date={date} />
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-slate-300 space-y-4 pt-24">
                <svg className="w-24 h-24 opacity-20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1"
                    d="M9 17a2 2 0 11-4 0 2 2 0 014 0zM19 17a2 2 0 11-4 0 2 2 0 014 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1"
                    d="M13 16V6a1 1 0 00-1-1H4a1 1 0 00-1 1v10a1 1 0 001 1h1m8-1a1 1 0 01-1 1H9m4-1V8a1 1 0 011-1h2.586a1 1 0 01.707.293l3.414 3.414a1 1 0 01.293.707V16a1 1 0 01-1 1h-1m-6-1a1 1 0 001 1h1M5 17a2 2 0 104 0m-4 0a2 2 0 114 0m6 0a2 2 0 104 0m-4 0a2 2 0 114 0" />
                </svg>
                <p className="font-black text-xs uppercase tracking-[0.4em]">Fill in trip parameters to generate your ELD logs</p>
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;