import React, { useState, useRef, useEffect } from 'react';

const MultiSelect = ({
    label,
    value = [],
    onChange,
    options = [],
    placeholder = 'Select options...'
}) => {
    const [isOpen, setIsOpen] = useState(false);
    const [searchTerm, setSearchTerm] = useState('');
    const containerRef = useRef(null);

    // Close dropdown on click outside
    useEffect(() => {
        const handleClickOutside = (event) => {
            if (containerRef.current && !containerRef.current.contains(event.target)) {
                setIsOpen(false);
            }
        };

        const handleKeyDown = (event) => {
            if (event.key === 'Escape') {
                setIsOpen(false);
            }
        };

        if (isOpen) {
            document.addEventListener('mousedown', handleClickOutside);
            document.addEventListener('keydown', handleKeyDown);
        }

        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
            document.removeEventListener('keydown', handleKeyDown);
        };
    }, [isOpen]);

    const handleToggle = (val) => {
        if (value.includes(val)) {
            onChange(value.filter(v => v !== val));
        } else {
            onChange([...value, val]);
        }
    };

    const handleSelectAll = () => {
        onChange(options.map(opt => opt.value));
    };

    const handleClearAll = () => {
        onChange([]);
    };

    const filteredOptions = options.filter(opt => {
        const query = searchTerm.toLowerCase();
        const labelMatch = (opt.label || '').toLowerCase().includes(query);
        const valueMatch = (opt.value || '').toLowerCase().includes(query);
        const titleMatch = (opt.title || '').toLowerCase().includes(query);
        return labelMatch || valueMatch || titleMatch;
    });

    // Label displayed on the trigger button
    const getTriggerLabel = () => {
        if (value.length === 0) {
            return <span style={{ color: 'var(--text-tertiary)' }}>{placeholder}</span>;
        }
        if (value.length <= 4) {
            return (
                <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', alignItems: 'center' }}>
                    {value.map(val => {
                        const opt = options.find(o => o.value === val);
                        return (
                            <span
                                key={val}
                                style={{
                                    backgroundColor: 'var(--border-color)',
                                    color: 'var(--text-primary)',
                                    padding: '2px 6px',
                                    borderRadius: '4px',
                                    fontSize: '0.75rem',
                                    fontWeight: 600
                                }}
                            >
                                {opt ? (opt.shortLabel || opt.value) : val}
                            </span>
                        );
                    })}
                </div>
            );
        }
        return <span>{value.length} drivers selected</span>;
    };

    return (
        <div
            className="input-group"
            ref={containerRef}
            style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '6px',
                position: 'relative',
                minWidth: '220px'
            }}
        >
            {label && (
                <label style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                    {label}
                </label>
            )}

            {/* Custom Trigger Button */}
            <div
                tabIndex={0}
                role="button"
                aria-haspopup="listbox"
                aria-expanded={isOpen}
                onClick={() => setIsOpen(prev => !prev)}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        setIsOpen(prev => !prev);
                    }
                }}
                style={{
                    background: 'var(--bg-surface-hover)',
                    border: `1px solid ${isOpen ? 'var(--text-secondary)' : 'var(--border-color)'}`,
                    color: 'var(--text-primary)',
                    padding: '8px 12px',
                    borderRadius: '8px',
                    cursor: 'pointer',
                    minHeight: '42px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '8px',
                    outline: 'none',
                    userSelect: 'none'
                }}
            >
                <div style={{ flex: 1, overflow: 'hidden' }}>
                    {getTriggerLabel()}
                </div>
                <span
                    style={{
                        fontSize: '0.75rem',
                        color: 'var(--text-secondary)',
                        transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                        transition: 'transform 0.2s ease'
                    }}
                >
                    ▼
                </span>
            </div>

            {/* Dropdown Menu */}
            {isOpen && (
                <div
                    style={{
                        position: 'absolute',
                        top: '100%',
                        left: 0,
                        right: 0,
                        marginTop: '6px',
                        backgroundColor: 'var(--bg-surface)',
                        border: '1px solid var(--border-color)',
                        borderRadius: '8px',
                        boxShadow: '0 12px 28px rgba(0, 0, 0, 0.4)',
                        zIndex: 100,
                        maxHeight: '320px',
                        display: 'flex',
                        flexDirection: 'column',
                        overflow: 'hidden'
                    }}
                >
                    {/* Header Controls: Search & Select/Clear */}
                    <div
                        style={{
                            padding: '8px 10px',
                            borderBottom: '1px solid var(--border-color)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '6px',
                            backgroundColor: 'var(--bg-surface)'
                        }}
                    >
                        {options.length > 8 && (
                            <input
                                type="text"
                                value={searchTerm}
                                onChange={(e) => setSearchTerm(e.target.value)}
                                placeholder="Search driver..."
                                onClick={(e) => e.stopPropagation()}
                                style={{
                                    width: '100%',
                                    background: 'var(--bg-surface-hover)',
                                    border: '1px solid var(--border-color)',
                                    color: 'var(--text-primary)',
                                    padding: '6px 10px',
                                    borderRadius: '6px',
                                    fontSize: '0.8125rem',
                                    outline: 'none'
                                }}
                            />
                        )}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
                                {value.length} of {options.length} selected
                            </span>
                            <div style={{ display: 'flex', gap: '8px' }}>
                                <button
                                    type="button"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        handleSelectAll();
                                    }}
                                    style={{
                                        background: 'transparent',
                                        border: 'none',
                                        color: 'var(--accent-blue, #38bdf8)',
                                        fontSize: '0.75rem',
                                        cursor: 'pointer',
                                        padding: 0
                                    }}
                                >
                                    Select All
                                </button>
                                <span style={{ color: 'var(--border-color)', fontSize: '0.75rem' }}>|</span>
                                <button
                                    type="button"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        handleClearAll();
                                    }}
                                    style={{
                                        background: 'transparent',
                                        border: 'none',
                                        color: 'var(--text-secondary)',
                                        fontSize: '0.75rem',
                                        cursor: 'pointer',
                                        padding: 0
                                    }}
                                >
                                    Clear
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Options List */}
                    <div
                        style={{
                            overflowY: 'auto',
                            maxHeight: '230px',
                            padding: '4px 0'
                        }}
                    >
                        {filteredOptions.length === 0 ? (
                            <div style={{ padding: '12px', textAlign: 'center', color: 'var(--text-tertiary)', fontSize: '0.875rem' }}>
                                No drivers found
                            </div>
                        ) : (
                            filteredOptions.map((opt, idx) => {
                                const isSelected = value.includes(opt.value);
                                return (
                                    <div
                                        key={opt.value}
                                        onClick={() => handleToggle(opt.value)}
                                        style={{
                                            padding: '8px 12px',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '10px',
                                            cursor: 'pointer',
                                            backgroundColor: isSelected ? 'rgba(225, 6, 0, 0.12)' : 'transparent',
                                            transition: 'background-color 0.15s ease'
                                        }}
                                        onMouseEnter={(e) => {
                                            if (!isSelected) e.currentTarget.style.backgroundColor = 'var(--bg-surface-hover)';
                                        }}
                                        onMouseLeave={(e) => {
                                            if (!isSelected) e.currentTarget.style.backgroundColor = 'transparent';
                                        }}
                                    >
                                        <input
                                            type="checkbox"
                                            checked={isSelected}
                                            onChange={() => {}} // Controlled by row click
                                            style={{
                                                cursor: 'pointer',
                                                accentColor: 'var(--f1-red, #E10600)',
                                                width: '14px',
                                                height: '14px'
                                            }}
                                        />

                                        {opt.position && (
                                            <span
                                                style={{
                                                    fontSize: '0.75rem',
                                                    color: 'var(--text-tertiary)',
                                                    minWidth: '22px',
                                                    textAlign: 'right',
                                                    fontVariantNumeric: 'tabular-nums'
                                                }}
                                            >
                                                P{opt.position}
                                            </span>
                                        )}

                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flex: 1 }}>
                                            <span style={{ fontWeight: 600, fontSize: '0.875rem', color: isSelected ? 'var(--text-primary)' : 'var(--text-primary)' }}>
                                                {opt.value}
                                            </span>
                                            {opt.title && (
                                                <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
                                                    {opt.title}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                );
                            })
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

export default MultiSelect;
