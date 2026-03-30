import React from 'react';

export default function ChartDisplay({ chartB64, question }) {
  if (!chartB64) return null;

  const handleDownload = () => {
    const link = document.createElement('a');
    link.href = `data:image/png;base64,${chartB64}`;
    link.download = 'chart.png';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="card flex-col gap-12">
      <div className="text-caption color-muted">{question}</div>
      <img 
        src={`data:image/png;base64,${chartB64}`} 
        alt="Data analysis chart" 
        style={{ width: '100%', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)' }}
      />
      <div style={{ textAlign: 'right' }}>
        <button 
          onClick={handleDownload}
          className="text-body color-muted"
          style={{ background: 'transparent', padding: 0 }}
        >
          <span style={{ cursor: 'pointer' }} onMouseOver={(e) => e.target.style.textDecoration='underline'} onMouseOut={(e) => e.target.style.textDecoration='none'}>Download PNG</span>
        </button>
      </div>
    </div>
  );
}
