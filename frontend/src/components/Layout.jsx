import React from 'react';
import { NavLink } from 'react-router-dom';
import { BarChart2, Activity, Gauge, Trophy } from 'lucide-react';
import './Layout.css'; // We'll create this or use usage in index.css

const Layout = ({ children }) => {
    return (
        <div className="app-layout">
            <aside className="sidebar">
                <div className="logo-area">
                    <Trophy size={28} color="var(--f1-red)" />
                    <span className="brand-name">F1 Analytics</span>
                </div>

                <nav className="nav-menu">
                    <NavLink to="/" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                        <BarChart2 size={20} />
                        <span>Standings</span>
                    </NavLink>
                    <NavLink to="/race-pace" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                        <Activity size={20} />
                        <span>Race Pace</span>
                    </NavLink>
                    <NavLink to="/telemetry" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                        <Gauge size={20} />
                        <span>Telemetry</span>
                    </NavLink>
                </nav>
            </aside>

            <main className="main-content">
                {children}
            </main>
        </div>
    );
};

export default Layout;
