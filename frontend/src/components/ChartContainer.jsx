import React from 'react';

const ChartContainer = ({ title, children, height = 400 }) => {
    return (
        <div className="card chart-container" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {title && (
                <div className="chart-header">
                    <h3 style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-primary)' }}>{title}</h3>
                </div>
            )}
            <div className="chart-body" style={{ height: height, width: '100%' }}>
                {children}
            </div>
        </div>
    );
};

export default ChartContainer;
