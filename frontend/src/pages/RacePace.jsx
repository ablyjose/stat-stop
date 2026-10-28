import React, { useEffect, useState } from 'react';
import { getRacePace, getEvents, getSessions, getDrivers } from '../services/api';
import ChartContainer from '../components/ChartContainer';
import InputSelect from '../components/InputSelect';
import MultiSelect from '../components/MultiSelect';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

const RacePace = () => {
    const [data, setData] = useState([]);
    const [totalLaps, setTotalLaps] = useState(0);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [events, setEvents] = useState([]);
    const [sessions, setSessions] = useState([]);
    const [session, setSession] = useState('R');
    const [driversList, setDriversList] = useState([]);
    const [selectedDrivers, setSelectedDrivers] = useState(['RUS', 'ANT', 'LEC', 'HAM']);

    // Form State
    const currentYear = new Date().getFullYear();
    const [year, setYear] = useState(currentYear);
    const [gp, setGp] = useState('Australian Grand Prix');

    useEffect(() => {
        let active = true;
        getEvents(year).then(result => {
            if (!active) return;
            setEvents(result);
            setGp(previous => result.some(event => event.EventName === previous)
                ? previous : (result[0]?.EventName || ''));
        }).catch(console.error);
        return () => { active = false; };
    }, [year]);

    useEffect(() => {
        if (!gp) return;
        let active = true;
        getSessions(year, gp)
            .then((data) => {
                if (!active) return;
                const raceSessions = (data || []).filter(s => s.SessionKey === 'R' || s.SessionKey === 'S');
                setSessions(raceSessions);
                setSession(prev => raceSessions.some(s => s.SessionKey === prev) ? prev : 'R');
            })
            .catch(console.error);
        return () => { active = false; };
    }, [year, gp]);

    useEffect(() => {
        if (!session || !gp) return;
        let active = true;
        getDrivers(year, gp, session)
            .then((data = []) => {
                if (!active) return;
                setDriversList(data);
                const availableCodes = new Set(data.map(d => d.Driver));
                setSelectedDrivers(prev => {
                    const valid = prev.filter(c => availableCodes.has(c));
                    return valid.length ? valid : data.slice(0, 4).map(d => d.Driver);
                });
            })
            .catch(console.error);
        return () => { active = false; };
    }, [year, gp, session]);

    const fetchData = async () => {
        if (selectedDrivers.length === 0) return;
        setLoading(true);
        setError('');
        try {
            const driverQuery = selectedDrivers.join(', ');
            const result = await getRacePace(year, gp, session, driverQuery);
            setData(result.Drivers || []);
            setTotalLaps(result.TotalLaps || 0);
        } catch (err) {
            console.error(err);
            setData([]);
            setError(err.response?.data?.detail || 'Could not load race pace. Please try again.');
        } finally {
            setLoading(false);
        }
    };

    // Transform data for Recharts if needed, or use multiple Lines with their own data.
    // We'll use multiple Lines, but we need a common X-axis domain or just one dataset if laps align.
    // For race pace, laps usually align. Let's merge them for the Tooltip to work nicely.

    const processDataForChart = () => {
        if (!data.length) return [];

        // Use total laps from the session (covers full race distance including safety car laps)
        const maxLaps = totalLaps > 0 ? totalLaps : Math.max(0, ...data.flatMap(d => d.Laps.map(lap => lap.LapNumber)));
        const chartData = [];

        for (let i = 1; i <= maxLaps; i++) {
            const point = { Lap: i };
            data.forEach(d => {
                const lapParams = d.Laps.find(l => l.LapNumber === i);
                if (lapParams) {
                    point[d.Driver] = lapParams.LapTime;
                }
            });
            chartData.push(point);
        }
        return chartData;
    };

    const chartData = processDataForChart();

    // Calculate Y-axis domain
    const allLapTimes = data.flatMap(d => d.Laps.map(l => l.LapTime));
    const minTime = allLapTimes.length > 0 ? Math.min(...allLapTimes) : 0;
    const maxTime = allLapTimes.length > 0 ? Math.max(...allLapTimes) : 0;
    const yDomain = allLapTimes.length > 0
        ? [Math.floor(minTime), Math.ceil(maxTime)]
        : ['auto', 'auto'];

    return (
        <div className="page-race-pace">
            <header style={{ marginBottom: '24px' }}>
                <h1 style={{ fontSize: '2rem', fontWeight: 700 }}>Race Pace Simulation</h1>
            </header>

            <div className="card" style={{ marginBottom: '24px' }}>
                <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', alignItems: 'end' }}>
                    <InputSelect label="Year" value={year} onChange={setYear} options={Array.from({ length: currentYear - 2018 + 1 }, (_, i) => ({ label: String(currentYear - i), value: currentYear - i }))} />
                    <InputSelect label="Grand Prix" value={gp} onChange={setGp} options={events.map(e => ({ label: e.EventName, value: e.EventName }))} />
                    {sessions.length > 1 && (
                        <InputSelect label="Session" value={session} onChange={setSession} options={sessions.map(s => ({ label: s.SessionName, value: s.SessionKey }))} />
                    )}
                    <MultiSelect
                        label="Drivers"
                        value={selectedDrivers}
                        onChange={setSelectedDrivers}
                        placeholder="Select drivers..."
                        options={driversList.map((d, index) => ({
                            value: d.Driver,
                            label: `${d.Driver} - ${d.Name}`,
                            shortLabel: d.Driver,
                            title: d.Name,
                            position: index + 1
                        }))}
                    />
                    <button className="btn btn-primary" onClick={fetchData} disabled={loading || selectedDrivers.length === 0}>
                        {loading ? 'Analyze...' : 'Analyze'}
                    </button>
                </div>
            </div>

            {error && <p role="alert">{error}</p>}
            <ChartContainer title={`Lap Times Comparison - ${gp} ${year}`} height={600}>
                {chartData.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={chartData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                            <XAxis dataKey="Lap" stroke="var(--text-secondary)" />
                            <YAxis domain={yDomain} stroke="var(--text-secondary)" label={{ value: 'Time (s)', angle: -90, position: 'insideLeft' }} />
                            <Tooltip
                                contentStyle={{ backgroundColor: '#1e1e1e', borderColor: '#333' }}
                                itemStyle={{ color: '#fff' }}
                            />
                            <Legend />
                            {data.map((driverSeries, idx) => (
                                <Line
                                    key={driverSeries.Driver}
                                    type="monotone"
                                    dataKey={driverSeries.Driver}
                                    stroke={driverSeries.Color || `hsl(${idx * 60}, 70%, 50%)`}
                                    strokeWidth={2}
                                    dot={{ r: 3 }}
                                    activeDot={{ r: 6 }}
                                />
                            ))}
                        </LineChart>
                    </ResponsiveContainer>
                ) : (
                    <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
                        Select parameters and click Analyze to view data.
                    </div>
                )}
            </ChartContainer>
        </div>
    );
};

export default RacePace;
