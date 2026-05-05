import React, { useEffect, useState } from 'react';
import { getStandings } from '../services/api';
import { Trophy } from 'lucide-react';
import InputSelect from '../components/InputSelect';

const Standings = () => {
    const [standings, setStandings] = useState([]);
    const [loading, setLoading] = useState(true);
    const currentYear = new Date().getFullYear();
    const [year, setYear] = useState(currentYear);

    useEffect(() => {
        const fetchStandings = async () => {
            try {
                const data = await getStandings(year);
                setStandings(data);
            } catch (err) {
                console.error("Failed to load standings", err);
            } finally {
                setLoading(false);
            }
        };

        fetchStandings();
    }, [year]);

    if (loading) return <div style={{ color: 'var(--text-primary)' }}>Loading Standings...</div>;

    return (
        <div className="page-standings">
            <header style={{ marginBottom: '22px' }}>
                <h1 style={{ fontSize: '2rem', fontWeight: 700, marginBottom: '8px' }}>Driver Standings</h1>
            </header>

            <div style={{ marginBottom: '24px', display: 'flex', justifyContent: 'flex-start' }}>
                <InputSelect
                    value={year}
                    onChange={setYear}
                    options={Array.from({ length: currentYear - 1950 + 1 }, (_, i) => ({
                        label: String(currentYear - i),
                        value: currentYear - i
                    }))}
                />
            </div>

            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th style={{ width: '60px' }}>Position</th>
                            <th>Driver</th>
                            <th>Team</th>
                            <th style={{ textAlign: 'right' }}>Points</th>
                        </tr>
                    </thead>
                    <tbody>
                        {standings.map((driver, index) => (
                            <tr key={driver.Driver}>
                                <td style={{ fontWeight: 600, color: index < 3 ? 'var(--f1-red)' : 'inherit' }}>
                                    {index + 1}
                                    {index === 0 && <Trophy size={14} style={{ display: 'inline', marginLeft: '6px' }} />}
                                </td>
                                <td style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                    <span style={{
                                        display: 'inline-block',
                                        width: '4px',
                                        height: '24px',
                                        borderRadius: '2px',
                                        background: driver.Color ? (driver.Color.startsWith('#') ? driver.Color : `#${driver.Color}`) : '#ccc'
                                    }}></span>
                                    <span style={{ fontWeight: 500 }}>{driver.Driver}</span>
                                    <span style={{ fontSize: '0.8rem', color: 'var(--text-tertiary)' }}>#{driver.DriverNumber}</span>
                                </td>
                                <td style={{ color: 'var(--text-secondary)' }}>{driver.Team}</td>
                                <td style={{ textAlign: 'right', fontWeight: 700 }}>{driver.Points}</td>
                            </tr>
                        ))}
                        {standings.length === 0 && (
                            <tr><td colSpan="4" style={{ textAlign: 'center', padding: '32px' }}>No standings data available yet.</td></tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

export default Standings;
