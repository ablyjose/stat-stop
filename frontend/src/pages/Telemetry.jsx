import React, { useEffect, useState } from 'react';
import { getTelemetry, getEvents } from '../services/api';
import ChartContainer from '../components/ChartContainer';
import InputSelect from '../components/InputSelect';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine } from 'recharts';

const TelemetryChart = React.memo(({ data, title, dataKey, yLabel, syncId = "telemetryId" }) => {
    const chartData = React.useMemo(() => {
        if (!data || !data.Driver1 || !data.Driver2) return [];
        const d1 = data.Driver1.Telemetry;
        const d2 = data.Driver2.Telemetry;

        const interpolate = (x, x0, y0, x1, y1) => {
            if (x1 === x0) return y0;
            return y0 + ((x - x0) * (y1 - y0)) / (x1 - x0);
        };

        let d2Idx = 0;
        return d1.map(p1 => {
            const dist = p1.Distance;
            const val1 = p1[dataKey];
            let val2 = null;

            // Find segment in d2
            while (d2Idx < d2.length - 1 && d2[d2Idx + 1].Distance < dist) {
                d2Idx++;
            }

            const p2Prev = d2[d2Idx];
            const p2Next = d2[d2Idx + 1];

            if (p2Prev) {
                if (p2Next && dist > p2Prev.Distance) {
                    val2 = interpolate(dist, p2Prev.Distance, p2Prev[dataKey], p2Next.Distance, p2Next[dataKey]);
                } else {
                    val2 = p2Prev[dataKey];
                }
            }

            return {
                Distance: dist,
                Driver1Value: val1,
                Driver2Value: val2
            };
        });
    }, [data, dataKey]);

    return (
        <ChartContainer title={title} height={300}>
            {data ? (
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} syncId={syncId}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                        <XAxis dataKey="Distance" type="number" domain={['auto', 'auto']} stroke="var(--text-secondary)" tick={false} />
                        <YAxis stroke="var(--text-secondary)" label={{ value: yLabel, angle: -90, position: 'insideLeft' }} domain={['auto', 'auto']} />
                        <Tooltip
                            labelFormatter={(v) => `Dist: ${Math.round(v)}m`}
                            contentStyle={{ backgroundColor: '#1e1e1e', borderColor: '#333' }}
                            formatter={(value) => Number(value).toFixed(2)}
                        />
                        <Legend />
                        <Line
                            dataKey="Driver1Value"
                            name={data.Driver1.Name}
                            stroke={data.Driver1.Color}
                            dot={false}
                            strokeWidth={2}
                        />
                        <Line
                            dataKey="Driver2Value"
                            name={data.Driver2.Name}
                            stroke={data.Driver2.Color}
                            dot={false}
                            strokeWidth={2}
                            strokeDasharray="4 4"
                        />
                        {data.Corners && data.Corners.map((corner, idx) => (
                            <ReferenceLine
                                key={idx}
                                x={corner.Distance}
                                stroke="#444"
                                strokeDasharray="3 3"
                                label={{
                                    value: corner.Number + corner.Letter,
                                    position: 'bottom',
                                    fill: 'var(--text-secondary)',
                                    fontSize: 10
                                }}
                            />
                        ))}
                    </LineChart>
                </ResponsiveContainer>
            ) : (
                <div className="placeholder-text">Load data to view</div>
            )}
        </ChartContainer>
    );
});

// const Telemetry = () => {

const Telemetry = () => {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [events, setEvents] = useState([]);

    // Form
    const [year, setYear] = useState(2026);
    const [gp, setGp] = useState('Australia');
    const [session, setSession] = useState('Q');
    const [driver1, setDriver1] = useState('RUS');
    const [driver2, setDriver2] = useState('ANT');

    useEffect(() => {
        getEvents(year).then(setEvents).catch(console.error);
    }, [year]);

    const fetchData = async () => {
        setLoading(true);
        try {
            const result = await getTelemetry(year, gp, session, driver1, driver2);
            setData(result);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="page-telemetry">
            <header>
                <h1 style={{ fontSize: '2rem', fontWeight: 700 }}>Telemetry Analysis</h1>
            </header>

            {/* Event Selection */}
            <div className="card" style={{ margin: '24px 0' }}>
                <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', alignItems: 'end' }}>
                    <InputSelect label="Year" value={year} onChange={setYear} options={[2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026].map(y => ({ label: y, value: y }))} />
                    <InputSelect label="Event" value={gp} onChange={setGp} options={events.map(e => ({ label: e.EventName, value: e.EventName }))} />
                    <InputSelect label="Session" value={session} onChange={setSession} options={[{ label: 'Practice 1', value: 'FP1' }, { label: 'Practice 2', value: 'FP2' }, { label: 'Practice 3', value: 'FP3' }, { label: 'Sprint Qualifying', value: 'SQ' }, { label: 'Sprint', value: 'S' }, { label: 'Qualifying', value: 'Q' }, { label: 'Race', value: 'R' }]} />

                    <div className="input-group">
                        <label style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>Driver 1</label>
                        <input className="input-text" value={driver1} onChange={e => setDriver1(e.target.value)} />
                    </div>
                    <div className="input-group">
                        <label style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>Driver 2</label>
                        <input className="input-text" value={driver2} onChange={e => setDriver2(e.target.value)} />
                    </div>

                    <button className="btn btn-primary" onClick={fetchData} disabled={loading}>
                        {loading ? 'Loading...' : 'Compare'}
                    </button>
                </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                <ChartContainer title="Time Delta" height={250}>
                    {data && data.Delta ? (
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={data.Delta}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                                <XAxis dataKey="Distance" type="number" domain={['auto', 'auto']} stroke="var(--text-secondary)" tick={false} />
                                <YAxis stroke="var(--text-secondary)" label={{ value: 'Delta (s)', angle: -90, position: 'insideLeft' }} />
                                <Tooltip
                                    contentStyle={{ backgroundColor: '#1e1e1e', borderColor: '#333' }}
                                    labelFormatter={(v) => `Dist: ${Math.round(v)}m`}
                                    formatter={(value) => Number(value).toFixed(3)}
                                />
                                <ReferenceLine y={0} stroke={data.Driver1.Color} strokeWidth={0.75} />
                                {data.Corners && data.Corners.map((corner, idx) => (
                                    <ReferenceLine
                                        key={idx}
                                        x={corner.Distance}
                                        stroke="#444"
                                        strokeDasharray="3 3"
                                        label={{
                                            value: corner.Number + corner.Letter,
                                            position: 'bottom',
                                            fill: 'var(--text-secondary)',
                                            fontSize: 10
                                        }}
                                    />
                                ))}
                                <Line type="monotone" dataKey="Delta" stroke={data.Driver2.Color} dot={false} strokeWidth={2} name={`Gap to ${data.Driver1.Name}`} />
                            </LineChart>
                        </ResponsiveContainer>
                    ) : <div className="placeholder-text">Load data to view</div>}
                </ChartContainer>
                <TelemetryChart data={data} title="Speed Trace" dataKey="Speed" yLabel="kmh" />
                <TelemetryChart data={data} title="Throttle" dataKey="Throttle" yLabel="%" />
                <TelemetryChart data={data} title="Brake" dataKey="Brake" yLabel="%" />
                <TelemetryChart data={data} title="RPM" dataKey="RPM" yLabel="RPM" />
                <TelemetryChart data={data} title="Gear" dataKey="nGear" yLabel="Gear" />
            </div>
            <style>{`
        .input-text {
            background: var(--bg-surface-hover);
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            padding: 10px 12px;
            border-radius: 8px;
            outline: none;
            width: 80px;
        }
        .placeholder-text {
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--text-secondary);
        }
      `}</style>
        </div>
    );
};

export default Telemetry;
