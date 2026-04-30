import React from 'react';

const InputSelect = ({ label, value, onChange, options = [], placeholder = 'Select...' }) => {
    return (
        <div className="input-group" style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {label && <label style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>{label}</label>}
            <select
                value={value}
                onChange={(e) => onChange(e.target.value)}
                style={{
                    background: 'var(--bg-surface-hover)',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-primary)',
                    padding: '10px 12px',
                    borderRadius: '8px',
                    outline: 'none',
                    minWidth: '150px',
                    fontFamily: 'inherit'
                }}
            >
                <option value="" disabled>{placeholder}</option>
                {options.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                        {opt.label}
                    </option>
                ))}
            </select>
        </div>
    );
};

export default InputSelect;
