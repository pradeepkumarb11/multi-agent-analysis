import React, { useState } from 'react';

export default function ChatInput({ onSend, disabled }) {
  const [text, setText] = useState('');
  const [isFocused, setIsFocused] = useState(false);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (text.trim() && !disabled) {
      onSend(text.trim());
      setText('');
    }
  };

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <form 
        onSubmit={handleSubmit}
        style={{
          display: 'flex',
          alignItems: 'center',
          backgroundColor: 'var(--surface)',
          border: `1px solid ${isFocused ? 'var(--accent)' : 'var(--border-color)'}`,
          boxShadow: isFocused ? '0 0 0 3px var(--accent-muted)' : 'none',
          borderRadius: 'var(--radius-pill)',
          padding: 'var(--space-4) var(--space-8)',
          transition: 'all 150ms ease',
        }}
      >
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          disabled={disabled}
          placeholder="Ask a question about the data..."
          className="text-input color-primary"
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            padding: 'var(--space-8) var(--space-12)',
            color: disabled ? 'var(--text-subtle)' : 'var(--text-primary)',
          }}
        />
        <button
          type="submit"
          disabled={disabled || !text.trim()}
          style={{
            width: '32px',
            height: '32px',
            borderRadius: '50%',
            backgroundColor: (disabled || !text.trim()) ? 'var(--surface-2)' : 'var(--accent)',
            color: (disabled || !text.trim()) ? 'var(--text-subtle)' : '#FFF',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginLeft: 'var(--space-4)',
          }}
        >
          ↑
        </button>
      </form>
      {disabled && (
        <div style={{ position: 'absolute', top: '-24px', left: '16px', fontSize: '12px', color: 'var(--text-subtle)' }}>
          Upload a CSV first
        </div>
      )}
    </div>
  );
}
