import React from 'react';

const AgentNode = ({ agent, status, content, isLast }) => {
  let dotColor = 'var(--bg-main)';
  let dotFill = 'var(--border-color)';
  let dotClass = '';

  if (status === 'started') {
    dotFill = 'var(--accent)';
    dotClass = 'dot-active';
  } else if (status === 'done' || status === 'code_generated') {
    dotFill = 'var(--success)';
  } else if (status === 'error') {
    dotFill = 'var(--error)';
  }

  return (
    <div className="flex-row animate-slide-in" style={{ position: 'relative', paddingBottom: isLast ? 0 : 'var(--space-24)', alignItems: 'flex-start' }}>
      {/* Vertical line connecting dots */}
      {!isLast && (
        <div style={{
          position: 'absolute', left: '3px', top: '16px', bottom: 0,
          width: '1px', backgroundColor: 'var(--border-color)'
        }} />
      )}
      
      {/* Dot */}
      <div style={{ marginTop: '4px', marginRight: 'var(--space-16)', zIndex: 1 }}>
        <div className={dotClass} style={{
          width: '8px', height: '8px', borderRadius: '50%',
          backgroundColor: dotFill,
        }} />
      </div>

      <div className="flex-col gap-4" style={{ flex: 1 }}>
        <div className="text-body color-primary" style={{ fontWeight: 500, textTransform: 'capitalize' }}>
          {agent === 'END' ? 'Final Result' : agent}
        </div>
        <div className="text-caption color-muted" style={{ whiteSpace: 'pre-wrap', fontFamily: status === 'code_generated' ? 'JetBrains Mono, monospace' : 'inherit' }}>
          {content}
        </div>
      </div>
    </div>
  );
};

export default function AgentTrace({ events }) {
  if (!events || events.length === 0) return null;

  return (
    <div className="card flex-col">
      <div className="text-heading" style={{ marginBottom: 'var(--space-24)' }}>Agent Trace</div>
      <div className="flex-col">
        {events.map((ev, i) => (
          <AgentNode key={i} {...ev} isLast={i === events.length - 1} />
        ))}
      </div>
    </div>
  );
}
